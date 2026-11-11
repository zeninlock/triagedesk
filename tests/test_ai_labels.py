import json
from datetime import timedelta

import httpx
import pytest
from conftest import raw_issue
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from triagedesk import ai_labels, triage
from triagedesk.ai_labels import AIUnavailable, IssueClassification, classification_result
from triagedesk.config import settings
from triagedesk.github import upsert_issue
from triagedesk.issue_lifecycle import purge_closed
from triagedesk.models import (
    Issue,
    IssueActivity,
    LabelAnalysis,
    LabelAssignment,
    LabelReview,
    Repository,
    Snapshot,
)
from triagedesk.text import digest


def proposed(**changes):
    return {
        "type": "type: bug",
        "priority": "priority: high",
        "priority_inferred": True,
        "area": "area: api",
        "help_wanted": True,
        "good_first_issue": False,
        "summary": "API fails for all users",
        "explanation": "The endpoint failure blocks all users without a workaround.",
        "confidence": 0.96,
        "uncertain": False,
        **changes,
    }


def provider_response(content):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "model": "gpt-4.1-mini",
        "status": "completed",
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": content, "annotations": []}],
            }
        ],
    }


@pytest.fixture
def issues(database):
    with Session(database) as db:
        repo = Repository(
            github_id=77, full_name="maintainer/project", source_url="https://github.com/maintainer/project"
        )
        db.add(repo)
        db.flush()
        for n in (1, 2, 3):
            upsert_issue(db, repo, raw_issue(n))
        db.commit()
        return repo.id, list(db.scalars(select(Issue.id).order_by(Issue.id)))


def use_ai(monkeypatch, **changes):
    monkeypatch.setenv("OPENAI_API_KEY", "sk_fake_test_key")
    settings.cache_clear()
    calls = []

    def request(*args):
        calls.append(args)
        return classification_result(IssueClassification.model_validate(proposed(**changes)))

    monkeypatch.setattr(ai_labels, "request_analysis", request)
    return calls


@pytest.mark.parametrize("kind", ai_labels.DEFAULT_TAXONOMY["type"])
def test_all_five_types_and_singletons(kind):
    result = classification_result(IssueClassification.model_validate(proposed(type=kind)))
    for group in ("type", "priority", "area"):
        assert sum(x.group == group for x in result.labels) == 1
    assert result.labels[0].name == kind


def test_unknown_urgency_always_defaults_low_and_simple_work_implies_help_wanted():
    result = classification_result(
        IssueClassification.model_validate(
            proposed(priority_inferred=False, area=None, good_first_issue=True, help_wanted=False)
        )
    )
    assert next(x.name for x in result.labels if x.group == "priority") == "priority: low"
    assert {x.name for x in result.labels if x.group == "contributor"} == {"help wanted", "good first issue"}
    assert not any(x.group == "area" for x in result.labels)


@pytest.mark.parametrize(
    "changes",
    [
        {"type": "unapproved"},
        {"priority": "critical"},
        {"area": "billing"},
        {"confidence": float("nan")},
        {"confidence": 1.1},
        {"good_first_issue": "yes"},
        {"work_status": "blocked"},
    ],
)
def test_invalid_or_status_containing_model_payloads_rejected(changes):
    with pytest.raises(ValidationError):
        IssueClassification.model_validate(proposed(**changes))


def test_openai_sdk_request_is_structured_bounded_and_private(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk_fake_test_key")
    settings.cache_clear()
    calls = []

    def respond(request):
        calls.append(request)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer sk_fake_test_key"
        body = json.loads(request.content)
        assert body["store"] is False and body["model"] == "gpt-4.1-mini"
        assert "sk_fake_test_key" not in request.content.decode()
        assert body["text"]["format"]["strict"] is True
        schema = body["text"]["format"]["schema"]
        assert schema["additionalProperties"] is False
        assert "work_status" not in schema["properties"]
        assert set(schema["required"]) == set(schema["properties"])
        text = json.loads(body["input"][1]["content"])
        assert len(text["title"]) <= 500 and len(text["body"]) <= 10000
        return httpx.Response(200, json=provider_response(json.dumps(proposed())))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        output = ai_labels.request_analysis("x" * 600, "y" * 11000, [], ai_labels.DEFAULT_TAXONOMY, client)
    assert len(calls) == 1 and output.uncertain  # Partial issue text requires human review.


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (401, "invalid_api_key", "invalid_credentials"),
        (403, "access_denied", "permission_denied"),
        (429, "rate_limit_exceeded", "rate_limited"),
        (429, "insufficient_quota", "billing_required"),
        (404, "model_not_found", "model_unavailable"),
        (500, "server_error", "provider_unavailable"),
    ],
)
def test_provider_failures_are_safe_and_not_retried_by_sdk(monkeypatch, status, code, expected):
    monkeypatch.setenv("OPENAI_API_KEY", "sk_fake_test_key")
    settings.cache_clear()
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status,
            json={"error": {"message": "PRIVATE DIAGNOSTIC", "code": code, "type": "test"}},
            headers={"retry-after": "60"},
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client, pytest.raises(AIUnavailable) as exc:
        ai_labels.request_analysis("API issue", "Fails", [], ai_labels.DEFAULT_TAXONOMY, client)
    assert str(exc.value) == expected and len(calls) == 1
    assert "PRIVATE" not in str(exc.value)


