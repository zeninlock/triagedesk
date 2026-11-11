import json
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from triagedesk.ai_labels import DEFAULT_TAXONOMY


def test_signin_connect_tabs_uncertain_review_and_logout(monkeypatch):
    """Exercise the tab workflow against a mocked API; never contact live providers."""
    connected, reviewed = False, False
    work_status, work_revision = "open", 0
    real_client = httpx.Client
    taxonomy_hash = "a" * 64
    label_queries = []

    def respond(request):
        nonlocal connected, reviewed, work_status, work_revision
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
            "labels": [
                {"group": "type", "name": "type: bug", "confidence": 0.6},
                {"group": "priority", "name": "priority: low", "confidence": 0.6},
            ],
            "work_status": work_status,
            "work_revision": work_revision,
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
                "labels": {
                    g: {n: int(n == "type: bug") for n in names} for g, names in DEFAULT_TAXONOMY.items()
                },
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
        elif path == "/triage/issues/1/status":
            body = json.loads(request.content)
            assert body["expected_revision"] == work_revision
            work_status = body["status"]
            work_revision += 1
            data = {"status": work_status, "revision": work_revision}
        elif path == "/triage/issues/1/reviews":
            assert json.loads(request.content)["labels"][0] == {"group": "type", "name": "type: bug"}
            reviewed = True
            data = {"id": 1, "revision": 1}
        else:
            raise AssertionError("Unexpected API path: " + path)
        return httpx.Response(200, json=data)

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs)
    )
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui/app.py"))
    app.run(timeout=30)
    assert not app.exception
    next(f for f in app.text_input if f.label == "GitHub token").set_value("ui-test-credential")
    next(b for b in app.button if b.label == "Verify GitHub identity").click().run(timeout=30)
    assert not app.exception
    assert {"Overview", "Issues", "Needs review", "Reviewed", "Connect repository"}.issubset(
        {t.label for t in app.tabs}
    )
    next(f for f in app.text_input if f.label == "Public repository").set_value("maintainer/project")
    next(b for b in app.button if b.label == "Verify maintainer and import issues").click().run(timeout=30)
    assert not app.exception
    app.session_state["workspace_tabs"] = "Needs review"
    app.run(timeout=30)
    app.session_state["selected_issue"] = 1
    app.session_state["selected_repository"] = 1
    app.run(timeout=30)
    assert not app.exception
    next(s for s in app.selectbox if s.label == "Issue work status").select("in progress")
    next(b for b in app.button if b.label == "Save work status").click().run(timeout=30)
    assert not app.exception and work_status == "in progress"
    assert next(s for s in app.selectbox if s.label == "Issue work status").value == "in progress"
    next(b for b in app.button if b.label == "Save reviewed labels").click().run(timeout=30)
    assert not app.exception and reviewed
    assert any("moved to the Reviewed tab" in message.value for message in app.success)
    app.session_state["workspace_tabs"] = "Issues"
    app.session_state["browse_group"] = "Area"
    app.session_state["labels_1_area"] = "area: api"
    app.run(timeout=30)
    assert not app.exception
    assert label_queries[-1]["group"] == "area" and label_queries[-1]["label"] == "area: api"
    next(b for b in app.button if b.label == "Sign out").click().run(timeout=30)
    assert not app.exception
    assert any(f.label == "GitHub token" for f in app.text_input)


@pytest.mark.parametrize("current_configured", [True, False])
@pytest.mark.parametrize("import_configured", [True, False])
def test_import_notice_uses_current_backend_status(current_configured, import_configured):
    ui_path = str(Path(__file__).resolve().parents[1] / "ui")
    app = AppTest.from_string(
        f"""
import sys
sys.path.insert(0, {ui_path!r})
import streamlit as st
from account import connections_page

def api(path):
    assert path == '/connections'
    return []

connections_page({{
    'auth_mode': 'github', 'writes_enabled': True,
    'ai_configured': st.session_state['current_configured'],
}}, api)
"""
    )
    app.session_state["current_configured"] = current_configured
    app.session_state["connection_job"] = "old-import"
    app.session_state["connection_result"] = {
        "id": "old-import",
        "repository_name": "maintainer/project",
        "status": "complete",
        "result": {"ai_labels": {"configured": import_configured, "analyzed": 0}},
    }
    app.run(timeout=30)
    assert not app.exception
    captions = [item.value for item in app.caption]
    messages = [item.value for item in app.info]
    assert any("OpenAI key loaded by the backend" in item for item in captions) == current_configured
    assert any("has not loaded an OpenAI API key" in item for item in messages) == (not current_configured)
    assert any("This import ran before AI was enabled" in item for item in messages) == (
        current_configured and not import_configured
    )
    assert any("During this import: 0 analyzed" in item for item in captions)


