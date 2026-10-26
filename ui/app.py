"""Streamlit is an API client only. No direct database or GitHub access."""

import hashlib
import os
import uuid
from datetime import datetime, time, timedelta, timezone

import httpx
import pandas as pd
import streamlit as st
from account import connections_page, sign_in

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


def select_issue(issue_id):
    st.session_state["selected_issue"] = issue_id
    st.session_state["navigation"] = "Issue details"


def method_text(value):
    return {
        "trained_model": "trained model",
        "source_label": "GitHub label",
        "rules": "text rules",
        "illustrative": "synthetic example",
    }.get(value, "suggestion")


def score_text(value):
    return "Unavailable" if value is None else f"{value:.2f}"


def show_related(data, issue=None, enabled=False):
    if not data:
        return
    st.caption(data.get("message", "Potentially related issues; similarity does not establish duplication."))
    if not data.get("items"):
        st.info("No current matching candidates. Build a retrieval index after importing issues.")
    for candidate in data.get("items", []):
        with st.expander(f"#{candidate['number']} · {candidate['title']}"):
            st.text(candidate["excerpt"])
            st.caption(f"{candidate['state']} · similarity {candidate['score']:.3f} · {data['method']}")
            st.link_button("Open source", candidate["source_url"])
            if issue:
                with st.form(f"judgment-{issue['id']}-{candidate['id']}"):
                    judgment = st.selectbox(
                        "Relationship", ["uncertain", "related", "duplicate", "unrelated"]
                    )
                    if st.form_submit_button("Save relationship judgment", disabled=not enabled):
                        payload = {
                            "candidate_issue_id": candidate["id"],
                            "query_snapshot_id": issue["snapshot_id"],
                            "candidate_snapshot_id": candidate["snapshot_id"],
                            "judgment": judgment,
                        }
                        payload["idempotency_key"] = key_for(payload)
                        if api(f"/issues/{issue['id']}/judgments", "POST", payload):
                            st.success("Judgment saved. UI judgments are separate from retrieval evaluation.")


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
with st.sidebar:
    st.title("▦ TriageDesk")
    st.caption("A clearer queue. A human decision.")
    if github_auth:
        st.caption(f"Signed in as @{account['login']}")
        if st.button("Sign out"):
            api("/auth/logout", "POST")
            st.session_state.clear()
            st.rerun()
    page = st.radio(
        "Workspace",
        (["Connect repository"] if github_auth else [])
        + [
            "Overview",
            "Review queue",
            "Issue details",
            "Try a new issue",
            "Model evaluation",
            "About & methodology",
        ]
        + ([] if github_auth else ["Connect repository"]),
        key="navigation",
    )
    st.divider()
    repo_names = {r["full_name"]: r["id"] for r in repos}
    repo_options = list(repo_names) if github_auth else ["All imported repositories", *repo_names]
    repo_choice = st.selectbox(
        "Repository", repo_options or ["Connect a repository first"], disabled=not repo_options
    )
    state = st.selectbox("Source state", ["All", "open", "closed"])
    category = st.selectbox("Category", ["All", "bug", "enhancement", "question"])
    cat_source = st.selectbox(
        "Category filter uses",
        ["effective", "predicted", "reviewed"],
        help="Effective uses the latest human category for the current snapshot, otherwise its prediction.",
    )
    review_status = st.selectbox("Review status", ["All", "awaiting", "reviewed", "deferred", "skipped"])
    date_range = st.date_input("Created date range (optional)", value=[])
    st.divider()
    if meta["writes_enabled"] and not github_auth:
        st.text_input(
            "Reviewer access token",
            type="password",
            key="reviewer_access",
            help="Set by the installation owner. The API independently checks every write.",
        )
    elif not meta["writes_enabled"]:
        st.caption("Read-only exploration. Reviewer writes are disabled by the server.")
    if st.button("Refresh data"):
        st.rerun()
filters = {"category_source": cat_source}
if repo_choice in repo_names:
    filters["repository_id"] = repo_names[repo_choice]
for name, value in (("state", state), ("category", category), ("review_status", review_status)):
    if value != "All":
        filters[name] = value
