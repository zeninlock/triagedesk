from datetime import timedelta

import httpx
import pytest
from conftest import raw_issue
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from triagedesk import authentication, connection_routes, connections
from triagedesk.api import app
from triagedesk.config import settings
from triagedesk.github import GitHubClient
from triagedesk.models import (
    AuthSession,
    ConnectionJob,
    DeviceLogin,
    Issue,
    Prediction,
    Repository,
    RepositoryAccess,
    Review,
    utcnow,
)

TOKEN = "github_test_provider_credential"
USER = {"id": 42, "login": "maintainer"}
REPO = {
    "id": 77,
    "full_name": "maintainer/project",
    "private": False,
    "has_issues": True,
    "html_url": "https://github.com/maintainer/project",
    "owner": {"id": 42, "type": "User"},
}


@pytest.fixture
def github_client(database, monkeypatch):
    monkeypatch.setenv("MODE", "real")
    monkeypatch.setenv("AUTH_MODE", "github")
    monkeypatch.setenv("AUTH_ENCRYPTION_KEY", "a-test-only-random-key-with-more-than-32-characters")
    settings.cache_clear()
    with TestClient(app) as client:
        yield client


def identity_provider(monkeypatch, repo=None, permission=None):
    def get(path, token):
        assert token == TOKEN
        if path == "/user":
            return 200, USER
        if "/collaborators/" in path:
            return 200, permission or {"permission": "read", "role_name": "read", "user": USER}
        return 200, repo or REPO

    monkeypatch.setattr(authentication, "github_get", get)


def login(client):
    response = client.post("/auth/token", json={"token": TOKEN})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def grant(db_engine, user_id=42, repo=REPO):
    with Session(db_engine) as db:
        row = Repository(github_id=repo["id"], full_name=repo["full_name"], source_url=repo["html_url"])
        db.add(row)
        db.flush()
        db.add(RepositoryAccess(repository_id=row.id, github_user_id=user_id, role="owner"))
        db.commit()
        return row.id


def test_identity_is_verified_and_credentials_are_encrypted(github_client, database, monkeypatch):
    identity_provider(monkeypatch)
    headers = login(github_client)
    me = github_client.get("/auth/session", headers=headers)
    assert me.json()["login"] == "maintainer"
    assert me.headers["cache-control"] == "no-store"
    with Session(database) as db:
        row = db.scalar(select(AuthSession))
        assert row.encrypted_token != TOKEN
        assert authentication.decrypt(row.encrypted_token) == TOKEN
        assert row.token_hash != headers["Authorization"].removeprefix("Bearer ")
    assert (
        github_client.post("/auth/token", json={"token": TOKEN, "login": "somebody-else"}).status_code == 422
    )
    assert github_client.get("/issues").status_code == 401
    assert (
        github_client.get("/issues", headers={"Authorization": "Bearer test-review-secret"}).status_code
        == 401
    )


def test_session_expiry_and_logout_are_enforced(github_client, database, monkeypatch):
    identity_provider(monkeypatch)
    headers = login(github_client)
    assert github_client.post("/auth/logout", headers=headers).status_code == 200
    assert github_client.get("/auth/session", headers=headers).status_code == 401
    headers = login(github_client)
    with Session(database) as db:
        row = db.scalar(select(AuthSession))
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert github_client.get("/auth/session", headers=headers).status_code == 401


@pytest.mark.parametrize(
    "value",
    [
        "http://github.com/maintainer/project",
        "https://evil.example/maintainer/project",
        "https://github.com@evil.example/maintainer/project",
        "../project",
        "https://github.com/maintainer/project?token=secret",
    ],
)
def test_invalid_repository_urls_are_rejected_before_fetch(github_client, monkeypatch, value):
    identity_provider(monkeypatch)
    headers = login(github_client)
    assert github_client.post("/connections", headers=headers, json={"repository": value}).status_code == 422


def test_personal_owner_and_organization_roles_are_verified(github_client, monkeypatch):
    identity_provider(monkeypatch)
    headers = login(github_client)
    with Session(connections.database.engine()) as db:
        principal = authentication.principal_for(db, headers["Authorization"].split()[1])
        assert authentication.verify_maintainer(principal, "maintainer/project")[1] == "owner"
        org = {**REPO, "owner": {"id": 88, "type": "Organization"}}
        identity_provider(
            monkeypatch, repo=org, permission={"permission": "read", "role_name": "triage", "user": USER}
        )
        assert authentication.verify_maintainer(principal, "maintainer/project")[1] == "triage"
        identity_provider(monkeypatch, repo=org)
        with pytest.raises(HTTPException) as error:
            authentication.verify_maintainer(principal, "maintainer/project")
        assert error.value.status_code == 403
        identity_provider(
            monkeypatch,
            repo=org,
            permission={"permission": "admin", "role_name": "admin", "user": {"id": 99}},
        )
        with pytest.raises(HTTPException):
            authentication.verify_maintainer(principal, "maintainer/project")


