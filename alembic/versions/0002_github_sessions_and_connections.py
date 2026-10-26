"""GitHub sessions, repository grants, observable imports, suggestion provenance.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "predictions", sa.Column("method", sa.String(30), nullable=False, server_default="trained_model")
    )
    op.add_column("predictions", sa.Column("explanation", sa.Text(), nullable=False, server_default=""))
    op.execute("UPDATE predictions SET method = 'illustrative' WHERE model_version LIKE 'fixture%'")
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("github_user_id", sa.BigInteger(), nullable=False),
        sa.Column("login", sa.String(100), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_sessions_github_user_id", "auth_sessions", ["github_user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table(
        "device_logins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("handle_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("encrypted_code", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval", sa.Integer(), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_device_logins_expires_at", "device_logins", ["expires_at"])
    op.create_table(
        "repository_access",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("github_user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("repository_id", "github_user_id", name="uq_repo_github_user"),
    )
    op.create_index("ix_repository_access_repository_id", "repository_access", ["repository_id"])
    op.create_index("ix_repository_access_github_user_id", "repository_access", ["github_user_id"])
    op.create_table(
        "connection_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("github_user_id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("auth_sessions.id", ondelete="SET NULL")),
        sa.Column("repository_name", sa.String(200), nullable=False),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id")),
        sa.Column("incremental", sa.Boolean(), nullable=False),
        sa.Column("object_limit", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(100), nullable=False),
        sa.Column("active_key", sa.String(20), unique=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('queued','running','complete','failed')", name="ck_connection_status"),
    )
    op.create_index("ix_connection_jobs_github_user_id", "connection_jobs", ["github_user_id"])


def downgrade():
    op.drop_table("connection_jobs")
    op.drop_table("repository_access")
    op.drop_table("device_logins")
    op.drop_table("auth_sessions")
    op.drop_column("predictions", "explanation")
    op.drop_column("predictions", "method")