if len(date_range) == 2:
    filters["created_from"] = datetime.combine(date_range[0], time.min, timezone.utc).isoformat()
    filters["created_before"] = datetime.combine(
        date_range[1] + timedelta(days=1), time.min, timezone.utc
    ).isoformat()
can_write = meta["writes_enabled"] and bool(
    st.session_state.get("github_session") if github_auth else st.session_state.get("reviewer_access")
)
if github_auth and not repos and page != "Connect repository":
    st.info("Connect a public repository from the Connect repository page first.")
    st.stop()
if meta["mode"] == "fixture":
    st.info(
        "SYNTHETIC DEMO · 24 invented issues and illustrative scores. These are excluded from all reported model evaluation."
    )
else:
    st.caption(
        "REAL DATA · Public GitHub issues collected as snapshots. Imported counts may cover only part of a repository."
    )
if st.session_state.pop("flash", None):
    st.success("Review saved. The queue and dashboard now use the latest decision.")

if page == "Connect repository":
    connections_page(meta, api)
elif page == "Overview":
    st.title("Make room for the next decision")
    st.write("Review incoming reports, find recurring concerns, and keep the maintainer in control.")
    data = api("/dashboard", params=filters)
    if data:
        cols = st.columns(4)
        for col, (label, value) in zip(
            cols,
            [
                ("Imported issues", data["imported"]),
                ("Awaiting review", data["awaiting_review"]),
                ("Needs extra review", data["low_score"]),
                ("Review completion", f"{data['review_completion_rate']:.0%}"),
            ],
        ):
            col.metric(label, value)
        st.caption(f"{data['open']} open · {data['closed']} closed · {data['scope']}")
        left, right = st.columns([1.25, 1])
        with left:
            st.subheader("Issue arrivals")
            st.caption("Month of issue creation in UTC, not import time.")
            if data["arrivals"]:
                st.bar_chart(pd.DataFrame(data["arrivals"]).set_index("month"), color="#4764ed")
            else:
                st.info("No issues match these filters.")
        with right:
            st.subheader("Category signals")
            tabs = st.tabs(["Category suggestions", "Human decisions"])
            for tab, field in zip(tabs, ["predicted_categories", "reviewed_categories"]):
                with tab:
                    st.bar_chart(pd.DataFrame({"issues": data[field]}), color="#0c9c87")
            st.caption(
                "Unreviewed issues appear as unavailable in human decisions. Charts use current snapshots."
            )
        st.subheader("Recent review activity")
        if data["recent_reviews"]:
            st.dataframe(pd.DataFrame(data["recent_reviews"]), hide_index=True, width="stretch")
        else:
            st.info("No reviews in this filtered view. Open the review queue to make the first decision.")
        with st.expander("Metric definitions"):
            st.write(
                "Awaiting review includes issues with no decision, deferred issues, and skipped issues. Completion requires the latest decision on the current snapshot to be accept or correct. Needs extra review includes low-scoring model predictions and unscored source-label/rule suggestions. Missing predictions are awaiting review but are not counted as low score."
            )

elif page == "Review queue":
    st.title("One issue at a time")
    st.caption("Filter the queue, inspect a report, and record a decision with its context.")
    search = st.text_input("Search title or description", max_chars=200)
    c1, c2 = st.columns([2, 1])
    sort = c1.selectbox("Sort issues", ["oldest", "newest", "lowest_score"])
    page_number = c2.number_input("Page", min_value=1, value=1, step=1)
    data = api(
        "/issues", params={**filters, "search": search, "sort": sort, "page": page_number, "page_size": 10}
    )
    if data:
        st.caption(f"{data['total']} matching issues · 10 per page")
        if not data["items"]:
            st.info(
                "No issues on this page. Change the filters, return to page 1, or connect a repository from the Connect repository page."
            )
        for item in data["items"]:
            with st.container(border=True):
                a, b = st.columns([5, 1])
                a.write(f"#{item['number']} · {item['title']}")
                a.caption(
                    f"{item['predicted_category'] or 'No suggestion'} · {('score ' + score_text(item['max_score'])) if item.get('prediction_method') in {'trained_model', 'illustrative', None} else 'unscored · ' + method_text(item['prediction_method'])} · {item['review_status']} · created {item['created_at'][:10]} · {item['state']}"
                )
                b.button("Inspect issue", key=f"open-{item['id']}", on_click=select_issue, args=(item["id"],))