def test_private_repository_is_refused(github_client, monkeypatch):
    identity_provider(monkeypatch, repo={**REPO, "private": True})
    response = github_client.post(
        "/connections", headers=login(github_client), json={"repository": "maintainer/project"}
    )
    assert response.status_code == 422


def test_read_only_blocks_imports(github_client, monkeypatch):
    identity_provider(monkeypatch)
    headers = login(github_client)
    monkeypatch.setenv("READ_ONLY", "true")
    settings.cache_clear()
    assert (
        github_client.post(
            "/connections", headers=headers, json={"repository": "maintainer/project"}
        ).status_code
        == 403
    )


def test_connected_workspaces_are_scoped_to_verified_user(github_client, database, monkeypatch):
    identity_provider(monkeypatch)
    headers = login(github_client)
    mine = grant(database)
    other = grant(database, user_id=99, repo={**REPO, "id": 78, "full_name": "other/project"})
    assert [r["id"] for r in github_client.get("/repositories", headers=headers).json()] == [mine]
    assert github_client.get("/issues", headers=headers).status_code == 422
    assert github_client.get("/issues", headers=headers, params={"repository_id": other}).status_code == 403
    assert github_client.get("/dashboard", headers=headers, params={"repository_id": mine}).status_code == 200


def mock_ingestion(monkeypatch):
    def respond(request):
        assert request.headers["authorization"] == "Bearer " + TOKEN
        if request.url.path == "/repos/maintainer/project":
            return httpx.Response(200, json=REPO)
        rows = [
            raw_issue(1, title="Export fails", labels=["bug"]),
            raw_issue(2, title="Please add PDF export", labels=["feature-request"]),
            raw_issue(
                3,
                title="How do I change the language?",
                body="Question about configuration",
                labels=["question"],
            ),
            {**raw_issue(4), "pull_request": {"url": "https://api.github.com/pulls/4"}},
        ]
        return httpx.Response(200, json=rows)

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        connections,
        "GitHubClient",
        lambda **kwargs: GitHubClient(
            client=httpx.Client(
                transport=transport,
                base_url="https://api.github.com",
                headers={"Authorization": "Bearer " + kwargs["token"]},
            )
        ),
    )


def test_connect_imports_categorizes_indexes_and_reviews_provider_payloads(
    github_client, database, monkeypatch
):
    identity_provider(monkeypatch)
    mock_ingestion(monkeypatch)
    headers = login(github_client)
    result = github_client.post(
        "/connections", headers=headers, json={"repository": "https://github.com/maintainer/project"}
    )
    assert result.status_code == 202, result.text
    job = github_client.get("/connections/jobs/" + result.json()["id"], headers=headers).json()
    assert job["status"] == "complete", job
    assert job["result"]["import"]["excluded"] == 1
    assert job["result"]["categorization"]["categories"] == {"bug": 1, "enhancement": 1, "question": 1}
    repo_id = job["repository_id"]
    queue = github_client.get(
        "/issues", headers=headers, params={"repository_id": repo_id, "category": "bug"}
    ).json()
    assert queue["total"] == 1
    issue = github_client.get(f"/issues/{queue['items'][0]['id']}", headers=headers).json()
    assert issue["prediction"]["method"] == "source_label"
    assert issue["prediction"]["scores"] == {}
    related = github_client.get(f"/issues/{issue['id']}/related", headers=headers).json()
    assert related["method"] == "tfidf"
    assert all(row["id"] != issue["id"] for row in related["items"])
    review = {
        "snapshot_id": issue["snapshot_id"],
        "expected_revision": issue["review_revision"],
        "prediction_id": issue["prediction"]["id"],
        "action": "accept",
        "category": "bug",
        "idempotency_key": "verified-review-1",
    }
    assert (
        github_client.post(f"/issues/{issue['id']}/reviews", headers=headers, json=review).status_code == 201
    )
    with Session(database) as db:
        assert db.scalar(select(Review)).reviewer == "github:maintainer#42"
        assert len(list(db.scalars(select(Issue)))) == 3
        assert len(list(db.scalars(select(Prediction)))) == 3
    # A second synchronization preserves identity and does not duplicate source rows/predictions.
    result = github_client.post(
        "/connections", headers=headers, json={"repository": "maintainer/project", "incremental": True}
    )
    assert result.status_code == 202
    with Session(database) as db:
        assert len(list(db.scalars(select(Issue)))) == 3
        assert len(list(db.scalars(select(Prediction)))) == 3


