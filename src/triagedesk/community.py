"""Run a private API alongside the UI for a small Community Cloud demo."""

import atexit
import hashlib
import json
import math
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path

from triagedesk.config import DEFAULT_AI_CONFIDENCE_THRESHOLD

ROOT = Path(__file__).resolve().parents[2]


class CommunityStartupError(RuntimeError):
    """A startup error whose message is safe to show without credentials."""


def _backend_configuration(values: Mapping) -> dict[str, str]:
    """Normalize only supported settings; never log this credential-bearing mapping."""
    threshold = values.get("AI_CONFIDENCE_THRESHOLD", DEFAULT_AI_CONFIDENCE_THRESHOLD)
    try:
        if isinstance(threshold, bool):
            raise ValueError
        threshold = float(threshold)
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise CommunityStartupError(
            "AI_CONFIDENCE_THRESHOLD must be a number from 0.0 to 1.0. Use 0.25 for a 25% cutoff."
        ) from None
    database = str(values.get("DATABASE_URL", "")).strip()
    key = str(values.get("AUTH_ENCRYPTION_KEY", ""))
    openai_key = values.get("OPENAI_API_KEY") or ""
    if not isinstance(openai_key, str) or any(char.isspace() for char in openai_key.strip()):
        raise CommunityStartupError(
            "Set OPENAI_API_KEY to one quoted API key, without spaces or line breaks."
        )
    if openai_key.strip() and openai_key.strip() == key.strip():
        raise CommunityStartupError(
            "OPENAI_API_KEY matches AUTH_ENCRYPTION_KEY. Use the key created on OpenAI for OPENAI_API_KEY; keep the encryption secret unchanged."
        )
    if not database.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise CommunityStartupError("Set DATABASE_URL to your PostgreSQL connection string in app secrets.")
    if len(key) < 32 or key.startswith("REPLACE_"):
        raise CommunityStartupError("Set AUTH_ENCRYPTION_KEY to a random secret of at least 32 characters.")
    migration_database = str(values.get("MIGRATION_DATABASE_URL") or database).strip()
    if not migration_database.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise CommunityStartupError("Set MIGRATION_DATABASE_URL to the direct Neon connection string.")
    return dict(
        DATABASE_URL=database,
        MIGRATION_DATABASE_URL=migration_database,
        AUTH_ENCRYPTION_KEY=key,
        MODE="real",
        AUTH_MODE="github",
        READ_ONLY="false",
        ALLOW_TOKEN_LOGIN="true",
        SESSION_HOURS="8",
        GITHUB_CLIENT_ID=str(values.get("GITHUB_CLIENT_ID", "")).strip(),
        OPENAI_API_KEY=openai_key.strip(),
        AI_MODEL=str(values.get("AI_MODEL", "gpt-4.1-mini")).strip(),
        AI_CONFIDENCE_THRESHOLD=str(threshold),
        AI_BATCH_SIZE=str(values.get("AI_BATCH_SIZE", 5)),
        AI_REQUEST_INTERVAL=str(values.get("AI_REQUEST_INTERVAL", 1)),
        AUTO_SYNC_SECONDS=str(values.get("AUTO_SYNC_SECONDS", 60)),
        GITHUB_TOKEN="",
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
    )


def backend_environment(values: Mapping) -> dict[str, str]:
    env = os.environ.copy()
    # Project-scoped API keys carry their own project. Do not let unrelated
    # inherited SDK headers override the key's scope.
    for name in ("OPENAI_ORG_ID", "OPENAI_PROJECT_ID"):
        env.pop(name, None)
    env.update(_backend_configuration(values))
    return env


class CommunityBackend:
    def __init__(self, process: subprocess.Popen, port: int):
        self.process = process
        self.api_url = f"http://127.0.0.1:{port}"

    def stop(self):
        atexit.unregister(self.stop)
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def alive(self):
        if self.process.poll() is None:
            return True
        self.stop()
        return False


class CommunityBackendManager:
    """Share one API across visitors and replace it when supported secrets change."""

    def __init__(self):
        self._lock = threading.Lock()
        self._backend: CommunityBackend | None = None
        self._fingerprint: str | None = None

    def ensure(self, values: Mapping) -> CommunityBackend:
        configuration = _backend_configuration(values)
        fingerprint = hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()
        with self._lock:
            if self._backend and self._fingerprint == fingerprint and self._backend.alive():
                return self._backend
            self._stop_locked()
            self._backend = start_backend(configuration)
            self._fingerprint = fingerprint
            return self._backend

    def _stop_locked(self):
        if self._backend:
            self._backend.stop()
        self._backend = None
        self._fingerprint = None

    def stop(self):
        with self._lock:
            self._stop_locked()


def start_backend(values: Mapping, timeout: float = 120) -> CommunityBackend:
    """Migrate once, start one loopback-only API, then wait for database readiness."""
    backend = None
    ready = False
    try:
        env = backend_environment(values)
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env={**env, "DATABASE_URL": env["MIGRATION_DATABASE_URL"]},
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
        backend = CommunityBackend(process, port)
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
        if not ready and backend is not None:
            backend.stop()
