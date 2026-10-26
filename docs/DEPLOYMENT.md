# Deployment operations

For the current verified-maintainer deployment, follow [HOSTING.md](HOSTING.md). The Render blueprint now uses `MODE=real`, `AUTH_MODE=github`, an encrypted credential store, a private API, and individual GitHub identities. The shared reviewer token belongs only to the local fixture demo.

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

The API startup script applies migrations before accepting traffic. Migration `0002` adds the session, device-login, repository-access, and connection-job tables plus suggestion provenance fields. It preserves existing issue and review records.

Local `docker compose down` retains named volumes. The database and artifact volumes persist across ordinary service recreation. Cloud persistence depends on keeping the managed PostgreSQL instance and API disk attached.

A stopped import retains committed GitHub pages. Its expired lease is released by a later status check or submission; retrying synchronization resumes from the saved update checkpoint. A process restart does not automatically recreate a background worker or retrain a classifier.

## Capacity boundaries

Use one API instance and one UI instance for this MVP. Web imports have a maximum 3,000-object request cap and one active import/index job per installation. Production synchronization is manually triggered through the connection screen. Very large corpora, multiple concurrent import workers, automatic scheduling, and sticky multi-instance UI sessions need additional engineering.

The default image uses TF-IDF retrieval. Optional MiniLM execution has a larger package and memory footprint; verify its capacity on an appropriately sized backend instead of assuming the small default plan is sufficient.

## What has and has not been verified

Local test reports and container checks belong in `evidence/`. Historical model quality is documented in [EVALUATION.md](EVALUATION.md). Authentication and repository jobs have dedicated automated tests with mocked GitHub responses and actual PostgreSQL integration checks. A GitHub App registration, a real maintainer sign-in, and a live cloud URL must be verified against the owner's accounts after provisioning; source preparation alone does not complete those steps.
