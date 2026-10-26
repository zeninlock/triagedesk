import os
import platform
import time

import httpx
import numpy as np
from sqlalchemy import func, select

from triagedesk.artifacts import write_json
from triagedesk.config import settings
from triagedesk.db import session_scope
from triagedesk.models import Issue, Repository, utcnow
from triagedesk.retrieval import retrieve
from triagedesk.serving import _load, classify_text, current_model


def timed(function):
    start = time.perf_counter()
    result = function()
    return (time.perf_counter() - start) * 1000, result


def summary(samples):
    return {
        "requests": len(samples),
        "p50_ms": float(np.percentile(samples, 50)),
        "p95_ms": float(np.percentile(samples, 95)) if len(samples) >= 20 else None,
        "min_ms": float(min(samples)),
        "max_ms": float(max(samples)),
    }


def benchmark(count=100, api_url=None):
    if not 20 <= count <= 1000:
        raise ValueError("Use 20–1000 requests; p95 from fewer observations is not reported")
    with session_scope() as session:
        where = Repository.synthetic == (settings().mode == "fixture")
        query_scope = where
        query_repository = "synthetic/campus-tools"
        if settings().mode == "real":
            try:
                _, metadata = current_model()
                query_repository = metadata["repository"]
                query_scope = where & (Repository.full_name == query_repository)
            except (FileNotFoundError, ValueError):
                query_repository = "all imported real repositories"
        issues = list(
            session.scalars(
                select(Issue)
                .join(Repository, Repository.id == Issue.repository_id)
                .where(query_scope, Issue.available.is_(True))
                .order_by(Issue.id)
                .limit(20)
            )
        )
        total = session.scalar(
            select(func.count()).select_from(Issue).join(Repository).where(where, Issue.available.is_(True))
        )
        if not issues:
            raise ValueError("No active issues to benchmark")
        query_count = session.scalar(
            select(func.count())
            .select_from(Issue)
            .join(Repository)
            .where(query_scope, Issue.available.is_(True))
        )
        first = issues[0]
        _load.cache_clear()  # Repository lookup above may have loaded it; measure artifact loading honestly.
        cold_classify, classification = timed(lambda: classify_text(first.title, first.body))
        cold_retrieve, _ = timed(
            lambda: retrieve(session, first.title, first.body, first.repository_id, first.id, method="tfidf")
        )
        samples = {}
        if classification["available"]:
            samples["classification"] = [
                timed(lambda row=issues[i % len(issues)]: classify_text(row.title, row.body))[0]
                for i in range(count)
            ]
        cold_semantic = None
        for method in ("tfidf", "semantic"):
            first_call_ms, check = timed(
                lambda: retrieve(
                    session, first.title, first.body, first.repository_id, first.id, method=method
                )
            )
            if check["method"] != method:
                continue
            if method == "semantic":
                cold_semantic = first_call_ms
            samples[f"retrieval_{method}"] = [
                timed(
                    lambda row=issues[i % len(issues)]: retrieve(
                        session, row.title, row.body, row.repository_id, row.id, method=method
                    )
                )[0]
                for i in range(count)
            ]
    if api_url:
        with httpx.Client(base_url=api_url, timeout=30) as client:
            for path in ("/issues", "/dashboard", f"/issues/{first.id}"):
                client.get(path).raise_for_status()
                values = []
                for _ in range(count):
                    start = time.perf_counter()
                    client.get(path).raise_for_status()
                    values.append((time.perf_counter() - start) * 1000)
                samples["api_" + path.replace("/", "_").strip("_")] = values
    result = {
        "measured_at": utcnow(),
        "mode": settings().mode,
        "issue_count": total,
        "query_repository": query_repository,
        "query_repository_issue_count": query_count,
        "hardware": {
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "logical_cpus": os.cpu_count(),
        },
        "cold_first_classification_ms": cold_classify if classification["available"] else None,
        "cold_first_tfidf_retrieval_ms": cold_retrieve,
        "cold_first_semantic_retrieval_ms": cold_semantic,
        "measurements": {name: summary(values) for name, values in samples.items()},
        "protocol": "Sequential warm requests cycling up to 20 titles. Model/index first load excluded from percentiles and measured separately. Semantic query encoding included; corpus embedding generation excluded. API requests include HTTP, SQL and serialization. No concurrency/load claim.",
        "classification_status": "measured"
        if classification["available"]
        else "unavailable; no classifier latency reported",
        "limitations": "Small imported corpus on this machine; targets for thousands of issues are not established by fixture measurements",
    }
    write_json(settings().artifact_dir / f"benchmark-{settings().mode}.json", result)
    return result
