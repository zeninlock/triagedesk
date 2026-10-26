import json
from pathlib import Path

import numpy as np
from sqlalchemy import select

from triagedesk.artifacts import file_hash, write_json
from triagedesk.config import settings
from triagedesk.db import session_scope
from triagedesk.models import Issue, Repository, SimilarityJudgment, Snapshot, utcnow
from triagedesk.retrieval import index_path, retrieve
from triagedesk.text import digest


def frozen_part(pool):
    return [
        {
            "query_issue_id": q["issue_id"],
            "query_snapshot_id": q["snapshot_id"],
            "rankings": q["rankings"],
            "candidates": [
                {"issue_id": c["issue_id"], "snapshot_id": c["snapshot_id"]} for c in q["candidates"]
            ],
        }
        for q in pool["queries"]
    ]


def create_pool(session, query_count, out):
    if settings().mode != "real":
        raise ValueError("Retrieval evaluation must use real issues, never fixture demonstration examples")
    if not 1 <= query_count <= 100:
        raise ValueError("Choose 1–100 query issues")
    used = set()
    for path in (settings().artifact_dir / "models").glob("*/split-manifest.json"):
        manifest = json.loads(path.read_text())
        used.update(row["github_id"] for rows in manifest["splits"].values() for row in rows)
    rows = list(
        session.scalars(
            select(Issue)
            .join(Repository, Repository.id == Issue.repository_id)
            .where(Repository.synthetic.is_(False), Issue.available.is_(True))
            .order_by(Issue.created_at, Issue.id)
        )
    )
    eligible = [r for r in rows if r.github_id not in used and len(r.title + r.body) >= 80]
    if not eligible:
        raise ValueError("No independent retrieval queries remain outside the classification dataset")
    selected = [
        eligible[int(i)]
        for i in np.unique(np.linspace(0, len(eligible) - 1, min(query_count, len(eligible)), dtype=int))
    ]
    queries, methods = [], set()
    for issue in selected:
        rankings, candidates = {}, {}
        for method in ("tfidf", "semantic"):
            result = retrieve(
                session,
                issue.title,
                issue.body,
                issue.repository_id,
                exclude_id=issue.id,
                method=method,
                before=issue.created_at,
            )
            if result["method"] != method:
                continue  # Never report a TF-IDF fallback as semantic results.
            methods.add(method)
            rankings[method] = [r["id"] for r in result["items"]]
            for candidate in result["items"]:
                row = session.get(Issue, candidate["id"])
                candidates[row.id] = {
                    "issue_id": row.id,
                    "snapshot_id": row.snapshot_id,
                    "title": row.title,
                    "body": row.body,
                    "source_url": row.source_url,
                    "created_at": row.created_at.isoformat(),
                    "judgment": None,
                    "reviewer": "",
                }
        if len(rankings.get("tfidf", [])) < 5:
            continue
        queries.append(
            {
                "issue_id": issue.id,
                "snapshot_id": issue.snapshot_id,
                "title": issue.title,
                "body": issue.body,
                "created_at": issue.created_at.isoformat(),
                "source_url": issue.source_url,
                "rankings": rankings,
                "candidates": list(candidates.values()),
            }
        )
    pool = {
        "created_at": utcnow(),
        "index_sha256": file_hash(index_path()),
        "synthetic": False,
        "query_selection": "Deterministic chronological quantiles among >=80-character real reports outside all classification manifests; at least five TF-IDF candidates",
        "historical_candidates": "Same repository, created no later than query; edited snapshot limitation applies",
        "available_methods": sorted(methods),
        "queries": queries,
        "instructions": "For every pooled pair fill reviewer and judgment: related/duplicate/unrelated/uncertain. Blind ranking method while judging. Resolve uncertain before scoring. Keep this file outside Git; it contains source text.",
    }
    pool["rankings_hash"] = digest(frozen_part(pool))
    write_json(out, pool)
    return {
        "out": out,
        "actual_queries": len(queries),
        "methods": sorted(methods),
        "status": "Pending genuine human relevance judgments; no retrieval quality score computed",
    }


def evaluate_pool(path):
    if settings().mode != "real":
        raise ValueError("Retrieval evaluation is available only in real mode")
    pool = json.loads(Path(path).read_text())
    if pool.get("synthetic") is not False or pool.get("rankings_hash") != digest(frozen_part(pool)):
        raise ValueError("Use an unchanged real frozen pool; rankings or candidate IDs differ")
    if not pool["queries"]:
        raise ValueError("No query issues")
    scores = {
        method: {"precision_at_5": [], "reciprocal_rank_at_5": []} for method in pool["available_methods"]
    }
    judgments = []
    for query in pool["queries"]:
        lookup = {candidate["issue_id"]: candidate for candidate in query["candidates"]}
        for candidate in query["candidates"]:
            if (
                candidate["judgment"] not in {"related", "duplicate", "unrelated"}
                or not candidate["reviewer"].strip()
            ):
                raise ValueError(
                    "Complete every pooled judgment and reviewer; adjudicate uncertain pairs before evaluation"
                )
            judgments.append((query, candidate))
        for method, ranking in query["rankings"].items():
            relevant = [lookup[id_]["judgment"] in {"related", "duplicate"} for id_ in ranking[:5]]
            scores[method]["precision_at_5"].append(sum(relevant) / 5)
            scores[method]["reciprocal_rank_at_5"].append(
                next((1 / (i + 1) for i, yes in enumerate(relevant) if yes), 0)
            )
    report = {
        "evaluated_at": utcnow(),
        "actual_queries": len(pool["queries"]),
        "judged_pairs": len(judgments),
        "index_sha256": pool["index_sha256"],
        "rankings_hash": pool["rankings_hash"],
        "methods": {
            method: {key: float(np.mean(values)) for key, values in metrics.items()}
            for method, metrics in scores.items()
        },
        "limitations": [
            "Pooled top-five judgments do not identify all relevant candidates; Recall@5 is not claimed",
            "Historical candidates exclude future creation dates, but text and labels may have been edited later",
            "TF-IDF vocabulary/IDF uses the full collected index; pretrained MiniLM postdates old queries. This is retrospective candidate filtering, not historical deployment simulation",
            "Small purposive query sample; not a statistically established generalization result",
        ],
    }
    with session_scope() as session:
        for query, candidate in judgments:
            if not session.get(Snapshot, query["snapshot_id"]) or not session.get(
                Snapshot, candidate["snapshot_id"]
            ):
                raise ValueError(
                    "Evaluation snapshots are absent from this database; use the originating dataset"
                )
            key = digest(
                [pool["rankings_hash"], query["issue_id"], candidate["issue_id"], candidate["reviewer"]]
            )
            if session.scalar(select(SimilarityJudgment.id).where(SimilarityJudgment.idempotency_key == key)):
                continue
            session.add(
                SimilarityJudgment(
                    query_issue_id=query["issue_id"],
                    candidate_issue_id=candidate["issue_id"],
                    query_snapshot_id=query["snapshot_id"],
                    candidate_snapshot_id=candidate["snapshot_id"],
                    judgment=candidate["judgment"],
                    reviewer=candidate["reviewer"],
                    purpose="evaluation",
                    idempotency_key=key,
                    payload_hash=digest(candidate),
                )
            )
    write_json(settings().artifact_dir / "retrieval-evaluation.json", report)
    return report
