"""Commit-pinned repository context and on-demand contributor guides."""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "repository_contexts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("tree", sa.JSON(), nullable=False),
        sa.Column("partial", sa.Boolean(), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("repository_id", "commit_sha", name="uq_context_repo_commit"),
    )
    op.create_index("ix_repository_contexts_repository_id", "repository_contexts", ["repository_id"])
    op.create_table(
        "contributor_guides",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("issue_id", sa.Integer(), sa.ForeignKey("issues.id"), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("snapshots.id"), nullable=False),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column(
            "session_id", sa.Integer(), sa.ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("requested_by", sa.String(100), nullable=False),
        sa.Column("request_key", sa.String(100), nullable=False, unique=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("version_key", sa.String(64), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=True),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("active_key", sa.String(100), nullable=True, unique=True),
        sa.Column("stage", sa.String(100), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("partial", sa.Boolean(), nullable=False),
        sa.Column("reused", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(100), nullable=True),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(100), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("status IN ('queued','running','complete','failed')", name="ck_guide_status"),
    )
    for column in ("issue_id", "snapshot_id", "repository_id", "cache_key"):
        op.create_index(f"ix_contributor_guides_{column}", "contributor_guides", [column])


def downgrade():
    op.drop_table("contributor_guides")
    op.drop_table("repository_contexts")
