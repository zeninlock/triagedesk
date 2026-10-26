"""Small hand-written synthetic examples. Never used for reported evaluation."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from triagedesk.github import upsert_issue
from triagedesk.models import Prediction, Repository

EXAMPLES = [
    (
        "CSV export loses the final row",
        "Exporting the attendance table to CSV omits the last student. Expected all 42 rows; got 41. Reproduces after refreshing.",
        "bug",
    ),
    (
        "Add dark mode to the study planner",
        "A theme toggle would make late-night planning more comfortable. Please follow the operating system preference.",
        "enhancement",
    ),
    (
        "How do I invite a second coordinator?",
        "I created a club workspace. Where can I add another coordinator, and what permissions will they have?",
        "question",
    ),
    (
        "Attendance export drops one record",
        "The downloaded CSV has one fewer row than the table. The final attendee is missing when I export the event.",
        "bug",
    ),
    (
        "Calendar shows events an hour late",
        "After daylight saving time changed, saved study sessions display one hour later. My timezone is Europe/London.",
        "bug",
    ),
    (
        "Recurring weekly study sessions",
        "Please let me repeat a calendar event every Monday without copying it manually. An end date would also help.",
        "enhancement",
    ),
    (
        "Does calendar sync support Outlook?",
        "I see a calendar link in settings. Can I subscribe from Outlook, or only from Google Calendar?",
        "question",
    ),
    (
        "Login loops after password reset",
        "After resetting my password, signing in sends me back to the login page with no explanation. Happens in Safari.",
        "bug",
    ),
    (
        "Search clubs by meeting day",
        "Add a weekday filter to the club directory so students can discover groups that match their schedules.",
        "enhancement",
    ),
    (
        "Where are archived events stored?",
        "I archived an old event but cannot find it in the list. Is there a way to restore it?",
        "question",
    ),
    (
        "Offline attendance check-in",
        "At our last event the Wi-Fi failed. It would help to record attendance offline and synchronize later.",
        "enhancement",
    ),
    (
        "Empty dashboard after switching clubs",
        "Switching from Robotics to Debate leaves the dashboard blank until I reload the page. No issues with the network.",
        "bug",
    ),
    (
        "Notification emails arriving twice",
        "Every event reminder arrives twice even though my email is registered once. Started after I changed clubs.",
        "bug",
    ),
    (
        "Digest instead of individual reminders",
        "Let members opt into a weekly email digest to reduce notification overload.",
        "enhancement",
    ),
    (
        "Can I export only this semester?",
        "I need an attendance report for the current semester. How do I choose a date range before exporting?",
        "question",
    ),
    (
        "Keyboard navigation in the event form",
        "Please support tab navigation and visible focus indicators so the form is easier to use without a mouse.",
        "enhancement",
    ),
    (
        "Mobile event form crashes on submit",
        "On an Android phone pressing Save clears the form and shows an error. Desktop submissions work.",
        "bug",
    ),
    (
        "Understanding workspace roles",
        "What is the difference between a member and a coordinator? I want someone to manage one event only.",
        "question",
    ),
    (
        "Improve the booking experience",
        "Sometimes room booking is confusing. I would like it to be easier, but I am not sure what should change.",
        None,
    ),
    (
        "Export behavior needs investigation",
        "Could the export include cancelled registrations? Currently I cannot tell whether this is intended behavior.",
        "conflict",
    ),
    (
        "Demo: model is unavailable for this issue",
        "This synthetic example intentionally has no prediction. A reviewer can still select a category and save a decision.",
        None,
    ),
    (
        "Room capacity validation missing",
        "Booking 80 people into a room with capacity 20 succeeds. Expected a clear warning before saving.",
        "bug",
    ),
    (
        "Download event details as PDF",
        "Add a printable event summary for noticeboards, including time, location, accessibility information and contact details.",
        "enhancement",
    ),
    (
        "Can guests register without an account?",
        "Our public workshop has external participants. Is there a guest-registration option?",
        "question",
    ),
]


def seed(session):
    repo = session.scalar(select(Repository).where(Repository.full_name == "synthetic/campus-tools"))
    if repo is None:
        repo = Repository(
            github_id=-1,
            full_name="synthetic/campus-tools",
            source_url="https://github.com",
            synthetic=True,
            partial=True,
        )
        session.add(repo)
        session.flush()
    for index, (title, body, category) in enumerate(EXAMPLES, 1):
        created = datetime(2026, 7, 1, tzinfo=timezone.utc) + timedelta(days=index * 3)
        raw = {
            "id": -1000 - index,
            "number": index,
            "title": title,
            "body": body,
            "html_url": "https://github.com",
            "state": "closed" if index % 4 == 0 else "open",
            "created_at": created.isoformat(),
            "updated_at": created.isoformat(),
            "closed_at": None,
            "labels": [category]
            if category in {"bug", "enhancement", "question"}
            else (["bug", "enhancement"] if category == "conflict" else []),
        }
        upsert_issue(session, repo, raw)
        from triagedesk.models import Issue

        issue = session.scalar(select(Issue).where(Issue.github_id == raw["id"]))
        if category in {"bug", "enhancement", "question"}:
            exists = session.scalar(
                select(Prediction.id).where(
                    Prediction.snapshot_id == issue.snapshot_id,
                    Prediction.model_version == "synthetic-illustration-v1",
                )
            )
            if not exists:
                # Illustrative scores, deliberately not presented as measured model quality.
                score = 0.46 if index % 5 == 0 else 0.73
                predicted = "question" if index == 15 else category
                scores = {
                    c: (score if c == predicted else (1 - score) / 2)
                    for c in ("bug", "enhancement", "question")
                }
                session.add(
                    Prediction(
                        issue_id=issue.id,
                        snapshot_id=issue.snapshot_id,
                        category=predicted,
                        scores=scores,
                        max_score=score,
                        needs_review=score < 0.6,
                        model_version="synthetic-illustration-v1",
                        input_hash=issue.content_hash,
                    )
                )
    return {
        "repository": repo.full_name,
        "synthetic_issues": len(EXAMPLES),
        "warning": "Hand-written fixtures and illustrative scores; excluded from all reported ML metrics",
    }
