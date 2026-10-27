import hmac
import json
import logging
import time
from typing import Annotated, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from triagedesk import triage
from triagedesk.ai_labels import (
    GROUPS,
    provider_cooldown,
    retry_correctable_failures,
    taxonomy_for,
    validate_taxonomy,
)
from triagedesk.authentication import Principal, authorize_repository_write, principal_for, require_connection
from triagedesk.config import settings
from triagedesk.connection_routes import Actor
from triagedesk.connection_routes import router as connection_router
from triagedesk.db import get_session
from triagedesk.models import ImportRun, Issue, Prediction, Repository, RepositoryAccess, Review
from triagedesk.queries import dashboard, issue_scope, list_issues
from triagedesk.reviews import submit_judgment, submit_review
from triagedesk.schemas import (
    DashboardSummary,
    IssueDetail,
    IssueFilters,
    IssuePage,
    JudgmentInput,
    ModelSummary,
    RelatedResults,
    RepositoryOut,
    ReviewHistory,
    ReviewInput,
    SavedJudgment,
    SavedReview,
    Suggestion,
    TextInput,
)

app = FastAPI(
    title="TriageDesk", version="0.3.4", description="Human-reviewed triage. GitHub operations are read-only."
)
app.include_router(connection_router)
log = logging.getLogger("triagedesk")
logging.basicConfig(level=logging.INFO, format="%(message)s")
auth = HTTPBearer(auto_error=False)
DB = Annotated[Session, Depends(get_session)]
Filters = Annotated[IssueFilters, Query()]


def writer(db: DB, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(auth)]):
    config = settings()
    if config.read_only:
        raise HTTPException(403, "This installation is read-only")
    if config.auth_mode == "github":
        if not credentials:
            raise HTTPException(401, "GitHub sign-in required")
        return principal_for(db, credentials.credentials)
    expected = config.reviewer_token.get_secret_value()
    if not expected or not credentials or not hmac.compare_digest(credentials.credentials, expected):
        raise HTTPException(401, "Reviewer access token required", headers={"WWW-Authenticate": "Bearer"})
    return config.reviewer_name


@app.middleware("http")
async def request_log(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    if request.url.path.startswith("/auth/"):
        response.headers["Cache-Control"] = "no-store"
    # Never log headers, request bodies, query text, tokens, or issue content.
    log.info(
        json.dumps(
            {
                "event": "http",
                "method": request.method,
                "route": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 2),
            }
        )
    )
    return response


@app.exception_handler(HTTPException)
async def http_error(_, exc):
    return JSONResponse(
        status_code=exc.status_code, content={"error": {"message": exc.detail}}, headers=exc.headers
    )


@app.exception_handler(RequestValidationError)
async def validation_error(_, exc):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "message": "Invalid request",
                "fields": [{"location": list(e["loc"]), "message": e["msg"]} for e in exc.errors()],
            }
        },
    )


@app.exception_handler(SQLAlchemyError)
async def database_error(_, exc):
    log.error(json.dumps({"event": "database_error", "type": type(exc).__name__}))
    return JSONResponse(
        status_code=503, content={"error": {"message": "Database unavailable; try again shortly"}}
    )


def active_issue(session, issue_id, actor=None):
    issue = session.get(Issue, issue_id)
    if not issue or not issue.available:
        raise HTTPException(404, "Issue not found or no longer available")
    repo = session.get(Repository, issue.repository_id)
    if repo.synthetic != (settings().mode == "fixture"):
        raise HTTPException(404, "Issue not in the active data mode")
    require_connection(session, actor, issue.repository_id)
    return issue


@app.get("/health/live")
def live():
    return {"status": "alive"}


@app.get("/health/ready")
def ready(db: DB):
    try:
        db.execute(text("SELECT 1"))
        db.execute(select(Repository.id).limit(1))
        version = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if version != "0003":
            raise HTTPException(503, "Database migration required")
    except SQLAlchemyError:
        raise HTTPException(503, "Database unavailable or migrations missing") from None
    return {"status": "ready", "mode": settings().mode, "model_required": False}


