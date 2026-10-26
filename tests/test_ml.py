from datetime import datetime, timedelta, timezone

import joblib
import numpy as np
import pytest
from sklearn.metrics import f1_score

from triagedesk.dataset import chronological_split
from triagedesk.text import clean_text, label_mapping, map_labels
from triagedesk.training import choose_threshold, metrics, pipeline


def test_label_mapping_excludes_conflicts_and_does_not_invent_questions():
    mapping = label_mapping()
    assert map_labels(["bug"], "fastapi/fastapi", mapping) == ("bug", "eligible")
    assert map_labels(["BUG", "question"], "fastapi/fastapi", mapping) == (None, "conflicting")
    assert map_labels(["docs"], "fastapi/fastapi", mapping) == (None, "unsupported_or_unlabeled")
    with pytest.raises(ValueError, match="No label mapping"):
        map_labels(["bug"], "missing/mapping", mapping)


def test_template_fields_removed_but_author_words_retained():
    text = clean_text(
        "A bug in CSV export",
        "<!-- category hint -->\nIssue type: bug\n- [x] Bug report\nA bug drops the final record",
    )
    assert "Issue type" not in text and "[x]" not in text and "category hint" not in text
    assert "A bug" in text and "final record" in text


def test_chronological_boundaries_and_exact_duplicates():
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    rows = [
        {
            "issue_id": i,
            "github_id": i,
            "snapshot_id": i,
            "title": f"unique record {i}",
            "body": f"token_{i}",
            "created_at": (base + timedelta(days=i)).isoformat(),
            "category": ["bug", "enhancement", "question"][i % 3],
        }
        for i in range(100)
    ]
    rows[90].update(title=rows[0]["title"], body=rows[0]["body"])
    splits, boundaries, excluded = chronological_split(list(reversed(rows)), near_threshold=1.1)
    assert len(splits["train"]) == 70 and len(splits["test"]) == 14
    assert excluded == [
        {
            "issue_id": 90,
            "snapshot_id": 90,
            "split": "test",
            "reason": "exact_duplicate",
            "earlier_issue_id": 0,
        }
    ]
    assert boundaries["train"]["end"] < boundaries["validation"]["start"] < boundaries["test"]["start"]
    assert all(r["issue_id"] < 70 for r in splits["train"])


def test_near_duplicate_newer_text_is_excluded():
    rows = [
        {
            "issue_id": i,
            "github_id": i,
            "snapshot_id": i,
            "title": f"Unique {i}",
            "body": f"term{i} " * 30,
            "created_at": f"2020-01-{i + 1:02d}",
            "category": "bug",
        }
        for i in range(30)
    ]
    rows[-1].update(title="Unique 0!", body=rows[0]["body"])
    _, _, excluded = chronological_split(rows)
    assert any(r["issue_id"] == 29 and r["reason"] == "near_duplicate" for r in excluded)


def test_preprocessing_fits_only_training_and_model_reload_consistent(tmp_path):
    config = {"ngram_range": (1, 2), "max_features": 100, "min_df": 1, "C": 1, "class_weight": "balanced"}
    train = ["crash on saving attendance", "please add calendar theme", "how to invite a member"] * 3
    y = ["bug", "enhancement", "question"] * 3
    model = pipeline(config).fit(train, y)
    held_out = ["secretvalidationonly calendar feature"]
    original = model.predict_proba(held_out)
    assert "secretvalidationonly" not in model.named_steps["tfidf"].vocabulary_
    path = tmp_path / "trusted.joblib"
    joblib.dump(model, path)
    assert np.allclose(original, joblib.load(path).predict_proba(held_out))


def test_threshold_selection_and_all_predictions_metrics():
    y = ["bug", "bug", "enhancement", "question"] * 4
    pred = ["bug", "question", "enhancement", "question"] * 4
    scores = np.array([0.9, 0.4, 0.8, 0.8] * 4)
    threshold, details = choose_threshold(y, pred, scores)
    result = metrics(y, pred, scores, threshold)
    assert details["target_met"] and result["review_flagged_fraction"] == 0.25
    assert result["unflagged_accuracy"] == 1 and result["accuracy"] == 0.75
    assert result["macro_f1"] == f1_score(y, pred, average="macro")
