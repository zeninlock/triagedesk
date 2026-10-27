import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest

from triagedesk import community
from triagedesk.community import (
    CommunityBackend,
    CommunityBackendManager,
    CommunityStartupError,
    backend_environment,
    start_backend,
)


def test_community_forces_github_auth_and_drops_shared_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("MODE", "fixture")
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("REVIEWER_TOKEN", "inherited-demo-token")
    monkeypatch.setenv("GITHUB_TOKEN", "inherited-provider-token")
    env = backend_environment(
        {
            "DATABASE_URL": "postgresql://user:password@db/example",
            "AUTH_ENCRYPTION_KEY": "k" * 48,
            "GROQ_API_KEY": "free-provider-test-key",
        },
        tmp_path,
    )
    assert env["MODE"] == "real" and env["AUTH_MODE"] == "github"
    assert env["REVIEWER_TOKEN"] == env["GITHUB_TOKEN"] == ""
    assert env["ARTIFACT_DIR"] == str(tmp_path)
    assert env["GROQ_API_KEY"] == "free-provider-test-key"


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"DATABASE_URL": "sqlite:///demo.db", "AUTH_ENCRYPTION_KEY": "k" * 48},
        {"DATABASE_URL": "postgresql://db/example", "AUTH_ENCRYPTION_KEY": "short"},
        {"DATABASE_URL": "postgresql://db/example", "AUTH_ENCRYPTION_KEY": "REPLACE_" + "x" * 48},
    ],
)
def test_community_rejects_missing_or_unsafe_configuration(values, tmp_path):
    with pytest.raises(CommunityStartupError):
        backend_environment(values, tmp_path)


def test_failed_migration_hides_database_credentials_and_removes_temporary_files(monkeypatch):
    artifact_dirs = []

    def failed_migration(*args, **kwargs):
        artifact_dirs.append(Path(kwargs["env"]["ARTIFACT_DIR"]))
        raise subprocess.CalledProcessError(1, ["alembic"], stderr="sensitive-database-password")

    monkeypatch.setattr(subprocess, "run", failed_migration)
    with pytest.raises(CommunityStartupError) as error:
        start_backend({"DATABASE_URL": "postgresql://db/example", "AUTH_ENCRYPTION_KEY": "k" * 48})
    assert "sensitive-database-password" not in str(error.value)
    assert artifact_dirs and not artifact_dirs[0].exists()


def community_values(**overrides):
    return {
        "DATABASE_URL": "postgresql://db/example",
        "AUTH_ENCRYPTION_KEY": "k" * 48,
        **overrides,
    }


def test_provider_key_is_trimmed_and_none_is_missing(tmp_path):
    for value, expected in [(None, ""), ("  dummy-provider-key\n", "dummy-provider-key")]:
        env = backend_environment(community_values(GROQ_API_KEY=value), tmp_path)
        assert env["GROQ_API_KEY"] == expected


@pytest.mark.parametrize("value", ["dummy key", "dummy\nkey", {"key": "dummy"}])
def test_malformed_provider_key_has_safe_actionable_error(tmp_path, value):
    with pytest.raises(CommunityStartupError, match="one quoted API key") as error:
        backend_environment(community_values(GROQ_API_KEY=value), tmp_path)
    assert "dummy" not in str(error.value)


def test_manager_shares_backend_without_restarting_for_unrelated_changes(monkeypatch):
    backend = Mock(spec=CommunityBackend)
    backend.alive.return_value = True
    start = Mock(return_value=backend)
    monkeypatch.setattr(community, "start_backend", start)
    manager = CommunityBackendManager()
    assert manager.ensure(community_values(GROQ_API_KEY="  dummy-key  ")) is backend
    monkeypatch.setenv("API_URL", "http://127.0.0.1:23456")
    assert manager.ensure(community_values(GROQ_API_KEY="dummy-key", unrelated="changed")) is backend
    start.assert_called_once()
    assert start.call_args.args[0]["GROQ_API_KEY"] == "dummy-key"
    manager.stop()
    manager.stop()
    backend.stop.assert_called_once()


@pytest.mark.parametrize(
    "changes",
    [
        {"GROQ_API_KEY": "new-dummy-key"},
        {"DATABASE_URL": "postgresql://db/other"},
        {"AUTH_ENCRYPTION_KEY": "n" * 48},
        {"AI_MODEL": "other-model"},
        {"AI_CONFIDENCE_THRESHOLD": 0.9},
    ],
)
def test_manager_stops_old_process_before_loading_changed_secrets(monkeypatch, changes):
    first, second = Mock(spec=CommunityBackend), Mock(spec=CommunityBackend)
    events = []
    first.stop.side_effect = lambda: events.append("stopped")

    def start(values):
        events.append("started")
        return first if len(events) == 1 else second

    monkeypatch.setattr(community, "start_backend", start)
    manager = CommunityBackendManager()
    assert manager.ensure(community_values()) is first
    assert manager.ensure(community_values(**changes)) is second
    assert events == ["started", "stopped", "started"]


def test_manager_restarts_a_crashed_backend(monkeypatch):
    first, second = Mock(spec=CommunityBackend), Mock(spec=CommunityBackend)
    first.alive.return_value = False
    start = Mock(side_effect=[first, second])
    monkeypatch.setattr(community, "start_backend", start)
    manager = CommunityBackendManager()
    assert manager.ensure(community_values()) is first
    assert manager.ensure(community_values()) is second
    first.stop.assert_called_once()


def test_manager_retries_failed_configuration_change(monkeypatch):
    first, second = Mock(spec=CommunityBackend), Mock(spec=CommunityBackend)
    start = Mock(side_effect=[first, CommunityStartupError("Startup failed"), second])
    monkeypatch.setattr(community, "start_backend", start)
    manager = CommunityBackendManager()
    manager.ensure(community_values())
    changed = community_values(GROQ_API_KEY="new-dummy-key")
    with pytest.raises(CommunityStartupError):
        manager.ensure(changed)
    assert manager.ensure(changed) is second
    first.stop.assert_called_once()


def test_concurrent_visitors_start_only_one_backend(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    callers = threading.Barrier(4)
    backend = Mock(spec=CommunityBackend)
    backend.alive.return_value = True

    def start(values):
        entered.set()
        assert release.wait(timeout=5)
        return backend

    factory = Mock(side_effect=start)
    monkeypatch.setattr(community, "start_backend", factory)
    manager = CommunityBackendManager()

    def visit():
        callers.wait(timeout=5)
        return manager.ensure(community_values())

    with ThreadPoolExecutor(max_workers=4) as pool:
        visits = [pool.submit(visit) for _ in range(4)]
        assert entered.wait(timeout=5)
        release.set()
        assert all(visit.result(timeout=5) is backend for visit in visits)
    factory.assert_called_once()
