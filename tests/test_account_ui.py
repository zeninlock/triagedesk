import json
from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from triagedesk.ai_labels import DEFAULT_TAXONOMY


def test_signin_connect_tabs_uncertain_review_and_logout(monkeypatch):
    """Exercise the tab workflow against a mocked API; never contact live providers."""
    connected, reviewed = False, False
    real_client = httpx.Client
    taxonomy_hash = "a" * 64
    label_queries = []

    def respond(request):
        nonlocal connected, reviewed
        path = request.url.path
        item = {
            "id": 1,
            "number": 1,
            "title": "API crashes",
            "source_url": "https://github.com/maintainer/project/issues/1",
            "state": "open",
            "status": "reviewed" if reviewed else "needs_review",
            "confidence": 0.6,
            "snapshot_id": 1,
            "review_revision": int(reviewed),
            "analysis_id": 1,
            "labels": [{"group": "type", "name": "bug", "confidence": 0.6}],
        }
        if path == "/meta":
            data = {
                "auth_mode": "github",
                "mode": "real",
                "writes_enabled": True,
                "github_browser_login": False,
                "token_login": True,
                "ai_configured": True,
            }
        elif path == "/auth/token":
            assert json.loads(request.content)["token"] == "ui-test-credential"
            data = {
                "access_token": "opaque-application-session",
                "login": "maintainer",
                "expires_at": "2030-01-01T00:00:00Z",
            }
        elif path == "/auth/session":
            data = {"login": "maintainer", "github_user_id": 42}
        elif path == "/auth/logout":
            data = {"signed_out": True}
        elif path == "/repositories":
            data = [{"id": 1, "full_name": "maintainer/project"}] if connected else []
        elif path == "/connections" and request.method == "POST":
            assert request.headers["authorization"] == "Bearer opaque-application-session"
            connected = True
            data = {"id": "job-one"}
        elif path == "/connections":
            data = []
        elif path == "/connections/jobs/job-one":
            data = {
                "id": "job-one",
                "repository_name": "maintainer/project",
                "status": "complete",
                "stage": "Ready",
                "result": {
                    "ai_labels": {"configured": True, "analyzed": 1},
                    "import": {"status": "complete"},
                },
            }
        elif path == "/triage/1/refresh":
            data = {"status": "idle"}
        elif path == "/triage/1/summary":
            data = {
                "counts": {
                    "auto_sorted": 0,
                    "needs_review": int(not reviewed),
                    "reviewed": int(reviewed),
                    "pending": 0,
                },
                "total": 1,
                "partial": False,
                "labels": {g: {n: int(n == "bug") for n in names} for g, names in DEFAULT_TAXONOMY.items()},
                "taxonomy": DEFAULT_TAXONOMY,
                "taxonomy_hash": taxonomy_hash,
                "ai_configured": True,
                "threshold": 0.85,
                "model": "test-model",
            }
        elif path == "/triage/1/issues":
            label_queries.append(dict(request.url.params))
            expected = request.url.params.get("status")
            items = [item] if expected in ("all", item["status"]) else []
            data = {"items": items, "total": len(items), "page": 1, "page_size": 20}
        elif path == "/triage/issues/1":
            data = {
                **item,
                "repository_id": 1,
                "body": "The API crashes on launch.",
                "source_labels": [],
                "taxonomy": DEFAULT_TAXONOMY,
                "taxonomy_hash": taxonomy_hash,
                "history": [],
                "analysis": {
                    "status": "complete",
                    "model": "test",
                    "summary": "Crash report",
                    "explanation": "Crash described",
                    "confidence": 0.6,
                    "uncertain": False,
                    "labels": [],
                },
            }
        elif path == "/issues/1/related":
            data = {"items": []}
        elif path == "/triage/issues/1/reviews":
            assert json.loads(request.content)["labels"][0] == {"group": "type", "name": "bug"}
            reviewed = True
            data = {"id": 1, "revision": 1}
        else:
            raise AssertionError("Unexpected API path: " + path)
        return httpx.Response(200, json=data)

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs)
    )
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui/app.py"))
    app.run(timeout=10)
    assert not app.exception
    next(f for f in app.text_input if f.label == "GitHub token").set_value("ui-test-credential")
    next(b for b in app.button if b.label == "Verify GitHub identity").click().run(timeout=10)
    assert not app.exception
    assert {"Overview", "Issues", "Needs review", "Reviewed", "Connect repository"}.issubset(
        {t.label for t in app.tabs}
    )
    next(f for f in app.text_input if f.label == "Public repository").set_value("maintainer/project")
    next(b for b in app.button if b.label == "Verify maintainer and import issues").click().run(timeout=10)
    assert not app.exception
    app.session_state["workspace_tabs"] = "Needs review"
    app.run(timeout=10)
    app.session_state["selected_issue"] = 1
    app.session_state["selected_repository"] = 1
    app.run(timeout=10)
    assert not app.exception
    next(b for b in app.button if b.label == "Save reviewed labels").click().run(timeout=10)
    assert not app.exception and reviewed
    assert any("moved to the Reviewed tab" in message.value for message in app.success)
    app.session_state["workspace_tabs"] = "Issues"
    app.session_state["browse_group"] = "Module"
    app.session_state["labels_1_scope"] = "API"
    app.run(timeout=10)
    assert not app.exception
    assert label_queries[-1]["group"] == "scope" and label_queries[-1]["label"] == "API"
    next(b for b in app.button if b.label == "Sign out").click().run(timeout=10)
    assert not app.exception
    assert any(f.label == "GitHub token" for f in app.text_input)
