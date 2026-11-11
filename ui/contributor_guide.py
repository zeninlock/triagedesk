"""Contributor guide card. Repository/model text is rendered without HTML."""

import streamlit as st

SECTIONS = {
    "starting_points": "Relevant files",
    "prerequisites": "Prerequisites",
    "investigation_steps": "First investigation steps",
    "tests": "Relevant tests",
    "completion_checklist": "Completion checklist",
    "documented_commands": "Documented commands",
}


def render_items(result):
    for section, title in SECTIONS.items():
        if not result.get(section):
            continue
        st.write(f"**{title}**")
        for item_index, item in enumerate(result[section]):
            st.text(item["text"])
            if section == "documented_commands":
                st.code(item["command"], language="bash")
            for evidence_index, evidence in enumerate(item["evidence"]):
                st.link_button(
                    "Source checked · " + evidence["label"],
                    evidence["url"],
                    key=f"guide_source_{section}_{item_index}_{evidence_index}",
                )
                with st.expander("View supporting quote"):
                    st.code(evidence["quote"], language=None)
    if result.get("missing_information"):
        st.write("**Missing information**")
        for question in result["missing_information"]:
            st.text("• " + question)


def contributor_guide(issue, api, key_for, can_write):
    issue_id = issue["id"]
    path = f"/triage/issues/{issue_id}/guide"
    st.subheader("Contributor guide")
    st.caption(
        "A starting plan with checked source references. Investigation steps and proposed fixes still need human judgment."
    )

    @st.fragment(run_every="4s")
    def card():
        data = api(path)
        if data is None:
            return
        guide = data.get("guide")
        busy = guide and guide["status"] in {"queued", "running"}
        stale = guide and (guide.get("outdated_issue") or guide.get("outdated_version"))
        if busy:
            st.info(guide["stage"] + ". You can continue browsing.")
            return
        if guide and guide["status"] == "failed":
            st.warning(guide["error"])
            if guide.get("retry_after"):
                st.caption("Earliest retry: " + str(guide["retry_after"]))
        if stale:
            st.warning(
                "This guide covers an older issue or guide configuration. Generate a current draft before approving it."
            )
        if guide and guide["status"] == "complete":
            if guide.get("approved_by"):
                st.success("Maintainer approved · " + guide["approved_by"])
            else:
                st.info("AI draft · awaiting maintainer review")
            commit = guide["commit_sha"]
            st.caption(f"Repository version {commit[:12]} · {guide['model']}")
            st.caption(
                "This guide covers that saved version. Check for updates to look for newer repository code."
            )
            if guide.get("reused"):
                st.caption("Saved analysis reused; this check did not make a new AI request.")
            if guide.get("partial"):
                st.caption(
                    "Context was limited by file, size, or coverage limits. Some repository content was unavailable."
                )
            if not guide["result"].get("sufficient_context"):
                st.warning("More context is needed for a reliable starting plan.")
            render_items(guide["result"])
            if not guide["result"].get("tests"):
                st.caption("No relevant tests were established from the retrieved excerpts.")
            approved = bool(guide.get("approved_by"))
            if st.button(
                "Remove guide approval" if approved else "Approve contributor guide",
                key=f"approve_guide_{guide['id']}_{guide['review_revision']}",
                disabled=not can_write
                or (not approved and (stale or not guide["result"].get("sufficient_context"))),
            ):
                if api(
                    path + f"/{guide['id']}/approval",
                    "PUT",
                    {
                        "approved": not approved,
                        "expected_revision": guide["review_revision"],
                    },
                ):
                    st.rerun()
        label = "Generate contributor guide"
        if guide:
            label = (
                "Check for updates"
                if guide["status"] == "complete" and not stale
                else "Generate current guide"
                if stale
                else "Retry contributor guide"
            )
        if st.button(
            label, key=f"generate_guide_{issue_id}", disabled=not can_write or not data.get("ai_configured")
        ):
            payload = {
                "snapshot_id": data.get("current_snapshot_id", issue["snapshot_id"]),
                "check_updates": bool(guide),
            }
            payload["idempotency_key"] = key_for(
                {
                    "kind": "contributor_guide",
                    "issue_id": issue_id,
                    "previous_guide": guide["id"] if guide else None,
                    **payload,
                }
            )
            if api(path, "POST", payload):
                st.rerun()
        if not data.get("ai_configured"):
            st.caption("The installation's OpenAI key is needed to generate a guide.")
        st.caption(
            "Generating a new draft may use one AI request. Reopening a saved guide uses none. Documented commands are displayed for review; TriageDesk does not run them."
        )

    card()
