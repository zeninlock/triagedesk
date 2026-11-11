# TriageDesk

A GitHub issue triage dashboard hosted on **Streamlit Community Cloud**, with **Neon PostgreSQL** for persistence and the **OpenAI Python SDK** for labeling. You can deploy, sign in, and demonstrate it entirely through your browser.

Start with [the complete deployment guide](docs/HOSTING.md), then follow [the interview demo walkthrough](docs/DEMO.md).

## What it does

Connect a public repository you maintain. OpenAI reads each issue's title and description and returns its type, inferred priority, primary area, contributor suitability, and a short explanation in one structured response. Confident decisions are auto-sorted; uncertain decisions appear in **Needs review**. You can correct any labels.

| Group | Values |
| --- | --- |
| Type — exactly one | `type: bug`, `type: feature or enhancement`, `type: docs`, `type: chore or refactor`, `type: question` |
| Priority — exactly one | `priority: high`, `priority: medium`, `priority: low` |
| Area — one when inferable | `area: frontend`, `area: backend`, `area: api` |
| Contributor — optional | `help wanted`, `good first issue` |
| Work status — set by the user | `open`, `in progress`, `blocked` |

Priority reflects the meaning, impact, and urgency of the report. When urgency or impact cannot be inferred, it defaults to **low**. A clearly bounded, simple, low-risk task can receive **good first issue**, which also adds **help wanted**. Vague or short descriptions do not imply easy work.

Work status starts at **open**. Only a signed-in maintainer can change it. AI labeling, refreshing, and GitHub synchronization preserve it. The work status and AI review state are separate: a reviewed issue can still be blocked or in progress.

Color-coded cells and badges distinguish types, priorities, areas, work statuses, and contributor tags. Labels remain readable without relying on color alone.

Select an issue and choose **Generate contributor guide** for a starting plan based on repository excerpts. Guides show relevant files, investigation steps, prerequisites, tests, completion checks, and missing information when supported. Items include checked quotes and links to a specific commit. Maintainers approve drafts separately from labels and work status. A checked source establishes that the quote exists; suggested actions still need human judgment.

See [contributor guide setup, limitations, and demo steps](docs/CONTRIBUTOR_GUIDES.md). No new secret is required. Enable **Contents: Read-only** on the selected repository's GitHub token to read source files.

## Deploy

1. Put this source at the root of a GitHub repository.
2. Create a Neon project and copy its pooled and direct connection URLs.
3. In Streamlit Community Cloud, deploy `ui/community_app.py` with **Python 3.12**.
4. Paste the values from [the secrets template](.streamlit/secrets.toml.example) into **Advanced settings → Secrets**, replacing the placeholders with your Neon URLs, encryption secret, and OpenAI API key.
5. Deploy. Database setup and upgrades run automatically in the cloud.
6. Sign in with a fine-grained GitHub token and connect a public repository you own or maintain.

The [full guide](docs/HOSTING.md) covers every step, including how to generate the encryption secret in your browser, sign-in permissions, upgrading an existing database, and troubleshooting.

## Efficiency and persistence

- One bounded OpenAI Responses API call produces all labels for an uncached issue; no separate call per tag.
- The default model is `gpt-4.1-mini`, with strict structured output, a 2,048-token output cap, and bounded issue input.
- Completed analyses and human reviews are reused for the same issue snapshot and classifier version. Timestamp-only GitHub changes reuse the snapshot. Text or source-label changes can require new analysis.
- Work status changes, browsing, and refreshing completed results do not call OpenAI. Model or classification-policy changes intentionally invalidate AI results; valid human decisions are retained.
- Five pending issues are processed per pass by default. The workspace continues small AI passes while open. Provider backoff is respected; invalid credentials or billing problems pause a repository's queue until explicitly retried.
- Neon retains issues, source snapshots, analyses, reviews, status changes, and repository access across app reboots. Confirmed closed GitHub issues and their dependent workspace records are removed on synchronization.

The app reads GitHub and stores decisions in Neon. It does not change GitHub issue labels or statuses. Your OpenAI key belongs in Streamlit Secrets; each user's GitHub token belongs only in the sign-in form. GitHub credentials are encrypted before storage.

## Code map

| Location | Purpose |
| --- | --- |
| `ui/community_app.py` | Cloud entrypoint; starts the private backend once for all visitors |
| `ui/app.py`, `ui/workspace.py`, `ui/account.py` | Dashboard, color-coded issues, sign-in, and imports |
| `src/triagedesk/ai_labels.py` | OpenAI schema, semantic classification policy, cache, claims, and backoff |
| `src/triagedesk/triage.py` | SQL filtering, human label reviews, and conflict-safe work status changes |
| `src/triagedesk/contributor_guides.py` | On-demand guides, evidence checks, caching, and maintainer approval |
| `src/triagedesk/repository_context.py` | Bounded, commit-pinned source retrieval |
| `src/triagedesk/authentication.py` | GitHub identity and maintainer permissions |
| `src/triagedesk/connections.py`, `github.py` | Import jobs and incremental issue synchronization |
| `src/triagedesk/models.py`, `alembic/` | Neon schema and upgrade history |
| `tests/` | Mocked-provider, API, UI, migration, and PostgreSQL concurrency checks |

The UI and its private FastAPI process run together inside Streamlit's hosting environment. The backend listens on the hosting server's loopback interface; no separate backend hosting service or public API port is required. Use one Streamlit app instance per database.

For maintainers: CI installs the lockfile, checks formatting, verifies migrations on PostgreSQL, and runs the tests. No application needs to run on your computer. `ui/requirements.txt` pins the cloud dependencies from `uv.lock`; regenerate it when updating dependencies.

See [the database and cleanup notes](docs/DATABASE.md) for the tables retained, upgrade behavior, and retired code. License: [MIT](LICENSE).