@app.get("/meta")
def meta():
    return {
        "name": "TriageDesk",
        "mode": settings().mode,
        "writes_enabled": not settings().read_only
        and (settings().auth_mode == "github" or bool(settings().reviewer_token.get_secret_value())),
        "auth_mode": settings().auth_mode,
        "github_browser_login": bool(settings().github_client_id),
        "token_login": settings().allow_token_login,
        "connection_limit": 3000,
        "scores": "Model scores are not calibrated probabilities",
        "github_writes": False,
        "ai_configured": bool(settings().groq_api_key.get_secret_value()),
        "ai_confidence_threshold": settings().ai_confidence_threshold,
        "auto_sync_seconds": settings().auto_sync_seconds,
    }


@app.get("/repositories", response_model=list[RepositoryOut])
def repositories(db: DB, actor: Actor):
    query = select(Repository).where(Repository.synthetic == (settings().mode == "fixture"))
    if actor:
        query = query.join(RepositoryAccess).where(RepositoryAccess.github_user_id == actor.github_user_id)
    repos = db.scalars(query)
    return [
        {
            "id": r.id,
            "full_name": r.full_name,
            "source_url": r.source_url,
            "partial": r.partial,
            "synthetic": r.synthetic,
            "last_synced_at": r.last_synced_at,
            "checkpoint": r.checkpoint,
        }
        for r in repos
    ]


@app.get("/issues", response_model=IssuePage)
def issues(db: DB, filters: Filters, actor: Actor):
    require_connection(db, actor, filters.repository_id)
    return list_issues(db, filters, settings().mode)


@app.get("/issues/{issue_id}", response_model=IssueDetail)
def issue_detail(issue_id: int, db: DB, actor: Actor):
    issue = active_issue(db, issue_id, actor)
    row = (
        db.execute(issue_scope(IssueFilters(), settings().mode).where(Issue.id == issue_id)).mappings().one()
    )
    result = dict(row)
    result.update(
        body=issue.body,
        labels=issue.labels,
        content_hash=issue.content_hash,
        ingested_at=issue.ingested_at,
        closed_at=issue.closed_at,
    )
    prediction = db.get(Prediction, result["prediction_id"]) if result["prediction_id"] else None
    result["prediction"] = (
        {
            "id": prediction.id,
            "category": prediction.category,
            "scores": prediction.scores,
            "max_score": prediction.max_score,
            "needs_review": prediction.needs_review,
            "model_version": prediction.model_version,
            "created_at": prediction.created_at,
            "input_hash": prediction.input_hash,
            "method": prediction.method,
            "explanation": prediction.explanation,
        }
        if prediction
        else None
    )
    return result


