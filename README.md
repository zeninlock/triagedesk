# TriageDesk

TriageDesk helps GitHub maintainers organize their issue backlog. It imports open issues from a public repository, uses an LLM to suggest labels, and puts uncertain results in a review queue. Issues, AI analysis, and maintainer decisions are saved in PostgreSQL so completed work can be reused across sessions.

The dashboard is built with Streamlit, with a FastAPI backend. AI labeling uses the Groq API.

## How it works

1. Sign in with GitHub and connect a public repository you maintain.
2. TriageDesk imports its open issues and analyzes them against the repository's label settings.
3. Confident results are labeled automatically. Results below the confidence threshold, or marked uncertain by the model, go to **Needs review**.
4. Review an issue, adjust its labels if needed, and save. It moves to **Reviewed**.
5. While the workspace is open, TriageDesk checks for new and updated issues and continues processing pending analysis. Issues confirmed closed on GitHub are removed from the local workspace.

Labels are organized into five groups:

| Group | Example labels |
| --- | --- |
| Type | `bug`, `enhancement`, `documentation`, `question` |
| Priority | `priority: high`, `priority: medium`, `priority: low`, `regression` |
| Module | `billing`, `onboarding`, `UI/UX`, `API` |
| Contributor | `good first issue`, `help wanted`, `easy` |
| Workflow | `waiting for op's response`, `dependencies`, `CI` |

You can change the labels for each repository in **Label settings**. The **Issues** tab lets you browse by group and label, and **Overview** shows the label distribution. Issue details include the model's explanation, supporting text, and related issues.

Labels and reviews stay inside TriageDesk; the app reads GitHub issues without changing them. Completed analyses are cached, so unchanged issues do not need another AI call on each login or refresh.

## Project structure

```text
triagedesk/
├── src/triagedesk/          # Backend and application logic
│   ├── api.py              # FastAPI routes
│   ├── authentication.py   # GitHub sign-in and application sessions
│   ├── connections.py      # Repository connections and imports
│   ├── github.py           # GitHub API client and issue synchronization
│   ├── ai_labels.py        # Groq requests and label validation
│   ├── triage.py           # Analysis jobs, caching, and review routing
│   ├── models.py           # Database tables
│   ├── retrieval.py        # Related-issue search
│   ├── training.py         # Offline scikit-learn classifier training
│   ├── config.py           # Application settings
│   └── cli.py              # Command-line tools
├── ui/
│   ├── app.py              # Local Streamlit entrypoint
│   ├── community_app.py    # Streamlit Community Cloud entrypoint
│   ├── account.py          # Sign-in and repository connection screens
│   └── workspace.py        # Issue browsing, labels, and review tabs
├── alembic/                # Database migrations
├── config/                 # Label mappings for the offline classifier
├── tests/                  # Unit, API, and database tests
├── scripts/                # Setup, startup, and maintenance scripts
├── docs/                   # Setup guides and technical documentation
├── evidence/               # Offline dataset and model reports
├── .github/workflows/      # Continuous integration
├── .streamlit/             # Streamlit configuration and secrets example
├── .env.example            # Example local environment settings
├── compose.yaml            # PostgreSQL, API, and UI services
├── Dockerfile              # Application image
├── pyproject.toml          # Python dependencies and tool settings
└── uv.lock                 # Locked dependencies
```

## Run locally

You will need Git, Python 3.12, Docker with Docker Compose, and a Groq API key for automatic labeling.

### 1. Clone and configure

```sh
git clone https://github.com/zeninlock/triagedesk.git
cd triagedesk
python3 scripts/setup-github-local.py
```

The setup script creates a local `.env` file, enables GitHub sign-in, and generates an encryption key for stored credentials. Add your Groq API key to that file:

```dotenv
GROQ_API_KEY=your_groq_api_key
```

Keep `.env` private. It is excluded from Git.

### 2. Start the application

With Docker running:

```sh
docker compose up --build -d --wait
```

This starts PostgreSQL, applies database migrations, and launches the API and dashboard.

- Dashboard: [http://localhost:8501](http://localhost:8501)
- API documentation: [http://localhost:8000/docs](http://localhost:8000/docs)

### 3. Connect a repository

1. Create a fine-grained personal access token in GitHub for the repository you want to connect. Grant **Metadata: read** and **Issues: read** permissions.
2. Use the token to sign in to TriageDesk.
3. Open **Connect repository**, enter `owner/repository`, and choose **Verify maintainer and import issues**.
4. Open the repository workspace to browse labels and review uncertain results.

Your GitHub account must own the repository or have triage, write, maintain, or admin access. Browser sign-in through a GitHub App is also supported; its configuration is covered in the [hosting guide](docs/HOSTING.md).

### Stop or inspect the application

```sh
docker compose logs -f api ui
docker compose down
```

Stopping the services keeps the database and saved reviews. Start them again with `docker compose up -d --wait`. After changing `.env`, run `docker compose up -d --wait` to apply the new settings.

## Try the demo

For a fresh checkout, you can use sample issues without GitHub credentials or a Groq key:

```sh
cp .env.example .env
docker compose up --build -d --wait
```

Open the dashboard and enter `local-demo-change-me` in the reviewer token field to save reviews. This mode seeds synthetic issues for exploring the interface; it does not run automatic Groq analysis. Use the GitHub setup above to work with a real repository.

## Configuration

Settings are loaded from `.env`. The main options are:

| Setting | Purpose |
| --- | --- |
| `GROQ_API_KEY` | API key used for AI labeling |
| `AI_MODEL` | Groq model used for analysis |
| `AI_CONFIDENCE_THRESHOLD` | Minimum model-reported confidence for automatic labeling; default `0.85` |
| `AI_BATCH_SIZE` | Issues processed in each analysis batch; default `5` |
| `AI_REQUEST_INTERVAL` | Minimum interval between AI requests, in seconds; default `10` |
| `AUTO_SYNC_SECONDS` | Interval between workspace sync checks; default `60` |
| `DATABASE_URL` | PostgreSQL connection URL; Compose supplies its internal database address |
| `AUTH_ENCRYPTION_KEY` | Secret generated by the setup script for encrypting stored credentials |
| `GITHUB_CLIENT_ID` | Optional GitHub App client ID for browser sign-in |

If issues remain **Waiting for AI**, check the Groq key and available quota. The dashboard shows analysis progress and provider errors. **Run AI now** processes pending analysis without importing the repository again.

## Development

Install dependencies with [uv](https://docs.astral.sh/uv/). After configuring `.env` with the setup script above, start PostgreSQL and run the API locally:

```sh
uv sync --frozen
docker compose up -d db
uv run alembic upgrade head
uv run uvicorn triagedesk.api:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```sh
uv run streamlit run ui/app.py
```

Run the tests and code checks with:

```sh
uv run pytest -q
uv run ruff check src ui tests
uv run ruff format --check src ui tests alembic
```

PostgreSQL integration tests also require `TEST_DATABASE_URL` pointing to a separate test database. The test suite skips those tests when it is unset.

## Hosting

See the [hosting guide](docs/HOSTING.md) to deploy the app with Streamlit Community Cloud and a PostgreSQL database, including GitHub authentication and app secrets.

## License

The project code is available under the [MIT License](LICENSE). Third-party data and model sources are listed in [attribution](docs/ATTRIBUTION.md).
