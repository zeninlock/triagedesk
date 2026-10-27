import json
import uuid

import httpx
import pytest
from conftest import raw_issue
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from triagedesk import ai_labels, triage
from triagedesk.ai_labels import AIUnavailable, AnalysisResult, analyze_issue, analyze_repository
from triagedesk.config import settings
from triagedesk.github import upsert_issue
from triagedesk.issue_lifecycle import purge_closed
from triagedesk.models import (
    Issue,
    LabelAnalysis,
    LabelAssignment,
    LabelReview,
    Repository,
    Snapshot,
    utcnow,
)
from triagedesk.text import digest


def proposed(confidence=0.96, uncertain=False):
    return {
        "summary": "The API crashes after an update.",
        "explanation": "The report describes a crash in the API.",
        "labels": [
            {"group": "type", "name": "bug", "confidence": confidence, "evidence": "crashes"},
            {"group": "scope", "name": "API", "confidence": confidence, "evidence": "API"},
        ],
        "confidence": confidence,
        "uncertain": uncertain,
    }


def repo_issues(engine):
    with Session(engine) as db:
        repo = Repository(
            github_id=77,
            full_name="maintainer/project",
            source_url="https://github.com/maintainer/project",
            synthetic=True,
        )
        db.add(repo)
        db.flush()
        for number in [1, 2]:
            upsert_issue(
                db, repo, raw_issue(number, title="API crashes after update", body="Previously worked.")
            )
        db.commit()
        return repo.id, list(db.scalars(select(Issue.id).order_by(Issue.id)))


def use_ai(monkeypatch, output=None):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_unit_test_only")
    settings.cache_clear()
    calls = []

    def infer(*args):
        calls.append(args)
        return AnalysisResult.model_validate(output or proposed())

    monkeypatch.setattr(ai_labels, "request_analysis", infer)
    return calls


def test_structured_provider_request_is_bounded_and_does_not_send_credentials(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_unit_test_only")
    settings.cache_clear()

    def respond(request):
        assert request.url == "https://api.groq.com/openai/v1/chat/completions"
        payload = json.loads(request.content)
        assert "gsk_unit_test_only" not in request.content.decode()
        assert "taxonomy" not in json.loads(payload["messages"][1]["content"])
        assert payload["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(proposed())}}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        output = ai_labels.request_analysis(
            "API crashes after update", "Previously worked.", [], ai_labels.DEFAULT_TAXONOMY, client
        )
    assert output.confidence == 0.96 and not output.uncertain


@pytest.mark.parametrize(
    "alteration", ["unknown_label", "wrong_group", "invented_evidence", "nan", "out_of_range", "duplicate"]
)
def test_invalid_model_outputs_are_never_auto_published(monkeypatch, alteration):
    monkeypatch.setenv("GROQ_API_KEY", "unit-test-key")
    settings.cache_clear()
    value = proposed()
    if alteration == "unknown_label":
        value["labels"][0]["name"] = "DROP TABLE issues"
    if alteration == "wrong_group":
        value["labels"][0]["group"] = "workflow"
    if alteration == "invented_evidence":
        value["labels"][0]["evidence"] = "no actual evidence"
    if alteration == "nan":
        value["confidence"] = float("nan")
    if alteration == "out_of_range":
        value["confidence"] = 1.5
    if alteration == "duplicate":
        value["labels"].append(value["labels"][0])
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})
    )
    with httpx.Client(transport=transport) as client, pytest.raises(AIUnavailable, match="invalid_output"):
        ai_labels.request_analysis("API crashes after update", "", [], ai_labels.DEFAULT_TAXONOMY, client)


def test_model_confidence_uses_the_lowest_label_score_and_requires_a_type(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "unit-test-key")
    settings.cache_clear()
    value = proposed()
    value["labels"][1]["confidence"] = 0.4

    def run(value):
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(value)}}]}
            )
        )
        with httpx.Client(transport=transport) as client:
            return ai_labels.request_analysis(
                "API crashes after update", "", [], ai_labels.DEFAULT_TAXONOMY, client
            )

    assert run(value).confidence == 0.4
    value["labels"] = [value["labels"][1]]
    assert run(value).uncertain


def test_cached_analysis_survives_sessions_and_is_not_called_again(database, monkeypatch):
    repo_id, ids = repo_issues(database)
    calls = use_ai(monkeypatch)
    assert analyze_issue(database, ids[0]) == "analyzed"
    assert analyze_issue(database, ids[0]) == "cached"
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(LabelAnalysis)) == 1
        assert db.scalar(select(func.count()).select_from(LabelAssignment)) == 2
    assert len(calls) == 1


