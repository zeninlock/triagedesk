import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest
from conftest import raw_issue
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_ai_labels import proposed, repo_issues, review_payload, use_ai

from triagedesk import ai_labels, triage
from triagedesk.ai_labels import AnalysisResult, analyze_issue
from triagedesk.config import settings
from triagedesk.github import upsert_issue
from triagedesk.issue_lifecycle import purge_closed
from triagedesk.models import (
    Issue,
    LabelAnalysis,
    LabelAssignment,
    LabelReview,
    Repository,
    Review,
    Snapshot,
    utcnow,
)

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


def test_postgres_failed_attempt_becomes_visible_and_direct_retry_reuses_cache(
    postgres_database, monkeypatch
):
    engine = postgres_database
    repo_id, ids = repo_issues(engine)
    monkeypatch.setenv("GROQ_API_KEY", "dummy-key-never-used-live")
    settings.cache_clear()
    rejected = True
    calls = []
    original = ai_labels.request_analysis

    def provider(request):
        calls.append(request)
        if rejected:
            return httpx.Response(401, json={"error": {"message": "private-provider-message"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(proposed())}}]})

    def infer(*args):
        with httpx.Client(transport=httpx.MockTransport(provider)) as client:
            return original(*args, client=client)

    monkeypatch.setattr(ai_labels, "request_analysis", infer)
    assert ai_labels.analyze_repository(engine, repo_id)["unavailable"] == 1
    with Session(engine) as db:
        repo = db.get(Repository, repo_id)
        before = triage.summary(db, repo)
        assert before["ai_activity"]["error"]["code"] == "invalid_credentials"
        assert before["ai_activity"]["states"] == {"queued": 1, "running": 0, "failed": 1}
        ai_labels.retry_correctable_failures(db, repo)
    rejected = False
    assert ai_labels.analyze_repository(engine, repo_id)["analyzed"] == 2
    assert ai_labels.analyze_repository(engine, repo_id)["cached"] == 2
    assert len(calls) == 3
    with Session(engine) as db:
        after = triage.summary(db, db.get(Repository, repo_id))
        assert after["counts"]["auto_sorted"] == 2 and after["counts"]["pending"] == 0
        assert after["ai_activity"]["error"] is None
        assert after["ai_activity"]["revision"] != before["ai_activity"]["revision"]


def test_postgres_three_invalid_outputs_retry_once_then_remain_cached_for_review(
    postgres_database, monkeypatch
):
    engine = postgres_database
    repo_id, ids = repo_issues(engine)
    original = ai_labels.request_analysis
    # Reproduce the production pattern: two reviewed reports and three discarded outputs.
    with Session(engine) as db:
        repo = db.get(Repository, repo_id)
        for number in (4, 5, 6):
            upsert_issue(
                db,
                repo,
                raw_issue(number, title=f"API crashes in report {number}", body="Previously worked."),
            )
        first = db.get(Issue, ids[0])
        db.add(
            Review(
                issue_id=first.id,
                snapshot_id=first.snapshot_id,
                revision=1,
                action="correct",
                category="bug",
                reviewer="test-maintainer",
                idempotency_key=str(uuid.uuid4()),
                payload_hash="f" * 64,
            )
        )
        db.commit()
    calls = use_ai(monkeypatch)
    analyze_issue(engine, ids[1])
    with Session(engine) as db:
        repo, second = db.get(Repository, repo_id), db.get(Issue, ids[1])
        triage.save_label_review(db, second, repo, review_payload(db, repo, second), "test-maintainer")
        kept_analysis = db.scalar(select(LabelAnalysis).where(LabelAnalysis.issue_id == second.id)).id
        for issue in db.scalars(
            select(Issue).where(Issue.repository_id == repo_id, Issue.number.in_([4, 5, 6]))
        ):
            db.add(
                LabelAnalysis(
                    issue_id=issue.id,
                    snapshot_id=issue.snapshot_id,
                    analyzer_key=ai_labels.analyzer_key(repo),
                    model=settings().ai_model,
                    status="failed",
                    error="invalid_output",
                    retry_after=utcnow() - timedelta(seconds=1),
                )
            )
        db.commit()
    calls.clear()
    paused = ai_labels.analyze_repository(engine, repo_id)
    assert paused["needs_attention"] == 3 and not calls
    value = proposed()
    value["labels"][1]["evidence"] = "An invented quotation"
    provider_calls = []

    def provider(request):
        provider_calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})

    def infer(*args):
        with httpx.Client(transport=httpx.MockTransport(provider)) as client:
            return original(*args, client=client)

    monkeypatch.setattr(ai_labels, "request_analysis", infer)
    with Session(engine) as db:
        ai_labels.retry_correctable_failures(db, db.get(Repository, repo_id))
    assert ai_labels.analyze_repository(engine, repo_id)["analyzed"] == 3
    for _ in range(4):
        assert ai_labels.analyze_repository(engine, repo_id)["cached"] == 4
    assert len(provider_calls) == 3
    with Session(engine) as db:
        info = triage.summary(db, db.get(Repository, repo_id))
        assert info["counts"] == {"auto_sorted": 0, "needs_review": 3, "reviewed": 2, "pending": 0}
        assert db.get(LabelAnalysis, kept_analysis).status == "complete"
