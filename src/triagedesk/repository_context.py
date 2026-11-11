"""Bounded, commit-pinned source retrieval. Nothing from a repository is executed."""

import base64
import binascii
import re
import time
from pathlib import PurePosixPath
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from triagedesk.github import GitHubError, valid_repository
from triagedesk.models import RepositoryContext

MAX_FILE_BYTES = 100_000
MAX_FETCH_FILES = 10
MAX_EXCERPTS = 10
MAX_EXCERPT_CHARS = 2400
MAX_TREE_PATHS = 20_000
MAX_CACHED_FILES = 64
SHA = re.compile(r"^[a-f0-9]{40}$")
EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".php",
    ".c",
    ".cpp",
    ".h",
    ".cs",
    ".swift",
    ".kt",
    ".vue",
    ".svelte",
    ".sql",
    ".sh",
    ".md",
    ".mdx",
    ".rst",
    ".txt",
    ".toml",
    ".json",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
}
EXCLUDED = {
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "coverage",
    ".next",
    "site-packages",
    "datasets",
    "checkpoints",
}
STOP_WORDS = set(
    "the a an this that these those is are was were be been being to of for from with without "
    "in on at and or not it its as by when then than but if can could would should have has had "
    "will do does did issue bug error fails failed failure please expected actual steps reproduce "
    "using use get got all some any after before app application project file files line code".split()
)


def terms(text):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return set(re.findall(r"[a-z][a-z0-9]{2,}", text.lower())) - STOP_WORDS


def source_kind(path):
    p = PurePosixPath(path)
    name = p.name.lower()
    if p.suffix.lower() in {".md", ".mdx", ".rst", ".txt"}:
        return "documentation"
    if (
        "test" in p.parts
        or "tests" in p.parts
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    ):
        return "test"
    if p.suffix.lower() in {".toml", ".json", ".yaml", ".yml", ".ini", ".cfg"}:
        return "configuration"
    if name in {"makefile", "dockerfile"}:
        return "configuration"
    return "code"


def eligible(entry):
    path = entry.get("path", "")
    p = PurePosixPath(path)
    name = p.name.lower()
    return (
        entry.get("type") == "blob"
        and entry.get("mode") in {"100644", "100755"}  # Never follow symlinks or submodules.
        and isinstance(entry.get("size"), int)
        and 0 < entry["size"] <= MAX_FILE_BYTES
        and bool(SHA.fullmatch(entry.get("sha", "")))
        and not p.is_absolute()
        and ".." not in p.parts
        and not any(part.lower() in EXCLUDED for part in p.parts)
        and not any(part.lower().startswith(".env") for part in p.parts)
        and not any(word in name for word in ("secret", "credential", ".min.", ".map"))
        and not name.endswith(".lock")
        and name not in {"package-lock.json", "pnpm-lock.yaml", "poetry.lock"}
        and (p.suffix.lower() in EXTENSIONS or name in {"makefile", "dockerfile"})
    )


def candidate_files(tree, title, body):
    title_terms, body_terms = terms(title[:500]), terms(body[:10000])
    scored, anchors = [], []
    for entry in tree:
        if not eligible(entry):
            continue
        path = entry["path"]
        name = PurePosixPath(path).name.lower()
        tokens = terms(path.replace("_", " ").replace("/", " "))
        score = len(tokens & title_terms) * 5 + len(tokens & body_terms) * 2
        if path.lower() in (title + " " + body).lower():
            score += 20
        if name in {
            "readme.md",
            "readme.rst",
            "contributing.md",
            "contributing.rst",
            "pyproject.toml",
            "package.json",
            "makefile",
        }:
            anchors.append((len(PurePosixPath(path).parts), path, entry))
        if score:
            scored.append((score, path, entry))
    ranked = sorted(scored, key=lambda x: (-x[0], x[1]))
    # Reserve context for both contribution instructions and issue-specific code/tests.
    chosen = [x[2] for x in sorted(anchors)[:3]]
    for _, _, entry in ranked:
        if entry not in chosen and len(chosen) < MAX_FETCH_FILES - 2:
            chosen.append(entry)
    stems = {
        PurePosixPath(x["path"]).stem.replace("test_", "") for x in chosen if source_kind(x["path"]) == "code"
    }
    related_tests = [
        x
        for x in tree
        if eligible(x)
        and source_kind(x["path"]) == "test"
        and any(stem in PurePosixPath(x["path"]).stem for stem in stems if len(stem) > 2)
    ]
    for entry in sorted(related_tests, key=lambda x: x["path"]) + [x[2] for x in ranked]:
        if entry not in chosen and len(chosen) < MAX_FETCH_FILES:
            chosen.append(entry)
    return chosen