@pytest.mark.parametrize(
    "variant,expected",
    [("invalid", "schema_invalid"), ("refused", "response_refused"), ("incomplete", "response_truncated")],
)
def test_invalid_refused_or_truncated_output_never_published(monkeypatch, variant, expected):
    monkeypatch.setenv("OPENAI_API_KEY", "sk_fake_test_key")
    settings.cache_clear()
    response = provider_response(json.dumps({"wrong": 1}))
    if variant == "refused":
        response["output"][0]["content"] = [{"type": "refusal", "refusal": "Cannot comply"}]
    if variant == "incomplete":
        response.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))) as client,
        pytest.raises(AIUnavailable, match=expected),
    ):
        ai_labels.request_analysis("API issue", "Fails", [], ai_labels.DEFAULT_TAXONOMY, client)


def test_completed_analysis_is_cached_and_status_changes_do_not_call_model(database, issues, monkeypatch):
    repo_id, ids = issues
    calls = use_ai(monkeypatch)
    assert ai_labels.analyze_issue(database, ids[0]) == "analyzed"
    with Session(database) as db:
        issue = db.get(Issue, ids[0])
        triage.save_work_status(
            db,
            issue,
            triage.WorkStatusInput(
                status="in progress", expected_revision=0, idempotency_key="status-first-change"
            ),
            "maintainer",
        )
    assert ai_labels.analyze_issue(database, ids[0]) == "cached" and len(calls) == 1
    with Session(database) as db:
        page = triage.list_labeled_issues(db, db.get(Repository, repo_id), work_status="in progress")
        assert page["total"] == 1 and page["items"][0]["status"] == "auto_sorted"
        assert db.get(Issue, ids[0]).work_status == "in progress"


def test_human_review_overrides_ai_distribution_and_prevents_repeat_calls(database, issues, monkeypatch):
    repo_id, ids = issues
    calls = use_ai(monkeypatch)
    ai_labels.analyze_issue(database, ids[0])
    with Session(database) as db:
        issue, repo = db.get(Issue, ids[0]), db.get(Repository, repo_id)
        payload = triage.LabelReviewInput(
            labels=[
                {"group": "type", "name": "type: docs"},
                {"group": "priority", "name": "priority: low"},
                {"group": "contributor", "name": "good first issue"},
            ],
            snapshot_id=issue.snapshot_id,
            expected_revision=0,
            taxonomy_hash=digest(ai_labels.DEFAULT_TAXONOMY),
            idempotency_key="human-review-first",
        )
        row = triage.save_label_review(db, issue, repo, payload, "maintainer")
        assert triage.save_label_review(db, issue, repo, payload, "maintainer").id == row.id
        summary = triage.summary(db, repo)
        assert summary["labels"]["type"]["type: docs"] == 1
        assert summary["labels"]["type"]["type: bug"] == 0
        assert summary["counts"]["reviewed"] == 1
    assert ai_labels.analyze_issue(database, ids[0]) == "cached" and len(calls) == 1


def test_new_snapshot_keeps_work_status_and_requires_new_analysis(database, issues, monkeypatch):
    repo_id, ids = issues
    calls = use_ai(monkeypatch)
    ai_labels.analyze_issue(database, ids[0])
    with Session(database) as db:
        issue, repo = db.get(Issue, ids[0]), db.get(Repository, repo_id)
        issue.work_status = "blocked"
        raw = raw_issue(1, body="Changed issue body")
        raw["updated_at"] = (issue.updated_at + timedelta(days=1)).isoformat()
        upsert_issue(db, repo, raw)
        db.commit()
    assert ai_labels.analyze_issue(database, ids[0]) == "analyzed" and len(calls) == 2
    with Session(database) as db:
        assert db.get(Issue, ids[0]).work_status == "blocked"


def test_timestamp_only_update_reuses_snapshot(database, issues):
    repo_id, ids = issues
    with Session(database) as db:
        issue, repo = db.get(Issue, ids[0]), db.get(Repository, repo_id)
        old = issue.snapshot_id
        # Pre-upgrade snapshots included source timestamps in their hash. Reuse them by content too.
        db.execute(
            update(Snapshot)
            .where(Snapshot.id == old)
            .values(
                snapshot_hash=digest([issue.title, issue.body, issue.labels, issue.updated_at.isoformat()])
            )
        )
        raw = raw_issue(1)
        raw["updated_at"] = (issue.updated_at + timedelta(days=1)).isoformat()
        upsert_issue(db, repo, raw)
        db.commit()
        assert issue.snapshot_id == old


@pytest.mark.parametrize("reason", ["rate_limited", "invalid_credentials", "billing_required"])
def test_provider_errors_stop_batch_and_do_not_repeat_on_other_issues(database, issues, monkeypatch, reason):
    repo_id, ids = issues
    monkeypatch.setenv("OPENAI_API_KEY", "sk_fake_test_key")
    settings.cache_clear()
    calls = []

    def fail(*args):
        calls.append(args)
        raise AIUnavailable(reason)

    monkeypatch.setattr(ai_labels, "request_analysis", fail)
    ai_labels.analyze_repository(database, repo_id)
    ai_labels.analyze_repository(database, repo_id)
    assert len(calls) == 1


def test_closed_issue_purge_removes_dependents(database, issues, monkeypatch):
    repo_id, ids = issues
    use_ai(monkeypatch)
    ai_labels.analyze_issue(database, ids[0])
    with Session(database) as db:
        issue = db.get(Issue, ids[0])
        triage.save_work_status(
            db,
            issue,
            triage.WorkStatusInput(
                status="blocked", expected_revision=0, idempotency_key="purge-status-test"
            ),
            "maintainer",
        )
        issue.state = "closed"
        db.commit()
        assert purge_closed(db, repo_id) == 1
        for model in (LabelAnalysis, LabelAssignment, LabelReview, IssueActivity, Snapshot):
            assert db.scalar(select(func.count()).select_from(model).where(model.issue_id == ids[0])) == 0
