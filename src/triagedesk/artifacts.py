import importlib.metadata
import json
import os
import re
from pathlib import Path

from triagedesk.text import digest


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")
    temporary.replace(path)


def versions():
    return {
        name: importlib.metadata.version(name)
        for name in ("scikit-learn", "numpy", "scipy", "joblib", "fastapi", "sqlalchemy", "streamlit")
    }


def safe_version(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", value):
        raise ValueError("Artifact version must contain only letters, digits, dot, underscore, or hyphen")
    return value


def file_hash(path):
    import hashlib

    hasher = hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def dataset_version(rows, mapping_version):
    return "dataset-" + digest([mapping_version, rows])[:16]
