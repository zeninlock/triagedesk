from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from conftest import raw_issue
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_ai_labels import proposed

from triagedesk import ai_labels, triage
from triagedesk.config import settings
from triagedesk.github import upsert_issue
from triagedesk.models import Issue, Repository


@pytest.mark.postgres
def test_concurrent_analysis_claim_makes_only_one_provider_call(postgres_database, monkeypatch):
    engine = postgres_database
    monkeypatch.setenv("OPENAI_API_KEY", "sk_fake_test_key")
    settings.cache_clear()
    with Session(engine) as db:
        repo = Repository(
            github_id=77, full_name="maintainer/project", source_url="https://github.com/maintainer/project"
        )
        db.add(repo)
        db.flush()
        upsert_issue(db, repo, raw_issue())
        db.commit()
        issue_id = db.scalar(select(Issue.id))
    entered, release = Event(), Event()
    calls = []

    def infer(*args):
        calls.append(args)
        entered.set()
        assert release.wait(10)
        return ai_labels.classification_result(ai_labels.IssueClassification.model_validate(proposed()))

    monkeypatch.setattr(ai_labels, "request_analysis", infer)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(ai_labels.analyze_issue, engine, issue_id)
        assert entered.wait(10)
        second = pool.submit(ai_labels.analyze_issue, engine, issue_id)
        assert second.result(10) == "waiting"
        release.set()
        assert first.result(10) == "analyzed"
    assert len(calls) == 1


@pytest.mark.postgres
def test_concurrent_work_status_update_conflicts(postgres_database):
    from fastapi import HTTPException

    engine = postgres_database
    with Session(engine) as db:
        repo = Repository(
            github_id=78, full_name="maintainer/project", source_url="https://github.com/maintainer/project"
        )
        db.add(repo)
        db.flush()
        upsert_issue(db, repo, raw_issue())
        db.commit()
        issue_id = db.scalar(select(Issue.id))

    def change(status):
        with Session(engine) as db:
            issue = db.get(Issue, issue_id)
            try:
                return triage.save_work_status(
                    db,
                    issue,
                    triage.WorkStatusInput(
                        status=status, expected_revision=0, idempotency_key="concurrent-" + status
                    ),
                    "maintainer",
                ).to_status
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(change, status) for status in ("blocked", "in progress")]
        results = [f.result(10) for f in futures]
    assert results.count(409) == 1
    with Session(engine) as db:
        assert db.get(Issue, issue_id).work_revision == 1
