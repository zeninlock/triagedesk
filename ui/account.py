"""Account and connection screens. All authorization and GitHub calls stay in the API."""

import pandas as pd
import streamlit as st


def remember_session(result):
    st.session_state.clear()
    st.session_state["github_session"] = {key: result[key] for key in ["access_token", "login", "expires_at"]}
    st.session_state.pop("device_attempt", None)
    st.rerun()


def sign_in(meta, api):
    st.title("Your repository. Your review desk.")
    st.write(
        "Sign in with GitHub, connect a public repository you maintain, and organize its actual issues. "
        "Your repository permissions are checked separately before importing or saving decisions."
    )
    if meta.get("github_browser_login"):
        if st.button("Sign in with GitHub", type="primary"):
            result = api("/auth/device/start", "POST")
            if result:
                st.session_state["device_attempt"] = result
        attempt = st.session_state.get("device_attempt")
        if attempt:
            st.write("Enter this one-time code on GitHub, then approve the application's read access:")
            st.code(attempt["user_code"], language=None)
            st.link_button("Continue on GitHub", attempt["verification_uri"])
            st.caption(
                "Keep this page open. It checks authorization automatically; codes expire after 15 minutes."
            )

            @st.fragment(run_every="5s")
            def check_authorization():
                result = api("/auth/device/poll", "POST", {"handle": attempt["handle"]})
                if result and result.get("status") == "authorized":
                    remember_session(result)
                elif result:
                    st.info("Waiting for approval on GitHub…")

            check_authorization()
            if st.button("Restart sign-in"):
                st.session_state.pop("device_attempt", None)
                st.rerun()
    if meta.get("token_login"):
        with st.expander(
            "Sign in with a fine-grained GitHub token", expanded=not meta.get("github_browser_login")
        ):
            st.write(
                "Use a fine-grained personal access token for the public repository you maintain, "
                "with Metadata: read and Issues: read. GitHub verifies the account behind the token. "
                "Having a read token alone does not make an account a repository maintainer."
            )
            st.link_button(
                "How to create a fine-grained token",
                "https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens",
            )
            with st.form("github-token-login", clear_on_submit=True):
                token = st.text_input("GitHub token", type="password", max_chars=1000)
                submitted = st.form_submit_button("Verify GitHub identity", type="primary")
            if submitted:
                if not token.strip():
                    st.warning("Enter a token first.")
                else:
                    result = api("/auth/token", "POST", {"token": token.strip()})
                    if result:
                        remember_session(result)
    if not meta.get("github_browser_login") and not meta.get("token_login"):
        st.error("The installation owner must configure a GitHub sign-in method before this app can be used.")
    st.caption(
        "GitHub credentials are encrypted in backend storage. Sessions expire and can be signed out. "
        "TriageDesk reads public issues and records local reviews; it does not change your GitHub repository."
    )


def connections_page(meta, api):
    st.title("Connect a public repository")
    st.write(
        "Import real GitHub issues, prepare category suggestions, and build related-report search in one step."
    )
    if meta.get("auth_mode") != "github":
        st.info(
            "This is the local fixture demonstration. To connect actual repositories, use MODE=real, "
            "AUTH_MODE=github, and a random AUTH_ENCRYPTION_KEY of at least 32 characters. "
            "The README contains the local setup and online hosting instructions."
        )
        return
    if not meta.get("writes_enabled"):
        st.info("The installation owner has disabled imports and review writes.")
        return
    if meta.get("ai_configured"):
        st.caption(
            "Groq key loaded by the backend. Waiting issues will be analyzed while a workspace is open."
        )
    else:
        st.info(
            "The backend has not loaded a Groq API key. The installation owner can add GROQ_API_KEY "
            "in Streamlit Secrets, save, then refresh the app."
        )
    with st.form("connect-repository"):
        repository = st.text_input(
            "Public repository",
            placeholder="owner/repository or https://github.com/owner/repository",
            max_chars=300,
        )
        limit = st.number_input(
            "Maximum GitHub response objects to fetch", min_value=1, max_value=3000, value=500, step=100
        )
        incremental = st.checkbox("Synchronize changes to an already connected repository")
        submitted = st.form_submit_button("Verify maintainer and import issues", type="primary")
    st.caption(
        "GitHub must confirm that you own the repository or have triage, write, maintain, or admin access. "
        "Pull requests are excluded. A capped import is partial; a repository without issues produces an empty queue."
    )
    if submitted:
        result = api(
            "/connections",
            "POST",
            {"repository": repository, "limit": int(limit), "incremental": incremental},
        )
        if result:
            st.session_state["connection_job"] = result["id"]
            st.session_state.pop("connection_result", None)
            st.rerun()
    job_id = st.session_state.get("connection_job")
    if job_id:

        @st.fragment(run_every="3s")
        def show_progress():
            cached = st.session_state.get("connection_result")
            job = cached if cached and cached["id"] == job_id else api(f"/connections/jobs/{job_id}")
            if not job:
                return
            st.subheader(job["repository_name"])
            if job["status"] in {"queued", "running"}:
                st.info(job["stage"] + "…")
                imported = job.get("result", {}).get("import", {})
                st.caption(
                    f"Fetched {imported.get('fetched', 0)} objects · {imported.get('imported', 0)} new issues · {imported.get('updated', 0)} updated · {imported.get('excluded', 0)} pull requests excluded"
                )
            else:
                if cached is None:
                    st.session_state["connection_result"] = job
                    st.rerun()  # Refresh the repository selector once when the job finishes.
                if job["status"] == "failed":
                    st.error(
                        job["error"] or "Import could not finish. Retry to continue from saved progress."
                    )
                else:
                    st.success("Imported and organized. Open the Issues or Needs review tab.")
                    result = job.get("result", {})
                    counts = result.get("ai_labels", {})
                    st.caption(
                        f"During this import: {counts.get('analyzed', 0)} analyzed · {counts.get('cached', 0)} cached analyses reused · {result.get('closed_removed', 0)} closed issues removed"
                    )
                    if meta.get("ai_configured") and not counts.get("configured"):
                        st.info(
                            "This import ran before AI was enabled. Pending issues will be processed "
                            "automatically while a workspace is open."
                        )
                    if result.get("import", {}).get("status") == "limited":
                        st.warning(
                            "The fetch limit was reached. This is a partial collection; increase the limit and run a full import to include more history."
                        )
                    st.button(
                        "Open needs review",
                        on_click=lambda: st.session_state.update(workspace_tabs="Needs review"),
                    )

        show_progress()
    st.subheader("Your connected repositories")
    connections = api("/connections")
    if connections:
        rows = [
            {
                "Repository": row["full_name"],
                "Confirmed role": row["role"],
                "Last permission check": row["verified_at"],
                "Last synchronized": row["last_synced_at"],
                "Collection": "Partial" if row["partial"] else "Complete",
            }
            for row in connections
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info("Connect a repository to create your first workspace.")
    st.caption(
        "New issues are analyzed automatically; completed results are reused from PostgreSQL. Only uncertain results need review. While a workspace is open, synchronization also checks for new and closed issues."
    )
