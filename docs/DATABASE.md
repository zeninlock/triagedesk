# Database, upgrade, and cleanup notes

The supported application store is Neon PostgreSQL. The source does not contain a populated Neon credential, so deployment supplies the actual database URLs through Streamlit Secrets. Migrations through `0005` apply automatically when the hosted app starts.

## Retained tables

| Table | Why it exists |
| --- | --- |
| `repositories` | GitHub identity, import checkpoints, and sync state |
| `issues` | Current issue content and independent `work_status` / `work_revision` |
| `snapshots` | Immutable versions supporting reproducible analysis and stale-review protection |
| `import_runs` | Bounded import diagnostics and counts |
| `auth_sessions` | Hashed session identifiers and encrypted GitHub credentials |
| `device_logins` | Optional GitHub browser sign-in exchanges |
| `repository_access` | Verified user/repository permissions |
| `connection_jobs` | Observable imports/AI passes, leases, and concurrency control |
| `label_analyses` | Cached model results, explanations, confidence, and provider errors |
| `label_reviews` | Human decisions and historical review notes |
| `label_assignments` | Current, indexed labels for fast filtering and counts |
| `issue_activity` | Actor and history for work status changes |
| `repository_contexts` | Commit-pinned file indexes and bounded text cache for contributor guides |
| `contributor_guides` | Guide requests, leases, excerpts, checked results, errors, and maintainer approval |
| `alembic_version` | Applied schema revision |

`label_assignments` and the historical JSON payloads serve different purposes: assignments make current filtering efficient; analysis/review payloads preserve the original decision. Neither is a second classifier.

## Upgrade behavior

For an existing Neon database, create a backup branch first. Deploy only one app instance while upgrading. Keep the existing encryption key if you want old encrypted sessions to remain readable.

Migration `0004`:

1. Adds `open`, `in progress`, and `blocked` work status, starting existing issues at open, plus a separate conflict-check revision and status activity table.
2. Maps recognized older human labels into the new five-type/four-group vocabulary. Reviews without a unique priority receive low priority. Unsupported custom labels stay in review history and can require a fresh decision. Previous label payloads are retained in review notes.
3. Copies old single-category human review records into `label_reviews`, including deferred/skipped history, before removing the old reviews table. The most recent decision by timestamp takes precedence.
4. Drops `experiments`, `predictions`, `reviews`, and `similarity_judgments`, which belonged to the retired classifier and related-report evaluation paths.
5. Removes the obsolete configurable taxonomy column. The requested vocabulary is now defined centrally in code.
6. Removes synthetic fixture repositories and their dependent records; real imported repositories and their histories are retained.

Old AI analyses are retained as history. The changed classification policy uses a new cache version, so old Groq/previous-policy results do not masquerade as the new taxonomy. Current real issues without a valid human decision are analyzed once under the new policy and then cached. Do not delete their history merely to reduce table count.

The original three migrations remain necessary for existing databases and for reproducible fresh installs. The data-consolidating upgrade has no destructive automatic downgrade. Restore the backup Neon branch and the prior application source together if you need to roll back.

## Ongoing housekeeping

Migration `0005` adds the two guide tables while preserving issues, labels, reviews, and work statuses. Guide cache identity includes the issue snapshot, commit, sources, model, and guide version. Approval is separate from label review. Reusable repository contexts are pruned after thirty days; source excerpts saved in guides remain with the issue. Closed-issue cleanup also removes its guides.

Expired sessions and device attempts are removed when users sign in. Completed/failed connection jobs older than seven days and import-run diagnostics older than thirty days are also pruned at sign-in. Active jobs and issue decisions are retained. On synchronization, confirmed closed GitHub issues and their dependent snapshots, labels, reviews, and status activity are removed from this open-issue workspace.

Changing a work status never changes the source snapshot or analysis cache key. Label reviews have a separate revision. Stale/concurrent submissions return a conflict instead of silently overwriting another user's change, and identical repeated submissions reuse the saved operation.

## Removed project material

- Docker/Compose and Render configuration, plus local setup/start/provision/smoke scripts.
- The trained scikit-learn classifier, datasets, CLI training/evaluation, heuristic/source-label categorization, embedding retrieval, similarity judgments, and their unused dependencies.
- Historical model/dataset evidence, screenshots of the old UI, and documentation describing the retired paths.
- One-off patch scripts, patch backups, original-file copies, and old interview notes that described the previous implementation.
- Generated Python/test caches from the delivery archive.

The existing private `.env` is not read by the hosted app and is excluded from the delivery archive. No secret has been copied into the source or deployment guide. Other projects and the separate learning-guide folder outside this application were not modified.

The source archive contains all cloud runtime files, schema history, relevant tests, CI, and current documentation. Test databases are isolated and disposable; automated checks never call OpenAI or modify a user's GitHub repository.
