"""Cloud taxonomy, user-managed status, and retirement of the offline classifier.

Existing issue text, AI history, and human review records are preserved. Legacy
single-category reviews are copied before their obsolete tables are removed.
"""

import hashlib
import json

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TAXONOMY = {
    "type": [
        "type: bug",
        "type: feature or enhancement",
        "type: docs",
        "type: chore or refactor",
        "type: question",
    ],
    "priority": ["priority: high", "priority: medium", "priority: low"],
    "area": ["area: frontend", "area: backend", "area: api"],
    "contributor": ["help wanted", "good first issue"],
}
TYPE_MAP = {
    "bug": "type: bug",
    "enhancement": "type: feature or enhancement",
    "documentation": "type: docs",
    "question": "type: question",
}


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()


def migrated_labels(labels):
    result = []
    for label in labels:
        group, name = label["group"], label["name"]
        if group == "type":
            name = TYPE_MAP.get(name, name)
        if group == "scope":
            group, name = "area", {"UI/UX": "area: frontend", "API": "area: api"}.get(name, name)
        if name in TAXONOMY.get(group, []) and {"group": group, "name": name} not in result:
            result.append({"group": group, "name": name})
    if sum(x["group"] == "type" for x in result) != 1:
        return None
    priorities = [x for x in result if x["group"] == "priority"]
    if len(priorities) != 1:
        result = [x for x in result if x["group"] != "priority"] + [
            {"group": "priority", "name": "priority: low"}
        ]
    areas = [x for x in result if x["group"] == "area"]
    if len(areas) > 1:
        result = [x for x in result if x["group"] != "area"]
    return result


def upgrade():
    op.add_column("issues", sa.Column("work_status", sa.String(20), nullable=False, server_default="open"))
    op.add_column("issues", sa.Column("work_revision", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint(
        "ck_issue_work_status", "issues", "work_status IN ('open','in progress','blocked')"
    )
    op.create_table(
        "issue_activity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("issue_id", sa.Integer(), sa.ForeignKey("issues.id"), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=False),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_issue_activity_issue_id", "issue_activity", ["issue_id"])
    bind = op.get_bind()
    metadata = sa.MetaData()
    reviews = sa.Table("reviews", metadata, autoload_with=bind)
    label_reviews = sa.Table("label_reviews", metadata, autoload_with=bind)
    assignments = sa.Table("label_assignments", metadata, autoload_with=bind)
    taxonomy_hash = fingerprint(TAXONOMY)
    # Keep human decisions usable with the new fixed vocabulary and retain their original labels in notes.
    for row in bind.execute(sa.select(label_reviews)).mappings().all():
        mapped = migrated_labels(row["labels"])
        if mapped is None:
            continue  # Unsupported custom reviews remain in history and queue for fresh AI/review.
        note = row["note"] + "\nPrevious labels: " + json.dumps(row["labels"], ensure_ascii=False)
        bind.execute(
            label_reviews.update()
            .where(label_reviews.c.id == row["id"])
            .values(labels=mapped, taxonomy_hash=taxonomy_hash, note=note)
        )
        current = bind.execute(
            sa.select(assignments.c.id).where(assignments.c.review_id == row["id"])
        ).first()
        if current:
            bind.execute(assignments.delete().where(assignments.c.review_id == row["id"]))
            bind.execute(
                assignments.insert(),
                [
                    dict(
                        issue_id=row["issue_id"],
                        snapshot_id=row["snapshot_id"],
                        review_id=row["id"],
                        analysis_id=row["analysis_id"],
                        origin="human",
                        group=x["group"],
                        name=x["name"],
                        confidence=None,
                    )
                    for x in mapped
                ],
            )
    for row in bind.execute(sa.select(reviews).order_by(reviews.c.id)).mappings().all():
        labels = migrated_labels([{"group": "type", "name": row["category"]}]) if row["category"] else None
        # Defer/skip records are retained as history, without preventing new analysis.
        labels = labels if row["action"] in ("accept", "correct") else []
        note = f"Previous {row['action']} review. " + row["note"]
        bind.execute(
            label_reviews.insert().values(
                issue_id=row["issue_id"],
                snapshot_id=row["snapshot_id"],
                analysis_id=None,
                taxonomy_hash=taxonomy_hash if labels else "legacy-" + "0" * 57,
                labels=labels or [],
                note=note,
                reviewer=row["reviewer"],
                revision=row["revision"],
                idempotency_key="legacy-review-" + str(row["id"]),
                payload_hash=row["payload_hash"],
                created_at=row["created_at"],
            )
        )
    issues = sa.Table("issues", metadata, autoload_with=bind)
    for issue in bind.execute(sa.select(issues.c.id, issues.c.snapshot_id)).mappings().all():
        latest = (
            bind.execute(
                sa.select(label_reviews)
                .where(label_reviews.c.snapshot_id == issue["snapshot_id"])
                .order_by(label_reviews.c.created_at.desc(), label_reviews.c.id.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        if latest and latest["taxonomy_hash"] == taxonomy_hash and latest["labels"]:
            bind.execute(
                assignments.delete().where(
                    assignments.c.issue_id == issue["id"], assignments.c.origin == "human"
                )
            )
            bind.execute(
                assignments.insert(),
                [
                    dict(
                        issue_id=issue["id"],
                        snapshot_id=issue["snapshot_id"],
                        review_id=latest["id"],
                        analysis_id=latest["analysis_id"],
                        origin="human",
                        group=x["group"],
                        name=x["name"],
                        confidence=None,
                    )
                    for x in latest["labels"]
                ],
            )
    op.drop_table("similarity_judgments")
    op.drop_table("reviews")
    op.drop_table("predictions")
    op.drop_table("experiments")
    # Synthetic fixture workspaces belonged to the retired local demonstration.
    for table in ("label_assignments", "label_reviews", "label_analyses", "issue_activity"):
        op.execute(
            sa.text(
                f"DELETE FROM {table} WHERE issue_id IN (SELECT i.id FROM issues i JOIN repositories r ON r.id=i.repository_id WHERE r.synthetic=true)"
            )
        )
    op.execute(
        "UPDATE issues SET snapshot_id=NULL WHERE repository_id IN (SELECT id FROM repositories WHERE synthetic=true)"
    )
    op.execute(
        "DELETE FROM snapshots WHERE issue_id IN (SELECT i.id FROM issues i JOIN repositories r ON r.id=i.repository_id WHERE r.synthetic=true)"
    )
    op.execute("DELETE FROM issues WHERE repository_id IN (SELECT id FROM repositories WHERE synthetic=true)")
    for table in ("connection_jobs", "repository_access", "import_runs"):
        op.execute(
            sa.text(
                f"DELETE FROM {table} WHERE repository_id IN (SELECT id FROM repositories WHERE synthetic=true)"
            )
        )
    op.execute("DELETE FROM repositories WHERE synthetic=true")
    op.drop_column("repositories", "label_taxonomy")


def downgrade():
    raise RuntimeError("Restore a pre-upgrade Neon branch to roll back this data-preserving consolidation.")
