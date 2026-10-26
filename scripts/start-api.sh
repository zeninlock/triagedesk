#!/bin/sh
set -eu
# Single API instance; apply additive migrations before accepting connections.
alembic upgrade head
triagedesk demo-init
exec uvicorn triagedesk.api:app --host 0.0.0.0 --port "${PORT:-8000}" --no-access-log
