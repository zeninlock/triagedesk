import base64
import gzip
import json
import uuid
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from conftest import raw_issue
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from streamlit.testing.v1 import AppTest
from test_ai_labels import provider_response
from test_github_access import REPO, grant, identity_provider, login

from triagedesk import ai_labels
from triagedesk import contributor_guides as guides
from triagedesk.api import app
from triagedesk.config import settings
from triagedesk.github import GitHubClient, GitHubError, upsert_issue
from triagedesk.issue_lifecycle import purge_closed
from triagedesk.models import ContributorGuide, Issue, Repository, RepositoryContext, utcnow
from triagedesk.repository_context import (
    candidate_files,
    eligible,
    excerpt,
    notebook_cells,
    repository_context,
)

COMMIT = "a" * 40
TREE = "b" * 40
FILES = {
    "README.md": "# Example\nInstall Python 3.12.\nRun the tests with `python -m pytest`.\n",
    "src/export.py": "import csv\n\ndef csv_export(rows):\n    return rows[:-1]\n",
    "tests/test_export.py": "def test_export_preserves_rows():\n    assert csv_export([1, 2]) == [1, 2]\n",
}


def evidence(source, quote=None):
    choices = list(guides.citation_catalog([source]).values())
    selected = next(c for c in choices if not quote or quote in c["quote"])
    return {"citation_id": selected["citation_id"]}


def proposal(sources):
    source = next(s for s in sources if s.get("path") == "src/export.py")
    doc = next(s for s in sources if s.get("path") == "README.md")
    test = next(s for s in sources if s.get("path") == "tests/test_export.py")
    issue = next(s for s in sources if s["id"] == "issue_1")
    return {
        "sufficient_context": True,
        "starting_points": [{"text": "Inspect how CSV export handles rows.", "evidence": [evidence(source)]}],
        "prerequisites": [{"text": "The README requires Python 3.12.", "evidence": [evidence(doc)]}],
        "investigation_steps": [
            {"text": "Compare the input rows with the returned slice.", "evidence": [evidence(source)]}
        ],
        "tests": [{"text": "Review the existing row-preservation test.", "evidence": [evidence(test)]}],
        "completion_checklist": [
            {"text": "All input rows appear in the export.", "evidence": [evidence(issue)]}
        ],
        "missing_information": [],
    }


@pytest.fixture
def workspace(database, monkeypatch):
    identity_provider(monkeypatch, repo={**REPO, "default_branch": "main"})
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key-never-sent-to-live-provider")
    settings.cache_clear()
    repository_id = grant(database)
    with Session(database) as db:
        repo = db.get(Repository, repository_id)
        issue = upsert_issue(db, repo, raw_issue())
        db.commit()
        ids = list(db.scalars(select(Issue.id)))
        issue = db.get(Issue, ids[0])
        snapshot = issue.snapshot_id
    with TestClient(app) as client:
        headers = login(client)
        yield client, headers, ids[0], snapshot, repository_id


@pytest.fixture
def providers(monkeypatch):
    calls = {"github": [], "ai": [], "commit": COMMIT, "mutate": None}
    entries, blobs = [], {}
    for n, (path, content) in enumerate(FILES.items(), 1):
        sha = str(n) * 40
        data = content.encode()
        entries.append({"path": path, "sha": sha, "size": len(data), "type": "blob", "mode": "100644"})
        blobs[sha] = {"sha": sha, "encoding": "base64", "content": base64.b64encode(data).decode()}

    def github(request):
        calls["github"].append(request.url.path)
        path = request.url.path
        if "/commits/" in path:
            return httpx.Response(200, json={"sha": calls["commit"], "commit": {"tree": {"sha": TREE}}})
        if "/git/trees/" in path:
            return httpx.Response(200, json={"tree": entries, "truncated": False})
        if "/git/blobs/" in path:
            return httpx.Response(200, json=blobs[path.rsplit("/", 1)[1]])
        raise AssertionError(path)

    real_client, real_provider = httpx.Client, ai_labels.OpenAI
    monkeypatch.setattr(
        guides,
        "GitHubClient",
        lambda **kwargs: GitHubClient(
            client=real_client(base_url="https://api.github.com", transport=httpx.MockTransport(github)),
            **kwargs,
        ),
    )

    def openai(request):
        payload = json.loads(request.content)
        calls["ai"].append(payload)
        assert payload["store"] is False and payload["text"]["format"]["strict"] is True
        sources = json.loads(payload["input"][1]["content"])["sources"]
        sources = [{**s, "text": "\n".join(c["quote"] for c in s["citations"])} for s in sources]
        value = proposal(sources)
        if calls["mutate"]:
            calls["mutate"](value)
        if not calls["mutate"]:
            Draft202012Validator(payload["text"]["format"]["schema"]).validate(value)
        return httpx.Response(200, json=provider_response(json.dumps(value)))

    monkeypatch.setattr(
        ai_labels,
        "OpenAI",
        lambda **kwargs: real_provider(
            **{**kwargs, "http_client": real_client(transport=httpx.MockTransport(openai))},
        ),
    )
    return calls


