import hashlib
import json
import re
from pathlib import Path

import yaml

CATEGORIES = ["bug", "enhancement", "question"]
# Remove explicit template type declarations, not ordinary narrative words such as 'bug'.
TYPE_FIELD = re.compile(
    r"(?im)^(?:#{1,6}\s*)?(?:issue type|category|type|type of issue|is this a bug report or feature request)"
    r"\s*[:?].*$|^\s*-\s*\[[ xX]\]\s*(?:bug report|feature request|question)\s*$"
)


def clean_text(title: str, body: str) -> str:
    text = TYPE_FIELD.sub("", f"{title}\n{body}")
    return re.sub(r"<!--.*?-->", " ", text, flags=re.S).strip()


def digest(value) -> str:
    raw = (
        value
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def content_hash(title, body):
    return digest([title, body])


def label_mapping(path: str | Path = "config/labels.v1.yaml"):
    return yaml.safe_load(Path(path).read_text())


def map_labels(labels, repository, mapping):
    rules = mapping["repositories"].get(repository.lower())
    if rules is None:
        raise ValueError(f"No label mapping for {repository}; audit labels and add a versioned mapping")
    names = {str(x).casefold() for x in labels}
    matches = [
        category for category in CATEGORIES if names.intersection(x.casefold() for x in rules[category])
    ]
    if len(matches) > 1:
        return None, "conflicting"
    return (matches[0], "eligible") if matches else (None, "unsupported_or_unlabeled")
