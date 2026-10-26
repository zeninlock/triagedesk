import importlib.metadata
import json
from functools import lru_cache
from pathlib import Path

import joblib

from triagedesk.artifacts import file_hash, safe_version, write_json
from triagedesk.config import settings


@lru_cache(maxsize=2)
def _load(root, stamp):
    # Only owner-managed artifacts inside ARTIFACT_DIR. No upload/deserialization endpoint exists.
    root = Path(root)
    manifest = json.loads((root / "active.json").read_text())
    version = safe_version(manifest["version"])
    folder = root / "models" / version
    metadata = json.loads((folder / "evaluation.json").read_text())
    if metadata["dependencies"]["scikit-learn"] != importlib.metadata.version("scikit-learn"):
        raise ValueError("The classifier dependency version differs; rebuild with the locked environment")
    if file_hash(folder / "model.joblib") != manifest["sha256"]:
        raise ValueError("The classifier checksum does not match its activation manifest")
    return joblib.load(folder / "model.joblib"), metadata


def current_model():
    root = settings().artifact_dir.resolve()
    active = root / "active.json"
    if not active.exists():
        raise FileNotFoundError(
            "No active classifier; import real issues, train, evaluate, and activate an artifact"
        )
    return _load(str(root), active.stat().st_mtime_ns)


def activate(version):
    root = settings().artifact_dir
    folder = root / "models" / safe_version(version)
    report = json.loads((folder / "evaluation.json").read_text())
    if report.get("synthetic"):
        raise ValueError("Cannot activate synthetic evaluation artifacts")
    from sqlalchemy import select

    from triagedesk.db import session_scope
    from triagedesk.models import Experiment

    with session_scope() as session:
        experiment = session.scalar(select(Experiment).where(Experiment.version == version))
        if experiment is None:
            session.add(
                Experiment(
                    version=version,
                    dataset_version=report["dataset_version"],
                    config=report["config"],
                    splits=report["splits"],
                    metrics=report,
                    artifact_path=str(folder),
                )
            )
        elif experiment.dataset_version != report["dataset_version"]:
            raise ValueError("Registered model version refers to a different dataset")
        else:
            experiment.artifact_path = str(folder)
    write_json(root / "active.json", {"version": version, "sha256": file_hash(folder / "model.joblib")})
    _load.cache_clear()
    return {"active": version}


def classify_text(title, body):
    if settings().mode == "fixture":
        return {
            "available": False,
            "reason": "Fixture scores illustrate saved suggestions only. Train a real-data classifier to classify new text.",
        }
    try:
        model, report = current_model()
        scores = model.predict_proba([f"{title}\n{body}"])[0]
        best = int(scores.argmax())
        return {
            "available": True,
            "category": str(model.classes_[best]),
            "scores": {str(c): float(score) for c, score in zip(model.classes_, scores)},
            "max_score": float(scores[best]),
            "needs_review": bool(scores[best] < report["threshold"]),
            "model_version": report["model_version"],
        }
    except (FileNotFoundError, ValueError, KeyError, OSError):
        return {
            "available": False,
            "reason": "Classifier unavailable or incompatible. Run the documented training and activation commands.",
        }


def model_metadata():
    root = settings().artifact_dir
    result = {"classification": None, "retrieval": None, "benchmark": None}
    if settings().mode == "fixture":
        result["status"] = (
            "Synthetic demonstration only. Fixture suggestions are illustrative; no classification quality is reported."
        )
    else:
        try:
            _, result["classification"] = current_model()
            result["status"] = "Chronological retrospective evaluation using collected real issue snapshots"
        except (FileNotFoundError, ValueError, KeyError, OSError):
            result["status"] = "No compatible active classifier. Evaluation is unavailable."
        path = root / "retrieval-evaluation.json"
        if path.exists():
            result["retrieval"] = json.loads(path.read_text())
    path = root / f"benchmark-{settings().mode}.json"
    if path.exists():
        result["benchmark"] = json.loads(path.read_text())
    return result