def test_repository_permissions_are_rechecked_before_review(github_client, database, monkeypatch):
    org = {**REPO, "owner": {"id": 88, "type": "Organization"}}
    identity_provider(
        monkeypatch, repo=org, permission={"permission": "write", "role_name": "maintain", "user": USER}
    )
    mock_ingestion(monkeypatch)
    headers = login(github_client)
    result = github_client.post("/connections", headers=headers, json={"repository": "maintainer/project"})
    job = github_client.get("/connections/jobs/" + result.json()["id"], headers=headers).json()
    row = github_client.get(
        "/issues", headers=headers, params={"repository_id": job["repository_id"]}
    ).json()["items"][0]
    identity_provider(monkeypatch, repo=org)  # GitHub now reports read-only collaborator access.
    payload = {
        "snapshot_id": row["snapshot_id"],
        "expected_revision": row["review_revision"],
        "action": "correct",
        "category": "bug",
        "idempotency_key": "revoked-access-review",
    }
    assert (
        github_client.post(f"/issues/{row['id']}/reviews", headers=headers, json=payload).status_code == 403
    )
    with Session(database) as db:
        grant = db.scalar(select(RepositoryAccess))
        grant.verified_at = utcnow() - timedelta(minutes=10)
        db.commit()
    assert (
        github_client.get(
            "/issues", headers=headers, params={"repository_id": job["repository_id"]}
        ).status_code
        == 403
    )


def test_duplicate_active_import_reuses_job_and_logout_cancels_worker(github_client, database, monkeypatch):
    identity_provider(monkeypatch)
    headers = login(github_client)
    monkeypatch.setattr(connection_routes, "run_job", lambda _: None)
    first = github_client.post(
        "/connections", headers=headers, json={"repository": "maintainer/project"}
    ).json()
    second = github_client.post(
        "/connections", headers=headers, json={"repository": "maintainer/project"}
    ).json()
    assert first["id"] == second["id"]
    assert github_client.post("/auth/logout", headers=headers).status_code == 200
    connections.run_job(first["id"])
    with Session(database) as db:
        job = db.get(ConnectionJob, first["id"])
        assert job.status == "failed" and job.active_key is None


def test_interrupted_job_lease_is_released(github_client, database, monkeypatch):
    identity_provider(monkeypatch)
    headers = login(github_client)
    monkeypatch.setattr(connection_routes, "run_job", lambda _: None)
    first = github_client.post(
        "/connections", headers=headers, json={"repository": "maintainer/project"}
    ).json()
    with Session(database) as db:
        db.get(ConnectionJob, first["id"]).lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    status = github_client.get("/connections/jobs/" + first["id"], headers=headers).json()
    assert status["status"] == "failed"
    new = github_client.post(
        "/connections", headers=headers, json={"repository": "maintainer/project"}
    ).json()
    assert new["id"] != first["id"]


