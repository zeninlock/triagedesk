"""Authenticated sign-in and repository connection endpoints."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from triagedesk.authentication import (
    create_session,
    normalize_repository,
    poll_device_login,
    principal_for,
    start_device_login,
    verify_maintainer,
)
from triagedesk.config import settings
from triagedesk.connections import expire_jobs, job_output, run_job, start_job
from triagedesk.db import get_session
from triagedesk.models import AuthSession, ConnectionJob, Repository, RepositoryAccess

router = APIRouter()
scheme = HTTPBearer(auto_error=False)
DB = Annotated[Session, Depends(get_session)]


def current_principal(db: DB, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(scheme)]):
    if settings().auth_mode == "local":
        return None
    if not credentials:
        raise HTTPException(401, "Sign in with GitHub to continue", headers={"WWW-Authenticate": "Bearer"})
    return principal_for(db, credentials.credentials)


Actor = Annotated[object, Depends(current_principal)]


def github_mode():
    if settings().auth_mode != "github":
        raise HTTPException(403, "GitHub connections require AUTH_MODE=github and MODE=real")


class TokenLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr = Field(min_length=8, max_length=1000)


class DevicePoll(BaseModel):
    model_config = ConfigDict(extra="forbid")
    handle: str = Field(min_length=32, max_length=200)


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str = Field(min_length=3, max_length=300)
    limit: int = Field(500, ge=1, le=3000)
    incremental: bool = False


@router.post("/auth/token")
def token_login(payload: TokenLogin, db: DB):
    github_mode()
    if not settings().allow_token_login:
        raise HTTPException(403, "Token sign-in is disabled; use GitHub browser sign-in")
    return create_session(db, payload.token.get_secret_value())


@router.post("/auth/device/start")
def device_start(db: DB):
    github_mode()
    return start_device_login(db)


@router.post("/auth/device/poll")
def device_poll(payload: DevicePoll, db: DB):
    github_mode()
    return poll_device_login(db, payload.handle)


@router.get("/auth/session")
def session_info(db: DB, actor: Actor):
    github_mode()
    session = db.get(AuthSession, actor.session_id)
    return {"login": actor.login, "github_user_id": actor.github_user_id, "expires_at": session.expires_at}


@router.post("/auth/logout")
def logout(db: DB, actor: Actor):
    github_mode()
    db.execute(delete(AuthSession).where(AuthSession.id == actor.session_id))
    db.commit()
    return {"signed_out": True}


@router.get("/connections")
def connections(db: DB, actor: Actor):
    github_mode()
    rows = db.execute(
        select(Repository, RepositoryAccess)
        .join(RepositoryAccess)
        .where(RepositoryAccess.github_user_id == actor.github_user_id)
        .order_by(Repository.full_name)
    )
    return [
        {
            "repository_id": repo.id,
            "full_name": repo.full_name,
            "role": grant.role,
            "verified_at": grant.verified_at,
            "last_synced_at": repo.last_synced_at,
            "partial": repo.partial,
        }
        for repo, grant in rows
    ]


@router.post("/connections", status_code=202)
def connect(payload: ConnectionInput, tasks: BackgroundTasks, db: DB, actor: Actor):
    github_mode()
    if settings().read_only:
        raise HTTPException(403, "This installation is read-only")
    try:
        name = normalize_repository(payload.repository)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    metadata, role = verify_maintainer(actor, name)
    # Reject redirects/identity mismatches rather than importing an unverified identifier.
    canonical = str(metadata.get("full_name", name)).casefold()
    if canonical != name:
        raise HTTPException(409, "Use the repository's current owner/name and reconnect")
    try:
        job, created = start_job(db, actor, name, metadata, role, payload.limit, payload.incremental)
    except IntegrityError:
        # A simultaneous first connection can race the repository/grant inserts.
        db.rollback()
        job = db.scalar(select(ConnectionJob).where(ConnectionJob.active_key == "import"))
        if not job or job.github_user_id != actor.github_user_id or job.repository_name != name:
            raise HTTPException(409, "An import was started concurrently; refresh its status") from None
        created = False
    if created:
        tasks.add_task(run_job, job.id)
    return job_output(job)


@router.get("/connections/jobs/{job_id}")
def job_status(job_id: str, db: DB, actor: Actor):
    github_mode()
    expire_jobs(db)
    job = db.get(ConnectionJob, job_id)
    if not job or job.github_user_id != actor.github_user_id:
        raise HTTPException(404, "Import job not found")
    return job_output(job)
