import json
import platform
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer
from sqlalchemy import select

from triagedesk.artifacts import safe_version, versions, write_json
from triagedesk.config import settings
from triagedesk.dataset import LIMITATION
from triagedesk.db import session_scope
from triagedesk.models import Experiment
from triagedesk.text import CATEGORIES, clean_text

SEED = 42
CONFIGURATIONS = [
    {"ngram_range": (1, 2), "max_features": 30000, "min_df": 2, "C": 1.0, "class_weight": None},
    {"ngram_range": (1, 2), "max_features": 30000, "min_df": 2, "C": 2.0, "class_weight": "balanced"},
    {"ngram_range": (1, 1), "max_features": 20000, "min_df": 1, "C": 1.0, "class_weight": "balanced"},
]


def normalize_documents(documents):
    # Persisted inside the Pipeline, so serving and evaluation use the same deterministic removal rules.
    return [clean_text("", document) for document in documents]


def pipeline(config):
    return Pipeline(
        [
            ("clean", FunctionTransformer(normalize_documents, validate=False)),
            (
                "tfidf",
                TfidfVectorizer(
                    ngram_range=config["ngram_range"],
                    max_features=config["max_features"],
                    min_df=config["min_df"],
                    sublinear_tf=True,
                    strip_accents="unicode",
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    C=config["C"], class_weight=config["class_weight"], max_iter=1000, random_state=SEED
                ),
            ),
        ]
    )


def metrics(y, predicted, scores=None, threshold=None):
    report = classification_report(y, predicted, labels=CATEGORIES, output_dict=True, zero_division=0)
    result = {
        "macro_f1": float(f1_score(y, predicted, labels=CATEGORIES, average="macro", zero_division=0)),
        "accuracy": float(accuracy_score(y, predicted)),
        "support": len(y),
        "per_class": {c: report[c] for c in CATEGORIES},
        "confusion_matrix": confusion_matrix(y, predicted, labels=CATEGORIES).tolist(),
    }
    if scores is not None and threshold is not None:
        selected = np.asarray(scores) >= threshold
        result["review_flagged_fraction"] = float((~selected).mean())
        result["unflagged_support"] = int(selected.sum())
        result["unflagged_accuracy"] = (
            float(accuracy_score(np.asarray(y)[selected], np.asarray(predicted)[selected]))
            if selected.any()
            else None
        )
        result["unflagged_macro_f1"] = (
            float(
                f1_score(
                    np.asarray(y)[selected],
                    np.asarray(predicted)[selected],
                    labels=CATEGORIES,
                    average="macro",
                    zero_division=0,
                )
            )
            if selected.any()
            else None
        )
    return result


def choose_threshold(y, predicted, scores):
    candidates = []
    for threshold in np.arange(0.35, 0.951, 0.05):
        mask = scores >= threshold
        support = int(mask.sum())
        acc = float(accuracy_score(np.asarray(y)[mask], np.asarray(predicted)[mask])) if support else 0.0
        candidates.append(
            {
                "threshold": round(float(threshold), 2),
                "coverage": float(mask.mean()),
                "unflagged_support": support,
                "unflagged_accuracy": acc,
            }
        )
    good = [c for c in candidates if c["unflagged_support"] >= 10 and c["unflagged_accuracy"] >= 0.85]
    if good:
        chosen = max(good, key=lambda c: (c["coverage"], -c["threshold"]))
    else:
        chosen = max(
            candidates, key=lambda c: (c["unflagged_accuracy"] * np.sqrt(c["coverage"]), -c["threshold"])
        )
    return chosen["threshold"], {
        "policy": "Maximize validation coverage with accuracy>=0.85 and >=10 unflagged; otherwise maximize accuracy*sqrt(coverage)",
        "candidates": candidates,
        "target_met": bool(good),
    }


