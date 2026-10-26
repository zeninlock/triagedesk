# TriageDesk

**GitHub-authenticated issue triage and product feedback dashboard**

TriageDesk is a web application for verified GitHub maintainers to connect public repositories and organize their actual issues. It imports public reports through the dashboard, prepares **bug**, **enhancement**, or **question** suggestions, retrieves potentially related issues, and records a human decision with the verified reviewer identity.

It combines a review dashboard with a reproducible machine-learning pipeline. GitHub access is read-only: the application never changes source labels, closes issues, or posts comments. Classification and similarity scores support a reviewer; they do not establish correctness or prove that reports are duplicates.

Implemented end to end with FastAPI, PostgreSQL, SQLAlchemy/Alembic, scikit-learn, optional CPU Sentence Transformers, Streamlit, Docker Compose, pytest and GitHub Actions. No paid AI API or GPU is needed.

![Actual synthetic overview](docs/screenshots/overview.jpg)

## Contents

- [Connect your repository](#connect-your-repository)
- [Host online](#host-online)
- [Problem and intended users](#problem-and-intended-users)
- [Features](#features)
- [Example workflow](#example-workflow)
- [Verified status](#verified-status)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Data and machine learning](#data-and-machine-learning)
- [Quick start](#quick-start)
- [Real snapshots](#real-snapshots)
- [Real-data workflow](#real-data-workflow)
- [Development and tests](#development-and-tests)
- [API and configuration](#api-and-configuration)
- [Troubleshooting](#troubleshooting)
- [Publishing to GitHub](#publishing-to-github)
- [Roadmap](#roadmap)
- [Documentation](#documentation-and-limits)
- [License and attribution](#license-and-attribution)

## Connect your repository

The production workflow is **sign in → verify maintainer access → paste a public repository → import and categorize → review**. Terminal import commands are no longer required for normal maintainers.

To try verified mode locally, with Docker running and Python 3 available for the one-time configuration helper:

```sh
python3 scripts/setup-github-local.py
docker compose up --build -d --wait
```

The helper preserves existing settings, generates a private encryption key if needed, and selects `MODE=real`, `AUTH_MODE=github`, and protected writes. Open [the dashboard](http://localhost:8501). Sign in with a fine-grained GitHub token granting Metadata: read and Issues: read for the repository. Alternatively, configure a read-only GitHub App and `GITHUB_CLIENT_ID` to enable browser/device sign-in; see [the hosting guide](docs/HOSTING.md).

Open **Connect repository**, enter `owner/repository` or its canonical GitHub URL, choose the fetch cap, and submit. GitHub must confirm ownership or triage/write/maintain/admin access. The app tracks import progress, excludes PRs, saves issue snapshots, prepares suggestions, and builds TF-IDF search. Select the repository and use the category filter in the review queue. Later, use the same form's synchronization option to fetch updates.

A repository without issues yields an empty queue. Capped imports are partial. Trained models are used for their own repository when installed; otherwise, clear GitHub category labels and unscored text rules provide suggestions. Ambiguous reports remain for manual categorization. No measured accuracy is claimed for these fallback methods, and human decisions take precedence.

## Host online

Follow [the complete Render hosting and GitHub authentication guide](docs/HOSTING.md). The included blueprint provisions a public HTTPS interface, private API, managed PostgreSQL, persistent artifact disk, and generated encryption key. It uses individual GitHub sessions and does not accept the shared local reviewer token. Review Render's current paid-resource total before provisioning. No cloud resources or live deployment have been created by this source update.

## Problem and intended users

An issue tracker can accumulate bug reports, feature requests, usage questions, and overlapping discussions. A maintainer must read those reports, understand their intent, search for previous work, and track decisions. TriageDesk provides one review interface for that initial assessment.

The intended users are maintainers of student projects and small open-source projects who want to inspect an imported backlog. Potential benefits include less repetitive categorization, easier discovery of related discussions, and a durable record of reviews. **Time savings and intended-user usefulness have not yet been established through a maintainer study.** Classification alone is a modest feature; related-report usefulness also requires human evaluation.

Here, “product feedback” means the reports in a GitHub issue tracker. The application does not ingest email, surveys, or support chats. It does not fix source code, determine business priority, assign developers, or automatically close duplicate reports.

## Features

| Capability | Behavior |
|---|---|
| Verified GitHub connection | Sign in, confirm repository maintainer permissions, and start an observable import/sync job from the dashboard. |
| Public GitHub ingestion | Import open and closed issues, exclude pull requests, handle pagination and rate limits, and preserve source revisions. |
| Category suggestions | Use a compatible repository classifier when installed; otherwise show clearly marked source-label/rule suggestions and leave ambiguous reports for manual review. |
| Related-report search | Retrieve up to five candidates with TF-IDF or optional pinned CPU MiniLM embeddings; exclude self and stale/unavailable records. |
| Human review | Accept or correct a suggestion, defer or skip a report, add a note, and inspect previous decisions. |
| Review safeguards | Reject stale forms and conflicting updates; recognize repeated submissions without duplicating history. |
| Filtered analytics | Filter by repository, source creation date, open/closed state, category source, and review status. |
| Reproducible evaluation | Preserve dataset membership, label mapping, chronological splits, model settings, dependency versions, metrics, and artifacts. |
| Deployment | Run locally with Docker Compose, or provision the included GitHub-authenticated Render blueprint. |

The interface contains **Connect repository**, **Overview**, **Review queue**, **Issue details**, **Try a new issue**, **Model evaluation**, and **About/methodology** views. “Try a new issue” classifies entered text without creating a GitHub issue or storing a new report. A trained artifact is required for that classification request.

## Example workflow

1. Open the overview and select the repository or backlog slice to inspect.
2. Open the review queue and inspect an issue, for example the synthetic report **“CSV export loses the final row.”**
3. Read the source text and labels, then inspect the category suggestion and potentially related reports.
4. Choose **accept**, **correct**, **defer**, or **skip**, and optionally add a note.
5. Save the decision and inspect its history. A completed category decision changes the filtered dashboard counts.

Accept and correct complete the review for the current issue snapshot. Defer and skip leave the issue awaiting a completed decision. If the source issue changes, its earlier history remains available but a previous decision no longer counts as the current review. Relationship judgments can separately record **related**, **duplicate**, **unrelated**, or **uncertain**.

These actions update TriageDesk's database. A maintainer must make any desired change on GitHub separately.

## Verified status

| Evidence | Status |
|---|---|
| Runnable fixture demo | Verified with Docker Compose, migrations, 24 invented issues and health checks |
| Protected reviews and durable audit | Browser and HTTP saves verified; history/count changes and PostgreSQL restart persistence verified |
| Automated checks | 68 tests passed, including eight PostgreSQL integration tests; legacy functionality and new identity/permission/import flows checked |
| GitHub authentication | Device and fine-grained-token flows implemented; encrypted credential persistence, expiry/logout, role checks, isolation, and mocked end-to-end imports tested. Live App setup/sign-in remains owner verification. |
| Real ingestion | 2,999 VS Code issues plus a separate 1,165-issue Streamlit pilot imported; PRs excluded; pilot was rejected for classification |
| Real classification | 1,123 usable VS Code snapshots; chronological test macro-F1 **0.5446** vs majority **0.2847**; accuracy **0.6923** vs majority **0.7456** |
| Retrieval | TF-IDF and pinned MiniLM built over 4,164 real issues; self/repository/stale filtering verified; relevance quality pending |
| Latency | 100 warm requests per operation measured; see evaluation report for hardware, p50/p95 and loading costs |
| Deployment | Render Blueprint/schema and local containers prepared/checked; **not deployed**, no hosted URL claimed |
| Maintainer study | Protocol/materials ready; **pending**, no user findings or feedback-based improvements claimed |

This is a working local MVP. Hosted verification, genuine retrieval judgments, maintainer sessions, and a measured improvement based on user feedback remain pending. Read [evaluation](docs/EVALUATION.md) before citing a model score. Results below were recorded locally on 26 October 2026; repository publication does not itself verify a hosted deployment or a remote CI run.

## Architecture

```mermaid
flowchart TD
    GH[Public GitHub issues] --> ING[Import and synchronization jobs]
    ING --> DB[(PostgreSQL)]
    DB --> JOBS[Dataset, training, and search-index jobs]
    JOBS --> ART[Saved models and indexes]
    USER[Maintainer] <--> UI[Streamlit interface]
    UI <--> API[FastAPI backend]
    API <--> DB
    ART --> API
```

| Component | Responsibility |
|---|---|
| Streamlit | Render the review interface, collect input, and call the backend over HTTP. |
| FastAPI / Pydantic | Validate requests, enforce mode and write authorization, run application logic, and return typed responses. |
| PostgreSQL / SQLAlchemy | Persist reports, model suggestions, review history, and experiment metadata; execute filtered SQL queries and aggregates. |
| Alembic | Apply versioned database migrations. |
| scikit-learn | Clean and vectorize text, train the classifier and baseline, and calculate evaluation metrics. |
| Sentence Transformers / CPU PyTorch | Optionally encode text for semantic retrieval. |
| Docker Compose | Coordinate startup, readiness checks, migrations, seeding, and persistent storage. |
| pytest / Ruff / GitHub Actions | Verify behavior, formatting, and database migrations through local checks and a configured CI workflow. |

### Online requests and offline jobs

Ordinary page requests read scoped reports, summaries, classifications, and related-report rankings using saved artifacts. A verified `POST /connections` request starts a bounded background import/sync, categorization, and indexing job. Progress and results live in PostgreSQL. One database-enforced active job and a renewable lease prevent overlapping web import/index work and allow interrupted work to be retried from committed page checkpoints.

Model training, dataset preparation, activation, and evaluation remain explicit private CLI jobs. Web requests never train a classifier or download encoder weights. See [hosting](docs/HOSTING.md) for the single-instance runner's limits.

### Database and audit design

The twelve tables are `repositories`, `issues`, `snapshots`, `predictions`, `reviews`, `similarity_judgments`, `experiments`, `import_runs`, `auth_sessions`, `device_logins`, `repository_access`, and `connection_jobs`.

Source labels, model suggestions, and human decisions are stored separately. Snapshots preserve the text and labels used for a decision. Predictions record the snapshot, input hash, model version, scores, and time. Reviews append a decision, note, configured reviewer identity, submission key, and revision.

A conditional database update checks the snapshot and revision shown to a reviewer before saving. Competing decisions cannot silently overwrite each other. An identical transport retry returns its original review. Production authorization verifies individual GitHub identities and checks each repository role again before writes. Provider tokens are encrypted at rest, opaque application session tokens are stored only as digests, and production workspaces are scoped to the signed-in account. The shared token remains available only in explicitly selected local mode.

See [architecture](docs/ARCHITECTURE.md) and [design decisions](docs/DECISIONS.md) for details.

## Repository layout

```text
triagedesk/
├── src/triagedesk/
│   ├── api.py                 # HTTP endpoints, authorization, and errors
│   ├── authentication.py      # GitHub identity, encryption, sessions, role checks
│   ├── connection_routes.py   # Sign-in and repository connection endpoints
│   ├── connections.py         # Leased background import/sync jobs
│   ├── auto_categories.py     # Trained-model / label / rule suggestions
│   ├── schemas.py             # Validated request and response types
│   ├── models.py              # Database tables and constraints
│   ├── db.py                  # Database engines, sessions, transactions
│   ├── queries.py             # Shared filters, queue queries, aggregates
│   ├── reviews.py             # Review and relationship-judgment writes
│   ├── github.py              # Import, pagination, retries, synchronization
│   ├── audit.py               # Repository and label inspection
│   ├── text.py                # Text cleanup, hashes, label mapping
│   ├── dataset.py             # Frozen datasets, splits, duplicate checks
│   ├── training.py            # Classifier selection and sealed evaluation
│   ├── serving.py             # Artifact checks, activation, classification
│   ├── retrieval.py           # TF-IDF / MiniLM indexes and ranking
│   ├── retrieval_eval.py      # Frozen relevance pool and evaluation
│   ├── artifacts.py           # Versioned artifact and metadata helpers
│   ├── benchmark.py           # Measured inference and API latency
│   ├── fixtures.py            # Invented demonstration reports
│   ├── config.py              # Environment-based settings
│   └── cli.py                 # Administrative command entrypoint
├── ui/app.py                  # Streamlit application
├── ui/account.py              # Sign-in, repository connection, import progress
├── tests/                     # Unit, API, and PostgreSQL tests
├── alembic/                   # Database migration history
├── config/labels.v1.yaml       # Repository-specific category mappings
├── scripts/                   # Startup, smoke checks, artifact restoration
├── docs/                      # Architecture, data/model cards, study materials
├── evidence/                  # Recorded local results and verification reports
├── .github/workflows/ci.yml   # Configured automated checks
├── .env.example               # Local demonstration configuration
├── .gitignore                 # Excludes secrets and generated runtime files
├── compose.yaml               # Local multi-service deployment
├── Dockerfile                 # Application image
├── render.yaml                # Prepared Render deployment blueprint
├── pyproject.toml             # Python dependencies and tool configuration
├── uv.lock                    # Locked dependency resolution
└── LICENSE                    # MIT license for project code
```

Generated datasets and model caches belong in ignored runtime directories or Docker volumes. They are not part of the source repository.

## Data and machine learning

### Data sources and preparation

The recorded collection contains **2,999 VS Code issues** and a separate **1,165-issue Streamlit pilot**, for **4,164 real issues** available to retrieval. Both imports are partial collections. Pull requests are excluded.

Only **1,123 VS Code reports** were eligible for the classifier: **666 bugs, 305 enhancements, and 152 questions**. Unsupported/unlabeled reports and conflicting category mappings were excluded from supervised learning, but remain available for browsing and review. The Streamlit pilot had no eligible questions and was rejected for three-class training.

The frozen dataset is `dataset-66cb4613b0925284`. A chronological split assigns 786 reports to training, 168 to validation, and 169 to testing. Exact and near-text duplicate checks protect those partitions. In the primary collection no duplicate exclusions were found; that does not establish that no semantic duplicates exist.

Source creation dates span November 2015 to October 2017; the snapshots were downloaded in October 2026. Text or labels may have been edited after creation. This is a **chronological retrospective evaluation using collected snapshots**, with limited evidence about present-day or cross-project performance. See the [data card](docs/DATA_CARD.md).

### Category classifier

The classifier takes **title and body only**:

```text
Title + body → deterministic text cleaning → TF-IDF → logistic regression
                                                        ↓
                                 bug / enhancement / question scores
```

It does not use source labels, issue state, reviewer decisions, author profiles, or later metadata as input features. Cleaning removes HTML comments and narrow explicit category/type fields. It does not establish that every possible template shortcut was removed.

Three configurations were compared on validation macro-F1. The selected model uses word unigrams, up to 20,000 features, balanced class weights, `C=1`, and seed 42. A majority-class `DummyClassifier` provides the baseline. Settings and the review threshold were frozen before evaluating the 169 test reports; the selected classifier was not refitted on validation data.

### Recorded classification results

Historical trained-model baseline: **`vscode-tfidf-v1`**. These metrics do not evaluate the new source-label/rule fallback, maintainer authentication, or hosted performance.

| Metric on all 169 test reports | Classifier | Majority baseline |
|---|---:|---:|
| Macro-F1 | **0.5446** | 0.2847 |
| Accuracy | **0.6923** | 0.7456 |

The baseline always predicts bug. The trained classifier improves the equal-weighted score across categories, while losing on overall accuracy. No overall accuracy improvement is claimed.

| Category | Precision | Recall | F1 | Test reports |
|---|---:|---:|---:|---:|
| Bug | 0.8739 | 0.7698 | 0.8186 | 126 |
| Enhancement | 0.2222 | 0.7143 | 0.3390 | 14 |
| Question | 0.7692 | 0.3448 | 0.4762 | 29 |

Question recall is weak: only 10 of 29 are correctly identified. Enhancement predictions are often wrong: 10 of 45 match the source label. The small enhancement test support limits confidence in that estimate. Source labels themselves were not independently adjudicated.

A validation-selected threshold of **0.55** flags **55.03%** of test predictions for extra review. The remaining 76 reports have accuracy 0.8816. That easier-subset score is separate from overall accuracy. Scores are uncalibrated and should not be interpreted as verified correctness probabilities. See the [model card](docs/MODEL_CARD.md) and [full evaluation](docs/EVALUATION.md).

### Related-report retrieval

TF-IDF provides the default lexical search. Optional `sentence-transformers/all-MiniLM-L6-v2` supplies semantic embeddings. The encoder is pretrained separately from this project's category classifier. Embeddings are cached by content hash and model revision, and similarity ranking uses the saved index; a vector database is not required for this small collection.

Both methods were built and exercised over the real corpus. A frozen 39-query comparison pool is ready, but genuine human relevance judgments are pending. Therefore, no Precision@5, MRR, duplicate-detection accuracy, or retrieval-quality improvement is claimed. Snapshot edits, full-corpus TF-IDF fitting, and the encoder's later training date limit historical interpretation.

### Recorded latency

Measurements used 100 sequential warm requests per operation on an arm64 macOS machine with eight logical CPUs, native Python, and PostgreSQL in a local Docker VM. The index contained 4,164 real issues; example retrieval queries filtered to the 2,999-issue VS Code collection.

| Operation | Median (p50), ms | p95, ms |
|---|---:|---:|
| Classifier call | 0.239 | 0.367 |
| TF-IDF retrieval | 3.868 | 5.482 |
| Semantic retrieval | 10.989 | 17.310 |
| Issue-list API | 13.879 | 16.669 |
| Dashboard API | 27.208 | 30.735 |
| Issue-detail API | 4.832 | 6.543 |

Classifier/retrieval rows measure those operations, not complete page loads. API rows include local HTTP, SQL, and serialization. Semantic query encoding is included; corpus embedding generation is excluded. First artifact/model loads were measured separately: classifier 28.9 ms, TF-IDF 119.3 ms, and semantic 3.27 seconds. These results do not establish cloud or concurrent-load performance. See [the benchmark report](evidence/benchmark-real.json) and [evaluation protocol](docs/EVALUATION.md).

## Quick start

Prerequisite: Docker Desktop/Engine with Docker Compose running. No host Python, token or model download is required for this demo. Run the following commands from this project's root directory. Create `.env` once for a fresh checkout; keep an existing configuration instead of replacing it.


```sh
cp .env.example .env
docker compose up --build -d --wait
```

Open [TriageDesk](http://localhost:8501) and [API documentation](http://localhost:8000/docs). Startup waits for PostgreSQL, applies Alembic migrations, idempotently seeds 24 synthetic issues and builds a small TF-IDF index. Data is not deleted. The demo is clearly labeled synthetic and its saved scores are illustrations, not trained-model results. The default source-only demo has no trained classifier for arbitrary new text; the new-text view reports that state explicitly. Use the separately provided real snapshot bundle or train a real model to enable classification.

To save a local review, enter `local-demo-change-me` in the sidebar’s reviewer token field. This documented demonstration credential is for the loopback-bound local setup only. Open **Review queue → Inspect issue**, read the text and suggestion, inspect related reports, choose accept/correct/defer/skip and save. Without a prediction, choose correct to categorize manually. Dashboard counts use the latest completed decision on the current snapshot; defer and skip leave work awaiting review.

```sh
docker compose logs api ui
docker compose down
```

`down` keeps the database, datasets and artifact volumes. Reopening with `up -d --wait` preserves reviews. Ports 5433, 8000 and 8501 bind to 127.0.0.1. Use `READ_ONLY=true` to disable writes regardless of UI controls. Replace the demo token before any public hosting.

## Real snapshots

The real snapshot archive is a separate owner-provided delivery, **not included in a Git clone** and not hosted by this repository. The separate `triagedesk-real-data.tar.gz` delivery contains the exact database, frozen dataset/model, pending relevance pool and cached artifacts used for the recorded results. Keep it outside your source repository. After the quick start, with the archive beside this project folder:

```sh
sh scripts/restore-local-evidence.sh ../triagedesk-real-data.tar.gz
```

Open [the read-only real snapshot demo](http://localhost:18503). It uses separate database/artifact volumes and ports 55433/18003/18503, and the helper refuses to overwrite an existing schema. Its default small image serves the trained classifier and a clearly labeled TF-IDF fallback; optional semantic setup is below. Database counts, classifier availability, fallback labeling and read-only behavior were checked after an actual restore. Normal GitHub collection is still available through the workflow below.

To stop that separate demo while retaining its volumes:

```sh
MODE=real READ_ONLY=true DB_PORT=55433 API_PORT=18003 UI_PORT=18503 docker compose --project-name triagedesk-evidence down
```

## Real-data workflow

Set `MODE=real` in `.env`; optionally set `GITHUB_TOKEN` there for a higher API quota. Keep credentials uncommitted. Existing fixtures stay stored but are hidden by the mode boundary. Restart services after changing mode:

```sh
docker compose up -d --wait
docker compose run --rm api triagedesk audit microsoft/vscode --out data/repository-audit.json
docker compose run --rm api triagedesk import microsoft/vscode --limit 3000
docker compose run --rm api triagedesk sync microsoft/vscode --limit 3000
docker compose run --rm api triagedesk prepare microsoft/vscode --out data/dataset.json
docker compose run --rm api triagedesk train data/dataset.json --version my-vscode-v1
docker compose run --rm api triagedesk evaluate my-vscode-v1
docker compose run --rm api triagedesk activate my-vscode-v1
docker compose run --rm api triagedesk predict
docker compose run --rm api triagedesk index
```

These are explicit private administrative CLI jobs. Maintainers can instead use the authenticated connection screen for bounded imports, synchronization, categorization, and indexing. Imports include open/closed issues, follow Link pagination, exclude PR objects, upsert by external ID and commit checkpoints with each persisted page. Limits count REST response objects, including excluded PRs. A ten-minute update-time overlap protects synchronization; a capped corpus stays marked partial. An anonymous rate-limit error preserves committed pages and reports when to retry. Audit sample size is bounded at 100 objects per early/recent cohort. Source deletions are not inferred from a partial traversal; after confirming an inaccessible/deleted source, use `triagedesk mark-unavailable <internal-issue-id>` and rebuild indexes. History remains.

Versioned label mapping is in `config/labels.v1.yaml`. VS Code uses `bug`, `feature-request`, and literal `*question`. Conflicts and unsupported labels are excluded from supervision, not forced into a class. All three chronological partitions must support the three categories or training refuses. A new download may differ from the frozen evaluation included here; it needs a new dataset and immutable model version. Do not retune or repartition to improve an existing test headline.

Artifacts persist in the Compose `artifacts` volume and datasets in `datasets`. Training writes Pipeline/baseline, model card, frozen snapshots/splits, metrics, config, mapping, seed, dependencies and lock. Activation creates a checksum pointer used by serving. Missing or incompatible models yield an explicit unavailable state; human review still works. Never load someone else’s untrusted joblib artifact.

### Optional semantic retrieval

The default image uses the clearly labeled TF-IDF fallback. To install CPU semantic dependencies and download the pinned model once:

```sh
docker compose build --build-arg INSTALL_SEMANTIC=true
docker compose up -d --wait
docker compose run --rm api triagedesk index --semantic --allow-download
```

MiniLM revision `c9745ed1d9f207416be6d2e6f8de32d1f16199bf` is Apache-2.0 and uses a 384-dimensional embedding of the first 256 wordpieces. Weights are about 90 MB; package/cache storage is additional. Linux PyTorch is locked to CPU wheels. Corpus embeddings are cached by content hash and model version and regenerated after relevant text changes. Requests never download models or fit indexes. Results are **potentially related issues**, not automatically duplicates.

### Retrieval judgments and future labels

```sh
docker compose run --rm api triagedesk retrieval-pool --queries 40 --out data/retrieval-pool.json
# A real reviewer fills each pooled pair’s reviewer and judgment fields, without changing rankings.
docker compose run --rm api triagedesk evaluate-retrieval data/retrieval-pool.json
docker compose run --rm api triagedesk review-dataset --out data/future-reviewed-dataset.json
```

The current prepared pool has 39 queries after eligibility checks. Human quality scores are pending. UI judgments and frozen evaluation judgments are separate. Candidate creation dates are bounded by each query; edited snapshots and globally fitted index vocabulary still limit historical interpretation. No Recall@5 is claimed without a complete relevance set. Future review exports exclude held-out GitHub identities across saved manifests; they are not automatically trained or merged. Preserve all manifests when moving artifacts.

## Other operator commands

```sh
docker compose run --rm migrate                                  # explicit migration
docker compose run --rm api triagedesk seed-fixtures              # MODE=fixture only
docker compose run --rm api triagedesk benchmark --requests 100 --api-url http://api:8000
docker compose exec -T db pg_dump -U triagedesk -d triagedesk -Fc > triagedesk.dump
```

Benchmark results are saved in the artifact volume, with p50/p95, actual issue/request counts, hardware and loading protocol. No made-up speedup or concurrent load claim is used. See [deployment](docs/DEPLOYMENT.md) for restore into a new staging database and artifact provisioning.

## Development and tests

Use Python 3.12 and [uv](https://docs.astral.sh/uv/). PostgreSQL is still required for application persistence. SQLite is used only in fast unit tests.

```sh
uv sync --frozen                     # add --extra semantic for optional CPU retrieval
cp .env.example .env
docker compose up -d db
uv run alembic upgrade head
uv run triagedesk demo-init
uv run uvicorn triagedesk.api:app --host 127.0.0.1 --port 8000 --no-access-log
# Second terminal:
uv run streamlit run ui/app.py
```

The copied `.env` points to PostgreSQL on localhost:5433. `API_URL` defaults to localhost:8000. Training and serving must use the same trusted artifact directory and locked classifier version.

```sh
uv run ruff check src ui tests
uv run ruff format --check src ui tests alembic
uv run pytest -q                     # eight PG tests skip if TEST_DATABASE_URL is unset
docker compose exec db createdb -U triagedesk triagedesk_test  # once; skip if it already exists
TEST_DATABASE_URL=postgresql+psycopg://triagedesk:triagedesk@localhost:5433/triagedesk_test uv run pytest -q
uv run alembic check
API_URL=http://localhost:8000 REVIEWER_TOKEN=local-demo-change-me uv run python scripts/smoke.py
```

### What was tested

The updated PostgreSQL-enabled local run contains **68 passed tests**, with no failures or skips. Eight use actual PostgreSQL; other checks use in-memory SQLite, local components, or mocked external responses where appropriate.

- **Identity and access:** encrypted provider credentials, hashed sessions, expiry/logout, numeric GitHub identity, repository isolation, denied roles, revoked write access, device polling, malformed URLs, and concurrent import admission.
- **Ingestion:** page traversal, PR exclusion, idempotent imports, failed-page rollback, partial collection status, preserved snapshots, API failures, and rate-limit handling.
- **ML:** label conflicts, unsupported labels, chronological boundaries, exact/near duplicate screening, training-only preprocessing, save/load consistency, and threshold metrics.
- **API and reviews:** authorization, read-only enforcement, input bounds, filtered aggregates, manual review without a model, history, repeated submissions, and stale forms.
- **PostgreSQL:** persistence and constraints, review history across sessions, competing review revisions, changed-source invalidation, and identical concurrent retry behavior.
- **Retrieval and provenance:** self/stale/unavailable exclusion, historical candidate filtering, embedding-cache reuse, held-out identity protection, and rejection of synthetic training data or incomplete relevance judgments.

Additional local checks covered an actual browser save, clean Docker startup from the extracted source, review survival after service/container restart, restoration into a new database, and the optional Linux CPU semantic container. Passing these checks establishes the tested software behavior, not model accuracy or user usefulness.

The smoke script intentionally writes only to synthetic mode and refuses real data. Integration tests create isolated schemas in the dedicated test database and remove only their own generated schemas. CI uses a PostgreSQL service, mocked GitHub and no live token/model downloads. Local result: 68 passed; a remote GitHub Actions success must be checked after publication.

## API and configuration

### Main endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/auth/token`, `/auth/device/start`, `/auth/device/poll` | GitHub identity verification and sign-in. |
| GET / POST | `/auth/session`, `/auth/logout` | Inspect or invalidate the current application session. |
| GET / POST | `/connections` | List own connections or start a verified import/sync job. |
| GET | `/connections/jobs/{id}` | Inspect own import progress/results. |
| GET | `/health/live`, `/health/ready` | Process and database readiness checks. |
| GET | `/meta`, `/repositories` | Mode, configuration summary, and visible source repositories. |
| GET | `/issues`, `/issues/{id}` | Paginated queue and issue details. |
| GET | `/issues/{id}/reviews` | Stored review history. |
| GET | `/issues/{id}/related` | Related candidates in the same repository. |
| GET | `/dashboard` | Filtered counts, trends, and review progress. |
| GET | `/models`, `/imports` | Model availability/evaluation and import status. |
| POST | `/classify` | Classify entered title/body without saving an issue. |
| POST | `/related` | Search using entered title/body. |
| POST | `/issues/{id}/reviews` | Save a protected human review. |
| POST | `/issues/{id}/judgments` | Save a protected relationship judgment. |

After startup, open the interactive schema at [http://localhost:8000/docs](http://localhost:8000/docs).

In local demo mode, read-only requests can be explored with the examples below. Production data routes additionally require the signed-in application bearer session and an authorized repository filter:

```sh
curl http://localhost:8000/health/ready
curl 'http://localhost:8000/issues?page=1&page_size=10'
curl http://localhost:8000/dashboard
```

Review/judgment requests additionally require an authorization token and the displayed source snapshot. A current revision is required for reviews. Consult the interactive schemas for the complete payload rather than inventing IDs.

### Configuration

OpenAPI documents typed inputs/outputs. Queue filters include repository, UTC creation interval, state, literal text search, category source and review status, with bounded pagination/sorting. Production review/judgment writes require an individual GitHub-backed application session, current repository maintainer access, and a unique submission key. Local demo mode uses its configured shared token. A stale issue/review returns 409; refresh and reconsider. Do not blindly retry with a changed revision.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy PostgreSQL URL; common provider postgres/postgresql URLs normalize to psycopg |
| `MODE` | `fixture` or `real`; data/metric boundary |
| `ARTIFACT_DIR` | Persistent trusted model/index/cache directory |
| `READ_ONLY` | Backend import/review write lock; application default true; verified production blueprint explicitly enables writes |
| `AUTH_MODE` | `local` demo or `github` individual maintainer authentication |
| `AUTH_ENCRYPTION_KEY` | Random secret of at least 32 characters for encrypted provider credentials |
| `GITHUB_CLIENT_ID` | Optional GitHub App Client ID enabling browser/device sign-in |
| `ALLOW_TOKEN_LOGIN` | Enable fine-grained GitHub token sign-in |
| `SESSION_HOURS` | Expiring application sessions, 1–24 hours; default 8 |
| `REVIEWER_TOKEN`, `REVIEWER_NAME` | Explicit local-demo mode only; ignored for production GitHub identities |
| `GITHUB_TOKEN` | Optional, read-only public ingestion authorization; never sent to the interface |
| `API_URL` | Streamlit’s backend URL |
| `DB_PORT`, `API_PORT`, `UI_PORT` | Optional host port overrides; container ports remain fixed |
| `EMBEDDING_MODEL`, `EMBEDDING_REVISION` | Pinned optional encoder settings; changing them requires rebuilding the index/cache |

Issue bodies and review notes render as safe text; custom HTML contains only the static stylesheet. SQL is parameterized. Repository identifiers cannot be arbitrary fetch URLs. Credentials are excluded from images/repositories and application logs. This MVP supports individual GitHub sessions and scoped connected workspaces. It does not implement enterprise SSO, private repositories, automatic retraining, an LLM, a vector database, or persistent browser-login cookies.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Docker cannot connect to its engine | Start Docker Desktop/Engine and wait for it to be ready. |
| The application ports are already in use | Stop the previous project or set unused `DB_PORT`, `API_PORT`, and `UI_PORT` values in `.env`, then restart. |
| Classifier unavailable in the fixture demo | Expected: fixture suggestions are illustrative. Restore the real bundle or train and activate a real model. |
| Semantic search is unavailable | The base image intentionally uses TF-IDF. Install optional semantic dependencies and build the pinned index to enable MiniLM. |
| Review save is rejected | In production, check GitHub identity, repository role, and `READ_ONLY`; in local mode, check the reviewer token. Refresh stale snapshots/revisions. |
| Import hits a GitHub rate limit | Keep the committed progress, wait until the reported reset, and retry. An optional token may increase the quota. |
| Training refuses a dataset | Each chronological partition must support all three categories. Collect suitable data rather than moving held-out reports into training. |
| Eight tests skip | Set `TEST_DATABASE_URL` to a dedicated PostgreSQL test database to run the integration checks. |
| Restore helper refuses an existing database | It intentionally avoids overwriting tables. Reuse the already restored app, or choose a new evidence project and unused ports. |

Inspect `docker compose ps` and `docker compose logs api ui` for startup problems. Plain `docker compose down` preserves volumes. Do not add `--volumes` unless you intend to delete stored application data.

## Publishing to GitHub

See the [step-by-step GitHub upload guide](docs/GITHUB_UPLOAD.md) for GitHub Desktop and terminal options. Publish the contents of this project directory, so this `README.md` appears at the repository root.

The repository includes `.github/workflows/ci.yml`, `.env.example`, and `uv.lock`. Local `.env` settings, virtual environments, generated models, database dumps, and the real snapshot bundle are excluded. The synthetic Docker demo works without the bulk data archive; no release download URL is claimed.

## Roadmap

- Obtain genuine human relevance judgments for the prepared retrieval pool.
- Run the documented maintainer study and measure review effort and usefulness.
- Make and evaluate at least one improvement justified by that feedback.
- Collect recent, consistently labeled reports and compare classifier improvements on fresh held-out data.
- Provision and verify a hosted deployment using the prepared blueprint.
- Verify remote CI after publishing the repository.

Changes to classification, retrieval, and workflow should have separate evidence. No target score, user time saving, or deployment success is assumed in advance.

## Contributing

Use a focused branch, keep generated data and secrets out of commits, and run the relevant checks before opening a pull request. Preserve existing experiment versions and held-out manifests when changing ML code. Include the problem, resulting behavior, validation, and relevant limitations in the change description. See [design decisions](docs/DECISIONS.md) for current tradeoffs.

## Documentation and limits

- [Online hosting and verified GitHub connections](docs/HOSTING.md)
- [GitHub upload instructions](docs/GITHUB_UPLOAD.md)
- [Product brief and acceptance criteria](docs/PRODUCT_BRIEF.md)
- [Architecture and Mermaid diagram](docs/ARCHITECTURE.md), [decisions](docs/DECISIONS.md)
- [Data card](docs/DATA_CARD.md), [model card](docs/MODEL_CARD.md), [actual evaluation and benchmarks](docs/EVALUATION.md)
- [Render deployment preparation and costs](docs/DEPLOYMENT.md)
- [Maintainer study, consent, recruitment, form and iteration log](docs/USER_VALIDATION.md)
- [3–5 minute demo script](docs/DEMO_SCRIPT.md), [interview preparation and AI disclosure](docs/INTERVIEW_PREP.md), [résumé drafts](docs/RESUME.md)
- [Progress and remaining work](docs/PROGRESS.md), [data/model/documentation attribution](docs/ATTRIBUTION.md)

The classification result is a **chronological retrospective evaluation using collected snapshots**. Historical issue text and labels may have been edited or assigned after creation; their availability at historical cutoffs is unproven. Data is old, partial and imbalanced; question recall is weak and current/cross-project quality is unknown. Source labels are noisy. Model scores are uncalibrated. Retrieval relevance and intended-user usefulness need human evidence. Deployment is prepared, not claimed complete.

![Actual saved synthetic review](docs/screenshots/review-saved.jpg)

## License and attribution

The project code is distributed under the [MIT license](LICENSE). Public issue text remains subject to its original authors' rights; the code license does not relicense that content. The optional MiniLM model has a separate Apache-2.0 license. Source links, data/model attribution, and the role of AI-assisted development are documented in [attribution](docs/ATTRIBUTION.md) and [interview preparation](docs/INTERVIEW_PREP.md).
