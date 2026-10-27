# Hosting

TriageDesk can run on Streamlit Community Cloud with a PostgreSQL database in Neon. This runs independently of your laptop. A Cloudflare Quick Tunnel is another option for temporarily sharing an existing local installation.

## Streamlit Community Cloud and Neon

### 1. Prepare the repository

Keep `pyproject.toml`, `src/`, `ui/`, and `alembic/` at the repository root. The cloud entrypoint is **`ui/community_app.py`**.

This entrypoint runs the UI and a private, loopback-only API in the same installation. It enables GitHub authentication and uses an external PostgreSQL database.

### 2. Create a PostgreSQL database

Create a Neon project and copy its connection string from the **Connect** dialog. Preserve its SSL parameters. See [Neon's connection documentation](https://neon.com/docs/connect/connect-from-any-app).

The database stores connected repositories, issues, encrypted GitHub credentials, analysis results, and reviews.

### 3. Generate an encryption secret

Run this locally:

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Save the generated value for `AUTH_ENCRYPTION_KEY`. Keep it private and retain the same value across deployments so existing stored credentials remain readable.

### 4. Deploy the app

Create an app in Streamlit Community Cloud, select the repository and branch, and choose:

- Main file: `ui/community_app.py`
- Python version: **3.12**

Before deploying, add these values in **Advanced settings → Secrets**. Replace all placeholders:

```toml
DATABASE_URL = "postgresql://USER:PASSWORD@YOUR-NEON-HOST/DATABASE?sslmode=require"
AUTH_ENCRYPTION_KEY = "REPLACE_WITH_YOUR_GENERATED_SECRET"
GROQ_API_KEY = "REPLACE_WITH_YOUR_GROQ_API_KEY"
AI_MODEL = "qwen/qwen3.8-27b"
AI_CONFIDENCE_THRESHOLD = 0.85
AI_BATCH_SIZE = 5
AI_REQUEST_INTERVAL = 10
AUTO_SYNC_SECONDS = 60
GITHUB_CLIENT_ID = ""
```

Use top-level settings and keep API keys on a single line. The checked-in `.streamlit/secrets.toml.example` is a template; populated secrets belong in the hosting settings.

Deploy the app. Startup applies database migrations and starts the private API. See [Streamlit's deployment documentation](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app) for account setup and deployment controls.

### 5. Sign in and connect a repository

1. Create a fine-grained GitHub personal access token for a public repository you maintain.
2. Grant **Metadata: read** and **Issues: read**.
3. Use the token to sign in to TriageDesk.
4. Open **Connect repository**, enter `owner/repository`, and choose **Verify maintainer and import issues**.

GitHub must confirm repository ownership or triage, write, maintain, or admin access. Read access alone does not grant maintainer rights. Each visitor uses their own credential; personal GitHub tokens do not belong in app-wide secrets.

Imported issues are analyzed automatically. Open **Issues**, **Needs review**, or **Reviewed** to inspect the results. Labels remain inside TriageDesk.

### Optional browser sign-in

To enable **Sign in with GitHub**:

1. Register a GitHub App with the deployed app's homepage URL.
2. Enable device flow and read-only repository Metadata and Issues permissions.
3. Install the App on the repositories you want to connect.
4. Add its **Client ID** to `GITHUB_CLIENT_ID` in Streamlit Secrets, then reload or reboot the app.

Sign in using the displayed device code and GitHub verification page. This flow needs no callback route, client secret, or App private key. See [GitHub's device-flow documentation](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app#using-the-device-flow-to-generate-a-user-access-token).

### Persistence and limits

PostgreSQL retains issues, analyses, reviews, and job records across app reboots. Detected closed issues and their dependent local records are removed during synchronization. Keep the database project and back up data you need to retain.

Search indexes use temporary local storage and are rebuilt by repository synchronization after a backend restart. Cached AI analysis remains in PostgreSQL. Browser refreshes or session expiry can require signing in again.

Use one app instance for this setup. Synchronization and analysis continue while a signed-in workspace is open; sleeping hosting or an inactive workspace delays them. Provider quotas and storage allowances also apply.

## Share a local installation temporarily

Start the GitHub-authenticated local setup from the repository root:

```sh
python3 scripts/setup-github-local.py
docker compose up --build -d --wait
```

Add `GROQ_API_KEY` to `.env` to enable labeling, and apply it with `docker compose up -d --wait`.

Install `cloudflared` using the [official downloads](https://developers.cloudflare.com/tunnel/downloads/). On macOS with Homebrew:

```sh
brew install cloudflared
cloudflared tunnel --url http://localhost:8501
```

If you configured another UI port, use that port in the tunnel command. Share the generated HTTPS address. Keep the computer awake, Docker running, and the tunnel open. Press **Ctrl+C** in the tunnel terminal to close the public link.

Only the dashboard port needs a tunnel. Visitors still sign in with GitHub and need maintainer access. See [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

## Troubleshooting

| Problem | What to check |
| --- | --- |
| Package import fails | Deploy from the project root with `src/`, `pyproject.toml`, and `ui/requirements.txt` present. |
| Database startup fails | Check the connection URL, SSL parameters, and database availability. |
| Private API cannot start | Use `ui/community_app.py`, Python 3.12, and valid top-level secrets. |
| Repository access is refused | Confirm maintainer rights, token or App repository selection, and required organization approval. |
| Import is interrupted or busy | Allow the expired job lease to be released, then retry; committed pages remain saved. |
| Issues stay Waiting for AI | Check current key status, provider errors, and quota. See [AI_LABELS.md](AI_LABELS.md). |
| Related search is unavailable after restart | Synchronize the repository to rebuild its temporary search index. |

For backups, updates, and the optional Render deployment, see [DEPLOYMENT.md](DEPLOYMENT.md).
