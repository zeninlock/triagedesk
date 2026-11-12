import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
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
            "OPENAI_API_KEY": "free-provider-test-key",
        },
    )
    assert env["MODE"] == "real" and env["AUTH_MODE"] == "github"
    assert env["GITHUB_TOKEN"] == ""
    assert env["OPENAI_API_KEY"] == "free-provider-test-key"
    assert env["AI_CONFIDENCE_THRESHOLD"] == "0.25"


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
        backend_environment(values)


def test_failed_migration_hides_database_credentials_and_removes_temporary_files(monkeypatch):

    def failed_migration(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["alembic"], stderr="sensitive-database-password")

    monkeypatch.setattr(subprocess, "run", failed_migration)
    with pytest.raises(CommunityStartupError) as error:
        start_backend({"DATABASE_URL": "postgresql://db/example", "AUTH_ENCRYPTION_KEY": "k" * 48})
    assert "sensitive-database-password" not in str(error.value)


def community_values(**overrides):
    return {
        "DATABASE_URL": "postgresql://db/example",
        "AUTH_ENCRYPTION_KEY": "k" * 48,
        **overrides,
    }


def test_provider_key_is_trimmed_and_none_is_missing(tmp_path):
    for value, expected in [(None, ""), ("  dummy-provider-key\n", "dummy-provider-key")]:
        env = backend_environment(community_values(OPENAI_API_KEY=value))
        assert env["OPENAI_API_KEY"] == expected


@pytest.mark.parametrize("value", ["dummy key", "dummy\nkey", {"key": "dummy"}])
def test_malformed_provider_key_has_safe_actionable_error(tmp_path, value):
    with pytest.raises(CommunityStartupError, match="one quoted API key") as error:
        backend_environment(community_values(OPENAI_API_KEY=value))
    assert "dummy" not in str(error.value)


def test_manager_shares_backend_without_restarting_for_unrelated_changes(monkeypatch):
    backend = Mock(spec=CommunityBackend)
    backend.alive.return_value = True
    start = Mock(return_value=backend)
    monkeypatch.setattr(community, "start_backend", start)
    manager = CommunityBackendManager()
    assert manager.ensure(community_values(OPENAI_API_KEY="  dummy-key  ")) is backend
    monkeypatch.setenv("API_URL", "http://127.0.0.1:23456")
    assert manager.ensure(community_values(OPENAI_API_KEY="dummy-key", unrelated="changed")) is backend
    start.assert_called_once()
    assert start.call_args.args[0]["OPENAI_API_KEY"] == "dummy-key"
    manager.stop()
    manager.stop()
    backend.stop.assert_called_once()


@pytest.mark.parametrize(
    "changes",
    [
        {"OPENAI_API_KEY": "new-dummy-key"},
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


def test_manager_applies_lower_threshold_and_normalizes_numeric_strings(monkeypatch):
    first, second = Mock(spec=CommunityBackend), Mock(spec=CommunityBackend)
    first.alive.return_value = second.alive.return_value = True
    start = Mock(side_effect=[first, second])
    monkeypatch.setattr(community, "start_backend", start)
    manager = CommunityBackendManager()
    manager.ensure(community_values(AI_CONFIDENCE_THRESHOLD=0.85))
    assert manager.ensure(community_values(AI_CONFIDENCE_THRESHOLD=0.25)) is second
    first.stop.assert_called_once()
    assert start.call_args.args[0]["AI_CONFIDENCE_THRESHOLD"] == "0.25"
    assert manager.ensure(community_values(AI_CONFIDENCE_THRESHOLD="0.250")) is second
    assert start.call_count == 2


@pytest.mark.parametrize(
    "threshold", [-0.01, 1.01, "25%", "invalid-private-value", None, True, float("nan"), float("inf")]
)
def test_bad_threshold_is_reported_before_migration_without_stopping_backend(monkeypatch, threshold):
    first = Mock(spec=CommunityBackend)
    first.alive.return_value = True
    start = Mock(return_value=first)
    monkeypatch.setattr(community, "start_backend", start)
    manager = CommunityBackendManager()
    manager.ensure(community_values())
    with pytest.raises(CommunityStartupError, match="Use 0.25") as exc:
        manager.ensure(community_values(AI_CONFIDENCE_THRESHOLD=threshold))
    assert "invalid-private-value" not in str(exc.value)
    first.stop.assert_not_called()
    start.assert_called_once()


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
    changed = community_values(OPENAI_API_KEY="new-dummy-key")
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


def test_migration_uses_direct_neon_url_without_changing_runtime_url(monkeypatch):
    def migrate(*args, **kwargs):
        assert kwargs["env"]["DATABASE_URL"] == "postgresql://direct/db"
        raise subprocess.CalledProcessError(1, ["alembic"])

    monkeypatch.setattr(subprocess, "run", migrate)
    with pytest.raises(CommunityStartupError):
        start_backend(
            community_values(
                DATABASE_URL="postgresql://pooled/db", MIGRATION_DATABASE_URL="postgresql://direct/db"
            )
        )


def test_openai_key_cannot_be_the_neon_encryption_secret():
    with pytest.raises(CommunityStartupError, match="matches AUTH_ENCRYPTION_KEY") as exc:
        backend_environment(community_values(OPENAI_API_KEY="k" * 48))
    assert "k" * 48 not in str(exc.value)


def test_cloud_backend_drops_unrelated_inherited_openai_scope_headers(monkeypatch):
    monkeypatch.setenv("OPENAI_ORG_ID", "unrelated-org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "unrelated-project")
    env = backend_environment(community_values(OPENAI_API_KEY="sk_test_key"))
    assert "OPENAI_ORG_ID" not in env and "OPENAI_PROJECT_ID" not in env
