import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_ai_labels import proposed, repo_issues

from triagedesk import ai_labels, triage
from triagedesk.config import settings
from triagedesk.models import Issue, LabelAnalysis, Repository
from triagedesk.text import digest


def wire_result(label_id="type:1", evidence_id="source:0", confidence=0.95):
    return {
        "summary": "The report requests an improvement.",
        "explanation": "The supplied excerpt describes the requested change.",
        "labels": [{"label_id": label_id, "confidence": confidence, "evidence_id": evidence_id}],
        "confidence": confidence,
        "uncertain": False,
    }


@pytest.mark.parametrize(
    "title,label_id,label_name",
    [
        ("Add a shared evaluation script and model comparison table", "type:1", "enhancement"),
        ("Document dataset shapes, label mapping, and preprocessing", "type:2", "documentation"),
        ("Set and document seeds for augmentation and model training", "type:1", "enhancement"),
    ],
)
def test_high_confidence_reference_labels_are_retained_without_a_generated_quote(
    monkeypatch, title, label_id, label_name
):
    monkeypatch.setenv("GROQ_API_KEY", "dummy-key")
    settings.cache_clear()

    def provider(request):
        payload = json.loads(request.content)
        schema = payload["response_format"]["json_schema"]
        props = schema["schema"]["$defs"]["ReferencedLabel"]["properties"]
        assert schema["strict"] and label_id in props["label_id"]["enum"]
        assert "source:0" in props["evidence_id"]["enum"]
        assert "evidence" not in props and "group" not in props and "name" not in props
        data = json.loads(payload["messages"][1]["content"])
        assert data["source_excerpts"][0]["text"] == title
        assert "dummy-key" not in request.content.decode()
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(wire_result(label_id))}}]}
        )

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        result = ai_labels.request_analysis(
            title, "Please implement this change.", [], ai_labels.DEFAULT_TAXONOMY, client
        )
    assert not result.uncertain and not result._validation_flags
    assert result.confidence == 0.95
    assert result.labels[0].name == label_name and result.labels[0].evidence == title


def test_live_playground_response_maps_to_exact_excerpt_and_auto_sort_confidence(monkeypatch):
    """Replay the observed #4 label/reference tuple; no new live model request."""
    monkeypatch.setenv("GROQ_API_KEY", "dummy-key")
    settings.cache_clear()
    title = "Add a shared evaluation script and model comparison table"
    body = "Please add one evaluation command for all saved model checkpoints."
    value = wire_result("type:1", "source:1", 0.95)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})
    )
    with httpx.Client(transport=transport) as client:
        result = ai_labels.request_analysis(title, body, [], ai_labels.DEFAULT_TAXONOMY, client)
    assert result.labels[0].name == "enhancement" and result.labels[0].evidence == body
    assert not result.uncertain and result.confidence >= settings().ai_confidence_threshold


@pytest.mark.parametrize(
    "label_id,evidence_id,reason",
    [
        ("unknown:999", "source:0", "unsupported_label_id"),
        ("type:1", "source:999", "unknown_evidence_id"),
    ],
)
def test_invalid_references_are_never_auto_published(monkeypatch, label_id, evidence_id, reason):
    monkeypatch.setenv("GROQ_API_KEY", "dummy-key")
    settings.cache_clear()
    value = wire_result(label_id, evidence_id)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(value)}}]}
            )
        )
    ) as client:
        result = ai_labels.request_analysis(
            "Add an export option", "Please add CSV export.", [], ai_labels.DEFAULT_TAXONOMY, client
        )
    assert result.uncertain and result.labels == [] and reason in result._validation_flags


def test_source_excerpts_are_bounded_and_custom_labels_use_exact_configured_names():
    taxonomy = {**ai_labels.DEFAULT_TAXONOMY, "type": ["Incident", "Improvement"]}
    options, sources = ai_labels.analysis_context("A" * 600, "B" * 12000, ["tag"] * 60, taxonomy)
    assert options["type:0"]["name"] == "Incident"
    assert all(len(source["text"]) <= 300 for source in sources.values())
    assert sum(len(source["text"]) for source in sources.values() if source["field"] == "title") == 500
    assert sum(len(source["text"]) for source in sources.values() if source["field"] == "body") == 10000
    assert sum(source["field"] == "github_label" for source in sources.values()) == 50


@pytest.mark.parametrize(
    "engine_fixture", ["database", pytest.param("postgres_database", marks=pytest.mark.postgres)]
)
def test_upgrade_reprocesses_empty_rejected_results_and_reuses_valid_legacy_cache(
    request, engine_fixture, monkeypatch
):
    database = request.getfixturevalue(engine_fixture)
    repo_id, ids = repo_issues(database)
    monkeypatch.setenv("GROQ_API_KEY", "dummy-key")
    settings.cache_clear()
    with Session(database) as db:
        repo = db.get(Repository, repo_id)
        old_key = digest([ai_labels.LEGACY_PROMPT_VERSION, settings().ai_model, ai_labels.taxonomy_for(repo)])
        for index, issue_id in enumerate(ids):
            issue = db.get(Issue, issue_id)
            old = proposed()
            db.add(
                LabelAnalysis(
                    issue_id=issue.id,
                    snapshot_id=issue.snapshot_id,
                    analyzer_key=old_key,
                    model=settings().ai_model,
                    status="complete",
                    labels=[] if index == 0 else old["labels"],
                    summary=old["summary"],
                    confidence=0.95 if index == 0 else old["confidence"],
                    uncertain=index == 0,
                    explanation="Validation needs review: unverified_evidence."
                    if index == 0
                    else old["explanation"],
                )
            )
        db.commit()
    original, calls = ai_labels.request_analysis, []

    def provider(request):
        calls.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(wire_result("type:0"))}}]}
        )

    def infer(*args):
        with httpx.Client(transport=httpx.MockTransport(provider)) as client:
            return original(*args, client=client)

    monkeypatch.setattr(ai_labels, "request_analysis", infer)
    result = ai_labels.analyze_repository(database, repo_id)
    assert result["analyzed"] == 1 and result["cached"] == 1
    for _ in range(3):
        assert ai_labels.analyze_repository(database, repo_id)["cached"] == 2
    assert len(calls) == 1
    with Session(database) as db:
        info = triage.summary(db, db.get(Repository, repo_id))
        assert info["counts"] == {"auto_sorted": 2, "needs_review": 0, "reviewed": 0, "pending": 0}
        assert len(list(db.scalars(select(LabelAnalysis)))) == 4  # Old records remain available.