def generate(workspace, check=False, key=None):
    client, headers, issue_id, snapshot, _ = workspace
    return client.post(
        f"/triage/issues/{issue_id}/guide",
        headers=headers,
        json={
            "snapshot_id": snapshot,
            "idempotency_key": key or str(uuid.uuid4()),
            "check_updates": check,
        },
    )


def read(workspace):
    client, headers, issue_id, _, _ = workspace
    response = client.get(f"/triage/issues/{issue_id}/guide", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["guide"]


def test_full_guide_sources_approval_cache_and_commit_updates(workspace, providers, database):
    assert read(workspace) is None
    assert generate(workspace).status_code == 202
    guide = read(workspace)
    assert guide["status"] == "complete", guide
    assert guide["commit_sha"] == COMMIT and not guide["approved_by"]
    assert guide["result"]["documented_commands"][0]["command"] == "python -m pytest"
    citation = guide["result"]["starting_points"][0]["evidence"][0]
    assert citation["url"] == f"https://github.com/maintainer/project/blob/{COMMIT}/src/export.py#L1-L4"
    assert len(providers["ai"]) == 1
    client, headers, issue_id, _, repo_id = workspace
    approve = client.put(
        f"/triage/issues/{issue_id}/guide/{guide['id']}/approval",
        headers=headers,
        json={"approved": True, "expected_revision": 0},
    )
    assert approve.status_code == 200, approve.text
    assert read(workspace)["approved_by"] == "github:maintainer#42"
    # Ordinary generate and page reads do not fetch sources or repeat paid requests.
    count = len(providers["github"])
    assert generate(workspace).json()["guide"]["id"] == guide["id"]
    assert len(providers["github"]) == count
    # Explicit update check fetches only the commit and reuses the checked guide.
    assert generate(workspace, check=True).status_code == 202
    assert read(workspace)["reused"] and read(workspace)["approved_by"]
    assert len(providers["github"]) == count + 1 and len(providers["ai"]) == 1
    providers["commit"] = "c" * 40
    assert generate(workspace, check=True).status_code == 202
    assert read(workspace)["commit_sha"] == "c" * 40
    assert not read(workspace)["approved_by"] and len(providers["ai"]) == 2
    with Session(database) as db:
        issue = db.get(Issue, issue_id)
        assert issue.work_status == "open" and issue.review_revision == 0
        assert db.scalar(select(func.count()).select_from(RepositoryContext)) == 2
        issue.state = "closed"
        db.commit()
        assert purge_closed(db, repo_id) == 1
        assert db.scalar(select(func.count()).select_from(ContributorGuide)) == 0


@pytest.mark.parametrize("bad_kind", ["unknown_source", "fabricated_lines", "wrong_kind"])
def test_invented_evidence_is_never_published(workspace, providers, bad_kind):
    def mutate(value):
        if bad_kind == "unknown_source":
            value["starting_points"][0]["evidence"][0]["citation_id"] = "invented"
        elif bad_kind == "fabricated_lines":
            value["starting_points"][0]["evidence"][0]["citation_id"] = "source_1:99999-99999"
        elif bad_kind == "wrong_kind":
            value["starting_points"][0]["evidence"] = value["completion_checklist"][0]["evidence"]

    providers["mutate"] = mutate
    assert generate(workspace).status_code == 202
    guide = read(workspace)
    assert guide["status"] == "failed" and guide["result"] == {}
    assert "could not be checked" in guide["error"]


def test_incomplete_plan_returns_missing_context_instead_of_false_source_error(workspace, providers):
    providers["mutate"] = lambda value: value.update(starting_points=[])
    assert generate(workspace).status_code == 202
    guide = read(workspace)
    assert guide["status"] == "complete" and not guide["result"]["sufficient_context"]
    assert guide["result"]["missing_information"] and not guide["error"]


def test_schema_restricts_references_by_section_before_model_generation():
    sources = [
        {"id": "source_1", "kind": "code", "start_line": 20, "text": "def window_slice(x):\n    return x"},
        {"id": "issue_1", "kind": "issue", "start_line": 1, "text": "Support the full-length window."},
    ]
    schema = guides.guide_schema(sources)

    def choices(section):
        return schema["properties"][section]["items"]["properties"]["evidence"]["items"]["properties"][
            "citation_id"
        ]["enum"]

    assert choices("starting_points") == ["source_1:20-21"]
    assert choices("completion_checklist") == ["issue_1:1-1"]
    assert schema["properties"]["prerequisites"]["maxItems"] == 0
    assert schema["properties"]["tests"]["maxItems"] == 0


def test_notebook_retrieval_finds_code_cells_and_caches_no_outputs(database):
    target = "pure_bilstm_final.ipynb"
    notebook = {
        "nbformat": 4,
        "metadata": {"private_metadata": "NEVER_SEND_THIS"},
        "cells": [
            {"cell_type": "markdown", "source": ["# Model experiments\n"]},
            {
                "cell_type": "code",
                "source": [
                    "def window_slice(x, window_ratio=0.9):\n",
                    "    seq_len = x.shape[0]\n",
                    "    window_size = int(seq_len * window_ratio)\n",
                    "    start = np.random.randint(0, seq_len - window_size)\n",
                    "    return x[start:start + window_size]\n",
                ],
                "outputs": [{"text": "NEVER_SEND_THIS_OUTPUT", "data": {"image/png": "binary_image"}}],
            },
        ],
    }
    contents = {
        target: json.dumps(notebook),
        "README.md": "# EEG\nModel experiments.",
        "requirements.txt": "numpy\ntensorflow\n",
    }
    entries, blobs = [], {}
    for n, (path, content) in enumerate(contents.items(), 1):
        sha = str(n) * 40
        data = content.encode()
        entries.append({"path": path, "sha": sha, "size": len(data), "type": "blob", "mode": "100644"})
        blobs[sha] = {"sha": sha, "encoding": "base64", "content": base64.b64encode(data).decode()}
    entries.append(
        {"path": "large_model.keras", "sha": "8" * 40, "size": 20_000_000, "type": "blob", "mode": "100644"}
    )
    fetched = []

    def github(request):
        fetched.append(request.url.path)
        if "/commits/" in request.url.path:
            return httpx.Response(200, json={"sha": COMMIT, "commit": {"tree": {"sha": TREE}}})
        if "/git/trees/" in request.url.path:
            return httpx.Response(200, json={"tree": entries, "truncated": False})
        return httpx.Response(200, json=blobs[request.url.path.rsplit("/", 1)[1]])

    client = GitHubClient(
        client=httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(github))
    )
    with Session(database) as db:
        repo = Repository(
            github_id=77, full_name="maintainer/project", source_url="https://github.com/maintainer/project"
        )
        db.add(repo)
        db.commit()
        repo_id = repo.id
    title = "Handle window_ratio=1.0 in window_slice"
    body = f"The function is in {target}. Support the full-length window."
    sha, sources, partial = repository_context(
        database, client, repo_id, "maintainer/project", 77, title, body, {**REPO, "default_branch": "main"}
    )
    assert not partial and sha == COMMIT
    code = next(s for s in sources if s.get("cell_number") == 2)
    assert "np.random.randint" in code["text"] and code["notebook"]
    assert code["path"] == target and code["start_line"] == 1
    assert not any("NEVER_SEND" in s["text"] for s in sources)
    with Session(database) as db:
        cache = db.scalar(select(RepositoryContext)).files
        assert "NEVER_SEND" not in json.dumps(cache) and "binary_image" not in json.dumps(cache)
    value = guides.GuideResult.model_validate(
        {
            "sufficient_context": False,
            "starting_points": [
                {"text": "Inspect the window selection function in cell 2.", "evidence": [evidence(code)]}
            ],
            "prerequisites": [],
            "tests": [],
            "investigation_steps": [],
            "completion_checklist": [],
            "missing_information": [],
        }
    )
    checked = guides.verified_result(value, sources, "maintainer/project", sha, 10)
    link = checked["starting_points"][0]["evidence"][0]
    assert "cell 2" in link["label"] and "#L" not in link["url"]
    assert link["url"].endswith(f"/{COMMIT}/{target}")
    count = len(fetched)
    repository_context(
        database, client, repo_id, "maintainer/project", 77, title, body, {**REPO, "default_branch": "main"}
    )
    assert len(fetched) == count + 1  # Only resolve the commit; notebook source is cached.