@pytest.mark.parametrize(
    "confidence,uncertain,expected",
    [(0.96, False, "auto_sorted"), (0.6, False, "needs_review"), (0.99, True, "needs_review")],
)
def test_review_queue_only_contains_uncertain_results(database, monkeypatch, confidence, uncertain, expected):
    repo_id, ids = repo_issues(database)
    use_ai(monkeypatch, proposed(confidence, uncertain))
    analyze_issue(database, ids[0])
    with Session(database) as db:
        repo = db.get(Repository, repo_id)
        data = triage.list_labeled_issues(db, repo, expected)
        assert data["total"] == 1 and data["items"][0]["id"] == ids[0]
        assert triage.summary(db, repo)["counts"]["pending"] == 1


def review_payload(db, repo, issue):
    return triage.LabelReviewInput(
        labels=[
            {"group": "type", "name": "documentation"},
            {"group": "workflow", "name": "waiting for op's response"},
        ],
        snapshot_id=issue.snapshot_id,
        expected_revision=issue.review_revision,
        taxonomy_hash=digest(ai_labels.taxonomy_for(repo)),
        idempotency_key=str(uuid.uuid4()),
        note="Confirmed by maintainer",
    )


def test_review_moves_issue_to_reviewed_and_overrides_labels_without_losing_ai_evidence(
    database, monkeypatch
):
    repo_id, ids = repo_issues(database)
    use_ai(monkeypatch, proposed(0.6))
    analyze_issue(database, ids[0])
    with Session(database) as db:
        repo, issue = db.get(Repository, repo_id), db.get(Issue, ids[0])
        payload = review_payload(db, repo, issue)
        first = triage.save_label_review(db, issue, repo, payload, "github:maintainer#42")
        assert triage.save_label_review(db, issue, repo, payload, "github:maintainer#42").id == first.id
        assert triage.list_labeled_issues(db, repo, "needs_review")["total"] == 0
        reviewed = triage.list_labeled_issues(db, repo, "reviewed")
        assert reviewed["total"] == 1
        assert {x["name"] for x in reviewed["items"][0]["labels"]} == {
            "documentation",
            "waiting for op's response",
        }
        assert (
            triage.list_labeled_issues(db, repo, group="workflow", label="waiting for op's response")["total"]
            == 1
        )
        assert triage.list_labeled_issues(db, repo, group="type", label="bug")["total"] == 0
        assert triage.summary(db, repo)["labels"]["type"]["bug"] == 1


def test_new_snapshot_invalidates_old_analysis_and_review(database, monkeypatch):
    repo_id, ids = repo_issues(database)
    calls = use_ai(monkeypatch)
    analyze_issue(database, ids[0])
    with Session(database) as db:
        repo, issue = db.get(Repository, repo_id), db.get(Issue, ids[0])
        old_snapshot = issue.snapshot_id
        payload = review_payload(db, repo, issue)
        triage.save_label_review(db, issue, repo, payload, "maintainer")
        changed = raw_issue(1, title="Different report", body="New issue content", day=1)
        upsert_issue(db, repo, changed)
        db.commit()
        assert issue.snapshot_id != old_snapshot
        assert triage.list_labeled_issues(db, repo, "reviewed")["total"] == 0
        with pytest.raises(Exception) as error:
            triage.save_label_review(
                db,
                issue,
                repo,
                payload.model_copy(update={"idempotency_key": str(uuid.uuid4())}),
                "maintainer",
            )
        assert error.value.status_code == 409
    assert analyze_issue(database, ids[0]) == "analyzed"
    assert len(calls) == 2
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(LabelReview)) == 1


def test_rate_limit_failure_is_persisted_and_does_not_repeat_across_issues(database, monkeypatch):
    repo_id, ids = repo_issues(database)
    use_ai(monkeypatch)
    calls = []

    def limited(*args):
        calls.append(1)
        raise AIUnavailable("rate_limited", 600)

    monkeypatch.setattr(ai_labels, "request_analysis", limited)
    analyze_repository(database, repo_id)
    again = analyze_repository(database, repo_id)
    assert len(calls) == 1 and again["waiting"] == 2
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(LabelAssignment)) == 0
        assert triage.summary(db, db.get(Repository, repo_id))["counts"]["needs_review"] == 0


def test_missing_key_keeps_issues_pending_without_fake_ai_results(database):
    repo_id, ids = repo_issues(database)
    assert not analyze_repository(database, repo_id)["configured"]
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(LabelAnalysis)) == 0
        assert triage.list_labeled_issues(db, db.get(Repository, repo_id), "pending")["total"] == 2


