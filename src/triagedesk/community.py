"""Run a private API alongside the UI for a small Community Cloud demo."""

import atexit
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CommunityStartupError(RuntimeError):
    """A startup error whose message is safe to show without credentials."""


def backend_environment(values: Mapping, artifacts: Path) -> dict[str, str]:
    database = str(values.get("DATABASE_URL", "")).strip()
    key = str(values.get("AUTH_ENCRYPTION_KEY", ""))
    if not database.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise CommunityStartupError("Set DATABASE_URL to your PostgreSQL connection string in app secrets.")
    if len(key) < 32 or key.startswith("REPLACE_"):
        raise CommunityStartupError("Set AUTH_ENCRYPTION_KEY to a random secret of at least 32 characters.")
    env = os.environ.copy()
    env.update(
        DATABASE_URL=database,
        AUTH_ENCRYPTION_KEY=key,
        MODE="real",
        AUTH_MODE="github",
        READ_ONLY="false",
        ALLOW_TOKEN_LOGIN="true",
        SESSION_HOURS="8",
        GITHUB_CLIENT_ID=str(values.get("GITHUB_CLIENT_ID", "")).strip(),
        GITHUB_TOKEN="",
        REVIEWER_TOKEN="",
        ARTIFACT_DIR=str(artifacts),
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
    )
    return env


class CommunityBackend:
    def __init__(self, process: subprocess.Popen, artifacts: tempfile.TemporaryDirectory, port: int):
        self.process = process
        self.artifacts = artifacts
        self.api_url = f"http://127.0.0.1:{port}"

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.artifacts.cleanup()

    def alive(self):
        if self.process.poll() is None:
            return True
        self.stop()
        return False


def start_backend(values: Mapping, timeout: float = 120) -> CommunityBackend:
    """Migrate once, start one loopback-only API, then wait for database readiness."""
    artifacts = tempfile.TemporaryDirectory(prefix="triagedesk-community-")
    backend = None
    ready = False
    try:
        env = backend_environment(values, Path(artifacts.name))
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            timeout=timeout,
        )
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "triagedesk.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
            ],
            cwd=ROOT,
            env=env,
        )
        backend = CommunityBackend(process, artifacts, port)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise CommunityStartupError("The private API stopped. Reboot the app and check its logs.")
            try:
                with urllib.request.urlopen(f"{backend.api_url}/health/ready", timeout=3) as response:
                    if response.status == 200:
                        atexit.register(backend.stop)
                        ready = True
                        return backend
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
            time.sleep(0.25)
        raise CommunityStartupError("The database did not become ready. Check app secrets, then reboot.")
    except CommunityStartupError:
        raise
    except (subprocess.SubprocessError, OSError):
        # Subprocess errors can contain database connection details: do not expose them in the UI.
        raise CommunityStartupError(
            "Startup failed. Check the database connection in app secrets and reboot."
        ) from None
    finally:
        if not ready:
            if backend is None:
                artifacts.cleanup()
            else:
                backend.stop()
