"""Purge remotely closed reports from connected workspaces, including cached analysis."""

from sqlalchemy import delete, or_, select, update

from triagedesk.models import (
    Issue,
    LabelAnalysis,
    LabelAssignment,
    LabelReview,
    Prediction,
    Review,
    SimilarityJudgment,
    Snapshot,
)


def purge_closed(db, repository_id):
    ids = list(
        db.scalars(
            select(Issue.id)
            .where(Issue.repository_id == repository_id, Issue.state == "closed")
            .with_for_update()
        )
    )
    if not ids:
        return 0
    db.execute(
        delete(SimilarityJudgment).where(
            or_(SimilarityJudgment.query_issue_id.in_(ids), SimilarityJudgment.candidate_issue_id.in_(ids))
        )
    )
    for table in [LabelAssignment, LabelReview, LabelAnalysis, Review, Prediction]:
        db.execute(delete(table).where(table.issue_id.in_(ids)))
    db.execute(update(Issue).where(Issue.id.in_(ids)).values(snapshot_id=None))
    # Intentional bulk purge: immutable historical snapshots remain immutable during normal updates.
    db.execute(delete(Snapshot).where(Snapshot.issue_id.in_(ids)))
    db.execute(delete(Issue).where(Issue.id.in_(ids)))
    db.commit()
    return len(ids)