def test_changed_taxonomy_invalidates_cached_labels(database, monkeypatch):
    repo_id, ids = repo_issues(database)
    use_ai(monkeypatch)
    analyze_issue(database, ids[0])
    with Session(database) as db:
        repo = db.get(Repository, repo_id)
        repo.label_taxonomy = {**ai_labels.DEFAULT_TAXONOMY, "scope": ["database"]}
        db.commit()
        assert triage.summary(db, repo)["counts"]["pending"] == 2
        assert sum(triage.summary(db, repo)["labels"]["type"].values()) == 0


def test_closed_issue_purges_its_snapshots_ai_and_reviews_but_keeps_other_issues(database, monkeypatch):
    repo_id, ids = repo_issues(database)
    use_ai(monkeypatch)
    analyze_issue(database, ids[0])
    with Session(database) as db:
        repo, issue = db.get(Repository, repo_id), db.get(Issue, ids[0])
        triage.save_label_review(db, issue, repo, review_payload(db, repo, issue), "maintainer")
        raw = raw_issue(1, day=1)
        raw.update(state="closed", closed_at=utcnow().isoformat())
        upsert_issue(db, repo, raw)
        db.commit()
        assert purge_closed(db, repo_id) == 1
        assert db.get(Issue, ids[1]) is not None
        for table in [LabelAnalysis, LabelAssignment, LabelReview, Snapshot]:
            assert db.scalar(select(func.count()).select_from(table).where(table.issue_id == ids[0])) == 0
        assert db.scalar(select(func.count()).select_from(Issue)) == 1


def test_label_review_api_enforces_auth_validation_staleness_and_queue_separation(
    client, database, auth_headers, monkeypatch
):
    use_ai(monkeypatch, proposed(0.6))
    analyze_issue(database, 1)
    issue = client.get("/triage/issues/1").json()
    repository_id = client.get("/issues/1").json()["repository_id"]
    payload = {
        "labels": [{"group": "type", "name": "documentation"}],
        "snapshot_id": issue["snapshot_id"],
        "expected_revision": issue["review_revision"],
        "taxonomy_hash": issue["taxonomy_hash"],
        "idempotency_key": str(uuid.uuid4()),
    }
    assert client.post("/triage/issues/1/reviews", json=payload).status_code == 401
    assert (
        client.post(
            "/triage/issues/1/reviews",
            headers=auth_headers,
            json={**payload, "labels": [{"group": "scope", "name": "invented"}]},
        ).status_code
        == 422
    )
    assert client.post("/triage/issues/1/reviews", headers=auth_headers, json=payload).status_code == 201
    assert (
        client.get(f"/triage/{repository_id}/issues", params={"status": "needs_review"}).json()["total"] == 0
    )
    assert client.get(f"/triage/{repository_id}/issues", params={"status": "reviewed"}).json()["total"] == 1
    assert (
        client.post(
            "/triage/issues/1/reviews",
            headers=auth_headers,
            json={**payload, "idempotency_key": str(uuid.uuid4())},
        ).status_code
        == 409
    )
    monkeypatch.setenv("READ_ONLY", "true")
    settings.cache_clear()
    assert client.post("/triage/issues/1/reviews", headers=auth_headers, json=payload).status_code == 403


def test_truncated_report_requires_review_even_when_model_is_confident(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "unit-test-key")
    settings.cache_clear()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(proposed())}}]}
        )
    )
    with httpx.Client(transport=transport) as client:
        result = ai_labels.request_analysis(
            "API crashes", "a" * 11000, [], ai_labels.DEFAULT_TAXONOMY, client
        )
    assert result.uncertain and result.confidence == 0.96


def test_legacy_completed_review_is_visible_and_does_not_call_ai_again(
    client, database, auth_headers, monkeypatch
):
    calls = use_ai(monkeypatch)
    issue = client.get("/issues/1").json()
    payload = {
        "action": "correct",
        "category": "bug",
        "snapshot_id": issue["snapshot_id"],
        "expected_revision": issue["review_revision"],
        "idempotency_key": str(uuid.uuid4()),
        "note": "Pre-upgrade review",
    }
    assert client.post("/issues/1/reviews", headers=auth_headers, json=payload).status_code == 201
    assert analyze_issue(database, 1) == "cached" and not calls
    detail = client.get("/triage/issues/1").json()
    assert detail["status"] == "reviewed" and detail["history"][0]["note"] == "Pre-upgrade review"
