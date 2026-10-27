# Deployment operations

For free temporary hosting with verified maintainers, follow [HOSTING.md](HOSTING.md). The recommended Community Cloud/Neon setup runs the UI and a loopback-only API in one app, with durable PostgreSQL in Neon and temporary local artifacts. A Cloudflare Quick Tunnel can instead share your local Docker installation. Both methods require `MODE=real` and `AUTH_MODE=github`; the cloud helper enforces these. The shared reviewer token belongs only to the local fixture demo. The existing Render blueprint is a separate paid option and is not needed for the free methods.

## Storage and recovery

Back up PostgreSQL using the provider's supported backup mechanism or `pg_dump`. The database contains source snapshots, local review history, repository access observations, encrypted provider credentials, and job state. Treat a backup as installation data, not a source-code artifact.

For a local Compose installation:

```sh
docker compose exec -T db pg_dump -U triagedesk -d triagedesk -Fc > triagedesk.dump
```

Restore into a new staging database first. Never overwrite a working database as a trial. Use `pg_restore --no-owner --no-acl` with the staging database credentials, apply the current Alembic migrations, and verify record counts and a representative review history before relying on the restore.

Preserve the API artifact disk separately: trained models, their frozen manifests, active-model pointer, and search indexes live there. A rebuilt TF-IDF index can be generated from imported issues. A trained classifier requires its trusted saved model and metadata. Keep all old held-out manifests to retain future review-export exclusions.

Preserve `AUTH_ENCRYPTION_KEY` securely if restoring sessions from a database backup. Without the matching key, stored provider credentials cannot be decrypted; users must sign in again. Application session digests alone cannot reconstruct bearer session tokens. Never publish backups, environment settings, or model caches in Git.

## Restart and update behavior

The API startup script applies migrations before accepting traffic. Migration `0003` adds per-repository label settings, persistent LLM analyses, label assignments, and human label reviews. It preserves existing issue, snapshot, and review records during migration. Authenticated synchronization subsequently purges reports confirmed closed, including their local dependent analysis/review history, according to the active-workspace retention policy.

Local `docker compose down` retains named volumes. The database and artifact volumes persist across ordinary service recreation. For Community Cloud/Neon, database persistence depends on keeping the Neon project. Backend restarts discard temporary artifacts; rebuild TF-IDF through the connection form after restarting. For the optional paid Render setup, persistence depends on keeping its managed PostgreSQL instance and API disk attached.

A stopped import retains committed GitHub pages. Its expired lease is released by a later status check or submission; retrying synchronization resumes from the saved update checkpoint. A process restart does not automatically recreate a background worker or retrain a classifier.

## Capacity boundaries

Use one API instance and one UI instance for this MVP. Web imports have a maximum 3,000-object request cap and one active import/index job per installation. A signed-in, open workspace polls for updates about every 60 seconds; manual synchronization remains available. AI processing is limited to small batches and respects provider backoff. Very large corpora, multiple concurrent import workers, automatic scheduling, and sticky multi-instance UI sessions need additional engineering.

The default image uses TF-IDF retrieval. Optional MiniLM execution has a larger package and memory footprint; verify its capacity on an appropriately sized backend instead of assuming the small default plan is sufficient.

## Deployment checks

After an update, confirm that sign-in, repository import, AI analysis, and saving a review work against the deployed database. Reboot the app and confirm that saved decisions remain available. Tests and local container checks complement these deployment checks.

## Groq credentials and label persistence

Keep `GROQ_API_KEY` in the private environment or Community Cloud Secrets. The default threshold is 0.85 and the batch size is five issues per pass. Groq free-plan limits can delay the queue. Cached AI output and human reviews live in PostgreSQL, so a transient app filesystem does not cause reanalysis of unchanged snapshots. See [AI_LABELS.md](AI_LABELS.md) for activation, policy, and model limitations.