elif page == "Issue details":
    st.title("Inspect, then decide")
    selected = st.session_state.get("selected_issue")
    if not selected:
        st.info("Select an issue with “Inspect issue” in the review queue.")
    else:
        issue = api(f"/issues/{selected}")
        if issue:
            st.subheader(issue["title"])
            st.caption(
                f"#{issue['number']} · {issue['state']} · created {issue['created_at'][:10]} · current status {issue['review_status']}"
            )
            st.link_button(
                "View on GitHub" if meta["mode"] == "real" else "Synthetic example · no source issue",
                issue["source_url"],
            )
            left, right = st.columns([1.6, 1])
            p = issue["prediction"]
            with left:
                with st.container(border=True):
                    st.text(issue["body"] or "No description supplied.")
                st.write("Source labels:", ", ".join(issue["labels"]) or "None")
                st.write(
                    "Human-reviewed category:", issue["reviewed_category"] or "No completed current review"
                )
                st.subheader("Potentially related issues")
                show_related(api(f"/issues/{selected}/related"), issue, can_write)
            with right:
                st.subheader("Category suggestion")
                if p:
                    st.write(p["category"].capitalize())
                    st.caption(p.get("explanation") or "Inspect this suggestion before deciding.")
                    if p["scores"]:
                        st.dataframe(
                            pd.DataFrame([{"category": k, "model score": v} for k, v in p["scores"].items()]),
                            hide_index=True,
                        )
                        st.caption("Scores are not calibrated probabilities.")
                    else:
                        st.caption(
                            "Unscored suggestion from "
                            + method_text(p.get("method", "rules"))
                            + "; no ML probability is claimed."
                        )
                    if p["needs_review"]:
                        st.warning("This suggestion needs human review.")
                    with st.expander("Prediction provenance"):
                        st.json({k: p[k] for k in ["model_version", "created_at", "input_hash"]})
                else:
                    st.info("No prediction for this snapshot. You can categorize it manually.")
                if not can_write:
                    st.caption(
                        "Sign in with repository maintainer access to save."
                        if github_auth
                        else "Enter the reviewer token in the sidebar to save, if this server permits writes."
                    )
                with st.form(f"review-{selected}-{issue['review_revision']}"):
                    actions = ["accept", "correct", "defer", "skip"] if p else ["correct", "defer", "skip"]
                    action = st.selectbox(
                        "Decision",
                        actions,
                        help="Use correct for a manual category; defer or skip leaves the issue awaiting review.",
                    )
                    categories = ["bug", "enhancement", "question"]
                    category_value = st.selectbox(
                        "Selected category (used for accept/correct)",
                        categories,
                        index=categories.index(p["category"]) if p else 0,
                    )
                    note = st.text_area("Optional review note", max_chars=2000)
                    if st.form_submit_button("Save review", disabled=not can_write, type="primary"):
                        payload = {
                            "action": action,
                            "category": category_value if action in {"accept", "correct"} else None,
                            "note": note,
                            "prediction_id": p["id"] if p else None,
                            "snapshot_id": issue["snapshot_id"],
                            "expected_revision": issue["review_revision"],
                        }
                        payload["idempotency_key"] = key_for(payload)
                        if api(f"/issues/{selected}/reviews", "POST", payload):
                            st.session_state["flash"] = True
                            st.rerun()
                st.subheader("Review history")
                history = api(f"/issues/{selected}/reviews")
                if history:
                    for review in history:
                        st.write(
                            f"{review['action']} · {review['category'] or 'no category'} · {review['reviewer']}"
                        )
                        st.caption(
                            f"{review['created_at']} · snapshot {review['snapshot_id']} · revision {review['revision']}"
                        )
                        if review["note"]:
                            st.text(review["note"])
                else:
                    st.caption("No reviews yet.")

