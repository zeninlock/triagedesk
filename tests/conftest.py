import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from triagedesk import db
from triagedesk.api import app
from triagedesk.config import settings
from triagedesk.fixtures import seed
from triagedesk.models import Base


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("AUTH_ENCRYPTION_KEY", "")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "")
    monkeypatch.setenv("MODE", "fixture")
    monkeypatch.setenv("READ_ONLY", "false")
    monkeypatch.setenv("REVIEWER_TOKEN", "test-review-secret")
    monkeypatch.setenv("REVIEWER_NAME", "test-maintainer")
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("GITHUB_TOKEN", "")
    settings.cache_clear()
    yield
    settings.cache_clear()
    app.dependency_overrides.clear()


@pytest.fixture
def database(monkeypatch):
    database = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(database, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(database)
    monkeypatch.setattr(db, "engine", lambda: database)
    yield database
    database.dispose()


@pytest.fixture
def client(database):
    with Session(database) as session, session.begin():
        seed(session)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-review-secret"}


@pytest.fixture
def postgres_database(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not configured; PostgreSQL tests require a disposable test database")
    schema = "test_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))  # Generated UUID only, never user input.
    pg = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(pg)
    monkeypatch.setattr(db, "engine", lambda: pg)
    yield pg
    pg.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))  # Isolated test namespace only.
    admin.dispose()


def raw_issue(number=1, labels=None, day=0, title=None, body=None):
    created = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
    return {
        "id": number + 10000,
        "number": number,
        "title": title or f"Issue {number}: CSV export fails",
        "body": body or "The exported attendance file is missing a record. Expected all rows.",
        "html_url": f"https://github.com/example/project/issues/{number}",
        "state": "open",
        "labels": [{"name": x} for x in (labels or ["bug"])],
        "created_at": created.isoformat(),
        "updated_at": created.isoformat(),
        "closed_at": None,
    }
