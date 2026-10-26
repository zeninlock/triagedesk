from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from triagedesk.models import Issue, Prediction, Review, SimilarityJudgment
from triagedesk.text import digest


def submit_review(session, issue, payload, reviewer):
    payload_hash = digest([issue.id, payload.model_dump(), reviewer])
    prior = session.scalar(select(Review).where(Review.idempotency_key == payload.idempotency_key))
    if prior:
        if prior.payload_hash != payload_hash:
            raise HTTPException(409, "This submission key has already been used for a different review")
        return prior
    if payload.prediction_id is not None:
        prediction = session.get(Prediction, payload.prediction_id)
        if not prediction or prediction.issue_id != issue.id or prediction.snapshot_id != issue.snapshot_id:
            raise HTTPException(409, "The prediction no longer matches this issue; refresh before reviewing")
        if payload.action == "accept" and payload.category != prediction.category:
            raise HTTPException(422, "An accepted category must match the selected prediction")
    changed = session.execute(
        update(Issue)
        .where(
            Issue.id == issue.id,
            Issue.review_revision == payload.expected_revision,
            Issue.snapshot_id == payload.snapshot_id,
        )
        .values(review_revision=Issue.review_revision + 1)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        session.rollback()
        # An identical in-flight retry may have waited for the first writer to commit.
        prior = session.scalar(select(Review).where(Review.idempotency_key == payload.idempotency_key))
        if prior and prior.payload_hash == payload_hash:
            return prior
        raise HTTPException(409, "The issue or a review changed; refresh and inspect the latest decision")
    review = Review(
        issue_id=issue.id,
        snapshot_id=payload.snapshot_id,
        prediction_id=payload.prediction_id,
        action=payload.action,
        category=payload.category,
        note=payload.note,
        reviewer=reviewer,
        idempotency_key=payload.idempotency_key,
        payload_hash=payload_hash,
        revision=payload.expected_revision + 1,
    )
    session.add(review)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        prior = session.scalar(select(Review).where(Review.idempotency_key == payload.idempotency_key))
        if prior and prior.payload_hash == payload_hash:
            return prior
        raise HTTPException(409, "Concurrent submission; refresh and inspect the review history") from None
    return review


def submit_judgment(session, issue, candidate, payload, reviewer):
    payload_hash = digest([issue.id, payload.model_dump(), reviewer])
    prior = session.scalar(
        select(SimilarityJudgment).where(SimilarityJudgment.idempotency_key == payload.idempotency_key)
    )
    if prior:
        if prior.payload_hash != payload_hash:
            raise HTTPException(409, "Submission key was reused with different judgment data")
        return prior
    if issue.id == candidate.id or issue.repository_id != candidate.repository_id:
        raise HTTPException(422, "Choose a different issue in the same repository")
    if (
        issue.snapshot_id != payload.query_snapshot_id
        or candidate.snapshot_id != payload.candidate_snapshot_id
    ):
        raise HTTPException(409, "An issue changed; refresh related suggestions")
    judgment = SimilarityJudgment(
        query_issue_id=issue.id,
        candidate_issue_id=candidate.id,
        query_snapshot_id=issue.snapshot_id,
        candidate_snapshot_id=candidate.snapshot_id,
        judgment=payload.judgment,
        reviewer=reviewer,
        purpose="ui",
        idempotency_key=payload.idempotency_key,
        payload_hash=payload_hash,
    )
    session.add(judgment)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        prior = session.scalar(
            select(SimilarityJudgment).where(SimilarityJudgment.idempotency_key == payload.idempotency_key)
        )
        if prior and prior.payload_hash == payload_hash:
            return prior
        raise HTTPException(409, "Concurrent submission; refresh suggestions") from None
    return judgment