def excerpt(path, blob_sha, content, query, source_id):
    lines = content.splitlines()
    if not lines:
        return None
    scores = [len(terms(line[:1500]) & query) for line in lines]
    center = max(range(len(lines)), key=lambda i: scores[i]) if any(scores) else 0
    start = max(0, center - 10)
    end = min(len(lines), start + 45)
    while end > start and len("\n".join(lines[start:end])) > MAX_EXCERPT_CHARS:
        if start < center:
            start += 1
        else:
            end -= 1
    if end == start:
        return None  # Do not fabricate partial lines for minified/generated content.
    return {
        "id": source_id,
        "kind": source_kind(path),
        "path": path,
        "blob_sha": blob_sha,
        "start_line": start + 1,
        "end_line": end,
        "text": "\n".join(lines[start:end]),
    }


def repository_context(engine, client, repository_id, name, github_id, title, body, metadata):
    """Fetch at most ten text blobs. Persist the commit's index and bounded source cache."""
    name = valid_repository(name)
    if metadata.get("id") != github_id or metadata.get("private") is not False:
        raise GitHubError("Repository identity or visibility changed")
    if str(metadata.get("full_name", "")).lower() != name:
        raise GitHubError("Repository was renamed; reconnect it")
    deadline = time.monotonic() + 120
    branch = metadata.get("default_branch")
    if not isinstance(branch, str) or not branch:
        raise GitHubError("Repository has no default branch")
    commit = client.get(f"/repos/{name}/commits/{quote(branch, safe='')}", max_bytes=1_000_000).json()
    sha = commit.get("sha", "")
    tree_sha = commit.get("commit", {}).get("tree", {}).get("sha", "")
    if not SHA.fullmatch(sha) or not SHA.fullmatch(tree_sha):
        raise GitHubError("Repository has no readable commit")
    with Session(engine) as db:
        cached = db.scalar(
            select(RepositoryContext).where(
                RepositoryContext.repository_id == repository_id,
                RepositoryContext.commit_sha == sha,
            )
        )
        if cached:
            tree, files, partial = cached.tree, cached.files, cached.partial
        else:
            tree = None
    if tree is None:
        raw = client.get(
            f"/repos/{name}/git/trees/{tree_sha}", params={"recursive": "1"}, max_bytes=8_000_000
        ).json()
        entries = raw.get("tree")
        if not isinstance(entries, list):
            raise GitHubError("GitHub returned an incomplete file index")
        partial = bool(raw.get("truncated")) or len(entries) > MAX_TREE_PATHS
        tree = [
            {k: x[k] for k in ("path", "sha", "size", "type", "mode") if k in x}
            for x in entries[:MAX_TREE_PATHS]
            if isinstance(x, dict)
        ]
        files = {}
        with Session(engine) as db:
            db.add(
                RepositoryContext(
                    repository_id=repository_id, commit_sha=sha, tree=tree, files={}, partial=partial
                )
            )
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
    selected = candidate_files(tree, title, body)
    sources, additions = [], {}
    query = terms(title[:500] + " " + body[:10000]) | {"install", "setup", "test"}
    for entry in selected:
        if time.monotonic() >= deadline:
            partial = True
            break
        blob_sha = entry["sha"]
        content = files.get(blob_sha)
        if content is None:
            try:
                raw = client.get(f"/repos/{name}/git/blobs/{blob_sha}", max_bytes=160_000).json()
                if raw.get("encoding") != "base64" or raw.get("sha") != blob_sha:
                    partial = True
                    continue
                data = base64.b64decode(raw.get("content", "").replace("\n", ""), validate=True)
                if len(data) > MAX_FILE_BYTES or b"\x00" in data:
                    partial = True
                    continue
                content = data.decode("utf-8")
                additions[blob_sha] = content
            except (UnicodeError, binascii.Error, ValueError):
                partial = True
                continue
        item = excerpt(entry["path"], blob_sha, content, query, f"source_{len(sources) + 1}")
        if item:
            sources.append(item)
    if additions:
        with Session(engine) as db:
            cached = db.scalar(
                select(RepositoryContext)
                .where(
                    RepositoryContext.repository_id == repository_id,
                    RepositoryContext.commit_sha == sha,
                )
                .with_for_update()
            )
            combined = {**cached.files, **additions}
            cached.files = dict(list(combined.items())[-MAX_CACHED_FILES:])
            db.commit()
    partial = partial or len(title) > 500 or len(body) > 10000
    return sha, sources[:MAX_EXCERPTS], partial
