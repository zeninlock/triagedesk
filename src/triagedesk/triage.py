"""SQL-backed label browsing and idempotent human overrides."""

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from triagedesk.ai_labels import (
    GROUPS,
    analyzer_key,
    error_details,
    provider_cooldown,
    publish_labels,
    taxonomy_for,
)
from triagedesk.config import settings
from triagedesk.github import aware
from triagedesk.models import Issue, LabelAnalysis, LabelAssignment, LabelReview, Review, utcnow
from triagedesk.text import digest


class SelectedLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group: str = Field(max_length=30)
    name: str = Field(min_length=1, max_length=100)


class LabelReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    labels: list[SelectedLabel] = Field(min_length=1, max_length=30)
    snapshot_id: int
    expected_revision: int = Field(ge=0)
    taxonomy_hash: str = Field(min_length=64, max_length=64)
    note: str = Field("", max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=100)


def scope(repository):
    a, r, legacy = aliased(LabelAnalysis), aliased(LabelReview), aliased(Review)
    latest_a = (
        select(func.max(LabelAnalysis.id))
        .where(
            LabelAnalysis.snapshot_id == Issue.snapshot_id,
            LabelAnalysis.analyzer_key == analyzer_key(repository),
        )
        .correlate(Issue)
        .scalar_subquery()
    )
    latest_r = (
        select(func.max(LabelReview.id))
        .where(
            LabelReview.snapshot_id == Issue.snapshot_id,
            LabelReview.taxonomy_hash == digest(taxonomy_for(repository)),
        )
        .correlate(Issue)
        .scalar_subquery()
    )
    latest_legacy = (
        select(func.max(Review.id))
        .where(Review.snapshot_id == Issue.snapshot_id)
        .correlate(Issue)
        .scalar_subquery()
    )
    reviewed = or_(r.id.is_not(None), and_(legacy.id.is_not(None), legacy.action.in_(["accept", "correct"])))
    uncertain = or_(a.uncertain.is_(True), a.confidence < settings().ai_confidence_threshold)
    status = case(
        (reviewed, "reviewed"),
        (and_(a.status == "complete", uncertain), "needs_review"),
        (a.status == "complete", "auto_sorted"),
        else_="pending",
    )
    query = select(
        Issue.id,
        Issue.repository_id,
        Issue.number,
        Issue.title,
        Issue.state,
        Issue.source_url,
        Issue.created_at,
        Issue.updated_at,
        Issue.snapshot_id,
        Issue.review_revision,
        a.id.label("analysis_id"),
        a.status.label("analysis_status"),
        a.confidence,
        a.uncertain.label("analysis_uncertain"),
        a.summary,
        a.explanation,
        a.error.label("analysis_error"),
        a.retry_after.label("analysis_retry_after"),
        a.lease_until.label("analysis_lease_until"),
        r.id.label("label_review_id"),
        legacy.category.label("legacy_category"),
        legacy.action.label("legacy_action"),
        status.label("status"),
    )
    return (
        query.select_from(Issue)
        .outerjoin(a, a.id == latest_a)
        .outerjoin(r, r.id == latest_r)
        .outerjoin(legacy, legacy.id == latest_legacy)
        .where(Issue.repository_id == repository.id, Issue.available.is_(True), Issue.state == "open")
    )


