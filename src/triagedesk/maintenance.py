"""Remove expired credentials and old operational records; preserve issue decisions."""

from datetime import timedelta

from sqlalchemy import delete

from triagedesk.models import AuthSession, ConnectionJob, DeviceLogin, ImportRun, RepositoryContext, utcnow


def prune_transient_records(db):
    now = utcnow()
    conditions = (
        (AuthSession, AuthSession.expires_at < now),
        (DeviceLogin, DeviceLogin.expires_at < now),
        (
            ConnectionJob,
            (ConnectionJob.active_key.is_(None))
            & (ConnectionJob.status.in_(["complete", "failed"]))
            & (ConnectionJob.updated_at < now - timedelta(days=7)),
        ),
        (ImportRun, (ImportRun.completed_at < now - timedelta(days=30))),
        (RepositoryContext, RepositoryContext.created_at < now - timedelta(days=30)),
    )
    for table, condition in conditions:
        db.execute(delete(table).where(condition).execution_options(synchronize_session=False))
