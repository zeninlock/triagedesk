import json
import re
from collections import Counter

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sqlalchemy import func, select

from triagedesk.artifacts import dataset_version, write_json
from triagedesk.config import settings
from triagedesk.models import Issue, Repository, Review, Snapshot, utcnow
from triagedesk.text import clean_text, label_mapping, map_labels

LIMITATION = (
    "Chronological retrospective evaluation using collected snapshots. Historical issue text and labels may "
    "have been edited or assigned after creation; training-label availability at the cutoff is not established."
)


def chronological_split(rows, near_threshold=0.94):
    rows = sorted(rows, key=lambda row: (row["created_at"], row["github_id"]))
    n = len(rows)
    if n < 30:
        raise ValueError("Need at least 30 eligible real issues for a meaningful chronological split")
    cut1, cut2 = int(n * 0.70), int(n * 0.85)
    split_names = ["train" if i < cut1 else "validation" if i < cut2 else "test" for i in range(n)]
    texts = [re.sub(r"\s+", " ", clean_text(row["title"], row["body"]).lower()).strip() for row in rows]
    # Stateless hashing is used for duplicate detection only; it learns no vocabulary from held-out text.
    hasher = HashingVectorizer(
        analyzer="char_wb", ngram_range=(3, 5), n_features=2**18, alternate_sign=False, norm="l2"
    )
    vectors = hasher.transform(texts)
    exact, kept, excluded = {}, {"train": [], "validation": [], "test": []}, []
    for i, row in enumerate(rows):
        reason, earlier = None, None
        if texts[i] in exact:
            reason, earlier = "exact_duplicate", exact[texts[i]]
        elif i and len(texts[i]) >= 80:
            scores = (vectors[:i] @ vectors[i].T).toarray().ravel()
            candidate = int(np.argmax(scores))
            if scores[candidate] >= near_threshold:
                reason, earlier = "near_duplicate", candidate
        if reason:
            excluded.append(
                {
                    "issue_id": row["issue_id"],
                    "snapshot_id": row["snapshot_id"],
                    "split": split_names[i],
                    "reason": reason,
                    "earlier_issue_id": rows[earlier]["issue_id"],
                }
            )
        else:
            kept[split_names[i]].append(row)
        exact.setdefault(
            texts[i], i
        )  # Earliest occurrence always wins; never move newer reports into training.
    boundaries = {
        name: {
            "start": rows[lo]["created_at"],
            "end": rows[hi - 1]["created_at"],
            "before_deduplication": hi - lo,
            "after_deduplication": len(kept[name]),
            "class_support": dict(Counter(row["category"] for row in kept[name])),
        }
        for name, lo, hi in [("train", 0, cut1), ("validation", cut1, cut2), ("test", cut2, n)]
    }
    return kept, boundaries, excluded


def prepare_dataset(session, repository_name, mapping_path, out):
    mapping = label_mapping(mapping_path)
    repo = session.scalar(select(Repository).where(Repository.full_name == repository_name.lower()))
    if repo is None or repo.synthetic:
        raise ValueError("Choose an imported real repository; fixtures are forbidden in reported evaluation")
    records = session.execute(
        select(Issue, Snapshot)
        .join(Snapshot, Snapshot.id == Issue.snapshot_id)
        .where(Issue.repository_id == repo.id, Issue.available.is_(True))
        .order_by(Issue.created_at, Issue.github_id)
    ).all()
    rows, counts = [], Counter()
    template_fields = 0
    for issue, snapshot in records:
        category, status = map_labels(snapshot.labels, repo.full_name, mapping)
        counts[status] += 1
        if category is None:
            continue
        text = clean_text(snapshot.title, snapshot.body)
        if len(text) < 20:
            counts["too_short"] += 1
            continue
        from triagedesk.text import TYPE_FIELD

        template_fields += bool(TYPE_FIELD.search(f"{snapshot.title}\n{snapshot.body}"))
        rows.append(
            {
                "issue_id": issue.id,
                "github_id": issue.github_id,
                "number": issue.number,
                "snapshot_id": snapshot.id,
                "content_hash": snapshot.content_hash,
                "title": snapshot.title,
                "body": snapshot.body,
                "category": category,
                "created_at": issue.created_at.isoformat(),
                "source_updated_at": snapshot.source_updated_at.isoformat(),
                "collected_at": snapshot.collected_at.isoformat(),
                "source_url": issue.source_url,
            }
        )
    splits, boundaries, duplicates = chronological_split(rows)
    version = dataset_version(rows, mapping["version"])
    report = {
        "version": version,
        "repository": repo.full_name,
        "synthetic": False,
        "collected_at": utcnow(),
        "mapping": mapping,
        "counts": {
            "imported_available": len(records),
            **dict(counts),
            "eligible_before_deduplication": len(rows),
            "duplicates_excluded": len(duplicates),
            "eligible_after_deduplication": sum(map(len, splits.values())),
            "explicit_type_fields_removed": template_fields,
        },
        "class_support_before_deduplication": dict(Counter(row["category"] for row in rows)),
        "boundaries": boundaries,
        "splits": splits,
        "duplicates": duplicates,
        "duplicate_policy": "Preserve 70/15/15 boundaries; earliest exact/char-hash cosine>=0.94 text kept; later duplicate removed",
        "text_policy": "clean-v1: remove HTML comments and explicit inline type/category declarations or type checkboxes; keep narrative words",
        "limitations": [
            LIMITATION,
            "English-language suitability is audited by sample, not automatically guaranteed",
            "Template cleaning is narrow; sensitivity metrics and manual error inspection are needed",
        ],
    }
    write_json(out, report)
    return {key: report[key] for key in ["version", "repository", "counts", "boundaries", "limitations"]}


def reviewed_dataset(session, out):
    """Export future labels deliberately; never recycle any existing held-out issue or its later reviews."""
    protected = set()
    for path in (settings().artifact_dir / "models").glob("*/split-manifest.json"):
        manifest = json.loads(path.read_text())
        for name in ("validation", "test"):
            protected.update(row["github_id"] for row in manifest["splits"][name])
    latest = select(func.max(Review.id)).group_by(Review.issue_id)
    reviews = session.execute(
        select(Review, Issue, Snapshot)
        .join(Issue, Issue.id == Review.issue_id)
        .join(Snapshot, Snapshot.id == Review.snapshot_id)
        .join(Repository, Repository.id == Issue.repository_id)
        .where(
            Review.id.in_(latest),
            Review.action.in_(["accept", "correct"]),
            Review.snapshot_id == Issue.snapshot_id,
            Repository.synthetic.is_(False),
        )
    ).all()
    rows = [
        {
            "issue_id": issue.id,
            "snapshot_id": snapshot.id,
            "review_id": review.id,
            "category": review.category,
            "title": snapshot.title,
            "body": snapshot.body,
            "created_at": issue.created_at.isoformat(),
            "reviewed_at": review.created_at.isoformat(),
        }
        for review, issue, snapshot in reviews
        if issue.github_id not in protected
    ]
    result = {
        "purpose": "Candidate labels for a future separately versioned training dataset; not automatically trained",
        "excluded_held_out_issue_count": len(
            {issue.id for _, issue, _ in reviews if issue.github_id in protected}
        ),
        "rows": rows,
        "training_requires_new_frozen_splits": True,
    }
    write_json(out, result)
    return {"out": out, "eligible_reviews": len(rows), "protected_held_out_issues": len(protected)}
