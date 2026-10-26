from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import raw_issue
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_api import review_payload
from test_github import handler_for_issues, make_client

from triagedesk.fixtures import seed
from triagedesk.github import ingest, upsert_issue
from triagedesk.models import Issue, Repository, Review, Snapshot
from triagedesk.queries import dashboard, list_issues
from triagedesk.reviews import submit_review
from triagedesk.schemas import IssueFilters, ReviewInput

pytestmark = pytest.mark.postgres


def test_postgres_ingestion_persistence_and_snapshot_constraints(postgres_database):
    ingest(postgres_database, "example/project", client=make_client(handler_for_issues))
    ingest(postgres_database, "example/project", incremental=True, client=make_client(handler_for_issues))
    with Session(postgres_database) as session:
        assert session.scalar(select(func.count()).select_from(Issue)) == 2
        issue = session.scalar(select(Issue).order_by(Issue.id))
        assert session.get(Snapshot, issue.snapshot_id).content_hash == issue.content_hash
        assert issue.created_at.tzinfo is not None


def test_postgres_dashboard_and_review_history_across_sessions(postgres_database):
    with Session(postgres_database) as session, session.begin():
        seed(session)
    with Session(postgres_database) as session:
        issue = session.get(Issue, 1)
        payload = ReviewInput(
            **review_payload({"prediction_id": None, "snapshot_id": issue.snapshot_id, "review_revision": 0})
        )
        submit_review(session, issue, payload, "maintainer")
    with Session(postgres_database) as session:
        counts = dashboard(session, IssueFilters(state="open", category="enhancement"), "fixture")
        queue = list_issues(session, IssueFilters(state="open", category="enhancement"), "fixture")
        assert counts["imported"] == queue["total"] and counts["reviewed"] == 1
        assert counts["arrivals"] and session.scalar(select(func.count()).select_from(Review)) == 1
        assert session.get(Issue, 1).review_revision == 1


def test_concurrent_reviews_allow_exactly_one_revision(postgres_database):
    with Session(postgres_database) as session, session.begin():
        seed(session)

    def write(_):
        with Session(postgres_database) as session:
            issue = session.get(Issue, 1)
            payload = ReviewInput(
                **review_payload(
                    {"prediction_id": None, "snapshot_id": issue.snapshot_id, "review_revision": 0}
                )
            )
            try:
                submit_review(session, issue, payload, "maintainer")
                return 201
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, [1, 2])) == [201, 409]
    with Session(postgres_database) as session:
        assert session.scalar(select(func.count()).select_from(Review)) == 1


def test_sync_invalidates_review_on_changed_snapshot(postgres_database):
    with Session(postgres_database) as session, session.begin():
        repo = Repository(
            github_id=77, full_name="example/project", source_url="https://github.com/example/project"
        )
        session.add(repo)
        session.flush()
        upsert_issue(session, repo, raw_issue())
    with Session(postgres_database) as session:
        issue = session.scalar(select(Issue))
        payload = ReviewInput(
            **review_payload({"prediction_id": None, "snapshot_id": issue.snapshot_id, "review_revision": 0})
        )
        submit_review(session, issue, payload, "maintainer")
    with Session(postgres_database) as session, session.begin():
        repo = session.scalar(select(Repository))
        raw = raw_issue(day=1, body="A substantially revised report")
        upsert_issue(session, repo, raw)
    with Session(postgres_database) as session:
        counts = dashboard(session, IssueFilters(), "real")
        assert counts["reviewed"] == 0 and counts["awaiting_review"] == 1
        assert session.scalar(select(func.count()).select_from(Review)) == 1


def test_concurrent_identical_transport_retries_return_one_review(postgres_database):
    import threading
    import uuid

    with Session(postgres_database) as session, session.begin():
        seed(session)
        session.flush()
        snapshot_id = session.get(Issue, 1).snapshot_id
    payload = ReviewInput(
        action="correct",
        category="bug",
        snapshot_id=snapshot_id,
        expected_revision=0,
        idempotency_key=str(uuid.uuid4()),
    )
    barrier = threading.Barrier(2)

    def write(_):
        with Session(postgres_database) as session:
            issue = session.get(Issue, 1)
            barrier.wait(timeout=10)
            return submit_review(session, issue, payload, "maintainer").id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(write, [1, 2]))
    assert ids[0] == ids[1]
    with Session(postgres_database) as session:
        assert session.scalar(select(func.count()).select_from(Review)) == 1
        assert session.get(Issue, 1).review_revision == 1
