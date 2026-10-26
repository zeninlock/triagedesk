"""Community Cloud entrypoint: one shared private API, then the existing dashboard."""

import os
import runpy
from pathlib import Path

import streamlit as st

from triagedesk.community import CommunityStartupError, start_backend


@st.cache_resource(show_spinner="Starting TriageDesk…", validate=lambda backend: backend.alive())
def private_backend():
    return start_backend(dict(st.secrets))


try:
    backend = private_backend()
except (CommunityStartupError, FileNotFoundError) as exc:
    message = (
        str(exc) if isinstance(exc, CommunityStartupError) else "Add the required app secrets, then reboot."
    )
    st.error(message)
    st.stop()

os.environ["API_URL"] = backend.api_url
runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
