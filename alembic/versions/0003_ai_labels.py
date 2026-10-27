"""Persistent AI labels, custom taxonomy, and separate label reviews."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("repositories", sa.Column("label_taxonomy", sa.JSON(), nullable=True))
    op.create_table(
        "label_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("issue_id", sa.Integer(), sa.ForeignKey("issues.id"), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("snapshots.id"), nullable=False),
        sa.Column("analyzer_key", sa.String(64), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("uncertain", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(100), nullable=True),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.String(36), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("snapshot_id", "analyzer_key", name="uq_analysis_snapshot_analyzer"),
        sa.CheckConstraint("status IN ('running','complete','failed')", name="ck_analysis_status"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_analysis_score"
        ),
    )
    op.create_index("ix_label_analyses_issue_id", "label_analyses", ["issue_id"])
    op.create_index("ix_label_analyses_snapshot_id", "label_analyses", ["snapshot_id"])
    op.create_table(
        "label_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("issue_id", sa.Integer(), sa.ForeignKey("issues.id"), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("snapshots.id"), nullable=False),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("label_analyses.id"), nullable=True),
        sa.Column("taxonomy_hash", sa.String(64), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.String(100), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_label_reviews_issue_id", "label_reviews", ["issue_id"])
    op.create_index("ix_label_reviews_snapshot_id", "label_reviews", ["snapshot_id"])
    op.create_table(
        "label_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("issue_id", sa.Integer(), sa.ForeignKey("issues.id"), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("snapshots.id"), nullable=False),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("label_analyses.id"), nullable=True),
        sa.Column("review_id", sa.Integer(), sa.ForeignKey("label_reviews.id"), nullable=True),
        sa.Column("origin", sa.String(10), nullable=False),
        sa.Column("group", sa.String(30), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.UniqueConstraint("issue_id", "origin", "group", "name", name="uq_issue_origin_label"),
        sa.CheckConstraint("origin IN ('ai','human')", name="ck_label_origin"),
    )
    op.create_index("ix_label_assignments_issue_id", "label_assignments", ["issue_id"])
    op.create_index("ix_label_group_name", "label_assignments", ["group", "name"])


def downgrade():
    op.drop_table("label_assignments")
    op.drop_table("label_reviews")
    op.drop_table("label_analyses")
    op.drop_column("repositories", "label_taxonomy")