def train(dataset_path, version):
    version = safe_version(version)
    data = json.loads(Path(dataset_path).read_text())
    if data.get("synthetic") is not False:
        raise ValueError("Only a frozen real-data manifest may be used for reported evaluation")
    folder = settings().artifact_dir / "models" / version
    if folder.exists():
        raise ValueError(
            "Model versions are immutable. Use a new version; do not overwrite sealed test results"
        )
    splits = data["splits"]
    for name, rows in splits.items():
        if set(row["category"] for row in rows) != set(CATEGORIES):
            raise ValueError(
                f"{name} lacks class support. Collect more data; do not move held-out records into training"
            )
    texts = {name: [f"{row['title']}\n{row['body']}" for row in rows] for name, rows in splits.items()}
    labels = {name: [row["category"] for row in rows] for name, rows in splits.items()}
    candidates = []
    for config in CONFIGURATIONS:
        model = pipeline(config).fit(texts["train"], labels["train"])
        score = f1_score(
            labels["validation"],
            model.predict(texts["validation"]),
            labels=CATEGORIES,
            average="macro",
            zero_division=0,
        )
        candidates.append((float(score), model, config))
    _, model, config = max(candidates, key=lambda candidate: candidate[0])
    val_pred = model.predict(texts["validation"])
    val_scores = model.predict_proba(texts["validation"]).max(axis=1)
    threshold, threshold_selection = choose_threshold(labels["validation"], val_pred, val_scores)
    dummy = DummyClassifier(strategy="most_frequent", random_state=SEED)
    dummy.fit(np.zeros((len(labels["train"]), 1)), labels["train"])
    # All choices above are frozen before touching the test set. No refit on validation data.
    test_pred = model.predict(texts["test"])
    test_scores = model.predict_proba(texts["test"]).max(axis=1)
    errors = []
    for row, predicted, score in zip(splits["test"], test_pred, test_scores):
        if predicted != row["category"] and Counter(e["actual"] for e in errors)[row["category"]] < 4:
            errors.append(
                {
                    "issue_id": row["issue_id"],
                    "number": row["number"],
                    "title": row["title"],
                    "source_url": row["source_url"],
                    "actual": row["category"],
                    "predicted": str(predicted),
                    "score": float(score),
                    "text_characters": len(row["title"] + row["body"]),
                }
            )
    from triagedesk.text import TYPE_FIELD

    template_rows = [i for i, text in enumerate(texts["test"]) if TYPE_FIELD.search(text)]
    no_template_rows = [i for i in range(len(texts["test"])) if i not in template_rows]
    sensitivity = {
        "explicit_template_test_count": len(template_rows),
        "without_explicit_template_count": len(no_template_rows),
    }
    if no_template_rows:
        sensitivity["without_explicit_template_macro_f1"] = float(
            f1_score(
                np.asarray(labels["test"])[no_template_rows],
                test_pred[no_template_rows],
                labels=CATEGORIES,
                average="macro",
                zero_division=0,
            )
        )
    report = {
        "model_version": version,
        "dataset_version": data["version"],
        "repository": data["repository"],
        "synthetic": False,
        "seed": SEED,
        "dependencies": versions(),
        "python": platform.python_version(),
        "config": config,
        "validation_search": [{"config": c, "macro_f1": score} for score, _, c in candidates],
        "threshold": threshold,
        "threshold_selection": threshold_selection,
        "splits": data["boundaries"],
        "validation": metrics(labels["validation"], val_pred, val_scores, threshold),
        "test": metrics(labels["test"], test_pred, test_scores, threshold),
        "baseline_test": metrics(labels["test"], dummy.predict(np.zeros((len(test_pred), 1)))),
        "exclusions": data["counts"],
        "errors": errors,
        "template_sensitivity": sensitivity,
        "limitations": [
            LIMITATION,
            "Scores have not been calibrated; label noise is not ground-truth quality",
            "One repository and one collection; no cross-project performance claim",
            "Held-out issues remain protected from future review-derived training exports",
        ],
    }
    folder.mkdir(parents=True)
    if Path("uv.lock").exists():
        import shutil

        shutil.copyfile("uv.lock", folder / "uv.lock")
    joblib.dump(model, folder / "model.joblib")
    joblib.dump(dummy, folder / "baseline.joblib")
    reloaded = joblib.load(folder / "model.joblib")
    if not np.allclose(model.predict_proba(texts["validation"]), reloaded.predict_proba(texts["validation"])):
        raise RuntimeError("Saved model did not reproduce validation predictions")
    write_json(folder / "evaluation.json", report)
    write_json(folder / "split-manifest.json", data)
    write_json(folder / "category-mapping.json", data["mapping"])
    (folder / "MODEL_CARD.md").write_text(
        f"# {version}\n\nTitle/body-only TF-IDF + logistic regression; no labels or metadata as features.\n\n"
        f"Dataset: {data['version']}. Seed: {SEED}. Validation-selected threshold: {threshold}.\n\n"
        f"Test macro-F1: {report['test']['macro_f1']:.4f}; majority baseline: {report['baseline_test']['macro_f1']:.4f}.\n\n"
        f"{LIMITATION}\n\nScores are uncalibrated. See evaluation.json for support, coverage, errors and dependencies. "
        "Never load untrusted joblib files. Future training is explicit and must preserve held-out issue exclusions.\n"
    )
    with session_scope() as session:
        if session.scalar(select(Experiment.id).where(Experiment.version == version)):
            raise ValueError("Experiment version already exists")
        session.add(
            Experiment(
                version=version,
                dataset_version=data["version"],
                config=config,
                splits=data["boundaries"],
                metrics=report,
                artifact_path=str(folder),
            )
        )
    return {
        "version": version,
        "artifact_path": str(folder),
        "test": report["test"],
        "baseline_test": report["baseline_test"],
        "threshold": threshold,
        "status": "evaluated, saved and reload-verified; run activate to serve",
    }