elif page == "Try a new issue":
    st.title("Try a new issue")
    st.write("Explore a suggestion without creating an issue on GitHub or storing the text in the database.")
    with st.form("try-new"):
        title = st.text_input("Issue title", max_chars=500)
        body = st.text_area("Description", max_chars=50000, height=200)
        submitted = st.form_submit_button("Find suggestions", type="primary")
    if submitted:
        if not title.strip():
            st.warning("Add a title first.")
        else:
            with st.spinner("Finding suggestions…"):
                result = api(
                    "/classify",
                    "POST",
                    {"title": title, "body": body, "repository_id": filters.get("repository_id")},
                )
                if result and result["available"]:
                    st.write(f"Suggested category: {result['category']} · score {result['max_score']:.2f}")
                    st.caption(result["score_meaning"])
                    st.json(result["scores"])
                elif result:
                    st.info(result["reason"])
                st.subheader("Potentially related issues")
                show_related(
                    api(
                        "/related",
                        "POST",
                        {"title": title, "body": body, "repository_id": filters.get("repository_id")},
                    )
                )

elif page == "Model evaluation":
    st.title("Evidence before claims")
    data = api("/models")
    if data:
        st.info(data["status"])
        if data.get("classification"):
            report = data["classification"]
            st.write("Model:", report["model_version"], "· Dataset:", report["dataset_version"])
            cols = st.columns(2)
            cols[0].metric("Test macro-F1", f"{report['test']['macro_f1']:.3f}")
            cols[1].metric("Majority baseline macro-F1", f"{report['baseline_test']['macro_f1']:.3f}")
            st.caption(
                f"All test predictions: accuracy {report['test']['accuracy']:.1%}; majority baseline {report['baseline_test']['accuracy']:.1%}. Test support: {report['test']['support']} issues."
            )
            st.dataframe(pd.DataFrame(report["test"]["per_class"]).T, width="stretch")
            st.write("Confusion matrix · rows actual, columns predicted · bug / enhancement / question")
            st.dataframe(
                pd.DataFrame(
                    report["test"]["confusion_matrix"],
                    index=["bug", "enhancement", "question"],
                    columns=["bug", "enhancement", "question"],
                )
            )
            st.write("Validation-selected review threshold:", report["threshold"])
            with st.expander("Splits, coverage, exclusions and error examples"):
                st.json(
                    {
                        k: report[k]
                        for k in ["splits", "validation", "test", "exclusions", "errors", "limitations"]
                    }
                )
        for field, label in [("retrieval", "Retrieval evaluation"), ("benchmark", "Latency measurements")]:
            st.subheader(label)
            if data.get(field):
                st.json(data[field])
            else:
                st.info("Not available for this mode. No results have been invented.")
        st.caption(
            "Historical text and labels can be edited after issue creation. Chronological results are retrospective evaluations of collected snapshots."
        )

else:
    st.title("A small assistant for a real maintainer")
    st.write(
        "TriageDesk organizes bug reports, enhancement requests, and questions. It helps a person inspect suggestions and record decisions; every GitHub operation is read-only."
    )
    st.subheader("How to read the evidence")
    st.write(
        "Source labels are weak supervision, model suggestions are uncalibrated text scores, and reviews are human decisions on a specific snapshot. Effective categories use a current human decision first and then a model suggestion. Uncertain is a workflow state, not a training class."
    )
    st.write(
        "Classification uses title and description only, with vocabulary learned on the chronological training partition. Exact and near duplicates are removed from newer partitions. TF-IDF and optional pinned MiniLM embeddings provide potentially related issues; scores do not prove duplication. Long reports are truncated to the embedding model’s first 256 wordpieces."
    )
    st.subheader("Data and synchronization")
    for repo in repos:
        st.write(
            f"{repo['full_name']} · last sync: {repo['last_synced_at'] or 'fixture seed / not synchronized'}"
        )
        st.caption(
            "Partial imported corpus"
            if repo["partial"]
            else "Full endpoint traversal at the last initial import; source may change"
        )
    imports = api("/imports")
    if imports:
        st.dataframe(pd.DataFrame(imports), hide_index=True)
    st.subheader("Current limits")
    st.write(
        "The three categories may overlap. Repository labels and historical snapshots can be noisy. Model quality on one repository may not transfer. Reviewer access uses a shared installation token; the audit identity is configured by the owner. User validation and cloud deployment are pending until verified. The synthetic campus-tools fixture illustrates software maintained by a student club; a separate campus-feedback application is not implemented."
    )
