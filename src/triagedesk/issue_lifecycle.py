"""Purge remotely closed reports from connected workspaces, including cached analysis."""

from sqlalchemy import delete, select, update

from triagedesk.models import (
    ContributorGuide,
    Issue,
    IssueActivity,
    LabelAnalysis,
    LabelAssignment,
    LabelReview,
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
    for table in [ContributorGuide, LabelAssignment, LabelReview, LabelAnalysis, IssueActivity]:
        db.execute(delete(table).where(table.issue_id.in_(ids)))
    db.execute(update(Issue).where(Issue.id.in_(ids)).values(snapshot_id=None))
    # Intentional bulk purge: immutable historical snapshots remain immutable during normal updates.
    db.execute(delete(Snapshot).where(Snapshot.issue_id.in_(ids)))
    db.execute(delete(Issue).where(Issue.id.in_(ids)))
    db.commit()
    return len(ids)
