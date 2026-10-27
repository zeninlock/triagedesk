import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_ai_labels import proposed, repo_issues, review_payload, use_ai

from triagedesk import ai_labels, triage
from triagedesk.ai_labels import AnalysisResult, analyze_issue
from triagedesk.issue_lifecycle import purge_closed
from triagedesk.models import Issue, LabelAnalysis, LabelAssignment, LabelReview, Repository, Snapshot

pytestmark = pytest.mark.postgres


def test_postgres_claim_prevents_duplicate_provider_calls(postgres_database, monkeypatch):
    engine = postgres_database
    repo_id, ids = repo_issues(engine)
    use_ai(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow(*args):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return AnalysisResult.model_validate(proposed())

    monkeypatch.setattr(ai_labels, "request_analysis", slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(analyze_issue, engine, ids[0])
        try:
            assert entered.wait(5)
            second = pool.submit(analyze_issue, engine, ids[0])
            assert second.result(timeout=3) == "waiting"
        finally:
            release.set()
        assert first.result(timeout=5) == "analyzed"
    assert len(calls) == 1
    assert analyze_issue(engine, ids[0]) == "cached"
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(LabelAnalysis)) == 1
        assert triage.list_labeled_issues(db, db.get(Repository, repo_id), "auto_sorted")["total"] == 1


@pytest.mark.parametrize("identical", [False, True])
def test_postgres_label_reviews_are_atomic_and_retries_idempotent(postgres_database, monkeypatch, identical):
    engine = postgres_database
    repo_id, ids = repo_issues(engine)
    use_ai(monkeypatch, proposed(0.6))
    analyze_issue(engine, ids[0])
    with Session(engine) as db:
        data = review_payload(db, db.get(Repository, repo_id), db.get(Issue, ids[0])).model_dump()
    barrier = threading.Barrier(2)

    def save(index):
        with Session(engine) as db:
            repo, issue = db.get(Repository, repo_id), db.get(Issue, ids[0])
            payload = {**data, "idempotency_key": data["idempotency_key"] if identical else str(uuid.uuid4())}
            barrier.wait(timeout=5)
            try:
                result = triage.save_label_review(
                    db, issue, repo, triage.LabelReviewInput(**payload), "github:maintainer#42"
                )
                return 201, result.id
            except HTTPException as exc:
                return exc.status_code, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [0, 1]))
    assert sorted(code for code, _ in results) == ([201, 201] if identical else [201, 409])
    if identical:
        assert results[0][1] == results[1][1]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(LabelReview)) == 1
        assert triage.list_labeled_issues(db, db.get(Repository, repo_id), "needs_review")["total"] == 0
        assert triage.list_labeled_issues(db, db.get(Repository, repo_id), "reviewed")["total"] == 1


def test_postgres_purge_removes_closed_issue_and_all_its_label_cache(postgres_database, monkeypatch):
    engine = postgres_database
    repo_id, ids = repo_issues(engine)
    use_ai(monkeypatch, proposed(0.6))
    analyze_issue(engine, ids[0])
    analyze_issue(engine, ids[1])
    with Session(engine) as db:
        repo, issue = db.get(Repository, repo_id), db.get(Issue, ids[0])
        triage.save_label_review(db, issue, repo, review_payload(db, repo, issue), "maintainer")
        issue.state = "closed"
        db.commit()
        assert purge_closed(db, repo_id) == 1
        for table in [LabelAnalysis, LabelAssignment, LabelReview, Snapshot]:
            assert db.scalar(select(func.count()).select_from(table).where(table.issue_id == ids[0])) == 0
        assert db.get(Issue, ids[1])
        assert triage.summary(db, repo)["total"] == 1
