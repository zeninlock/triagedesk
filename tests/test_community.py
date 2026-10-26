import subprocess
from pathlib import Path

import pytest

from triagedesk.community import CommunityStartupError, backend_environment, start_backend


def test_community_forces_github_auth_and_drops_shared_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("MODE", "fixture")
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("REVIEWER_TOKEN", "inherited-demo-token")
    monkeypatch.setenv("GITHUB_TOKEN", "inherited-provider-token")
    env = backend_environment(
        {"DATABASE_URL": "postgresql://user:password@db/example", "AUTH_ENCRYPTION_KEY": "k" * 48},
        tmp_path,
    )
    assert env["MODE"] == "real" and env["AUTH_MODE"] == "github"
    assert env["REVIEWER_TOKEN"] == env["GITHUB_TOKEN"] == ""
    assert env["ARTIFACT_DIR"] == str(tmp_path)


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