@pytest.mark.parametrize(
    "raw",
    [
        "not JSON",
        '{"nbformat": 3, "cells": []}',
        '{"nbformat": 4, "cells": [{"cell_type": "code", "source": [42]}]}',
    ],
)
def test_invalid_notebooks_are_not_interpreted_as_source(raw):
    with pytest.raises(ValueError):
        notebook_cells(raw)


def test_idempotent_retry_and_snapshot_change(workspace, providers, database):
    key = str(uuid.uuid4())
    response = generate(workspace, key=key)
    assert generate(workspace, key=key).json()["guide"]["id"] == response.json()["guide"]["id"]
    assert len(providers["ai"]) == 1
    assert generate(workspace, check=True, key=key).status_code == 409
    client, headers, issue_id, _, repo_id = workspace
    with Session(database) as db:
        upsert_issue(db, db.get(Repository, repo_id), raw_issue(body="New behavior requires clarification."))
        db.commit()
    assert read(workspace)["outdated_issue"]
    guide = read(workspace)
    response = client.put(
        f"/triage/issues/{issue_id}/guide/{guide['id']}/approval",
        headers=headers,
        json={"approved": True, "expected_revision": 0},
    )
    assert response.status_code == 409
    assert generate(workspace).status_code == 409


def test_generation_and_approval_require_connected_maintainer(workspace, providers, database, monkeypatch):
    client, headers, issue_id, snapshot, _ = workspace
    path = f"/triage/issues/{issue_id}/guide"
    payload = {"snapshot_id": snapshot, "idempotency_key": str(uuid.uuid4())}
    assert client.get(path).status_code == 401
    assert client.post(path, json=payload).status_code == 401
    other = grant(database, user_id=99, repo={**REPO, "id": 78, "full_name": "other/project"})
    with Session(database) as db:
        upsert_issue(db, db.get(Repository, other), raw_issue(55))
        db.commit()
        other_issue = db.scalar(select(Issue).where(Issue.repository_id == other))
        other_id = other_issue.id
    assert client.get(f"/triage/issues/{other_id}/guide", headers=headers).status_code == 403
    assert client.post(f"/triage/issues/{other_id}/guide", headers=headers, json=payload).status_code == 403
    monkeypatch.setenv("READ_ONLY", "true")
    settings.cache_clear()
    assert client.post(path, headers=headers, json=payload).status_code == 403
    assert not providers["ai"]


