"""Private operator helper: read a trusted project-generated tar.gz from stdin.
Never expose this script as an HTTP endpoint. Activation remains a separate CLI step.
"""

import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

from triagedesk.artifacts import file_hash
from triagedesk.config import settings

root = settings().artifact_dir.resolve()
root.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix=".provision-", dir=root) as temporary:
    staging = Path(temporary)
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as archive:
        archive.extractall(staging, filter="data")
    files = [path for path in staging.rglob("*") if path.is_file()]
    for path in files:
        relative = path.relative_to(staging)
        if relative.parts[0] not in {"models", "embedding-model", "embedding-cache"}:
            raise SystemExit(f"Unexpected artifact family: {relative.parts[0]}")
        destination = root / relative
        if destination.exists() and file_hash(path) != file_hash(destination):
            raise SystemExit(f"Refusing to overwrite a different existing artifact: {relative}")
    for path in files:
        destination = root / path.relative_to(staging)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(path, destination, follow_symlinks=False)
print("Artifacts provisioned. Import destination data, activate a model, then rebuild its retrieval mapping.")
