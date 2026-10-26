from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

CATEGORIES = ("bug", "enhancement", "question")


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Repository(Base):
    __tablename__ = "repositories"
    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    full_name: Mapped[str] = mapped_column(String(200), unique=True)
    source_url: Mapped[str] = mapped_column(String(500))
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    first_imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checkpoint: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta_etag: Mapped[str | None] = mapped_column(String(300))
    partial: Mapped[bool] = mapped_column(Boolean, default=True)


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("repository_id", "number", name="uq_issue_repo_number"),
        CheckConstraint("state IN ('open','closed')", name="ck_issue_state"),
        Index("ix_issue_repo_created", "repository_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(String(500))
    state: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    labels: Mapped[list] = mapped_column(JSON, default=list)
    content_hash: Mapped[str] = mapped_column(String(64))
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshots.id", use_alter=True, name="fk_issue_current_snapshot")
    )
    review_revision: Mapped[int] = mapped_column(Integer, default=0)
    available: Mapped[bool] = mapped_column(Boolean, default=True)


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (UniqueConstraint("issue_id", "snapshot_hash", name="uq_snapshot_issue_hash"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), index=True)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    labels: Mapped[list] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(100), unique=True)
    dataset_version: Mapped[str] = mapped_column(String(100))
    config: Mapped[dict] = mapped_column(JSON)
    splits: Mapped[dict] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)
    artifact_path: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "model_version", name="uq_prediction_snapshot_model"),
        CheckConstraint("category IN ('bug','enhancement','question')", name="ck_prediction_category"),
        CheckConstraint("max_score >= 0 AND max_score <= 1", name="ck_prediction_score"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id"), index=True)
    category: Mapped[str] = mapped_column(String(20))
    scores: Mapped[dict] = mapped_column(JSON)
    max_score: Mapped[float] = mapped_column(Float)
    needs_review: Mapped[bool] = mapped_column(Boolean)
    model_version: Mapped[str] = mapped_column(String(100))
    input_hash: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(30), default="trained_model", server_default="trained_model")
    explanation: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("action IN ('accept','correct','defer','skip')", name="ck_review_action"),
        CheckConstraint(
            "category IS NULL OR category IN ('bug','enhancement','question')", name="ck_review_category"
        ),
        CheckConstraint(
            "(action IN ('accept','correct') AND category IS NOT NULL) OR "
            "(action IN ('defer','skip') AND category IS NULL)",
            name="ck_review_action_category",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id"))
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("predictions.id"))
    action: Mapped[str] = mapped_column(String(20))
    category: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str] = mapped_column(String(100))
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SimilarityJudgment(Base):
    __tablename__ = "similarity_judgments"
    __table_args__ = (
        CheckConstraint("query_issue_id != candidate_issue_id", name="ck_judgment_no_self"),
        CheckConstraint(
            "judgment IN ('related','duplicate','unrelated','uncertain')", name="ck_judgment_value"
        ),
        CheckConstraint("purpose IN ('ui','evaluation')", name="ck_judgment_purpose"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    query_issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), index=True)
    candidate_issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"))
    query_snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id"))
    candidate_snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id"))
    judgment: Mapped[str] = mapped_column(String(20))
    reviewer: Mapped[str] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(String(20), default="ui")
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportRun(Base):
    __tablename__ = "import_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")
    imported: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    excluded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    github_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    login: Mapped[str] = mapped_column(String(100))
    encrypted_token: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DeviceLogin(Base):
    __tablename__ = "device_logins"
    id: Mapped[int] = mapped_column(primary_key=True)
    handle_hash: Mapped[str] = mapped_column(String(64), unique=True)
    encrypted_code: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    next_poll_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    interval: Mapped[int] = mapped_column(Integer)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RepositoryAccess(Base):
    __tablename__ = "repository_access"
    __table_args__ = (UniqueConstraint("repository_id", "github_user_id", name="uq_repo_github_user"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    github_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    role: Mapped[str] = mapped_column(String(50))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConnectionJob(Base):
    __tablename__ = "connection_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','complete','failed')", name="ck_connection_status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    github_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("auth_sessions.id"))
    repository_name: Mapped[str] = mapped_column(String(200))
    repository_id: Mapped[int | None] = mapped_column(ForeignKey("repositories.id"))
    incremental: Mapped[bool] = mapped_column(Boolean, default=False)
    object_limit: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    stage: Mapped[str] = mapped_column(String(100), default="Waiting to import")
    active_key: Mapped[str | None] = mapped_column(String(20), unique=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@event.listens_for(Snapshot, "before_update")
@event.listens_for(Snapshot, "before_delete")
def immutable_snapshot(*_):
    raise ValueError("Issue snapshots are immutable; insert a new snapshot")
