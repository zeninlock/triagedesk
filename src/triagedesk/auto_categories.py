"""Categorize real imports with explicit provenance; never invent ML probabilities."""

import re
from collections import Counter

from sqlalchemy import select

from triagedesk.models import Issue, Prediction
from triagedesk.serving import classify_text, current_model
from triagedesk.text import clean_text

LABELS = {
    "bug": {"bug", "type:bug", "type/bug", "kind/bug", "defect"},
    "enhancement": {"enhancement", "feature-request", "feature request", "type:enhancement", "kind/feature"},
    "question": {"question", "*question", "type:question", "kind/question"},
}
RULES = {
    "bug": re.compile(
        r"\b(crash(?:es|ing|ed)?|regression|exception|traceback|broken|fails?|does(?:n't| not) work|incorrect|error)\b",
        re.I,
    ),
    "enhancement": re.compile(
        r"\b(feature request|please add|add support|would like|new feature|enhancement|implement|it would be nice)\b",
        re.I,
    ),
    "question": re.compile(
        r"\b(how (?:do|can|to|should)|is there a way|where (?:can|do)|what (?:is|does)|could someone explain|question)\b",
        re.I,
    ),
}


def fallback(title, body, labels):
    names = {str(label).strip().casefold() for label in labels}
    matches = [category for category, alternatives in LABELS.items() if names & alternatives]
    if len(matches) == 1:
        return {
            "category": matches[0],
            "method": "source_label",
            "model_version": "github-labels-v1",
            "explanation": "Suggested from an existing GitHub category label. Confirm or correct it locally.",
        }
    text = clean_text(title, body)
    votes = {category: len(rule.findall(text)) for category, rule in RULES.items()}
    ordered = sorted(votes, key=votes.get, reverse=True)
    if not votes[ordered[0]] or votes[ordered[0]] == votes[ordered[1]]:
        return None
    return {
        "category": ordered[0],
        "method": "rules",
        "model_version": "text-rules-v1",
        "explanation": "Unscored keyword-rule suggestion; this is not a trained-model prediction. Human review is required.",
    }


def categorize(session, repository):
    try:
        _, report = current_model()
        use_model = report["repository"].casefold() == repository.full_name.casefold()
    except (ValueError, RuntimeError, FileNotFoundError, KeyError, OSError):
        use_model = False
    result = {"categorized": 0, "needs_manual_category": 0, "categories": {}, "methods": {}}
    categories, methods = Counter(), Counter()
    issues = session.scalars(
        select(Issue)
        .where(Issue.repository_id == repository.id, Issue.available.is_(True))
        .order_by(Issue.id)
    )
    for issue in issues:
        suggestion = None
        if use_model:
            output = classify_text(issue.title, issue.body)
            if output["available"]:
                suggestion = {
                    **{
                        key: output[key]
                        for key in ["category", "scores", "max_score", "needs_review", "model_version"]
                    },
                    "method": "trained_model",
                    "explanation": "Trained classifier evaluated on this repository; scores are uncalibrated.",
                }
        if suggestion is None:
            suggestion = fallback(issue.title, issue.body, issue.labels)
        if suggestion is None:
            result["needs_manual_category"] += 1
            continue
        categories[suggestion["category"]] += 1
        methods[suggestion["method"]] += 1
        result["categorized"] += 1
        existing = session.scalar(
            select(Prediction.id).where(
                Prediction.snapshot_id == issue.snapshot_id,
                Prediction.model_version == suggestion["model_version"],
            )
        )
        if existing is None:
            values = {"scores": {}, "max_score": 0.0, "needs_review": True, **suggestion}
            session.add(
                Prediction(
                    issue_id=issue.id,
                    snapshot_id=issue.snapshot_id,
                    input_hash=issue.content_hash,
                    **values,
                )
            )
    result["categories"], result["methods"] = dict(categories), dict(methods)
    session.commit()
    return result