def test_ai_failure_is_visible_and_direct_retry_refreshes_issue_rows():
    ui_path = str(Path(__file__).resolve().parents[1] / "ui")
    app = AppTest.from_string(f"""
import sys
sys.path.insert(0, {ui_path!r})
import streamlit as st
from workspace import watch_workspace, issue_table

def info():
    done = st.session_state.get('analyzed', False)
    return {{
        'counts': {{'pending': 0 if done else 1, 'auto_sorted': 1 if done else 0}},
        'model': 'test-model', 'ai_configured': True,
        'ai_activity': {{
            'revision': 'complete' if done else 'failed', 'can_retry': True,
            'states': {{'queued': 0, 'running': 0, 'failed': 0 if done else 1}},
            'error': None if done else {{'message': 'OpenAI rejected the API key (401).', 'action': 'Replace it, then retry.'}},
        }},
    }}

def api(path, method='GET', **kwargs):
    if path.endswith('/summary'):
        return info()
    if path.endswith('/refresh'):
        assert not kwargs.get('quiet', False), 'Automatic sync errors must remain visible'
        return {{'status': 'idle'}}
    if path.endswith('/analyze'):
        st.session_state['analyzed'] = True
        return {{'id': 'ai-pass', 'status': 'queued'}}
    if path == '/connections/jobs/ai-pass':
        return {{'status': 'complete'}}
    if path.endswith('/issues'):
        done = st.session_state.get('analyzed', False)
        return {{'total': 1, 'items': [{{
            'id': 1, 'number': 1, 'title': 'API crashes', 'confidence': 0.96 if done else None,
            'status': 'auto_sorted' if done else 'pending',
            'analysis_status': 'complete' if done else 'failed',
            'analysis_failure': None if done else {{'message': 'OpenAI rejected the API key (401).'}},
            'labels': [{{'group': 'type', 'name': 'type: bug'}}] if done else [],
        }}]}}
    raise AssertionError(path)

watch_workspace(1, api, info())
issue_table(1, api, 'ai-progress')
""")
    app.run(timeout=30)
    assert not app.exception
    assert any("OpenAI rejected the API key (401)" in message.value for message in app.warning)
    assert app.dataframe[0].value.iloc[0]["AI triage"] == "AI needs attention"
    next(button for button in app.button if button.label == "Run AI now").click().run(timeout=30)
    assert not app.exception
    assert not app.warning
    assert app.dataframe[0].value.iloc[0]["AI triage"] == "Auto-sorted"
    assert app.dataframe[0].value.iloc[0]["Type"] == "type: bug"


def test_retry_button_remains_available_during_an_active_sync():
    ui_path = str(Path(__file__).resolve().parents[1] / "ui")
    app = AppTest.from_string(f"""
import sys
sys.path.insert(0,{ui_path!r})
import streamlit as st
from workspace import watch_workspace
info={{
 'counts':{{'pending':1}},'model':'test-model','ai_configured':True,
 'ai_activity':{{'revision':'failed','can_retry':True,'states':{{'failed':1}},
 'error':{{'message':'An earlier request failed authentication.','action':'Retry now.','automatic_retry':False}}}}
}}
def api(path,method='GET',**kwargs):
 if path.endswith('/refresh'):
  return {{'id':'active-sync','status':'running','stage':'Fetching issues'}}
 if path.endswith('/summary'):
  return info
 raise AssertionError(path)
watch_workspace(1,api,info)
""")
    app.run(timeout=30)
    assert not app.exception
    button = next(b for b in app.button if b.label == "Run AI now")
    assert not button.disabled
