import uuid

import pytest


def review_payload(issue, **updates):
    return {
        "action": "correct",
        "category": "enhancement",
        "note": "Maintainer clarification",
        "prediction_id": issue["prediction_id"],
        "snapshot_id": issue["snapshot_id"],
        "expected_revision": issue["review_revision"],
        "idempotency_key": str(uuid.uuid4()),
        **updates,
    }


def test_reviews_persist_audit_stale_and_repeated(client, auth_headers):
    issue = client.get("/issues/1").json()
    before = client.get("/dashboard").json()
    payload = review_payload(issue)
    first = client.post("/issues/1/reviews", json=payload, headers=auth_headers)
    assert first.status_code == 201
    repeated = client.post("/issues/1/reviews", json=payload, headers=auth_headers)
    assert repeated.json()["id"] == first.json()["id"]
    conflict = client.post("/issues/1/reviews", json=review_payload(issue), headers=auth_headers)
    assert conflict.status_code == 409
    tampered = client.post("/issues/1/reviews", json={**payload, "note": "different"}, headers=auth_headers)
    assert tampered.status_code == 409
    issue = client.get("/issues/1").json()
    deferred = client.post(
        "/issues/1/reviews", json=review_payload(issue, action="defer", category=None), headers=auth_headers
    )
    assert deferred.status_code == 201
    history = client.get("/issues/1/reviews").json()
    assert len(history) == 2 and history[0]["action"] == "defer" and history[1]["action"] == "correct"
    assert before["imported"] == 24
    assert client.get("/dashboard").json()["reviewed"] == 0  # Defer reopens review work.


def test_dashboard_counts_follow_all_filters(client, auth_headers):
    issue = client.get("/issues/1").json()
    assert (
        client.post("/issues/1/reviews", json=review_payload(issue), headers=auth_headers).status_code == 201
    )
    for filters in (
        {"state": "open"},
        {"category": "enhancement"},
        {"review_status": "awaiting"},
        {"review_status": "reviewed", "category_source": "reviewed"},
        {"search": "export"},
        {"created_from": "2026-08-01T00:00:00Z", "created_before": "2026-09-01T00:00:00Z"},
    ):
        queue = client.get("/issues", params={**filters, "page_size": 100}).json()
        totals = client.get("/dashboard", params=filters).json()
        assert totals["imported"] == queue["total"] == len(queue["items"])
        assert totals["open"] + totals["closed"] == totals["imported"]
        assert totals["reviewed"] == sum(r["review_status"] == "reviewed" for r in queue["items"])
        assert sum(totals["predicted_categories"].values()) == queue["total"]


def test_manual_review_without_model(client, auth_headers):
    issue = client.get("/issues/21").json()
    assert issue["prediction"] is None
    response = client.post("/issues/21/reviews", json=review_payload(issue), headers=auth_headers)
    assert response.status_code == 201
    assert client.get("/issues/21").json()["reviewed_category"] == "enhancement"


def test_read_only_and_authorization_enforced_by_api(client, auth_headers, monkeypatch):
    from triagedesk.config import settings

    issue = client.get("/issues/1").json()
    payload = review_payload(issue)
    assert client.post("/issues/1/reviews", json=payload).status_code == 401
    assert (
        client.post(
            "/issues/1/reviews", json=payload, headers={"Authorization": "Bearer incorrect"}
        ).status_code
        == 401
    )
    monkeypatch.setenv("READ_ONLY", "true")
    settings.cache_clear()
    assert client.post("/issues/1/reviews", json=payload, headers=auth_headers).status_code == 403


@pytest.mark.parametrize(
    "params",
    [{"page_size": 101}, {"page": 0}, {"category": "uncertain"}, {"created_from": "2020-01-01T00:00:00"}],
)
def test_filters_validate_bounds(client, params):
    response = client.get("/issues", params=params)
    assert response.status_code == 422 and "error" in response.json()


def test_accept_requires_matching_prediction(client, auth_headers):
    issue = client.get("/issues/1").json()
    response = client.post(
        "/issues/1/reviews",
        json=review_payload(issue, action="accept", category="question"),
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_safe_judgment_write_and_idempotence(client, auth_headers):
    query, candidate = client.get("/issues/1").json(), client.get("/issues/4").json()
    payload = {
        "candidate_issue_id": candidate["id"],
        "query_snapshot_id": query["snapshot_id"],
        "candidate_snapshot_id": candidate["snapshot_id"],
        "judgment": "related",
        "idempotency_key": str(uuid.uuid4()),
    }
    assert client.post("/issues/1/judgments", json=payload).status_code == 401
    first = client.post("/issues/1/judgments", json=payload, headers=auth_headers)
    assert first.status_code == 201 and first.json()["purpose"] == "ui"
    assert (
        client.post("/issues/1/judgments", json=payload, headers=auth_headers).json()["id"]
        == first.json()["id"]
    )
    assert (
        client.post(
            "/issues/1/judgments", json={**payload, "judgment": "unrelated"}, headers=auth_headers
        ).status_code
        == 409
    )


def test_fixture_metrics_not_exposed_as_real_evaluation(client):
    assert client.get("/models").json()["classification"] is None
    assert not client.post("/classify", json={"title": "A report"}).json()["available"]
    assert client.post("/classify", json={"title": "a" * 501}).status_code == 422
    assert client.get("/issues/9999").status_code == 404
