import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from triagedesk.fixtures import seed
from triagedesk.models import Issue, Repository
from triagedesk.retrieval import build_index, retrieve


def test_retrieval_excludes_self_and_stale_or_unavailable_records(database):
    with Session(database) as session, session.begin():
        seed(session)
        build_index(session)
        query = session.get(Issue, 1)
        result = retrieve(session, query.title, query.body, query.repository_id, exclude_id=query.id)
        assert result["method"] == "tfidf" and "fallback" in result["message"]
        assert 1 not in [r["id"] for r in result["items"]] and len(result["items"]) <= 5
        assert any(r["id"] == 4 for r in result["items"])
        session.get(Issue, 4).content_hash = "changed text hash"
        session.get(Issue, 15).available = False
        session.flush()
        after = retrieve(session, query.title, query.body, query.repository_id, query.id)
        assert all(r["id"] not in {1, 4, 15} for r in after["items"])
        assert retrieve(session, query.title, query.body, 999)["items"] == []


def test_semantic_cache_reuses_hashes_and_recomputes_changed_text(database, monkeypatch):
    import triagedesk.retrieval as retrieval

    calls = []

    class FakeEncoder:
        def encode(self, texts, **kwargs):
            calls.append(len(texts))
            return np.array([[1.0, 0.0, 0.0] for _ in texts], dtype=np.float32)

    monkeypatch.setattr(retrieval, "get_embedding_model", lambda **kwargs: FakeEncoder())
    with Session(database) as session, session.begin():
        seed(session)
        build_index(session, semantic=True)
        build_index(session, semantic=True)
        assert calls == [24]
        row = session.get(Issue, 1)
        row.content_hash, row.body = "new-hash", "Updated report"
        session.flush()
        build_index(session, semantic=True)
        assert calls == [24, 1]
        result = retrieve(session, "a report", "details", 1, exclude_id=1, method="semantic")
        assert result["method"] == "semantic" and all(item["id"] != 1 for item in result["items"])


def test_historical_candidates_exclude_newer_issues(database):
    with Session(database) as session, session.begin():
        seed(session)
        build_index(session)
        query = session.get(Issue, 4)
        result = retrieve(
            session, query.title, query.body, query.repository_id, query.id, before=query.created_at
        )
        ids = [r["id"] for r in result["items"]]
        assert ids and all(session.get(Issue, id_).created_at <= query.created_at for id_ in ids)
        assert len(session.scalars(select(Repository)).all()) == 1
