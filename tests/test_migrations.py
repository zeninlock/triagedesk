"""Upgrade real PostgreSQL schemas with and without existing review data."""

import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from triagedesk.models import Base

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def migration_database():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    schema = "migration_" + uuid.uuid4().hex
    admin = sa.create_engine(url)
    with admin.begin() as db:
        db.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    test_url = (
        make_url(url)
        .update_query_dict({"options": f"-csearch_path={schema}"})
        .render_as_string(hide_password=False)
    )
    engine = sa.create_engine(test_url)
    yield engine, test_url
    engine.dispose()
    with admin.begin() as db:
        db.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def migrate(url, target):
    env = {
        **os.environ,
        "DATABASE_URL": url,
        "AUTH_ENCRYPTION_KEY": "test-only-encryption-secret-over-32-characters",
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr


def test_fresh_schema_matches_model_metadata(migration_database):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    engine, url = migration_database
    migrate(url, "head")
    with engine.connect() as db:
        assert db.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0004"
        assert compare_metadata(MigrationContext.configure(db), Base.metadata) == []
    assert not {"reviews", "predictions", "experiments", "similarity_judgments"} & set(
        sa.inspect(engine).get_table_names()
    )


@pytest.mark.parametrize("existing_label_review", [False, True])
def test_old_human_reviews_survive_consolidation(migration_database, existing_label_review):
    from sqlalchemy.orm import Session

    from triagedesk import triage
    from triagedesk.models import Issue, LabelReview, Repository

    engine, url = migration_database
    migrate(url, "0003")
    m = sa.MetaData()
    m.reflect(engine)
    now = datetime.now(timezone.utc)
    with engine.begin() as db:
        db.execute(
            m.tables["repositories"]
            .insert()
            .values(
                id=1,
                github_id=77,
                full_name="maintainer/project",
                source_url="https://github.com/maintainer/project",
                synthetic=False,
                first_imported_at=now,
                partial=False,
            )
        )
        db.execute(
            m.tables["issues"]
            .insert()
            .values(
                id=1,
                github_id=101,
                repository_id=1,
                number=1,
                title="API fails",
                body="Broken API",
                source_url="https://github.com/maintainer/project/issues/1",
                state="open",
                created_at=now,
                updated_at=now,
                ingested_at=now,
                labels=[],
                content_hash="a" * 64,
                review_revision=1,
                available=True,
            )
        )
        db.execute(
            m.tables["snapshots"]
            .insert()
            .values(
                id=1,
                issue_id=1,
                title="API fails",
                body="Broken API",
                labels=[],
                content_hash="a" * 64,
                snapshot_hash="b" * 64,
                source_updated_at=now,
                collected_at=now,
            )
        )
        db.execute(m.tables["issues"].update().values(snapshot_id=1))
        db.execute(
            m.tables["reviews"]
            .insert()
            .values(
                id=1,
                issue_id=1,
                snapshot_id=1,
                action="correct",
                category="bug",
                note="Human decision",
                reviewer="maintainer",
                idempotency_key="legacy-key",
                payload_hash="c" * 64,
                revision=1,
                created_at=now,
            )
        )
    with engine.begin() as db:
        db.execute(
            m.tables["repositories"]
            .insert()
            .values(
                id=2,
                github_id=78,
                full_name="demo/synthetic",
                source_url="https://github.com/demo/synthetic",
                synthetic=True,
                first_imported_at=now,
                partial=False,
            )
        )
        if existing_label_review:
            db.execute(
                m.tables["label_reviews"]
                .insert()
                .values(
                    id=5,
                    issue_id=1,
                    snapshot_id=1,
                    analysis_id=None,
                    taxonomy_hash="d" * 64,
                    labels=[{"group": "type", "name": "documentation"}, {"group": "scope", "name": "API"}],
                    note="Newer label review",
                    reviewer="maintainer",
                    revision=2,
                    idempotency_key="newer-label-review",
                    payload_hash="e" * 64,
                    created_at=now + timedelta(seconds=1),
                )
            )
            db.execute(
                m.tables["label_assignments"].insert(),
                [
                    {
                        "issue_id": 1,
                        "snapshot_id": 1,
                        "review_id": 5,
                        "origin": "human",
                        "group": g,
                        "name": n,
                    }
                    for g, n in [("type", "documentation"), ("scope", "API")]
                ],
            )
    migrate(url, "head")
    with Session(engine) as db:
        issue = db.get(Issue, 1)
        assert issue.work_status == "open" and issue.work_revision == 0
        reviews = list(db.scalars(sa.select(LabelReview)))
        assert any("Human decision" in review.note for review in reviews)
        page = triage.list_labeled_issues(db, db.get(Repository, 1))
        assert page["items"][0]["status"] == "reviewed"
        expected = (
            {"type: docs", "priority: low", "area: api"}
            if existing_label_review
            else {"type: bug", "priority: low"}
        )
        assert {x["name"] for x in page["items"][0]["labels"]} == expected
        assert db.get(Repository, 2) is None
    migrate(url, "head")  # Restarting a cloud app must not duplicate migrated history.
    with Session(engine) as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(LabelReview)) == (
            2 if existing_label_review else 1
        )


def test_cloud_bootstrap_migrates_and_serves_ready_backend(migration_database):
    import json
    import urllib.request

    from triagedesk.community import start_backend

    engine, url = migration_database
    backend = start_backend(
        {"DATABASE_URL": url, "MIGRATION_DATABASE_URL": url, "AUTH_ENCRYPTION_KEY": "k" * 48}, timeout=30
    )
    try:
        with urllib.request.urlopen(backend.api_url + "/health/ready", timeout=5) as response:
            result = json.load(response)
        assert result["status"] == "ready"
        with engine.connect() as db:
            assert db.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0004"
    finally:
        backend.stop()
    assert not backend.alive()
