import json
import uuid

import pytest
from conftest import raw_issue
from sqlalchemy import select
from sqlalchemy.orm import Session

from triagedesk.artifacts import write_json
from triagedesk.config import settings
from triagedesk.dataset import prepare_dataset, reviewed_dataset
from triagedesk.fixtures import seed
from triagedesk.github import upsert_issue
from triagedesk.models import Issue, Repository, Snapshot
from triagedesk.retrieval_eval import evaluate_pool, frozen_part
from triagedesk.reviews import submit_review
from triagedesk.schemas import ReviewInput
from triagedesk.text import digest


def test_review_exports_protect_heldout_external_identity_after_id_remapping(database, tmp_path):
    with Session(database) as session, session.begin():
        repo = Repository(
            github_id=91, full_name="example/project", source_url="https://github.com/example/project"
        )
        session.add(repo)
        session.flush()
        upsert_issue(session, repo, raw_issue(1))
    with Session(database) as session:
        issue = session.scalar(select(Issue))
        payload = ReviewInput(
            action="correct",
            category="bug",
            snapshot_id=issue.snapshot_id,
            expected_revision=0,
            idempotency_key=str(uuid.uuid4()),
        )
        submit_review(session, issue, payload, "maintainer")
        external_id = issue.github_id
    write_json(
        settings().artifact_dir / "models/old/split-manifest.json",
        {"splits": {"validation": [{"issue_id": 999999, "github_id": external_id}], "test": []}},
    )
    with Session(database) as session:
        result = reviewed_dataset(session, tmp_path / "future.json")
        assert result["eligible_reviews"] == 0
        assert json.loads((tmp_path / "future.json").read_text())["excluded_held_out_issue_count"] == 1


def test_synthetic_dataset_cannot_be_prepared_for_reported_metrics(database, tmp_path):
    with Session(database) as session, session.begin():
        seed(session)
        with pytest.raises(ValueError, match="fixtures"):
            prepare_dataset(
                session, "synthetic/campus-tools", "config/labels.v1.yaml", tmp_path / "data.json"
            )


def test_snapshot_modification_is_rejected(database):
    with Session(database) as session, session.begin():
        seed(session)
    with Session(database) as session:
        snapshot = session.scalar(select(Snapshot).order_by(Snapshot.id))
        snapshot.body = "Attempt to rewrite an experiment input"
        with pytest.raises(ValueError, match="immutable"):
            session.flush()


def test_retrieval_evaluation_refuses_unjudged_pairs_or_changed_rankings(monkeypatch, tmp_path):
    monkeypatch.setenv("MODE", "real")
    settings.cache_clear()
    pool = {
        "synthetic": False,
        "available_methods": ["tfidf", "semantic"],
        "queries": [
            {
                "issue_id": 1,
                "snapshot_id": 1,
                "rankings": {"tfidf": [2], "semantic": [2]},
                "candidates": [{"issue_id": 2, "snapshot_id": 2, "judgment": None, "reviewer": ""}],
            }
        ],
    }
    pool["rankings_hash"] = digest(frozen_part(pool))
    path = tmp_path / "pool.json"
    write_json(path, pool)
    with pytest.raises(ValueError, match="Complete every"):
        evaluate_pool(path)
    pool["queries"][0]["rankings"]["tfidf"] = [3]
    write_json(path, pool)
    with pytest.raises(ValueError, match="unchanged"):
        evaluate_pool(path)


def test_literal_search_does_not_turn_wildcards_into_broad_queries(client):
    assert client.get("/issues", params={"search": "%"}).json()["total"] == 0
    assert client.get("/dashboard", params={"search": "%"}).json()["imported"] == 0
