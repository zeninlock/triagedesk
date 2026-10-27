"""Tab-based workspace. Data, inference, and authorization remain in FastAPI."""

import pandas as pd
import streamlit as st
from account import connections_page

GROUP_TITLES = {
    "type": "Type",
    "priority": "Priority",
    "scope": "Module",
    "contributor": "Contributor",
    "workflow": "Workflow",
}
STATUS_TITLES = {
    "auto_sorted": "Auto-sorted",
    "needs_review": "Needs review",
    "reviewed": "Reviewed",
    "pending": "Waiting for AI",
}


def watch_workspace(repository_id, api):
    @st.fragment(run_every="5s")
    def progress():
        job = api(f"/triage/{repository_id}/refresh", "POST", quiet=True)
        if not job:
            return
        if job.get("status") in {"queued", "running"}:
            st.session_state[f"active_job_{repository_id}"] = job["id"]
            st.caption("Updating workspace · " + job["stage"])
        else:
            previous = st.session_state.pop(f"active_job_{repository_id}", None)
            if previous:
                finished = api(f"/connections/jobs/{previous}", quiet=True)
                if finished and finished["status"] in {"complete", "failed"}:
                    if finished["status"] == "failed":
                        st.session_state["workspace_notice"] = (
                            finished.get("error") or "Synchronization needs attention."
                        )
                    st.rerun()
            st.caption("Checks for new and closed issues automatically while this workspace is open.")

    progress()


def overview(info):
    st.subheader("Your issues, organized")
    cols = st.columns(4)
    for col, status in zip(cols, STATUS_TITLES):
        col.metric(STATUS_TITLES[status], info["counts"].get(status, 0))
    st.caption(
        f"{info['total']} open imported issues · {'Partial collection' if info['partial'] else 'Complete collection'}"
    )
    st.subheader("How AI labeled the current issues")
    tabs = st.tabs(list(GROUP_TITLES.values()), key="chart_group", on_change="rerun")
    for tab, group in zip(tabs, GROUP_TITLES):
        if tab.open:
            with tab:
                values = info["labels"].get(group, {})
                if any(values.values()):
                    st.bar_chart(pd.DataFrame({"Issues": values}), color="#4764ed")
                else:
                    st.info("No AI labels in this group yet.")
    st.caption(
        "AI suggestions for current open issues, including uncertain suggestions. Human overrides are shown on the issue itself."
    )


def issue_table(repository_id, api, key, status="all", group=None, label=None):
    search = st.text_input("Search issues", max_chars=200, key=f"search_{key}")
    page = st.number_input("Page", min_value=1, step=1, key=f"page_{key}")
    context = (key, search, int(page))
    if st.session_state.get("detail_context") != context:
        st.session_state.pop("selected_issue", None)
        st.session_state["detail_context"] = context
    params = {"status": status, "search": search, "page": int(page), "page_size": 20}
    if group and label:
        params.update(group=group, label=label)
    data = api(f"/triage/{repository_id}/issues", params=params)
    if not data:
        return
    st.caption(f"{data['total']} matching issues · 20 per page · select a row to see details")
    if not data["items"]:
        st.info("No issues match this view.")
        return
    rows = [
        {
            "#": item["number"],
            "Issue": item["title"],
            "Labels": " · ".join(x["name"] for x in item["labels"]) or "Waiting for analysis",
            "Status": STATUS_TITLES[item["status"]],
            "AI confidence": f"{item['confidence']:.0%}" if item["confidence"] is not None else "—",
        }
        for item in data["items"]
    ]

    def selected():
        event = st.session_state.get(f"table_{key}", {})
        selection = event.get("selection", {}).get("rows", [])
        if selection and selection[0] < len(data["items"]):
            st.session_state["selected_issue"] = data["items"][selection[0]]["id"]

    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        key=f"table_{key}",
        on_select=selected,
        selection_mode="single-row",
    )


