"""Serial, read-only GitHub REST client. No CLI/API path accepts arbitrary URLs."""

import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from triagedesk.config import settings
from triagedesk.models import ImportRun, Issue, Repository, Snapshot, utcnow
from triagedesk.text import content_hash, digest

REPO_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}$")


class GitHubError(RuntimeError):
    pass


def valid_repository(name):
    if not REPO_PATTERN.fullmatch(name) or name.split("/")[1] in {".", ".."}:
        raise ValueError("Use a GitHub owner/repository identifier, not a URL")
    return name.lower()


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class GitHubClient:
    def __init__(self, client=None, sleep=time.sleep, max_retries=3, max_wait=60, token=None):
        token = settings().github_token.get_secret_value() if token is None else token
        self.client = client or httpx.Client(
            base_url="https://api.github.com",
            timeout=30,
            follow_redirects=True,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "TriageDesk/0.1",
                "X-GitHub-Api-Version": settings().github_api_version,
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
        )
        self.sleep, self.max_retries, self.max_wait = sleep, max_retries, max_wait
        self.remaining = None
        self.reset_at = None

    def close(self):
        self.client.close()

    def get(self, path, params=None, etag=None):
        parsed = urlparse(path)
        if parsed.scheme and (parsed.scheme != "https" or parsed.netloc != "api.github.com"):
            raise GitHubError("Refused a non-GitHub pagination URL")
        for attempt in range(self.max_retries + 1):
            if self.remaining == 0 and self.reset_at:
                delay = max(0, self.reset_at - time.time()) + 1
                if delay > self.max_wait:
                    raise GitHubError(
                        f"GitHub rate limit exhausted; retry after {int(self.reset_at)} UTC epoch seconds"
                    )
                self.sleep(delay)
            try:
                response = self.client.get(
                    path, params=params, headers={"If-None-Match": etag} if etag else {}
                )
            except httpx.TransportError:
                if attempt == self.max_retries:
                    raise GitHubError("GitHub connection failed after bounded retries") from None
                self.sleep(2**attempt)
                continue
            if "x-ratelimit-remaining" in response.headers:
                self.remaining = int(response.headers["x-ratelimit-remaining"])
            if "x-ratelimit-reset" in response.headers:
                self.reset_at = float(response.headers["x-ratelimit-reset"])
            if response.status_code in {200, 304}:
                return response
            limited = response.status_code == 429 or (
                response.status_code == 403
                and (
                    self.remaining == 0
                    or "retry-after" in response.headers
                    or "rate limit" in response.text.lower()
                )
            )
            if limited or response.status_code >= 500:
                if attempt == self.max_retries:
                    raise GitHubError(f"GitHub returned {response.status_code}; retry budget exhausted")
                retry_after = response.headers.get("retry-after")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = max(0, parsedate_to_datetime(retry_after).timestamp() - time.time())
                elif self.remaining == 0 and self.reset_at:
                    delay = max(0, self.reset_at - time.time()) + 1
                else:
                    delay = (60 if limited else 1) * 2**attempt
                if delay > self.max_wait:
                    raise GitHubError(f"GitHub asks for a {int(delay)} second pause; retry the command later")
                self.sleep(max(0, delay))
                continue
            explanations = {
                401: "token invalid",
                403: "access denied",
                404: "repository unavailable",
                422: "invalid parameters",
            }
            raise GitHubError(
                f"GitHub {response.status_code}: {explanations.get(response.status_code, 'request failed')}"
            )
        raise GitHubError("Retry budget exhausted")

    def issue_pages(self, name, since=None, state="all", direction="asc"):
        name = valid_repository(name)
        path = f"/repos/{name}/issues"
        params = {"state": state, "sort": "updated", "direction": direction, "per_page": 100}
        if since:
            params["since"] = aware(since).isoformat().replace("+00:00", "Z")
        while path:
            response = self.get(path, params=params)
            yield response.json(), bool(response.links.get("next"))
            path = response.links.get("next", {}).get("url")
            params = None


