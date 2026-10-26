"""GitHub identity, encrypted provider credentials, and per-repository authorization.

Application sessions are opaque bearer tokens. Only their digests are stored. Provider
credentials remain encrypted on the API server; the UI receives no provider token.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update

from triagedesk.config import settings
from triagedesk.github import aware, valid_repository
from triagedesk.models import AuthSession, DeviceLogin, Repository, RepositoryAccess, utcnow


@dataclass(frozen=True)
class Principal:
    session_id: int
    github_user_id: int
    login: str
    encrypted_token: str


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


def cipher():
    secret = settings().auth_encryption_key.get_secret_value()
    if len(secret) < 32:
        raise HTTPException(503, "GitHub sign-in has not been configured by the installation owner")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def encrypt(value):
    return cipher().encrypt(value.encode()).decode()


def decrypt(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except InvalidToken:
        raise HTTPException(401, "Your session can no longer be read; sign in again") from None


def provider_request(method, url, *, token=None, data=None):
    # Callers supply constant GitHub origins, never a submitted repository URL.
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc not in {"api.github.com", "github.com"}:
        raise ValueError("Unexpected identity provider origin")
    headers = {"Accept": "application/json", "User-Agent": "TriageDesk/0.2"}
    if token:
        headers.update(
            Authorization=f"Bearer {token}",
            **{"X-GitHub-Api-Version": settings().github_api_version},
        )
    try:
        with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
            response = client.request(method, url, headers=headers, data=data)
    except httpx.HTTPError:
        raise HTTPException(503, "GitHub could not be reached; try again shortly") from None
    if response.status_code == 401:
        raise HTTPException(401, "GitHub authorization expired or was revoked; sign in again")
    if response.status_code == 429 or response.headers.get("x-ratelimit-remaining") == "0":
        raise HTTPException(429, "GitHub's request allowance is exhausted; try again after it resets")
    if response.status_code >= 500:
        raise HTTPException(503, "GitHub is temporarily unavailable")
    try:
        body = response.json()
    except ValueError:
        raise HTTPException(503, "GitHub returned an unexpected response") from None
    return response.status_code, body


def github_get(path, token):
    return provider_request("GET", "https://api.github.com" + path, token=token)


def create_session(db, github_token, expires_in=None):
    status, user = github_get("/user", github_token)
    if status != 200 or not isinstance(user.get("id"), int) or not user.get("login"):
        raise HTTPException(401, "GitHub did not verify a user identity for this credential")
    # App installation tokens have no human /user identity and cannot sign in.
    login = str(user["login"])
    if len(login) > 100:
        raise HTTPException(401, "Unsupported GitHub identity")
    ttl = settings().session_hours * 3600
    if expires_in is not None:
        ttl = min(ttl, max(1, int(expires_in) - 30))
    session_token = secrets.token_urlsafe(48)
    expires = utcnow() + timedelta(seconds=ttl)
    db.execute(delete(AuthSession).where(AuthSession.expires_at < utcnow()))
    session = AuthSession(
        token_hash=fingerprint(session_token),
        github_user_id=user["id"],
        login=login,
        encrypted_token=encrypt(github_token),
        expires_at=expires,
    )
    db.add(session)
    db.commit()
    return {"access_token": session_token, "login": login, "expires_at": expires, "token_type": "bearer"}


def principal_for(db, session_token):
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == fingerprint(session_token)))
    if not session or aware(session.expires_at) <= utcnow():
        raise HTTPException(401, "Sign in with GitHub to continue", headers={"WWW-Authenticate": "Bearer"})
    return Principal(session.id, session.github_user_id, session.login, session.encrypted_token)


def normalize_repository(value):
    value = value.strip()
    if "://" in value:
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or parsed.netloc.lower() != "github.com"
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Paste an https://github.com/owner/repository URL or owner/repository")
        value = parsed.path.strip("/")
        if value.endswith("/issues"):
            value = value.removesuffix("/issues")
    if value.endswith(".git"):
        value = value[:-4]
    return valid_repository(value)


def verify_maintainer(principal, name):
    token = decrypt(principal.encrypted_token)
    status, repo = github_get(f"/repos/{name}", token)
    if status != 200:
        raise HTTPException(403, "GitHub could not verify access to that repository")
    if repo.get("private") is not False:
        raise HTTPException(422, "Only public repositories can be connected")
    if not repo.get("has_issues", True):
        raise HTTPException(422, "Enable the repository's GitHub issue tracker before connecting it")
    if not isinstance(repo.get("id"), int):
        raise HTTPException(503, "GitHub returned incomplete repository metadata")
    # Numeric identity, not a submitted username or a similarly named organization.
    owner = repo.get("owner", {})
    if owner.get("type") == "User" and owner.get("id") == principal.github_user_id:
        role = "owner"
    else:
        status, permission = github_get(f"/repos/{name}/collaborators/{principal.login}/permission", token)
        if status != 200 or permission.get("user", {}).get("id") != principal.github_user_id:
            raise HTTPException(403, "GitHub did not confirm repository maintainer access")
        role = permission.get("role_name", "")
        if role not in {"admin", "maintain", "write", "triage", "triage_plus"}:
            if permission.get("permission") in {"admin", "write"}:
                role = permission["permission"]
            else:
                raise HTTPException(403, "Repository triage, write, maintain, or admin access is required")
    return repo, role


def require_connection(db, principal, repository_id):
    if settings().auth_mode != "github":
        return
    if repository_id is None:
        raise HTTPException(422, "Choose one of your connected repositories")
    grant = db.scalar(
        select(RepositoryAccess).where(
            RepositoryAccess.repository_id == repository_id,
            RepositoryAccess.github_user_id == principal.github_user_id,
        )
    )
    if not grant:
        raise HTTPException(403, "Connect and verify this repository before accessing its workspace")
    if aware(grant.verified_at) < utcnow() - timedelta(minutes=5):
        repo = db.get(Repository, repository_id)
        metadata, role = verify_maintainer(principal, repo.full_name)
        if metadata["id"] != repo.github_id:
            raise HTTPException(409, "The repository identity changed; contact the installation owner")
        grant.role, grant.verified_at = role, utcnow()
        db.commit()


def authorize_repository_write(db, principal, repository_id):
    require_connection(db, principal, repository_id)
    repo = db.get(Repository, repository_id)
    metadata, role = verify_maintainer(principal, repo.full_name)
    if metadata["id"] != repo.github_id:
        raise HTTPException(409, "The GitHub repository identity changed; reconnect before reviewing")
    grant = db.scalar(
        select(RepositoryAccess).where(
            RepositoryAccess.repository_id == repo.id,
            RepositoryAccess.github_user_id == principal.github_user_id,
        )
    )
    grant.role, grant.verified_at = role, utcnow()
    # The review's commit also persists the fresh permission observation.


def start_device_login(db):
    if not settings().github_client_id:
        raise HTTPException(503, "GitHub browser sign-in is not configured; use the token sign-in option")
    db.execute(delete(DeviceLogin).where(DeviceLogin.expires_at < utcnow()))
    active = db.scalar(select(func.count()).select_from(DeviceLogin).where(DeviceLogin.consumed.is_(False)))
    if active >= 20:
        raise HTTPException(429, "Too many sign-in attempts are pending; try again later")
    status, data = provider_request(
        "POST", "https://github.com/login/device/code", data={"client_id": settings().github_client_id}
    )
    if status != 200 or not data.get("device_code") or not data.get("user_code"):
        raise HTTPException(503, "Enable device flow for the configured GitHub App")
    handle = secrets.token_urlsafe(48)
    interval = max(5, int(data.get("interval", 5)))
    expires = utcnow() + timedelta(seconds=min(900, int(data.get("expires_in", 900))))
    db.add(
        DeviceLogin(
            handle_hash=fingerprint(handle),
            encrypted_code=encrypt(data["device_code"]),
            expires_at=expires,
            next_poll_at=utcnow() + timedelta(seconds=interval),
            interval=interval,
        )
    )
    db.commit()
    return {
        "handle": handle,
        "user_code": data["user_code"],
        "verification_uri": "https://github.com/login/device",
        "interval": interval,
        "expires_at": expires,
    }


def poll_device_login(db, handle):
    attempt = db.scalar(select(DeviceLogin).where(DeviceLogin.handle_hash == fingerprint(handle)))
    if not attempt or attempt.consumed or aware(attempt.expires_at) <= utcnow():
        raise HTTPException(401, "This sign-in request expired; start again")
    if aware(attempt.next_poll_at) > utcnow():
        return {"status": "pending", "interval": attempt.interval}
    # Atomic polling reservation prevents parallel callers from racing the exchange.
    reserved = db.execute(
        update(DeviceLogin)
        .where(
            DeviceLogin.id == attempt.id,
            DeviceLogin.consumed.is_(False),
            DeviceLogin.next_poll_at <= utcnow(),
            DeviceLogin.expires_at > utcnow(),
        )
        .values(next_poll_at=utcnow() + timedelta(seconds=attempt.interval))
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if reserved.rowcount != 1:
        return {"status": "pending", "interval": attempt.interval}
    status, data = provider_request(
        "POST",
        "https://github.com/login/oauth/access_token",
        data={
            "client_id": settings().github_client_id,
            "device_code": decrypt(attempt.encrypted_code),
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
    )
    error = data.get("error")
    if error in {"authorization_pending", "slow_down"}:
        if error == "slow_down":
            attempt.interval += 5
            attempt.next_poll_at = utcnow() + timedelta(seconds=attempt.interval)
            db.commit()
        return {"status": "pending", "interval": attempt.interval}
    if status != 200 or not data.get("access_token"):
        attempt.consumed = True
        db.commit()
        raise HTTPException(401, "GitHub authorization was denied or expired; start again")
    attempt.consumed = True
    db.commit()
    return {"status": "authorized", **create_session(db, data["access_token"], data.get("expires_in"))}