def test_device_flow_obeys_poll_interval_and_consumes_handle(github_client, database, monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-client-id")
    settings.cache_clear()
    calls = []

    def provider(method, url, **kwargs):
        calls.append(url)
        if url.endswith("/device/code"):
            return 200, {
                "device_code": "private-device-code",
                "user_code": "ABCD-EFGH",
                "interval": 5,
                "expires_in": 900,
            }
        return 200, {"access_token": TOKEN, "expires_in": 3600}

    monkeypatch.setattr(authentication, "provider_request", provider)
    identity_provider(monkeypatch)
    attempt = github_client.post("/auth/device/start").json()
    assert "device_code" not in attempt
    assert (
        github_client.post("/auth/device/poll", json={"handle": attempt["handle"]}).json()["status"]
        == "pending"
    )
    assert len(calls) == 1
    with Session(database) as db:
        row = db.scalar(select(DeviceLogin))
        assert row.encrypted_code != "private-device-code"
        row.next_poll_at = utcnow() - timedelta(seconds=1)
        db.commit()
    result = github_client.post("/auth/device/poll", json={"handle": attempt["handle"]})
    assert result.status_code == 200 and result.json()["status"] == "authorized"
    assert github_client.post("/auth/device/poll", json={"handle": attempt["handle"]}).status_code == 401


def test_failed_provider_identity_cannot_create_session(github_client, database, monkeypatch):
    monkeypatch.setattr(authentication, "github_get", lambda *args: (403, {"message": "Forbidden"}))
    assert github_client.post("/auth/token", json={"token": TOKEN}).status_code == 401
    with Session(database) as db:
        assert db.scalar(select(AuthSession)) is None


def test_ai_views_and_settings_are_scoped_and_permission_checked(github_client, database, monkeypatch):
    from triagedesk.ai_labels import DEFAULT_TAXONOMY

    identity_provider(monkeypatch)
    headers = login(github_client)
    mine = grant(database)
    other = grant(database, user_id=99, repo={**REPO, "id": 78, "full_name": "other/project"})
    assert github_client.get(f"/triage/{mine}/summary").status_code == 401
    assert github_client.get(f"/triage/{mine}/summary", headers=headers).status_code == 200
    assert github_client.get(f"/triage/{other}/summary", headers=headers).status_code == 403
    assert (
        github_client.put(f"/triage/{other}/taxonomy", headers=headers, json=DEFAULT_TAXONOMY).status_code
        == 403
    )
    org = {**REPO, "owner": {"id": 88, "type": "Organization"}}
    identity_provider(monkeypatch, repo=org)
    assert (
        github_client.put(f"/triage/{mine}/taxonomy", headers=headers, json=DEFAULT_TAXONOMY).status_code
        == 403
    )
    assert github_client.post(f"/triage/{mine}/refresh", headers=headers).status_code == 403


def test_login_workspace_refresh_detects_new_issues_closures_and_reuses_ai_cache(
    github_client, database, monkeypatch
):
    from sqlalchemy import func
    from test_ai_labels import use_ai

    from triagedesk.models import LabelAnalysis

    identity_provider(monkeypatch)
    calls = use_ai(monkeypatch)
    phase, seen_queries = [0], []

    def respond(request):
        if request.url.path == "/repos/maintainer/project":
            return httpx.Response(200, json=REPO)
        seen_queries.append(dict(request.url.params))
        rows = [raw_issue(1, title="API crashes", body="Previously worked.")]
        if phase[0]:
            rows = [
                {**raw_issue(1, day=1), "state": "closed", "closed_at": utcnow().isoformat()},
                raw_issue(2, day=1, title="API crashes", body="New report"),
            ]
        return httpx.Response(200, json=rows)

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        connections,
        "GitHubClient",
        lambda **kw: GitHubClient(
            client=httpx.Client(transport=transport, base_url="https://api.github.com")
        ),
    )
    headers = login(github_client)
    result = github_client.post("/connections", headers=headers, json={"repository": "maintainer/project"})
    job = github_client.get("/connections/jobs/" + result.json()["id"], headers=headers).json()
    assert job["status"] == "complete", job
    repo_id = job["repository_id"]
    assert len(calls) == 1
    assert seen_queries[0]["state"] == "open" and seen_queries[0]["direction"] == "desc"
    # A normal refresh inside the interval does not import or call AI again.
    assert github_client.post(f"/triage/{repo_id}/refresh", headers=headers).json()["status"] == "idle"
    with Session(database) as db:
        last = db.get(ConnectionJob, job["id"])
        last.created_at -= timedelta(minutes=2)
        db.commit()
    # The next login/periodic refresh sees the same issue and reuses its persisted analysis.
    again = github_client.post(f"/triage/{repo_id}/refresh", headers=headers).json()
    assert "id" in again
    assert len(calls) == 1
    phase[0] = 1
    with Session(database) as db:
        last = db.get(ConnectionJob, again["id"])
        last.created_at -= timedelta(minutes=2)
        db.commit()
    updated = github_client.post(f"/triage/{repo_id}/refresh", headers=headers).json()
    finished = github_client.get("/connections/jobs/" + updated["id"], headers=headers).json()
    assert finished["status"] == "complete", finished
    assert finished["result"]["closed_removed"] == 1
    assert seen_queries[-1]["state"] == "all" and "since" in seen_queries[-1]
    assert len(calls) == 2
    with Session(database) as db:
        assert list(db.scalars(select(Issue.number))) == [2]
        assert db.scalar(select(func.count()).select_from(LabelAnalysis)) == 1