def upsert_issue(session, repository, raw):
    if "pull_request" in raw:
        return "excluded"
    issue = session.scalar(select(Issue).where(Issue.github_id == raw["id"]))
    labels = sorted(label["name"] if isinstance(label, dict) else label for label in raw.get("labels", []))
    title, body = raw["title"], raw.get("body") or ""
    updated_at = parse_time(raw["updated_at"])
    snapshot_hash = digest([title, body, labels, updated_at.isoformat()])
    text_hash = content_hash(title, body)
    is_new = issue is None
    if issue and aware(issue.updated_at) > updated_at:
        return "unchanged"  # Never overwrite a more recent source revision with an older response.
    if is_new:
        issue = Issue(
            github_id=raw["id"],
            repository_id=repository.id,
            number=raw["number"],
            title=title,
            body=body,
            source_url=raw["html_url"],
            state=raw["state"],
            created_at=parse_time(raw["created_at"]),
            updated_at=updated_at,
            labels=labels,
            content_hash=text_hash,
        )
        session.add(issue)
        session.flush()
    old_snapshot_id = issue.snapshot_id
    snapshot = session.scalar(
        select(Snapshot).where(Snapshot.issue_id == issue.id, Snapshot.snapshot_hash == snapshot_hash)
    )
    if snapshot is None:
        snapshot = Snapshot(
            issue_id=issue.id,
            title=title,
            body=body,
            labels=labels,
            content_hash=text_hash,
            snapshot_hash=snapshot_hash,
            source_updated_at=updated_at,
        )
        session.add(snapshot)
        session.flush()
    issue.title, issue.body, issue.labels = title, body, labels
    issue.content_hash, issue.snapshot_id = text_hash, snapshot.id
    issue.updated_at, issue.state = updated_at, raw["state"]
    issue.closed_at = parse_time(raw["closed_at"]) if raw.get("closed_at") else None
    issue.available = True
    if old_snapshot_id and old_snapshot_id != snapshot.id:
        issue.review_revision += 1  # Invalidate any open review form when its source snapshot changes.
    return "imported" if is_new else ("updated" if old_snapshot_id != snapshot.id else "unchanged")


def ingest(db_engine, name, limit=2000, incremental=False, client=None, progress=None, active_only=False):
    name = valid_repository(name)
    if not 1 <= limit <= 100_000:
        raise ValueError("Import limit must be between 1 and 100000 response objects")
    own_client = client is None
    client = client or GitHubClient()
    run_id = None
    try:
        with Session(db_engine, expire_on_commit=False) as session:
            with session.begin():
                repo = session.scalar(
                    select(Repository).where(Repository.full_name == name).with_for_update()
                )
                response = client.get(f"/repos/{name}", etag=repo.meta_etag if repo else None)
                if response.status_code != 304:
                    meta = response.json()
                    if meta.get("private"):
                        raise GitHubError("Only public repositories are supported")
                    if repo is None:
                        repo = Repository(github_id=meta["id"], full_name=name, source_url=meta["html_url"])
                        session.add(repo)
                    repo.meta_etag = response.headers.get("etag")
                session.flush()
                repo_id = repo.id
                since = (
                    aware(repo.checkpoint) - timedelta(minutes=10)
                    if incremental and repo.checkpoint
                    else None
                )
                run = ImportRun(repository_id=repo_id)
                session.add(run)
                session.flush()
                run_id = run.id
            exhausted = False
            pages = (
                client.issue_pages(name, since, state="open", direction="desc")
                if active_only and not incremental
                else client.issue_pages(name, since)
            )
            for page, has_next in pages:
                with session.begin():
                    repo = session.scalar(
                        select(Repository).where(Repository.id == repo_id).with_for_update()
                    )
                    run = session.get(ImportRun, run_id)
                    selected = page[: limit - run.fetched]
                    times = []
                    for raw in selected:
                        result = upsert_issue(session, repo, raw)
                        if result != "unchanged":
                            setattr(run, result, getattr(run, result) + 1)
                        run.fetched += 1
                        times.append(parse_time(raw["updated_at"]))
                    # Atomic with the page. A failed page cannot advance this checkpoint.
                    if times:
                        repo.checkpoint = max(times + ([aware(repo.checkpoint)] if repo.checkpoint else []))
                    exhausted = not has_next and len(selected) == len(page)
                    finished = run.fetched >= limit or exhausted
                if progress:
                    progress(
                        {key: getattr(run, key) for key in ("fetched", "imported", "updated", "excluded")}
                    )
                if finished:
                    break
            with session.begin():
                repo = session.get(Repository, repo_id)
                run = session.get(ImportRun, run_id)
                # Completing a delta sync does not prove the initial corpus was complete.
                if not incremental:
                    repo.partial = not exhausted
                repo.last_synced_at = utcnow()
                run.status, run.completed_at = ("complete" if exhausted else "limited"), utcnow()
            return {
                key: getattr(run, key)
                for key in ("id", "status", "fetched", "imported", "updated", "excluded", "failed")
            }
    except Exception as exc:
        if run_id:
            with Session(db_engine) as session, session.begin():
                run = session.get(ImportRun, run_id)
                run.status, run.failed, run.completed_at = "failed", run.failed + 1, utcnow()
                run.error = (
                    str(exc)[:500]
                    if isinstance(exc, (GitHubError, ValueError))
                    else "Persistence failed; inspect server logs"
                )
        raise
    finally:
        if own_client:
            client.close()