def test_lease_expiry_and_provider_cooldown(workspace, database, monkeypatch):
    monkeypatch.setattr(guides, "run_guide", lambda *_: None)
    response = generate(workspace)
    guide_id = response.json()["guide"]["id"]
    assert read(workspace)["status"] == "queued"
    with Session(database) as db:
        row = db.get(ContributorGuide, guide_id)
        row.lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    assert read(workspace)["status"] == "failed"
    with Session(database) as db:
        row = db.get(ContributorGuide, guide_id)
        row.error, row.retry_after = "rate_limited", utcnow() + timedelta(seconds=90)
        db.commit()
    assert generate(workspace).status_code == 429


def test_duplicate_workers_do_not_call_ai_twice(workspace, providers, monkeypatch):
    actual = guides.run_guide
    monkeypatch.setattr(guides, "run_guide", lambda *_: None)
    row = generate(workspace).json()["guide"]
    actual(row["id"])
    actual(row["id"])
    assert read(workspace)["status"] == "complete" and len(providers["ai"]) == 1


def test_no_repository_context_does_not_spend_an_ai_request(workspace, providers, monkeypatch):
    monkeypatch.setattr(guides, "repository_context", lambda *args: (COMMIT, [], True))
    assert generate(workspace).status_code == 202
    guide = read(workspace)
    assert guide["status"] == "complete" and not guide["result"]["sufficient_context"]
    assert guide["result"]["missing_information"] and not providers["ai"]
    client, headers, issue_id, _, _ = workspace
    response = client.put(
        f"/triage/issues/{issue_id}/guide/{guide['id']}/approval",
        headers=headers,
        json={"approved": True, "expected_revision": 0},
    )
    assert response.status_code == 409


