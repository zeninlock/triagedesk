"""Tab-based workspace. Data, inference, and authorization remain in FastAPI."""

from datetime import datetime, timezone
from html import escape

import pandas as pd
import streamlit as st
from account import connections_page

GROUP_TITLES = {"type": "Type", "priority": "Priority", "area": "Area", "contributor": "Contributor"}
WORK_STATUSES = ["open", "in progress", "blocked"]
COLORS = {
    "open": ("#dbeafe", "#1e40af"),
    "in progress": ("#fef3c7", "#92400e"),
    "blocked": ("#fee2e2", "#991b1b"),
    "type: bug": ("#fee2e2", "#991b1b"),
    "type: feature or enhancement": ("#dcfce7", "#166534"),
    "type: docs": ("#dbeafe", "#1e40af"),
    "type: chore or refactor": ("#e2e8f0", "#334155"),
    "type: question": ("#f3e8ff", "#6b21a8"),
    "priority: high": ("#ffe4e6", "#9f1239"),
    "priority: medium": ("#ffedd5", "#9a3412"),
    "priority: low": ("#e2e8f0", "#334155"),
    "area: frontend": ("#e0e7ff", "#3730a3"),
    "area: backend": ("#ccfbf1", "#115e59"),
    "area: api": ("#cffafe", "#155e75"),
    "help wanted": ("#fce7f3", "#9d174d"),
    "good first issue": ("#ede9fe", "#5b21b6"),
}


def badge_html(value):
    bg, fg = COLORS.get(value, ("#f1f5f9", "#334155"))
    return f'<span style="display:inline-block;background:{bg};color:{fg};padding:4px 10px;margin:3px;border-radius:16px;font-size:13px;font-weight:600">{escape(value)}</span>'


def show_badges(values):
    st.markdown(" ".join(badge_html(value) for value in values), unsafe_allow_html=True)


def cell_style(value):
    bg, fg = COLORS.get(value, ("#ffffff", "#334155"))
    return f"background-color: {bg}; color: {fg}; font-weight: 600"


STATUS_TITLES = {
    "auto_sorted": "Auto-sorted",
    "needs_review": "Needs review",
    "reviewed": "Reviewed",
    "pending": "Waiting for AI",
}


def retry_caption(value):
    if not value:
        return
    retry = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if retry > datetime.now(timezone.utc):
        st.caption(
            "Next automatic AI attempt after " + retry.astimezone(timezone.utc).strftime("%H:%M:%S UTC")
        )
    else:
        st.caption("The retry delay has ended.")


def watch_workspace(repository_id, api, displayed_info):
    first_run = True

    @st.fragment(run_every="5s")
    def progress():
        nonlocal first_run
        current = displayed_info if first_run else api(f"/triage/{repository_id}/summary")
        first_run = False
        if not current:
            return
        activity = current.get("ai_activity", {})
        # A fast job may finish between polls. Refresh the actual issue rows too.
        if (current["counts"], activity.get("revision")) != (
            displayed_info["counts"],
            displayed_info.get("ai_activity", {}).get("revision"),
        ):
            st.rerun()
        job = api(f"/triage/{repository_id}/refresh", "POST")
        job = job or {}
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
        pending = current["counts"].get("pending", 0)
        if (
            pending
            and job.get("status") not in {"queued", "running", "busy"}
            and activity.get("can_retry")
            and not activity.get("error")
        ):
            ai_job = api(
                f"/triage/{repository_id}/analyze", "POST", params={"retry_failed": "false"}, quiet=True
            )
            if ai_job and ai_job.get("id"):
                job = ai_job
                st.session_state[f"active_job_{repository_id}"] = job["id"]
        if pending:
            states = activity.get("states", {})
            error = activity.get("error")
            if error:
                st.warning(error["message"] + " " + error["action"])
                if error.get("automatic_retry", True):
                    retry_caption(activity.get("retry_after"))
            st.caption(
                f"AI progress: {states.get('running', 0)} analyzing · {states.get('queued', pending)} queued · "
                f"{states.get('failed', 0)} failed attempts. Model: {current['model']}."
            )
            if st.button("Run AI now", disabled=not activity.get("can_retry", current.get("ai_configured"))):
                started = api(f"/triage/{repository_id}/analyze", "POST")
                if started:
                    if started.get("id"):
                        st.session_state[f"active_job_{repository_id}"] = started["id"]
                        st.toast("Retry saved. Pending AI work will continue; completed analyses are reused.")
                        st.rerun()
                    elif started.get("status") == "idle":
                        st.toast("Retry saved. Pending issues will resume automatically.")
                        st.rerun()
                    else:
                        st.info("Another repository is processing. Try again after it finishes.")
            st.caption(
                "Run AI now analyzes pending issues directly, without re-importing GitHub issues. Provider backoff still applies."
            )

    progress()


