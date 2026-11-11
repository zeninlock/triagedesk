import json
from datetime import timedelta

import httpx
import pytest
from conftest import raw_issue
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_ai_labels import proposed, provider_response

from triagedesk import ai_labels, authentication, connection_routes, connections
from triagedesk.api import app
from triagedesk.config import settings
from triagedesk.github import GitHubClient, upsert_issue
from triagedesk.models import (
    AuthSession,
    ConnectionJob,
    DeviceLogin,
    Issue,
    LabelAnalysis,
    Repository,
    RepositoryAccess,
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


def pending_issues(db_engine, repository_id, count=5):
    with Session(db_engine) as db:
        repo = db.get(Repository, repository_id)
        for number in range(1, count + 1):
            upsert_issue(
                db, repo, raw_issue(number, title="API crashes after update", body="Previously worked.")
            )
        db.commit()


def test_ai_only_retry_labels_five_issues_without_import_or_search(github_client, database, monkeypatch):
    identity_provider(monkeypatch)
    headers = login(github_client)
    repo_id = grant(database)
    pending_issues(database, repo_id)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key-never-sent-to-live-provider")
    settings.cache_clear()
    calls = []
    real_client = httpx.Client
    real_provider = ai_labels.OpenAI

    def provider(request):
        assert request.url.host == "api.openai.com"
        calls.append(request)
        return httpx.Response(200, json=provider_response(json.dumps(proposed())))

    monkeypatch.setattr(
        ai_labels,
        "OpenAI",
        lambda **kwargs: real_provider(
            **{**kwargs, "http_client": real_client(transport=httpx.MockTransport(provider))}
        ),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("AI-only work must not fetch GitHub issues or rebuild search")

    monkeypatch.setattr(connections, "ingest", forbidden)
    response = github_client.post(f"/triage/{repo_id}/analyze", headers=headers)
    assert response.status_code == 202, response.text
    job = github_client.get(f"/connections/jobs/{response.json()['id']}", headers=headers).json()
    assert job["status"] == "complete" and job["result"]["ai_only"]
    assert job["result"]["ai_labels"]["analyzed"] == len(calls) == 5
    summary = github_client.get(f"/triage/{repo_id}/summary", headers=headers).json()
    assert summary["counts"]["auto_sorted"] == 5 and summary["counts"]["pending"] == 0
    # A second eligible pass must reuse all five saved results.
    with Session(database) as db:
        row = db.get(ConnectionJob, response.json()["id"])
        row.created_at = utcnow() - timedelta(seconds=20)
        db.commit()
    second = github_client.post(f"/triage/{repo_id}/analyze", headers=headers)
    assert second.status_code == 202
    saved = github_client.get(f"/connections/jobs/{second.json()['id']}", headers=headers).json()
    assert saved["result"]["ai_labels"]["cached"] == 5 and len(calls) == 5


def test_ai_retry_requires_connected_maintainer_and_writable_installation(
    github_client, database, monkeypatch
):
    identity_provider(monkeypatch)
    headers = login(github_client)
    repo_id = grant(database)
    other = grant(database, user_id=99, repo={**REPO, "id": 78, "full_name": "other/project"})
    assert github_client.post(f"/triage/{repo_id}/analyze").status_code == 401
    assert github_client.post(f"/triage/{other}/analyze", headers=headers).status_code == 403
    assert github_client.post(f"/triage/{repo_id}/analyze", headers=headers).status_code == 503
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    monkeypatch.setenv("READ_ONLY", "true")
    settings.cache_clear()
    assert github_client.post(f"/triage/{repo_id}/analyze", headers=headers).status_code == 403
    monkeypatch.setenv("READ_ONLY", "false")
    settings.cache_clear()
    identity_provider(monkeypatch, repo={**REPO, "owner": {"id": 88, "type": "Organization"}})
    assert github_client.post(f"/triage/{repo_id}/analyze", headers=headers).status_code == 403


def test_ai_retry_cannot_bypass_provider_backoff(github_client, database, monkeypatch):
    identity_provider(monkeypatch)
    headers = login(github_client)
    repo_id = grant(database)
    pending_issues(database, repo_id, 1)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    settings.cache_clear()
    with Session(database) as db:
        issue = db.scalar(select(Issue))
        db.add(
            LabelAnalysis(
                issue_id=issue.id,
                snapshot_id=issue.snapshot_id,
                analyzer_key=ai_labels.analyzer_key(db.get(Repository, repo_id)),
                model=settings().ai_model,
                status="failed",
                error="rate_limited",
                retry_after=utcnow() + timedelta(seconds=600),
            )
        )
        db.commit()
    response = github_client.post(f"/triage/{repo_id}/analyze", headers=headers)
    assert response.status_code == 429 and "backoff" in response.json()["error"]["message"]
    with Session(database) as db:
        assert db.scalar(select(ConnectionJob)) is None


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
    assert github_client.get("/repositories").status_code == 401
    assert (
        github_client.get("/repositories", headers={"Authorization": "Bearer test-review-secret"}).status_code
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
    assert github_client.get(f"/triage/{other}/issues", headers=headers).status_code == 403
    assert github_client.get(f"/triage/{mine}/summary", headers=headers).status_code == 200


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


def test_connect_imports_and_tags_with_openai(github_client, database, monkeypatch):
    from test_ai_labels import use_ai

    identity_provider(monkeypatch)
    mock_ingestion(monkeypatch)
    calls = use_ai(monkeypatch)
    headers = login(github_client)
    response = github_client.post("/connections", headers=headers, json={"repository": "maintainer/project"})
    assert response.status_code == 202
    job = github_client.get("/connections/jobs/" + response.json()["id"], headers=headers).json()
    assert job["status"] == "complete", job
    assert job["result"]["import"]["excluded"] == 1 and len(calls) == 3
    repo_id = job["repository_id"]
    issues = github_client.get(f"/triage/{repo_id}/issues", headers=headers).json()["items"]
    assert len(issues) == 3
    assert all(x["work_status"] == "open" and x["status"] == "auto_sorted" for x in issues)
    again = github_client.post(
        "/connections", headers=headers, json={"repository": "maintainer/project", "incremental": True}
    )
    assert again.status_code == 202 and len(calls) == 3


def test_status_is_authorized_idempotent_persistent_and_conflict_checked(
    github_client, database, monkeypatch
):
    identity_provider(monkeypatch)
    headers = login(github_client)
    repo_id = grant(database)
    pending_issues(database, repo_id, 1)
    item = github_client.get(f"/triage/{repo_id}/issues", headers=headers).json()["items"][0]
    path = f"/triage/issues/{item['id']}/status"
    payload = {"status": "in progress", "expected_revision": 0, "idempotency_key": "work-status-first"}
    assert github_client.put(path, json=payload).status_code == 401
    assert github_client.put(path, headers=headers, json={**payload, "status": "closed"}).status_code == 422
    response = github_client.put(path, headers=headers, json=payload)
    assert response.status_code == 200 and response.json()["revision"] == 1
    assert github_client.put(path, headers=headers, json=payload).json() == response.json()
    assert github_client.put(path, headers=headers, json={**payload, "status": "blocked"}).status_code == 409
    assert (
        github_client.put(
            path, headers=headers, json={**payload, "idempotency_key": "stale-work-status"}
        ).status_code
        == 409
    )
    detail = github_client.get(f"/triage/issues/{item['id']}", headers=headers).json()
    assert detail["work_status"] == "in progress" and len(detail["activity"]) == 1
    assert detail["activity"][0]["actor"] == "github:maintainer#42"
    filtered = github_client.get(
        f"/triage/{repo_id}/issues", headers=headers, params={"work_status": "blocked"}
    ).json()
    assert filtered["total"] == 0
    # A disconnected user cannot read or change this issue, even with its ID.
    monkeypatch.setattr(authentication, "github_get", lambda *a: (200, {"id": 99, "login": "outsider"}))
    outsider = login(github_client)
    assert github_client.get(f"/triage/issues/{item['id']}", headers=outsider).status_code == 403
    assert github_client.put(path, headers=outsider, json=payload).status_code == 403


def test_revoked_maintainer_permissions_block_status_and_label_writes(github_client, database, monkeypatch):
    identity_provider(monkeypatch)
    headers = login(github_client)
    repo_id = grant(database)
    pending_issues(database, repo_id, 1)
    item = github_client.get(f"/triage/{repo_id}/issues", headers=headers).json()["items"][0]
    identity_provider(monkeypatch, repo={**REPO, "owner": {"type": "Organization", "id": 88}})
    assert (
        github_client.put(
            f"/triage/issues/{item['id']}/status",
            headers=headers,
            json={"status": "blocked", "expected_revision": 0, "idempotency_key": "revoked-status-key"},
        ).status_code
        == 403
    )
    assert (
        github_client.post(
            f"/triage/issues/{item['id']}/reviews",
            headers=headers,
            json={
                "labels": [
                    {"group": "type", "name": "type: bug"},
                    {"group": "priority", "name": "priority: low"},
                ],
                "snapshot_id": item["snapshot_id"],
                "expected_revision": 0,
                "taxonomy_hash": "a" * 64,
                "idempotency_key": "revoked-review-key",
            },
        ).status_code
        == 403
    )


def failed_authentication(database, repo_id):
    with Session(database) as db:
        issue = db.scalar(select(Issue).where(Issue.repository_id == repo_id))
        row = LabelAnalysis(
            issue_id=issue.id,
            snapshot_id=issue.snapshot_id,
            analyzer_key=ai_labels.analyzer_key(db.get(Repository, repo_id)),
            model=settings().ai_model,
            status="failed",
            error="invalid_credentials",
        )
        db.add(row)
        db.commit()
        return row.id


def test_explicit_retry_clears_auth_error_even_when_joining_active_sync(github_client, database, monkeypatch):
    from test_ai_labels import use_ai

    identity_provider(monkeypatch)
    headers = login(github_client)
    repo_id = grant(database)
    pending_issues(database, repo_id, 1)
    calls = use_ai(monkeypatch)
    failure_id = failed_authentication(database, repo_id)
    monkeypatch.setattr(connection_routes, "run_job", lambda _: None)
    job = github_client.post(
        "/connections", headers=headers, json={"repository": "maintainer/project"}
    ).json()
    response = github_client.post(f"/triage/{repo_id}/analyze", headers=headers)
    assert response.status_code == 202 and response.json()["id"] == job["id"]
    with Session(database) as db:
        assert db.get(LabelAnalysis, failure_id).error is None
    ai_labels.analyze_repository(database, repo_id)
    assert len(calls) == 1


def test_explicit_retry_clears_auth_error_even_during_short_scheduling_delay(
    github_client, database, monkeypatch
):
    from test_ai_labels import use_ai

    identity_provider(monkeypatch)
    headers = login(github_client)
    repo_id = grant(database)
    pending_issues(database, repo_id, 1)
    calls = use_ai(monkeypatch)
    failure_id = failed_authentication(database, repo_id)
    with Session(database) as db:
        db.add(
            ConnectionJob(
                id="recent-pass",
                github_user_id=42,
                repository_name="maintainer/project",
                repository_id=repo_id,
                incremental=True,
                object_limit=500,
                status="complete",
                lease_until=utcnow(),
            )
        )
        db.commit()
    response = github_client.post(f"/triage/{repo_id}/analyze", headers=headers)
    assert response.status_code == 202 and response.json()["status"] == "idle"
    with Session(database) as db:
        assert db.get(LabelAnalysis, failure_id).error is None
    ai_labels.analyze_repository(database, repo_id)
    assert len(calls) == 1