def test_provider_failure_releases_claim_and_shares_backoff(workspace, providers, monkeypatch, database):
    def limited(*args):
        raise ai_labels.AIUnavailable("rate_limited", 90)

    monkeypatch.setattr(guides, "request_guide", limited)
    assert generate(workspace).status_code == 202
    guide = read(workspace)
    assert guide["status"] == "failed" and guide["retry_after"]
    with Session(database) as db:
        row = db.get(ContributorGuide, guide["id"])
        assert row.active_key is None
        assert ai_labels.provider_cooldown(db).error == "rate_limited"
    assert generate(workspace).status_code == 429


@pytest.mark.postgres
@pytest.mark.parametrize("same_issue", [True, False])
def test_concurrent_requests_claim_one_guide_per_repository(postgres_database, monkeypatch, same_issue):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from fastapi import HTTPException

    from triagedesk.authentication import Principal
    from triagedesk.models import AuthSession

    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    settings.cache_clear()
    with Session(postgres_database) as db:
        repo = Repository(
            github_id=77, full_name="maintainer/project", source_url="https://github.com/maintainer/project"
        )
        db.add(repo)
        session = AuthSession(
            token_hash="a" * 64,
            github_user_id=42,
            login="maintainer",
            encrypted_token="test-only",
            expires_at=utcnow() + timedelta(hours=1),
        )
        db.add(session)
        db.flush()
        for n in (1, 2):
            upsert_issue(db, repo, raw_issue(n))
        db.commit()
        actor = Principal(session.id, 42, "maintainer", "test-only")
        ids = list(db.scalars(select(Issue.id).order_by(Issue.id)))
    barrier = Barrier(2)

    def submit(issue_id):
        with Session(postgres_database) as db:
            issue = db.get(Issue, issue_id)
            payload = guides.GuideRequest(snapshot_id=issue.snapshot_id, idempotency_key=str(uuid.uuid4()))
            barrier.wait(timeout=10)
            try:
                row, created = guides.start_guide(db, issue, actor, payload)
                return row.id, created
            except HTTPException as exc:
                assert exc.status_code == 409
                return None, False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, [ids[0], ids[0] if same_issue else ids[1]]))
    assert sum(created for _, created in results) == 1
    with Session(postgres_database) as db:
        assert db.scalar(select(func.count()).select_from(ContributorGuide)) == 1


def test_source_selection_excludes_secrets_generated_data_and_symlinks():
    base = {"sha": "1" * 40, "size": 100, "type": "blob", "mode": "100644"}
    paths = [
        "src/export.py",
        "tests/test_export.py",
        "README.md",
        ".env",
        ".streamlit/secrets.toml",
        "node_modules/export.js",
        "package-lock.json",
        "dataset.csv",
        "large.py",
        "symlink.py",
    ]
    tree = [{**base, "path": p} for p in paths]
    tree[-2]["size"] = 999999
    tree[-1]["mode"] = "120000"
    selected = candidate_files(tree, "CSV export fails", "Rows are missing")
    assert {x["path"] for x in selected} == {"src/export.py", "tests/test_export.py", "README.md"}
    assert eligible({**base, "path": "src/block.py", "mode": "100755"})
    assert not eligible({**base, "path": "../export.py"})


