"""Community Cloud entrypoint: one shared private API, then the existing dashboard."""

import os
import runpy
from pathlib import Path

import streamlit as st

from triagedesk.community import CommunityBackendManager, CommunityStartupError


@st.cache_resource(show_spinner=False, on_release=lambda manager: manager.stop())
def private_backend_manager():
    return CommunityBackendManager()


try:
    # Read current secrets outside the cached function on every full app run.
    # The manager stops the previous child before starting a replacement.
    with st.spinner("Checking TriageDesk setup…"):
        backend = private_backend_manager().ensure(dict(st.secrets))
except (CommunityStartupError, FileNotFoundError) as exc:
    message = (
        str(exc) if isinstance(exc, CommunityStartupError) else "Add the required app secrets, then reboot."
    )
    st.error(message)
    st.stop()

os.environ["API_URL"] = backend.api_url
runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
