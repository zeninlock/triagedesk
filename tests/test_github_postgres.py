from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from triagedesk import authentication, connection_routes
from triagedesk.api import app
from triagedesk.config import settings
from triagedesk.models import AuthSession, ConnectionJob


def github_mode(monkeypatch):
    monkeypatch.setenv("MODE", "real")
    monkeypatch.setenv("AUTH_MODE", "github")
    monkeypatch.setenv("AUTH_ENCRYPTION_KEY", "postgres-test-key-with-at-least-32-characters")
    settings.cache_clear()


def test_postgres_github_session_persists_and_logout_invalidates(postgres_database, monkeypatch):
    github_mode(monkeypatch)
    monkeypatch.setattr(authentication, "github_get", lambda *args: (200, {"id": 42, "login": "maintainer"}))
    with Session(postgres_database) as db:
        result = authentication.create_session(db, "provider-credential-for-test")
    with Session(postgres_database) as db:
        principal = authentication.principal_for(db, result["access_token"])
        assert principal.login == "maintainer"
        assert authentication.decrypt(principal.encrypted_token) == "provider-credential-for-test"
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + result["access_token"]}
        assert client.post("/auth/logout", headers=headers).status_code == 200
        assert client.get("/auth/session", headers=headers).status_code == 401


@pytest.mark.parametrize("same_repository", [False, True])
def test_postgres_only_one_import_is_admitted_and_session_cleanup_is_safe(
    postgres_database, monkeypatch, same_repository
):
    github_mode(monkeypatch)

    def provider(path, token):
        if path == "/user":
            return 200, {"id": 42, "login": "maintainer"}
        name = path.removeprefix("/repos/")
        return 200, {
            "id": 101 if name.endswith("one") else 102,
            "full_name": name,
            "private": False,
            "has_issues": True,
            "owner": {"id": 42, "type": "User"},
        }

    monkeypatch.setattr(authentication, "github_get", provider)
    monkeypatch.setattr(connection_routes, "run_job", lambda _: None)
    with TestClient(app) as client:
        response = client.post("/auth/token", json={"token": "test-provider-token"})
        headers = {"Authorization": "Bearer " + response.json()["access_token"]}

        def submit(name):
            return client.post("/connections", headers=headers, json={"repository": name}).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(
                pool.map(
                    submit, ["maintainer/one", "maintainer/one" if same_repository else "maintainer/two"]
                )
            )
        assert sorted(codes) == ([202, 202] if same_repository else [202, 409])
        with Session(postgres_database) as db:
            jobs = list(db.scalars(select(ConnectionJob)))
            assert len(jobs) == 1 and jobs[0].active_key == "import"
        assert client.post("/auth/logout", headers=headers).status_code == 200
        with Session(postgres_database) as db:
            assert db.scalar(select(AuthSession)) is None
            assert db.scalar(select(ConnectionJob)).session_id is None
