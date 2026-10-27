"""Streamlit is an API client only. No direct database or GitHub access."""

import hashlib
import os
import uuid

import httpx
import streamlit as st
from account import sign_in
from workspace import render_workspace

st.set_page_config(page_title="TriageDesk", page_icon="▦", layout="wide")
st.markdown(
    """<style>
.block-container {padding-top:2rem;max-width:1450px}
h1 {letter-spacing:-.045em;font-weight:750} h2,h3 {letter-spacing:-.025em}
[data-testid="stMetric"] {background:#f4f7fc;border:1px solid #e1e8f3;border-radius:14px;padding:18px}
[data-testid="stSidebar"] {background:#f3f6fb}
[data-testid="stMetricLabel"] {color:#55637b}
.stButton>button {border-radius:8px} footer {visibility:hidden}
</style>""",
    unsafe_allow_html=True,
)  # Static stylesheet only; never interpolate issue content.
BASE = os.getenv("API_URL", "http://localhost:8000").rstrip("/")


def api(path, method="GET", payload=None, params=None, quiet=False):
    headers = {}
    token = st.session_state.get("github_session", {}).get("access_token") or st.session_state.get(
        "reviewer_access", ""
    )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=20) as client:
            response = client.request(method, f"{BASE}{path}", json=payload, params=params, headers=headers)
        if response.is_success:
            return response.json()
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = "The service could not complete this request"
        if response.status_code == 401 and st.session_state.get("github_session"):
            st.session_state.pop("github_session", None)
        if response.status_code == 409:
            st.warning(f"{message}. Refresh this page before saving again.")
        elif not quiet:
            st.error(str(message))
    except httpx.HTTPError:
        if not quiet:
            st.error("TriageDesk could not reach the API. Check that the services are running, then refresh.")
    return None


def key_for(payload):
    text = repr(sorted(payload.items()))
    fingerprint = hashlib.sha256(text.encode()).hexdigest()
    keys = st.session_state.setdefault("submission_keys", {})
    return keys.setdefault(fingerprint, str(uuid.uuid4()))


meta = api("/meta")
if not meta:
    st.stop()
github_auth = meta.get("auth_mode") == "github"
account = None
if github_auth:
    if not st.session_state.get("github_session"):
        sign_in(meta, api)
        st.stop()
    account = api("/auth/session", quiet=True)
    if not account:
        st.session_state.pop("github_session", None)
        st.rerun()
repos = api("/repositories")
if repos is None:
    st.stop()
render_workspace(meta, account, repos, api, key_for)