def overview(info):
    st.subheader("Your issues, organized")
    cols = st.columns(4)
    for col, status in zip(cols, STATUS_TITLES):
        col.metric(STATUS_TITLES[status], info["counts"].get(status, 0))
    st.caption(
        f"{info['total']} open imported issues · {'Partial collection' if info['partial'] else 'Complete collection'}"
    )
    cols = st.columns(3)
    for col, status in zip(cols, WORK_STATUSES):
        with col:
            show_badges([status])
            st.metric("Issues", info.get("work_statuses", {}).get(status, 0))
    st.subheader("Current issue labels")
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
        "Current labels include saved human corrections. Uncertain AI suggestions remain clearly marked for review."
    )


def issue_table(repository_id, api, key, status="all", group=None, label=None):
    work_status = st.selectbox("Work status", ["All", *WORK_STATUSES], key=f"work_filter_{key}")
    search = st.text_input("Search issues", max_chars=200, key=f"search_{key}")
    page = st.number_input("Page", min_value=1, step=1, key=f"page_{key}")
    context = (key, search, int(page), work_status)
    if st.session_state.get("detail_context") != context:
        st.session_state.pop("selected_issue", None)
        st.session_state["detail_context"] = context
    params = {"status": status, "search": search, "page": int(page), "page_size": 20}
    if work_status != "All":
        params["work_status"] = work_status
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
            **{
                title: next((x["name"] for x in item["labels"] if x.get("group") == group), "—")
                for group, title in GROUP_TITLES.items()
                if group != "contributor"
            },
            "Help wanted": "help wanted" if any(x["name"] == "help wanted" for x in item["labels"]) else "—",
            "Good first issue": "good first issue"
            if any(x["name"] == "good first issue" for x in item["labels"])
            else "—",
            "Work status": item.get("work_status", "open"),
            "AI triage": (
                "AI needs attention"
                if item["status"] == "pending" and item.get("analysis_failure")
                else "Analyzing"
                if item["status"] == "pending" and item.get("analysis_status") == "running"
                else STATUS_TITLES[item["status"]]
            ),
            "AI confidence": f"{item['confidence']:.0%}" if item["confidence"] is not None else "—",
            "AI details": (item.get("analysis_failure") or {}).get("message")
            or item.get("review_reason", ""),
        }
        for item in data["items"]
    ]

    def selected():
        event = st.session_state.get(f"table_{key}", {})
        selection = event.get("selection", {}).get("rows", [])
        if selection and selection[0] < len(data["items"]):
            st.session_state["selected_issue"] = data["items"][selection[0]]["id"]

    st.dataframe(
        pd.DataFrame(rows).style.map(
            cell_style, subset=["Type", "Priority", "Area", "Help wanted", "Good first issue", "Work status"]
        ),
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
    show_badges([issue.get("work_status", "open"), *(x["name"] for x in issue["labels"])])
    with st.form(f"status_{selected}_{issue.get('work_revision', 0)}"):
        work_status = st.selectbox(
            "Issue work status", WORK_STATUSES, index=WORK_STATUSES.index(issue.get("work_status", "open"))
        )
        save_status = st.form_submit_button("Save work status", disabled=not can_write)
    if save_status:
        payload = {"status": work_status, "expected_revision": issue.get("work_revision", 0)}
        payload["idempotency_key"] = key_for({"issue_id": selected, "change": "status", **payload})
        if api(f"/triage/issues/{selected}/status", "PUT", payload):
            st.toast("Work status saved")
            st.rerun()
    left, right = st.columns([1.4, 1])
    with left:
        st.text(issue["body"] or "No description provided.")
        st.caption("GitHub source labels: " + (", ".join(issue["source_labels"]) or "None"))
        with st.expander("Status history"):
            for event in issue.get("activity", []):
                st.write(f"{event['from_status']} → {event['to_status']}")
                st.caption(f"{event['actor']} · {event['created_at']}")
            if not issue.get("activity"):
                st.caption("No work status changes yet.")
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
        if not issue["labels"]:
            st.caption("Labels pending")
        analysis = issue.get("analysis")
        if analysis and analysis["status"] == "complete":
            st.text(analysis["summary"])
            st.text(analysis["explanation"])
            st.caption(
                f"AI confidence: {analysis['confidence']:.0%}. Model-reported score, not a calibrated probability."
            )
            with st.expander("Labels and confidence"):
                for label in analysis["labels"]:
                    st.write(f"{label['name']} · {label['confidence']:.0%}")
        elif issue["status"] == "pending" and issue.get("analysis_failure"):
            failure = issue["analysis_failure"]
            st.warning(failure["message"] + " " + failure["action"])
            if failure.get("automatic_retry", True):
                retry_caption(issue.get("analysis_retry_after"))
        elif issue["status"] == "pending":
            st.info("AI analysis is pending. It will run automatically when the service is available.")
        elif issue["status"] == "reviewed" and not analysis:
            st.caption("Human labels are saved; AI analysis is not required for this issue.")
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
                    if group in {"type", "priority", "area"}:
                        options = (["Not inferred"] if group == "area" else []) + issue["taxonomy"][group]
                        selected_type = st.selectbox(
                            title,
                            options,
                            index=options.index(defaults[0])
                            if defaults
                            else options.index("priority: low")
                            if group == "priority"
                            else 0
                            if group == "area"
                            else None,
                            placeholder="Not inferred" if group == "area" else f"Choose one {title.lower()}",
                        )
                        values[group] = (
                            [selected_type] if selected_type and selected_type != "Not inferred" else []
                        )
                    else:
                        values[group] = st.multiselect(title, issue["taxonomy"][group], default=defaults)
                note = st.text_area("Review note", max_chars=2000)
                submitted = st.form_submit_button(
                    "Save reviewed labels", type="primary", disabled=not can_write
                )
            if submitted:
                if not values["type"] or not values["priority"]:
                    st.warning("Choose one type and one priority.")
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
    st.subheader("Label guide")
    st.write(
        "AI assigns one type and one priority. It chooses an area when the issue gives enough context, and contributor tags when suitable. You can correct labels in any issue."
    )
    for group, title in GROUP_TITLES.items():
        st.write(f"**{title}**")
        show_badges(info["taxonomy"][group])
    st.write("**Work status · changed by you**")
    show_badges(WORK_STATUSES)
    st.caption(
        "Priority reflects inferred impact and urgency. When neither can be inferred, it defaults to low. Good first issue is reserved for clearly bounded, low-risk work."
    )
    st.caption(
        f"Model: {info['model']} · Auto-sort cutoff: {info['threshold']:.0%}. Confidence is model-reported, not measured accuracy."
    )


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
        st.caption("GitHub stays unchanged. Labels and decisions are saved in TriageDesk.")
    if st.session_state.get("selected_repository") != repository_id:
        st.session_state.pop("selected_issue", None)
        st.session_state["selected_repository"] = repository_id
    can_write = meta.get("writes_enabled") and bool(
        st.session_state.get("github_session") if github else st.session_state.get("reviewer_access")
    )
    st.title("TriageDesk")
    st.caption("Your open issues. Automatically organized.")
    if st.session_state.pop("review_saved", False):
        st.success("Review saved. The issue has moved to the Reviewed tab.")
    if st.session_state.get("workspace_notice"):
        st.warning(st.session_state.pop("workspace_notice"))
    pages = ["Overview", "Issues", "Needs review", "Reviewed", "Connect repository", "Label guide"]
    tabs = st.tabs(
        pages,
        default="Overview" if repositories else "Connect repository",
        key="workspace_tabs",
        on_change="rerun",
    )
    info = api(f"/triage/{repository_id}/summary") if repository_id else None
    if info and not info["ai_configured"]:
        st.info(
            "Automatic AI labeling needs the installation's OpenAI API key. Your issues remain visible while analysis is pending."
        )
    if repository_id and github and can_write and info:
        watch_workspace(repository_id, api, info)
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
            elif page == "Label guide":
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
