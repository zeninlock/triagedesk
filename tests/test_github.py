from datetime import timedelta

import httpx
import pytest
from conftest import raw_issue
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from triagedesk.github import GitHubClient, GitHubError, ingest, upsert_issue, valid_repository
from triagedesk.models import ImportRun, Issue, Repository, Snapshot


def make_client(handler, sleeps=None):
    return GitHubClient(
        httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com"),
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
    )


def handler_for_issues(request):
    if request.url.path == "/repos/example/project":
        return httpx.Response(
            200,
            json={"id": 99, "html_url": "https://github.com/example/project", "private": False},
            headers={"etag": "meta-v1"},
        )
    if request.url.params.get("page") == "2":
        return httpx.Response(200, json=[raw_issue(2, day=2)])
    pr = {**raw_issue(3, day=1), "pull_request": {"url": "https://api.github.com/pulls/3"}}
    return httpx.Response(
        200,
        json=[raw_issue(1), pr],
        headers={"link": '<https://api.github.com/repos/example/project/issues?page=2>; rel="next"'},
    )


def test_pagination_pr_exclusion_idempotence_and_sync(database):
    calls = []

    def handler(request):
        calls.append(request)
        return handler_for_issues(request)

    client = make_client(handler)
    first = ingest(database, "example/project", client=client)
    second = ingest(database, "example/project", client=client)
    delta = ingest(database, "example/project", incremental=True, client=client)
    assert first["imported"] == 2 and first["excluded"] == 1
    assert second["imported"] == 0 and second["updated"] == 0
    assert delta["status"] == "complete"
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(Issue)) == 2
        assert session.scalar(select(func.count()).select_from(Snapshot)) == 2
        repo = session.scalar(select(Repository))
        assert repo.checkpoint.day == 3 and repo.last_synced_at is not None
    sync_call = [c for c in calls if c.url.params.get("since")][0]
    assert "2019" not in sync_call.url.params["since"]
    assert sync_call.url.params["state"] == "all" and sync_call.url.params["direction"] == "asc"
    assert any(c.headers.get("if-none-match") == "meta-v1" for c in calls)


def test_checkpoint_only_advances_after_persistence(database):
    def broken(request):
        if request.url.params.get("page") == "2":
            bad = raw_issue(2, day=2)
            bad["state"] = "invalid"
            return httpx.Response(200, json=[bad])
        return handler_for_issues(request)

    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        ingest(database, "example/project", client=make_client(broken))
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(Issue)) == 1
        assert session.scalar(select(Repository)).checkpoint.day == 2  # First page PR update time persisted.
        run = session.scalar(select(ImportRun))
        assert run.status == "failed" and run.failed == 1


def test_limit_does_not_mark_partial_import_complete(database):
    result = ingest(database, "example/project", limit=1, client=make_client(handler_for_issues))
    assert result["status"] == "limited"
    with Session(database) as session:
        assert session.scalar(select(Repository)).partial


def test_snapshots_survive_text_and_label_updates(database):
    with Session(database) as session, session.begin():
        repo = Repository(
            github_id=1, full_name="example/project", source_url="https://github.com/example/project"
        )
        session.add(repo)
        session.flush()
        raw = raw_issue()
        upsert_issue(session, repo, raw)
        issue = session.scalar(select(Issue))
        original = session.get(Snapshot, issue.snapshot_id)
        raw["body"] = "Changed content"
        raw["labels"] = [{"name": "enhancement"}]
        raw["updated_at"] = (issue.updated_at + timedelta(days=1)).isoformat()
        assert upsert_issue(session, repo, raw) == "updated"
        assert original.body != issue.body and original.labels == ["bug"]
        assert original.id != issue.snapshot_id and issue.review_revision == 1
        assert session.scalar(select(func.count()).select_from(Snapshot)) == 2


@pytest.mark.parametrize("status", [401, 404, 422])
def test_selected_api_failures_have_safe_messages(status):
    with pytest.raises(GitHubError, match=str(status)):
        make_client(lambda _: httpx.Response(status, text="private diagnostics")).get(
            "/repos/example/project"
        )


def test_rate_limit_retry_after_and_bounded_server_retries():
    responses = [
        httpx.Response(429, headers={"retry-after": "2"}),
        httpx.Response(503),
        httpx.Response(200, json=[]),
    ]
    sleeps = []
    client = make_client(lambda _: responses.pop(0), sleeps)
    assert client.get("/issues").status_code == 200
    assert sleeps == [2, 2]
    with pytest.raises(GitHubError, match="pause"):
        make_client(lambda _: httpx.Response(403, headers={"retry-after": "3600"})).get("/issues")


def test_rate_limit_reset_header_does_not_retry_early():
    import time

    sleeps = []
    client = make_client(
        lambda _: httpx.Response(
            403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(time.time()) + 3600)}
        ),
        sleeps,
    )
    with pytest.raises(GitHubError):
        client.get("/issues")
    assert sleeps == []


def test_etag_not_modified_supported():
    client = make_client(
        lambda r: httpx.Response(304) if r.headers["if-none-match"] == "known" else httpx.Response(200)
    )
    assert client.get("/repos/example/project", etag="known").status_code == 304


@pytest.mark.parametrize("value", ["https://github.com/a/b", "a/b/extra", "a/..", "a/b?token=bad", "../repo"])
def test_repository_validation_rejects_urls(value):
    with pytest.raises(ValueError):
        valid_repository(value)


def test_untrusted_pagination_host_rejected():
    with pytest.raises(GitHubError, match="non-GitHub"):
        make_client(lambda _: httpx.Response(200)).get("https://example.com/steal-token")
