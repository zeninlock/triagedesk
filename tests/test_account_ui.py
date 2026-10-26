import json
from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest


def test_signin_connect_progress_queue_and_logout(monkeypatch):
    """Exercise UI state transitions without a live identity provider or exposing credentials."""
    connected = False
    real_client = httpx.Client

    def respond(request):
        nonlocal connected
        path = request.url.path
        if path == "/meta":
            data = {
                "auth_mode": "github",
                "mode": "real",
                "writes_enabled": True,
                "github_browser_login": False,
                "token_login": True,
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
            assert json.loads(request.content)["repository"] == "maintainer/project"
            connected = True
            data = {"id": "job-one"}
        elif path == "/connections":
            data = (
                [
                    {
                        "full_name": "maintainer/project",
                        "role": "owner",
                        "verified_at": "2026-10-26T00:00:00Z",
                        "last_synced_at": "2026-10-26T00:00:00Z",
                        "partial": False,
                    }
                ]
                if connected
                else []
            )
        elif path == "/connections/jobs/job-one":
            data = {
                "id": "job-one",
                "repository_name": "maintainer/project",
                "status": "complete",
                "stage": "Ready to review",
                "result": {
                    "categorization": {
                        "categories": {"bug": 2, "enhancement": 1},
                        "methods": {"source_label": 3},
                        "needs_manual_category": 0,
                    },
                    "import": {"status": "complete"},
                },
            }
        elif path == "/issues":
            data = {"items": [], "total": 0, "page": 1, "page_size": 10}
        else:
            raise AssertionError("Unexpected UI API path " + path)
        return httpx.Response(200, json=data)

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs)
    )
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui/app.py"))
    app.run(timeout=10)
    assert not app.exception
    assert any(field.label == "GitHub token" for field in app.text_input)
    next(field for field in app.text_input if field.label == "GitHub token").set_value("ui-test-credential")
    next(button for button in app.button if button.label == "Verify GitHub identity").click().run(timeout=10)
    assert not app.exception
    next(field for field in app.text_input if field.label == "Public repository").set_value(
        "maintainer/project"
    )
    next(
        button for button in app.button if button.label == "Verify maintainer and import issues"
    ).click().run(timeout=10)
    assert not app.exception
    assert any("Imported and ready" in message.value for message in app.success)
    next(button for button in app.button if button.label == "Open review queue").click().run(timeout=10)
    assert not app.exception
    assert app.radio(key="navigation").value == "Review queue"
    next(button for button in app.button if button.label == "Sign out").click().run(timeout=10)
    assert not app.exception
    assert any(field.label == "GitHub token" for field in app.text_input)
