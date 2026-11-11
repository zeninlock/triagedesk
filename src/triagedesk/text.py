"""Stable cache fingerprints; never include credentials in these payloads."""

import hashlib
import json


def digest(value) -> str:
    raw = (
        value
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def content_hash(title, body):
    return digest([title, body])
