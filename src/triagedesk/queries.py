"""Shared SQL scope for queue and dashboard. Charts never scan rows in the browser."""

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import aliased

from triagedesk.models import Issue, Prediction, Repository, Review
from triagedesk.schemas import IssueFilters


def issue_scope(filters: IssueFilters, mode: str):
    p, r = aliased(Prediction), aliased(Review)
    latest_p = (
        select(func.max(Prediction.id))
        .where(Prediction.issue_id == Issue.id, Prediction.snapshot_id == Issue.snapshot_id)
        .correlate(Issue)
        .scalar_subquery()
    )
    latest_r = (
        select(func.max(Review.id))
        .where(Review.issue_id == Issue.id, Review.snapshot_id == Issue.snapshot_id)
        .correlate(Issue)
        .scalar_subquery()
    )
    reviewed = and_(r.id.is_not(None), r.action.in_(["accept", "correct"]))
    status = case(
        (reviewed, "reviewed"),
        (r.action == "defer", "deferred"),
        (r.action == "skip", "skipped"),
        else_="awaiting",
    )
    source = {
        "predicted": p.category,
        "reviewed": r.category,
        "effective": func.coalesce(r.category, p.category),
    }[filters.category_source]
    query = (
        select(
            Issue.id.label("id"),
            Issue.repository_id,
            Issue.number,
            Issue.title,
            Issue.source_url,
            Issue.state,
            Issue.created_at,
            Issue.updated_at,
            Issue.snapshot_id,
            Issue.review_revision,
            p.id.label("prediction_id"),
            p.category.label("predicted_category"),
            p.max_score,
            p.needs_review,
            p.model_version,
            p.method.label("prediction_method"),
            r.category.label("reviewed_category"),
            status.label("review_status"),
            reviewed.label("review_complete"),
        )
        .join(Repository, Repository.id == Issue.repository_id)
        .outerjoin(p, p.id == latest_p)
        .outerjoin(r, r.id == latest_r)
        .where(Repository.synthetic == (mode == "fixture"), Issue.available.is_(True))
    )
    conditions = []
    if filters.repository_id is not None:
        conditions.append(Issue.repository_id == filters.repository_id)
    if filters.created_from:
        conditions.append(Issue.created_at >= filters.created_from)
    if filters.created_before:
        conditions.append(Issue.created_at < filters.created_before)
    if filters.state:
        conditions.append(Issue.state == filters.state)
    if filters.category:
        conditions.append(source == filters.category)
    if filters.review_status == "awaiting":
        conditions.append(or_(r.id.is_(None), r.action.in_(["defer", "skip"])))
    elif filters.review_status:
        conditions.append(status == filters.review_status)
    if filters.search:
        # autoescape makes '%' and '_' literal search characters; values remain bound parameters.
        conditions.append(
            or_(
                Issue.title.icontains(filters.search, autoescape=True),
                Issue.body.icontains(filters.search, autoescape=True),
            )
        )
    return query.where(*conditions)


def list_issues(session, filters, mode):
    scoped = issue_scope(filters, mode).subquery()
    count = session.scalar(select(func.count()).select_from(scoped))
    order = {
        "oldest": scoped.c.created_at.asc(),
        "newest": scoped.c.created_at.desc(),
        "lowest_score": scoped.c.max_score.asc().nullsfirst(),
    }[filters.sort]
    rows = (
        session.execute(
            select(scoped)
            .order_by(order, scoped.c.id)
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
        )
        .mappings()
        .all()
    )
    return {
        "items": [dict(row) for row in rows],
        "total": count,
        "page": filters.page,
        "page_size": filters.page_size,
    }


def dashboard(session, filters, mode):
    q = issue_scope(filters, mode).subquery()

    def one(condition):
        return func.sum(case((condition, 1), else_=0))

    totals = (
        session.execute(
            select(
                func.count().label("imported"),
                one(q.c.state == "open").label("open"),
                one(q.c.state == "closed").label("closed"),
                one(q.c.review_complete).label("reviewed"),
                one(q.c.needs_review.is_(True)).label("low_score"),
            ).select_from(q)
        )
        .mappings()
        .one()
    )
    result = {key: int(value or 0) for key, value in totals.items()}
    result["awaiting_review"] = result["imported"] - result["reviewed"]
    result["review_completion_rate"] = result["reviewed"] / result["imported"] if result["imported"] else 0
    for field, name in (
        (q.c.predicted_category, "predicted_categories"),
        (q.c.reviewed_category, "reviewed_categories"),
    ):
        result[name] = {
            category or "unavailable": count
            for category, count in session.execute(select(field, func.count()).group_by(field))
        }
    # UTC month of source creation, not ingestion. SQLite branch exists only for fast unit tests.
    month = (
        func.to_char(func.timezone("UTC", q.c.created_at), "YYYY-MM")
        if session.bind.dialect.name == "postgresql"
        else func.strftime("%Y-%m", q.c.created_at)
    )
    result["arrivals"] = [
        {"month": m, "issues": n}
        for m, n in session.execute(select(month, func.count()).group_by(month).order_by(month))
    ]
    recent = session.execute(
        select(Review.id, Review.issue_id, Review.action, Review.category, Review.reviewer, Review.created_at)
        .join(q, q.c.id == Review.issue_id)
        .order_by(Review.id.desc())
        .limit(10)
    ).mappings()
    result["recent_reviews"] = [dict(row) for row in recent]
    result["scope"] = (
        "Imported, available issues matching all active filters; partial imports are not repository totals"
    )
    return result