def browse(repository_id, info, api):
    choice = st.selectbox("Show", ["All open issues", "Auto-sorted", "Waiting for AI"], key="issues_status")
    status = {"All open issues": "all", "Auto-sorted": "auto_sorted", "Waiting for AI": "pending"}[choice]
    names = ["All labels", *GROUP_TITLES.values()]
    tabs = st.tabs(names, key="browse_group", on_change="rerun")
    for tab, group in zip(tabs, [None, *GROUP_TITLES]):
        if tab.open:
            with tab:
                if group is None:
                    issue_table(repository_id, api, f"{repository_id}_all_{status}", status)
                else:
                    labels = ["All", *info["taxonomy"][group]]
                    children = st.tabs(labels, key=f"labels_{repository_id}_{group}", on_change="rerun")
                    for child, label in zip(children, labels):
                        if child.open:
                            with child:
                                issue_table(
                                    repository_id,
                                    api,
                                    f"{repository_id}_{group}_{label}_{status}",
                                    status,
                                    group,
                                    label if label != "All" else None,
                                )


def issue_details(repository_id, api, key_for, can_write):
    selected = st.session_state.get("selected_issue")
    if not selected:
        return
    issue = api(f"/triage/issues/{selected}", quiet=True)
    if not issue or issue["repository_id"] != repository_id:
        st.session_state.pop("selected_issue", None)
        return
    # Repository changes must not leave a different workspace's issue on screen.
    st.divider()
    st.subheader(f"#{issue['number']} · {issue['title']}")
    st.link_button("View on GitHub", issue["source_url"])
    left, right = st.columns([1.4, 1])
    with left:
        st.text(issue["body"] or "No description provided.")
        st.caption("GitHub source labels: " + (", ".join(issue["source_labels"]) or "None"))
        with st.expander("Related issues"):
            related = api(f"/issues/{selected}/related", quiet=True)
            if related:
                for candidate in related.get("items", []):
                    st.link_button(f"#{candidate['number']} · {candidate['title']}", candidate["source_url"])
                if not related.get("items"):
                    st.caption("No related reports currently available.")
        with st.expander("Review history"):
            for row in issue["history"]:
                st.write(" · ".join(x["name"] for x in row["labels"]))
                st.caption(f"{row['reviewer']} · {row['created_at']}")
                if row["note"]:
                    st.text(row["note"])
            if not issue["history"]:
                st.caption("No human reviews yet.")
    with right:
        st.write("**" + STATUS_TITLES[issue["status"]] + "**")
        st.write(" · ".join(x["name"] for x in issue["labels"]) or "Labels pending")
        analysis = issue.get("analysis")
        if analysis and analysis["status"] == "complete":
            st.text(analysis["summary"])
            st.text(analysis["explanation"])
            st.caption(
                f"AI confidence: {analysis['confidence']:.0%}. Model-reported score, not a calibrated probability."
            )
            with st.expander("Label evidence"):
                for label in analysis["labels"]:
                    st.write(f"{label['name']} · {label['confidence']:.0%}")
                    st.text(label["evidence"])
        else:
            st.info("AI analysis is pending. It will run automatically when the service is available.")
        expanded = issue["status"] == "needs_review"
        with st.expander(
            "Review uncertain labels" if expanded else "Adjust labels (optional)", expanded=expanded
        ):
            with st.form(f"labels_review_{selected}_{issue['review_revision']}_{issue['analysis_id']}"):
                values = {}
                for group, title in GROUP_TITLES.items():
                    defaults = [
                        x["name"]
                        for x in issue["labels"]
                        if x["group"] == group and x["name"] in issue["taxonomy"][group]
                    ]
                    if group == "type":
                        options = issue["taxonomy"][group]
                        selected_type = st.selectbox(
                            title,
                            options,
                            index=options.index(defaults[0]) if defaults else None,
                            placeholder="Choose one type",
                        )
                        values[group] = [selected_type] if selected_type else []
                    else:
                        values[group] = st.multiselect(title, issue["taxonomy"][group], default=defaults)
                note = st.text_area("Review note", max_chars=2000)
                submitted = st.form_submit_button(
                    "Save reviewed labels", type="primary", disabled=not can_write
                )
            if submitted:
                if not values["type"]:
                    st.warning("Choose one primary type.")
                else:
                    payload = {
                        "labels": [
                            {"group": g, "name": name} for g, names in values.items() for name in names
                        ],
                        "snapshot_id": issue["snapshot_id"],
                        "expected_revision": issue["review_revision"],
                        "taxonomy_hash": issue["taxonomy_hash"],
                        "note": note,
                    }
                    payload["idempotency_key"] = key_for(payload)
                    if api(f"/triage/issues/{selected}/reviews", "POST", payload):
                        st.session_state.pop("selected_issue", None)
                        st.session_state["review_saved"] = True
                        st.rerun()


