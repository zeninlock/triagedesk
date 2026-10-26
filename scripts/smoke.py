"""Exercise a running local fixture API; saves one synthetic review. Never use for production data."""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

url = os.getenv("API_URL", "http://localhost:8000")
token = os.getenv("REVIEWER_TOKEN", "")
if not token:
    raise SystemExit("Set REVIEWER_TOKEN for this local fixture smoke test")
with httpx.Client(base_url=url, timeout=30) as client:
    assert client.get("/health/ready").status_code == 200
    assert client.get("/meta").json()["mode"] == "fixture", "Smoke writes are limited to synthetic mode"
    before = client.get("/dashboard").json()
    queue = client.get("/issues", params={"review_status": "awaiting"}).json()
    if not queue["items"]:
        raise SystemExit("No synthetic issues awaiting review; seed a fresh demo database")
    issue_id = queue["items"][0]["id"]
    issue = client.get(f"/issues/{issue_id}").json()
    related = client.get(f"/issues/{issue_id}/related").json()
    assert all(row["id"] != issue_id for row in related["items"])
    payload = {
        "action": "correct",
        "category": "bug",
        "note": "Automated fixture smoke check",
        "snapshot_id": issue["snapshot_id"],
        "prediction_id": issue["prediction_id"],
        "expected_revision": issue["review_revision"],
        "idempotency_key": str(uuid.uuid4()),
    }
    response = client.post(
        f"/issues/{issue_id}/reviews", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201, response.text
    review_id = response.json()["id"]
    repeat = client.post(
        f"/issues/{issue_id}/reviews", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert repeat.json()["id"] == review_id
# A new HTTP client demonstrates a new request/DB session sees the persisted write.
with httpx.Client(base_url=url, timeout=30) as client:
    after = client.get("/dashboard").json()
    history = client.get(f"/issues/{issue_id}/reviews").json()
    assert any(review["id"] == review_id for review in history)
    assert after["reviewed"] == before["reviewed"] + 1
    assert after["awaiting_review"] == before["awaiting_review"] - 1
result = {
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "mode": "fixture",
    "issue_id": issue_id,
    "review_id": review_id,
    "before": before["reviewed"],
    "after": after["reviewed"],
    "related_self_exclusion": True,
    "repeat_submission_idempotent": True,
    "status": "passed",
}
Path("evidence").mkdir(exist_ok=True)
Path("evidence/compose-smoke.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