def test_excerpt_uses_original_line_numbers_and_escapes_link_paths():
    source = excerpt(
        "src/export file.py", "1" * 40, "\n".join(f"line {n}" for n in range(100)), {"line"}, "source_1"
    )
    assert source["start_line"] == 1 and source["text"].startswith("line 0\n")
    issue = {"id": "issue_1", "kind": "issue", "text": "Expected all rows", "start_line": 1}
    item = {"text": "Inspect these lines", "evidence": [evidence(source, "line 1\nline 2")]}
    value = guides.GuideResult.model_validate(
        {
            "sufficient_context": False,
            "starting_points": [item],
            "prerequisites": [],
            "tests": [],
            "investigation_steps": [],
            "completion_checklist": [],
            "missing_information": [],
        }
    )
    checked = guides.verified_result(value, [source, issue], "maintainer/project", COMMIT, 1)
    link = checked["starting_points"][0]["evidence"][0]["url"]
    assert link.endswith("/src/export%20file.py#L1-L12")


def test_bounded_github_reads_reject_oversized_responses_and_redirects():
    for response in [
        httpx.Response(200, content=b"x" * 51),
        httpx.Response(302, headers={"Location": "https://example.com"}),
    ]:
        calls = []

        def transport(request):
            calls.append(request.url)
            return response

        client = GitHubClient(
            client=httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(transport))
        )
        with pytest.raises(GitHubError):
            client.get("/repos/maintainer/project", max_bytes=50)
        assert len(calls) == 1


def test_bounded_github_reads_decode_compression_once():
    payload = gzip.compress(b'{"sha": "example"}')
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            content=payload,
            headers={"Content-Encoding": "gzip", "Content-Length": str(len(payload))},
        )
    )
    client = GitHubClient(client=httpx.Client(base_url="https://api.github.com", transport=transport))
    assert client.get("/repos/maintainer/project", max_bytes=100).json() == {"sha": "example"}


def test_contributor_card_generate_approve_and_stale_state():
    ui_path = str(Path(__file__).resolve().parents[1] / "ui")
    # Model the API state, then exercise real Streamlit buttons and rendered references.
    result = {
        **{s: [] for s in guides.SECTIONS},
        "sufficient_context": True,
        "documented_commands": [],
        "missing_information": [],
    }
    result["starting_points"] = [
        {
            "text": "Inspect export handling",
            "evidence": [
                {
                    "label": "src/export.py · lines 1–4",
                    "url": f"https://github.com/maintainer/project/blob/{COMMIT}/src/export.py#L1-L4",
                    "quote": "def csv_export(rows):",
                }
            ],
        }
    ]
    result["investigation_steps"] = result["starting_points"]
    card = AppTest.from_string(f"""
import sys
sys.path.insert(0, {ui_path!r})
import streamlit as st
from contributor_guide import contributor_guide
def api(path, method='GET', payload=None):
    if method == 'POST':
        assert payload['snapshot_id'] == 1
        st.session_state['generated'] = True
    if method == 'PUT':
        st.session_state['approved'] = payload['approved']
    if not st.session_state.get('generated'):
        return {{'guide': None, 'ai_configured': True}}
    return {{'ai_configured': True, 'guide': {{
        'id': 'guide-1', 'status': 'complete', 'commit_sha': {COMMIT!r}, 'model': 'test-model',
        'outdated_issue': st.session_state.get('stale', False), 'outdated_version': False,
        'approved_by': 'maintainer' if st.session_state.get('approved') else None,
        'review_revision': 0, 'result': {result!r},
    }}}}
contributor_guide({{'id': 1, 'snapshot_id': 1}}, api, lambda p: 'test-request-key-at-least-16', True)
""")
    card.run(timeout=20)
    assert not card.exception
    card.button[0].click().run(timeout=20)
    assert not card.exception
    assert any("AI draft" in x.value for x in card.info)
    next(x for x in card.button if x.label == "Approve contributor guide").click().run(timeout=20)
    assert not card.exception
    assert any("Maintainer approved" in x.value for x in card.success)
    card.session_state["approved"] = False
    card.session_state["stale"] = True
    card.run(timeout=20)
    assert next(x for x in card.button if x.label == "Approve contributor guide").disabled