def label_settings(repository_id, info, api, can_write):
    st.subheader("Your repository's label groups")
    st.caption(
        "One label per line. Type requires at least one label. AI uses these exact names on its next update."
    )
    with st.form(f"taxonomy_{repository_id}"):
        values = {
            group: st.text_area(
                title,
                "\n".join(info["taxonomy"][group]),
                max_chars=2000,
                key=f"taxonomy_{repository_id}_{group}",
            )
            for group, title in GROUP_TITLES.items()
        }
        submitted = st.form_submit_button("Save label settings", disabled=not can_write)
    if submitted:
        payload = {
            group: [x.strip() for x in text.splitlines() if x.strip()] for group, text in values.items()
        }
        if api(f"/triage/{repository_id}/taxonomy", "PUT", payload):
            st.success(
                "Label settings saved. New analysis will use these groups; previous decisions remain in history."
            )
    st.caption(
        f"Auto-sort cutoff: {info['threshold']:.0%}. Model: {info['model']}. Scores express model confidence, not measured accuracy."
    )
    with st.expander("Recorded model evidence"):
        data = api("/models")
        if data:
            st.caption("Historical classifier evaluation is separate from this new multi-label LLM workflow.")
            st.json(data)


def render_workspace(meta, account, repositories, api, key_for):
    github = meta.get("auth_mode") == "github"
    with st.sidebar:
        st.title("▦ TriageDesk")
        if github:
            st.caption(f"Signed in as @{account['login']}")
            if st.button("Sign out"):
                api("/auth/logout", "POST")
                st.session_state.clear()
                st.rerun()
        names = {r["full_name"]: r["id"] for r in repositories}
        repo_name = st.selectbox(
            "Repository", list(names) or ["Connect a repository first"], disabled=not names
        )
        repository_id = names.get(repo_name)
        if not github and meta.get("writes_enabled"):
            st.text_input("Reviewer access token", type="password", key="reviewer_access")
        st.caption("GitHub stays unchanged. Labels and decisions are saved in TriageDesk.")
    if st.session_state.get("selected_repository") != repository_id:
        st.session_state.pop("selected_issue", None)
        st.session_state["selected_repository"] = repository_id
    can_write = meta.get("writes_enabled") and bool(
        st.session_state.get("github_session") if github else st.session_state.get("reviewer_access")
    )
    st.title("TriageDesk")
    if meta.get("mode") == "fixture":
        st.info("Synthetic local demo. Issue text and demonstration scores are illustrative.")
    st.caption("Your open issues. Automatically organized.")
    if st.session_state.pop("review_saved", False):
        st.success("Review saved. The issue has moved to the Reviewed tab.")
    if st.session_state.get("workspace_notice"):
        st.warning(st.session_state.pop("workspace_notice"))
    pages = ["Overview", "Issues", "Needs review", "Reviewed", "Connect repository", "Label settings"]
    tabs = st.tabs(
        pages,
        default="Overview" if repositories else "Connect repository",
        key="workspace_tabs",
        on_change="rerun",
    )
    info = api(f"/triage/{repository_id}/summary") if repository_id else None
    if info and not info["ai_configured"]:
        st.info(
            "Automatic AI labeling needs the installation's Groq API key. Your issues remain visible while analysis is pending."
        )
    if repository_id and github and can_write:
        watch_workspace(repository_id, api)
    for tab, page in zip(tabs, pages):
        if not tab.open:
            continue
        with tab:
            if page == "Connect repository":
                connections_page(meta, api)
            elif not info:
                st.info("Connect a public repository to start organizing its issues.")
            elif page == "Overview":
                overview(info)
            elif page == "Label settings":
                label_settings(repository_id, info, api, can_write)
            else:
                st.subheader(page)
                if page == "Issues":
                    browse(repository_id, info, api)
                else:
                    status = "needs_review" if page == "Needs review" else "reviewed"
                    st.caption(
                        "Only uncertain AI decisions appear here."
                        if status == "needs_review"
                        else "Completed human reviews, separated from pending work."
                    )
                    issue_table(repository_id, api, f"{repository_id}_{status}", status)
                issue_details(repository_id, api, key_for, can_write)
