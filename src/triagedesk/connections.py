"""Bounded, observable repository imports for verified maintainers.

One import/index job runs per installation. PostgreSQL's unique active_key enforces
that across request threads. A renewable lease releases interrupted jobs for retry;
GitHub page checkpoints preserve completed work. This is a small single-API-instance
runner, not a distributed queue or an automatic synchronization scheduler.
"""

import json
import logging
import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from triagedesk import db as database
from triagedesk.ai_labels import analyze_repository
from triagedesk.authentication import Principal, decrypt, verify_maintainer
from triagedesk.auto_categories import categorize
from triagedesk.github import GitHubClient, GitHubError, aware, ingest
from triagedesk.issue_lifecycle import purge_closed
from triagedesk.models import AuthSession, ConnectionJob, Repository, RepositoryAccess, utcnow
from triagedesk.retrieval import build_index

LEASE_SECONDS = 180


def expire_jobs(db):
    db.execute(
        update(ConnectionJob)
        .where(ConnectionJob.active_key.is_not(None), ConnectionJob.lease_until < utcnow())
        .values(
            status="failed",
            active_key=None,
            stage="Import interrupted",
            error="The import stopped before completion. Retry to continue from saved page checkpoints.",
            updated_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()


def start_job(db, principal, name, metadata, role, limit, incremental):
    expire_jobs(db)
    active = db.scalar(select(ConnectionJob).where(ConnectionJob.active_key == "import"))
    if active:
        if active.github_user_id == principal.github_user_id and active.repository_name == name:
            return active, False
        raise HTTPException(409, "Another repository import is running; try again after it finishes")
    repo = db.scalar(select(Repository).where(Repository.github_id == metadata["id"]))
    if repo is None:
        repo = Repository(github_id=metadata["id"], full_name=name, source_url=f"https://github.com/{name}")
        db.add(repo)
        db.flush()
    elif repo.full_name != name:
        repo.full_name = name
    grant = db.scalar(
        select(RepositoryAccess).where(
            RepositoryAccess.repository_id == repo.id,
            RepositoryAccess.github_user_id == principal.github_user_id,
        )
    )
    if grant is None:
        grant = RepositoryAccess(repository_id=repo.id, github_user_id=principal.github_user_id, role=role)
        db.add(grant)
    grant.role, grant.verified_at = role, utcnow()
    job = ConnectionJob(
        id=str(uuid.uuid4()),
        github_user_id=principal.github_user_id,
        session_id=principal.session_id,
        repository_name=name,
        repository_id=repo.id,
        incremental=incremental,
        object_limit=limit,
        active_key="import",
        lease_until=utcnow() + timedelta(seconds=LEASE_SECONDS),
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        active = db.scalar(select(ConnectionJob).where(ConnectionJob.active_key == "import"))
        if active and active.github_user_id == principal.github_user_id and active.repository_name == name:
            return active, False
        raise HTTPException(409, "An import was started concurrently; refresh its status") from None
    return job, True


def job_output(job):
    return {
        key: getattr(job, key)
        for key in [
            "id",
            "repository_name",
            "repository_id",
            "incremental",
            "status",
            "stage",
            "result",
            "error",
            "created_at",
            "updated_at",
        ]
    }


def touch(job_id, stage, result=None):
    with Session(database.engine(), expire_on_commit=False) as db:
        job = db.get(ConnectionJob, job_id)
        if not job or job.active_key != "import" or job.status == "failed":
            raise RuntimeError("The import lease is no longer active")
        session = db.get(AuthSession, job.session_id) if job.session_id else None
        if not session or aware(session.expires_at) <= utcnow():
            raise HTTPException(401, "The GitHub session expired or was signed out; sign in and retry")
        job.status, job.stage = "running", stage
        if result is not None:
            job.result = {**job.result, **result}
        job.updated_at = utcnow()
        job.lease_until = utcnow() + timedelta(seconds=LEASE_SECONDS)
        db.commit()


def run_job(job_id):
    client = None
    try:
        touch(job_id, "Verifying GitHub repository access")
        with Session(database.engine(), expire_on_commit=False) as db:
            job = db.get(ConnectionJob, job_id)
            session = db.get(AuthSession, job.session_id)
            principal = Principal(session.id, session.github_user_id, session.login, session.encrypted_token)
            metadata, _ = verify_maintainer(principal, job.repository_name)
            repo = db.get(Repository, job.repository_id)
            if metadata["id"] != repo.github_id:
                raise HTTPException(409, "The repository identity changed; reconnect it")
            name, limit, incremental = job.repository_name, job.object_limit, job.incremental
        touch(job_id, "Fetching actual GitHub issues")
        client = GitHubClient(token=decrypt(principal.encrypted_token), max_wait=30)
        imported = ingest(
            database.engine(),
            name,
            limit,
            incremental=incremental,
            client=client,
            active_only=True,
            progress=lambda counts: touch(job_id, "Fetching actual GitHub issues", {"import": counts}),
        )
        touch(job_id, "Categorizing imported issues", {"import": imported})
        with Session(database.engine(), expire_on_commit=False) as db:
            job = db.get(ConnectionJob, job_id)
            repository = db.get(Repository, job.repository_id)
            removed = purge_closed(db, repository.id)
            categories = categorize(db, repository)
        touch(job_id, "Assigning AI labels", {"closed_removed": removed})
        ai_result = analyze_repository(
            database.engine(), repository.id, progress=lambda: touch(job_id, "Assigning AI labels")
        )
        touch(job_id, "Saving AI labels", {"ai_labels": ai_result})
        touch(job_id, "Building related-report search", {"categorization": categories})
        with Session(database.engine(), expire_on_commit=False) as db:
            index = build_index(db)
        with Session(database.engine()) as db:
            job = db.get(ConnectionJob, job_id)
            if job.active_key != "import" or job.status == "failed":
                return
            job.result = {**job.result, "retrieval": index}
            job.status, job.stage, job.active_key = "complete", "Ready to review", None
            job.updated_at = utcnow()
            db.commit()
    except Exception as exc:
        logging.getLogger("triagedesk").error(
            json.dumps({"event": "connection_job_failed", "job_id": job_id, "type": type(exc).__name__})
        )
        if isinstance(exc, HTTPException):
            message = str(exc.detail)
        elif isinstance(exc, GitHubError):
            message = str(exc)
        else:
            message = "The import could not finish. Retry from saved progress or inspect the service logs."
        with Session(database.engine()) as db:
            job = db.get(ConnectionJob, job_id)
            if job:
                job.status, job.stage, job.active_key = "failed", "Import needs attention", None
                job.error, job.updated_at = message[:500], utcnow()
                db.commit()
    finally:
        if client:
            client.close()