def labels_for_rows(db, rows):
    items = {row["id"]: {**dict(row), "labels": []} for row in rows}
    if not items:
        return []
    for assignment in db.scalars(select(LabelAssignment).where(LabelAssignment.issue_id.in_(items))):
        item = items[assignment.issue_id]
        if assignment.snapshot_id != item["snapshot_id"]:
            continue
        origin = "human" if item["label_review_id"] else "ai"
        if item["status"] == "reviewed" and not item["label_review_id"]:
            continue
        if (
            assignment.origin != origin
            or (origin == "ai" and assignment.analysis_id != item["analysis_id"])
            or (origin == "human" and assignment.review_id != item["label_review_id"])
        ):
            continue
        item["labels"].append(
            {"group": assignment.group, "name": assignment.name, "confidence": assignment.confidence}
        )
    for item in items.values():
        item["analysis_failure"] = error_details(item["analysis_error"])
        item["review_reason"] = ""
        if item["status"] == "needs_review":
            if (item["explanation"] or "").startswith("Validation needs review:"):
                item["review_reason"] = "Some supporting details could not be verified."
            elif item["analysis_uncertain"]:
                item["review_reason"] = "The classification is marked uncertain."
            else:
                item["review_reason"] = "AI confidence is below the configured cutoff."
        if item["status"] == "reviewed" and not item["label_review_id"] and item["legacy_category"]:
            item["labels"] = [{"group": "type", "name": item["legacy_category"], "confidence": None}]
    return list(items.values())


def list_labeled_issues(
    db, repository, status="all", group=None, label=None, search="", page=1, page_size=20
):
    q = scope(repository).subquery()
    conditions = []
    if status != "all":
        conditions.append(q.c.status == status)
    if search:
        conditions.append(q.c.title.icontains(search, autoescape=True))
    if label:
        match = (
            select(LabelAssignment.id)
            .where(
                LabelAssignment.issue_id == q.c.id,
                LabelAssignment.snapshot_id == q.c.snapshot_id,
                LabelAssignment.group == group,
                LabelAssignment.name == label,
                or_(
                    and_(
                        q.c.label_review_id.is_not(None),
                        LabelAssignment.origin == "human",
                        LabelAssignment.review_id == q.c.label_review_id,
                    ),
                    and_(
                        q.c.status != "reviewed",
                        LabelAssignment.origin == "ai",
                        LabelAssignment.analysis_id == q.c.analysis_id,
                    ),
                ),
            )
            .correlate(q)
            .exists()
        )
        if group == "type":
            match = or_(
                match,
                and_(q.c.status == "reviewed", q.c.label_review_id.is_(None), q.c.legacy_category == label),
            )
        conditions.append(match)
    query = select(q).where(*conditions)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        db.execute(
            query.order_by(q.c.updated_at.desc(), q.c.id).offset((page - 1) * page_size).limit(page_size)
        )
        .mappings()
        .all()
    )
    return {"items": labels_for_rows(db, rows), "total": total, "page": page, "page_size": page_size}


def analysis_activity(db, repository, counts):
    q = scope(repository).subquery()
    pending = q.c.status == "pending"
    state = case(
        (and_(q.c.analysis_status == "running", q.c.analysis_lease_until > utcnow()), "running"),
        (q.c.analysis_status == "failed", "failed"),
        else_="queued",
    )
    states = {name: 0 for name in ("queued", "running", "failed")}
    states.update(dict(db.execute(select(state, func.count()).where(pending).group_by(state)).all()))
    failure = db.execute(
        select(q.c.analysis_error, q.c.analysis_retry_after)
        .where(pending, q.c.analysis_status == "failed", q.c.analysis_error.is_not(None))
        .order_by(q.c.analysis_id.desc())
        .limit(1)
    ).first()
    cooldown = provider_cooldown(db) if counts["pending"] else None
    error = error_details(cooldown.error if cooldown else failure.analysis_error if failure else None)
    retry = cooldown.retry_after if cooldown else failure.analysis_retry_after if failure else None
    retry_after = aware(retry).isoformat() if retry else None
    latest = db.scalar(select(func.max(q.c.analysis_id)))
    return {
        "states": states,
        "error": error,
        "retry_after": retry_after,
        "can_retry": bool(settings().groq_api_key.get_secret_value()) and cooldown is None,
        "revision": digest([counts, states, latest, error, retry_after]),
    }