@app.get("/issues/{issue_id}/reviews", response_model=list[ReviewHistory])
def history(issue_id: int, db: DB, actor: Actor):
    active_issue(db, issue_id, actor)
    rows = db.scalars(select(Review).where(Review.issue_id == issue_id).order_by(Review.id.desc()).limit(100))
    return [
        {
            "id": r.id,
            "snapshot_id": r.snapshot_id,
            "prediction_id": r.prediction_id,
            "action": r.action,
            "category": r.category,
            "note": r.note,
            "reviewer": r.reviewer,
            "revision": r.revision,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@app.post("/issues/{issue_id}/reviews", status_code=201, response_model=SavedReview)
def save_review(issue_id: int, payload: ReviewInput, db: DB, reviewer: Annotated[str, Depends(writer)]):
    issue = active_issue(db, issue_id, reviewer if isinstance(reviewer, Principal) else None)
    if isinstance(reviewer, Principal):
        authorize_repository_write(db, reviewer, issue.repository_id)
        reviewer = f"github:{reviewer.login}#{reviewer.github_user_id}"
    review = submit_review(db, issue, payload, reviewer)
    return {
        "id": review.id,
        "revision": review.revision,
        "action": review.action,
        "category": review.category,
        "created_at": review.created_at,
    }


@app.post("/issues/{issue_id}/judgments", status_code=201, response_model=SavedJudgment)
def save_judgment(issue_id: int, payload: JudgmentInput, db: DB, reviewer: Annotated[str, Depends(writer)]):
    actor = reviewer if isinstance(reviewer, Principal) else None
    issue = active_issue(db, issue_id, actor)
    candidate = active_issue(db, payload.candidate_issue_id, actor)
    if actor:
        authorize_repository_write(db, actor, issue.repository_id)
        reviewer = f"github:{actor.login}#{actor.github_user_id}"
    result = submit_judgment(db, issue, candidate, payload, reviewer)
    return {"id": result.id, "judgment": result.judgment, "purpose": result.purpose}


@app.get("/dashboard", response_model=DashboardSummary)
def summary(db: DB, filters: Filters, actor: Actor):
    require_connection(db, actor, filters.repository_id)
    return dashboard(db, filters, settings().mode)


@app.post("/classify", response_model=Suggestion)
def classify(payload: TextInput, db: DB, actor: Actor):
    from triagedesk.serving import classify_text

    require_connection(db, actor, payload.repository_id)
    return classify_text(payload.title, payload.body)


@app.post("/related", response_model=RelatedResults)
def related_text(
    payload: TextInput, db: DB, actor: Actor, method: Literal["auto", "tfidf", "semantic"] = "auto"
):
    from triagedesk.retrieval import retrieve

    require_connection(db, actor, payload.repository_id)
    return retrieve(db, payload.title, payload.body, payload.repository_id, method=method)


@app.get("/issues/{issue_id}/related", response_model=RelatedResults)
def related(issue_id: int, db: DB, actor: Actor, method: Literal["auto", "tfidf", "semantic"] = "auto"):
    from triagedesk.retrieval import retrieve

    issue = active_issue(db, issue_id, actor)
    return retrieve(db, issue.title, issue.body, issue.repository_id, exclude_id=issue.id, method=method)


@app.get("/models", response_model=ModelSummary)
def models(actor: Actor):
    from triagedesk.serving import model_metadata

    return model_metadata()


@app.get("/imports")
def import_status(db: DB, actor: Actor):
    query = (
        select(ImportRun, Repository.full_name)
        .join(Repository)
        .where(Repository.synthetic == (settings().mode == "fixture"))
        .order_by(ImportRun.id.desc())
        .limit(20)
    )
    if actor:
        query = query.where(
            Repository.id.in_(
                select(RepositoryAccess.repository_id).where(
                    RepositoryAccess.github_user_id == actor.github_user_id
                )
            )
        )
    rows = db.execute(query)
    return [
        {
            "id": run.id,
            "repository": name,
            "status": run.status,
            "imported": run.imported,
            "updated": run.updated,
            "excluded": run.excluded,
            "failed": run.failed,
            "fetched": run.fetched,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "error": run.error,
        }
        for run, name in rows
    ]


def triage_repository(db, repository_id, actor):
    require_connection(db, actor, repository_id)
    repo = db.get(Repository, repository_id)
    if not repo or repo.synthetic != (settings().mode == "fixture"):
        raise HTTPException(404, "Repository not found")
    return repo


@app.get("/triage/{repository_id}/summary")
def label_summary(repository_id: int, db: DB, actor: Actor):
    return triage.summary(db, triage_repository(db, repository_id, actor))


@app.get("/triage/{repository_id}/issues")
def labeled_issues(
    repository_id: int,
    db: DB,
    actor: Actor,
    status: Literal["all", "auto_sorted", "needs_review", "reviewed", "pending"] = "all",
    group: str | None = Query(None, max_length=30),
    label: str | None = Query(None, max_length=100),
    search: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    repo = triage_repository(db, repository_id, actor)
    if (group and group not in GROUPS) or (label and label not in taxonomy_for(repo).get(group, [])):
        raise HTTPException(422, "Choose a label in one of the five groups")
    return triage.list_labeled_issues(db, repo, status, group, label, search, page, page_size)


@app.get("/triage/issues/{issue_id}")
def labeled_issue_detail(issue_id: int, db: DB, actor: Actor):
    issue = active_issue(db, issue_id, actor)
    repo = triage_repository(db, issue.repository_id, actor)
    rows = db.execute(triage.scope(repo).where(Issue.id == issue_id)).mappings().all()
    if not rows:
        raise HTTPException(404, "The issue is closed or unavailable")
    result = triage.labels_for_rows(db, rows)[0]
    result.update(
        body=issue.body,
        source_labels=issue.labels,
        taxonomy=taxonomy_for(repo),
        taxonomy_hash=triage.digest(taxonomy_for(repo)),
    )
    analysis = db.get(triage.LabelAnalysis, result["analysis_id"]) if result["analysis_id"] else None
    result["analysis"] = (
        {
            "model": analysis.model,
            "labels": analysis.labels,
            "created_at": analysis.created_at,
            "confidence": analysis.confidence,
            "uncertain": analysis.uncertain,
            "status": analysis.status,
            "summary": analysis.summary,
            "explanation": analysis.explanation,
        }
        if analysis
        else None
    )
    result["history"] = [
        {
            "labels": row.labels,
            "note": row.note,
            "reviewer": row.reviewer,
            "created_at": row.created_at,
            "snapshot_id": row.snapshot_id,
        }
        for row in db.scalars(
            select(triage.LabelReview)
            .where(triage.LabelReview.issue_id == issue_id)
            .order_by(triage.LabelReview.id.desc())
            .limit(100)
        )
    ]
    result["history"].extend(
        {
            "labels": [{"group": "type", "name": row.category}] if row.category else [],
            "note": row.note,
            "reviewer": row.reviewer,
            "created_at": row.created_at,
            "snapshot_id": row.snapshot_id,
        }
        for row in db.scalars(
            select(Review).where(Review.issue_id == issue_id).order_by(Review.id.desc()).limit(100)
        )
    )
    result["history"].sort(key=lambda row: row["created_at"].timestamp(), reverse=True)
    result["history"] = result["history"][:100]
    return result


@app.post("/triage/issues/{issue_id}/reviews", status_code=201)
def review_labels(
    issue_id: int, payload: triage.LabelReviewInput, db: DB, reviewer: Annotated[str, Depends(writer)]
):
    actor = reviewer if isinstance(reviewer, Principal) else None
    issue = active_issue(db, issue_id, actor)
    repo = triage_repository(db, issue.repository_id, actor)
    if actor:
        authorize_repository_write(db, actor, repo.id)
        reviewer = f"github:{actor.login}#{actor.github_user_id}"
    review = triage.save_label_review(db, issue, repo, payload, reviewer)
    return {"id": review.id, "revision": review.revision, "labels": review.labels}


@app.put("/triage/{repository_id}/taxonomy")
def update_label_taxonomy(
    repository_id: int, payload: dict, db: DB, reviewer: Annotated[str, Depends(writer)]
):
    actor = reviewer if isinstance(reviewer, Principal) else None
    repo = triage_repository(db, repository_id, actor)
    if actor:
        authorize_repository_write(db, actor, repo.id)
    try:
        repo.label_taxonomy = validate_taxonomy(payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    db.commit()
    return {"taxonomy": repo.label_taxonomy}


@app.post("/triage/{repository_id}/refresh", status_code=202)
def refresh_workspace(repository_id: int, tasks: BackgroundTasks, db: DB, actor: Actor):
    return schedule_workspace_job(repository_id, tasks, db, actor)


@app.post("/triage/{repository_id}/analyze", status_code=202)
def analyze_workspace(repository_id: int, tasks: BackgroundTasks, db: DB, actor: Actor):
    return schedule_workspace_job(repository_id, tasks, db, actor, ai_only=True)


def schedule_workspace_job(repository_id, tasks, db, actor, ai_only=False):
    from datetime import timedelta

    from triagedesk.authentication import verify_maintainer
    from triagedesk.connections import expire_jobs, job_output, run_job, start_job
    from triagedesk.github import aware
    from triagedesk.models import ConnectionJob, utcnow

    if not actor:
        raise HTTPException(403, "Automatic synchronization requires GitHub sign-in")
    if settings().read_only:
        raise HTTPException(403, "This installation is read-only")
    repo = triage_repository(db, repository_id, actor)
    expire_jobs(db)
    active = db.scalar(select(ConnectionJob).where(ConnectionJob.active_key == "import"))
    if active:
        if active.github_user_id == actor.github_user_id and active.repository_id == repository_id:
            return job_output(active)
        return {"status": "busy"}
    if ai_only:
        if not settings().groq_api_key.get_secret_value():
            raise HTTPException(503, "The backend has not loaded a Groq API key")
        cooldown = provider_cooldown(db)
        if cooldown:
            raise HTTPException(
                429, f"AI is waiting for provider backoff until {aware(cooldown.retry_after).isoformat()}"
            )
    latest = db.scalar(
        select(ConnectionJob.created_at)
        .where(ConnectionJob.repository_id == repository_id)
        .order_by(ConnectionJob.created_at.desc())
        .limit(1)
    )
    interval = 10 if ai_only else settings().auto_sync_seconds
    if latest and aware(latest) + timedelta(seconds=interval) > utcnow():
        return {"status": "idle"}
    metadata, role = verify_maintainer(actor, repo.full_name)
    job, created = start_job(db, actor, repo.full_name, metadata, role, 3000, True)
    if created:
        if ai_only:
            retry_correctable_failures(db, repo)
        tasks.add_task(run_job, job.id, ai_only=ai_only)
    return job_output(job)
