from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from triagedesk.maintenance import prune_transient_records
from triagedesk.models import AuthSession, ConnectionJob, DeviceLogin, ImportRun, Repository, utcnow


def test_only_expired_credentials_and_old_operational_records_are_pruned(database):
    now = utcnow()
    with Session(database) as db:
        repo = Repository(
            github_id=99, full_name="maintainer/project", source_url="https://github.com/maintainer/project"
        )
        db.add(repo)
        db.flush()
        for name, expires in [("expired", now - timedelta(hours=1)), ("active", now + timedelta(hours=1))]:
            db.add(
                AuthSession(
                    token_hash=name,
                    github_user_id=42,
                    login="maintainer",
                    encrypted_token="encrypted",
                    expires_at=expires,
                )
            )
            db.add(
                DeviceLogin(
                    handle_hash=name,
                    encrypted_code="encrypted",
                    expires_at=expires,
                    next_poll_at=now,
                    interval=5,
                )
            )
        for name, age, status in [("old", 8, "complete"), ("new", 1, "complete"), ("running", 8, "running")]:
            db.add(
                ConnectionJob(
                    id=name,
                    github_user_id=42,
                    repository_name=repo.full_name,
                    repository_id=repo.id,
                    incremental=True,
                    object_limit=500,
                    status=status,
                    updated_at=now - timedelta(days=age),
                    lease_until=now + timedelta(minutes=3),
                    active_key="import" if status == "running" else None,
                )
            )
        db.add(ImportRun(repository_id=repo.id, status="complete", completed_at=now - timedelta(days=31)))
        db.add(ImportRun(repository_id=repo.id, status="complete", completed_at=now - timedelta(days=1)))
        db.commit()
        prune_transient_records(db)
        db.commit()
        assert list(db.scalars(select(AuthSession.token_hash))) == ["active"]
        assert list(db.scalars(select(DeviceLogin.handle_hash))) == ["active"]
        assert set(db.scalars(select(ConnectionJob.id))) == {"new", "running"}
        assert len(list(db.scalars(select(ImportRun)))) == 1
        assert db.get(Repository, repo.id) is not None
