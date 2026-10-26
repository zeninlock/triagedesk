"""Exact local search. Build indexes with CLI jobs; HTTP requests never fit vectors or download weights."""

import json
import os
from functools import lru_cache

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sqlalchemy import select

from triagedesk.artifacts import file_hash, write_json
from triagedesk.config import settings
from triagedesk.models import Issue, Repository
from triagedesk.text import clean_text, digest


def index_path():
    return settings().artifact_dir / f"retrieval-{settings().mode}.joblib"


@lru_cache(maxsize=2)
def embedding_model(model_id, revision, cache, local_only):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(
        model_id,
        revision=revision,
        device="cpu",
        cache_folder=cache,
        local_files_only=local_only,
        trust_remote_code=False,
    )
    model.max_seq_length = 256
    return model


def get_embedding_model(local_only=True):
    config = settings()
    return embedding_model(
        config.embedding_model,
        config.embedding_revision,
        str(config.artifact_dir / "embedding-model"),
        local_only,
    )


def build_index(session, semantic=False, allow_download=False):
    config = settings()
    rows = list(
        session.scalars(
            select(Issue)
            .join(Repository, Repository.id == Issue.repository_id)
            .where(Repository.synthetic == (config.mode == "fixture"), Issue.available.is_(True))
            .order_by(Issue.id)
        )
    )
    if not rows:
        raise ValueError("No issues in the active mode. Seed fixtures or import a repository first")
    texts = [clean_text(row.title, row.body) for row in rows]
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=40000, sublinear_tf=True)
    vectors = vectorizer.fit_transform(texts)
    mapping = [
        {
            "id": row.id,
            "repository_id": row.repository_id,
            "content_hash": row.content_hash,
            "snapshot_id": row.snapshot_id,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
    artifact = {
        "mapping": mapping,
        "vectorizer": vectorizer,
        "vectors": vectors,
        "semantic": None,
        "semantic_version": None,
    }
    if semantic:
        model = get_embedding_model(local_only=not allow_download)
        version = f"{config.embedding_model}@{config.embedding_revision}:first256:clean-v1"
        cache_dir = config.artifact_dir / "embedding-cache" / digest(version)[:16]
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached, pending = [], []
        for i, row in enumerate(rows):
            path = cache_dir / f"{row.content_hash}.npy"
            if path.exists():
                cached.append(np.load(path, allow_pickle=False))
            else:
                cached.append(None)
                pending.append(i)
        if pending:
            generated = model.encode(
                [texts[i] for i in pending],
                batch_size=32,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            for i, vector in zip(pending, generated):
                cached[i] = vector
                np.save(cache_dir / f"{rows[i].content_hash}.npy", vector, allow_pickle=False)
        artifact["semantic"] = np.vstack(cached)
        artifact["semantic_version"] = version
    path = index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    joblib.dump(artifact, temporary)
    temporary.replace(path)
    manifest = {
        "issues": len(rows),
        "mode": config.mode,
        "semantic_version": artifact["semantic_version"],
        "mapping": mapping,
        "sha256": file_hash(path),
        "truncation": "Semantic: first 256 wordpieces; TF-IDF: full title and body",
    }
    write_json(path.with_suffix(".json"), manifest)
    _load_index.cache_clear()
    return {k: manifest[k] for k in ["issues", "mode", "semantic_version", "sha256"]}


@lru_cache(maxsize=2)
def _load_index(path, stamp):
    from pathlib import Path

    path = Path(path)
    manifest = json.loads(path.with_suffix(".json").read_text())
    if file_hash(path) != manifest["sha256"]:
        raise ValueError("Retrieval checksum mismatch; rebuild the index")
    return joblib.load(path)


def retrieve(session, title, body, repository_id=None, exclude_id=None, method="auto", before=None):
    path = index_path()
    if not path.exists():
        return {
            "items": [],
            "method": "unavailable",
            "message": "Retrieval index unavailable. Run triagedesk index.",
        }
    try:
        index = _load_index(str(path), path.stat().st_mtime_ns)
    except (ValueError, OSError, KeyError):
        return {
            "items": [],
            "method": "unavailable",
            "message": "Retrieval index incompatible. Rebuild it with triagedesk index.",
        }
    text = clean_text(title, body)
    fallback = None
    actual = "tfidf"
    if method in {"auto", "semantic"} and index["semantic"] is not None:
        try:
            query = get_embedding_model(local_only=True).encode(
                [text], normalize_embeddings=True, convert_to_numpy=True
            )[0]
            scores = index["semantic"] @ query
            actual = "semantic"
        except (ImportError, OSError, RuntimeError, ValueError):
            fallback = "Semantic model unavailable locally; using TF-IDF fallback."
    elif method != "tfidf":
        fallback = "Semantic embeddings unavailable; using TF-IDF fallback."
    if actual == "tfidf":
        scores = (index["vectors"] @ index["vectorizer"].transform([text]).T).toarray().ravel()
    mapping = index["mapping"]
    # Refresh candidate metadata and availability from SQL. Stale text is omitted rather than misrepresented.
    scoped = (
        select(Issue)
        .join(Repository, Repository.id == Issue.repository_id)
        .where(Repository.synthetic == (settings().mode == "fixture"), Issue.available.is_(True))
    )
    if repository_id:
        scoped = scoped.where(Issue.repository_id == repository_id)
    if before:
        scoped = scoped.where(Issue.created_at <= before)
    if exclude_id:
        scoped = scoped.where(Issue.id != exclude_id)
    ranked = [
        int(i)
        for i in np.argsort(-scores, kind="stable")
        if scores[i] > 0 and (repository_id is None or mapping[int(i)]["repository_id"] == repository_id)
    ]
    items = []
    # Read bounded ranked batches instead of loading every issue body on each query.
    for offset in range(0, len(ranked), 100):
        batch = ranked[offset : offset + 100]
        ids = [mapping[i]["id"] for i in batch]
        current = {row.id: row for row in session.scalars(scoped.where(Issue.id.in_(ids)))}
        for i in batch:
            entry = mapping[i]
            issue = current.get(entry["id"])
            if issue is None or issue.content_hash != entry["content_hash"]:
                continue
            items.append(
                {
                    "id": issue.id,
                    "snapshot_id": issue.snapshot_id,
                    "number": issue.number,
                    "title": issue.title,
                    "excerpt": issue.body[:350],
                    "source_url": issue.source_url,
                    "state": issue.state,
                    "score": float(scores[i]),
                }
            )
            if len(items) == 5:
                break
        if len(items) == 5:
            break
    return {
        "items": items,
        "method": actual,
        "message": (fallback + " " if fallback else "")
        + "Potentially related issues; similarity alone does not establish duplication.",
    }
