#!/bin/sh
# Restore only into a new, isolated local project. Never overwrite an existing database.
set -eu
bundle=${1:?Usage: sh scripts/restore-local-evidence.sh /absolute/path/triagedesk-real-data.tar.gz}
export MODE=real READ_ONLY=true AUTH_MODE=local
export DB_PORT=${DB_PORT:-55433} API_PORT=${API_PORT:-18003} UI_PORT=${UI_PORT:-18503}
project_name=${TRIAGEDESK_EVIDENCE_PROJECT:-triagedesk-evidence}
compose() { docker compose --project-name "$project_name" "$@"; }
compose up -d --wait db
existing_tables=$(compose exec -T db psql -U triagedesk -d triagedesk -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
if [ "$existing_tables" != "0" ]; then
  echo "Refusing to restore over existing tables. Choose a new TRIAGEDESK_EVIDENCE_PROJECT and unused ports."
  exit 1
fi
scratch_dir=$(mktemp -d)
trap 'rm -rf "$scratch_dir"' EXIT HUP INT TERM
tar -xzf "$bundle" -C "$scratch_dir" triagedesk.dump
compose exec -T db pg_restore -U triagedesk -d triagedesk --no-owner --no-acl < "$scratch_dir/triagedesk.dump"
# Owner-generated archive restores persistent artifacts and frozen data; no remote download is performed.
compose run --rm --no-deps -T api python -c 'import sys,tarfile; tarfile.open(fileobj=sys.stdin.buffer,mode="r|gz").extractall("/app",filter="data")' < "$bundle"
compose run --rm --no-deps api triagedesk activate vscode-tfidf-v1
compose up -d --wait
echo "Real snapshot demo: http://localhost:$UI_PORT (read-only; TF-IDF fallback until optional semantic image is installed)."