def summary(db, repository):
    q = scope(repository).subquery()
    counts = {name: 0 for name in ["auto_sorted", "needs_review", "reviewed", "pending"]}
    counts.update(dict(db.execute(select(q.c.status, func.count()).group_by(q.c.status)).all()))
    labels = {group: {name: 0 for name in names} for group, names in taxonomy_for(repository).items()}
    # Show the LLM's own current-snapshot distribution, separately from human overrides.
    rows = db.execute(
        select(LabelAssignment.group, LabelAssignment.name, func.count())
        .join(q, q.c.id == LabelAssignment.issue_id)
        .where(
            LabelAssignment.origin == "ai",
            LabelAssignment.snapshot_id == q.c.snapshot_id,
            LabelAssignment.analysis_id == q.c.analysis_id,
            q.c.analysis_status == "complete",
        )
        .group_by(LabelAssignment.group, LabelAssignment.name)
    )
    for group, name, count in rows:
        if name in labels.get(group, {}):
            labels[group][name] = count
    return {
        "counts": counts,
        "ai_activity": analysis_activity(db, repository, counts),
        "total": sum(counts.values()),
        "labels": labels,
        "taxonomy": taxonomy_for(repository),
        "taxonomy_hash": digest(taxonomy_for(repository)),
        "groups": GROUPS,
        "ai_configured": bool(settings().groq_api_key.get_secret_value()),
        "threshold": settings().ai_confidence_threshold,
        "model": settings().ai_model,
        "last_synced_at": repository.last_synced_at,
        "partial": repository.partial,
    }


def save_label_review(db, issue, repository, payload, reviewer):
    fingerprint = digest([issue.id, payload.model_dump(), reviewer])
    prior = db.scalar(select(LabelReview).where(LabelReview.idempotency_key == payload.idempotency_key))
    if prior:
        if prior.payload_hash != fingerprint:
            raise HTTPException(409, "Submission key was already used for a different review")
        return prior
    taxonomy = taxonomy_for(repository)
    if payload.taxonomy_hash != digest(taxonomy):
        raise HTTPException(409, "The label settings changed; refresh before reviewing")
    labels = [x.model_dump() for x in payload.labels]
    if any(x["group"] not in taxonomy or x["name"] not in taxonomy[x["group"]] for x in labels):
        raise HTTPException(422, "Choose labels from this repository's current taxonomy")
    if (
        len({(x["group"], x["name"]) for x in labels}) != len(labels)
        or sum(x["group"] == "type" for x in labels) != 1
    ):
        raise HTTPException(422, "Choose one primary type and avoid duplicate labels")
    changed = db.execute(
        update(Issue)
        .where(
            Issue.id == issue.id,
            Issue.snapshot_id == payload.snapshot_id,
            Issue.state == "open",
            Issue.review_revision == payload.expected_revision,
        )
        .values(review_revision=Issue.review_revision + 1)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        prior = db.scalar(select(LabelReview).where(LabelReview.idempotency_key == payload.idempotency_key))
        if prior and prior.payload_hash == fingerprint:
            return prior
        raise HTTPException(409, "The issue or review changed; refresh before saving")
    analysis = db.scalar(
        select(LabelAnalysis).where(
            LabelAnalysis.snapshot_id == payload.snapshot_id,
            LabelAnalysis.analyzer_key == analyzer_key(repository),
            LabelAnalysis.status == "complete",
        )
    )
    row = LabelReview(
        issue_id=issue.id,
        snapshot_id=payload.snapshot_id,
        analysis_id=analysis.id if analysis else None,
        taxonomy_hash=payload.taxonomy_hash,
        labels=labels,
        note=payload.note,
        reviewer=reviewer,
        revision=payload.expected_revision + 1,
        idempotency_key=payload.idempotency_key,
        payload_hash=fingerprint,
    )
    db.add(row)
    try:
        db.flush()
        publish_labels(db, issue, labels, "human", analysis_id=row.analysis_id, review_id=row.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = db.scalar(select(LabelReview).where(LabelReview.idempotency_key == payload.idempotency_key))
        if prior and prior.payload_hash == fingerprint:
            return prior
        raise HTTPException(409, "Concurrent label review; refresh and inspect the saved decision") from None
    return row
