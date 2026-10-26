# Host TriageDesk temporarily for free

Use **Streamlit Community Cloud + Neon Free** for a public demo that works while your laptop is off. Both offer free plans; no Render deployment, paid disk, or GPU is needed. This guide also includes a **Cloudflare Quick Tunnel** for sharing a running local installation for a short session.

Provider details checked on **26 October 2026**. Select the free plans described here; the existing `render.yaml` provisions paid resources and is not used by either method below. This source update prepares deployment; it does not create your provider accounts or a hosted URL.

## Choose your setup

| | Free cloud demo — recommended | Temporary link from your laptop |
|---|---|---|
| Services | Streamlit Community Cloud + Neon Free | Existing Docker installation + Cloudflare Quick Tunnel |
| Laptop can be off? | Yes | No |
| Public address | A `https://...streamlit.app` address | A temporary `https://...trycloudflare.com` address |
| Database | External PostgreSQL on Neon | PostgreSQL in your local Docker volume |
| Appropriate use | Portfolio, project submission, small maintainer demo | Interview, short demonstration, testing with a friend |
| Main limit | Free capacity, sleep/restart behavior, temporary app filesystem | Computer, Docker, internet, and tunnel must remain running |

## Option A: Free cloud demo

### 1. Upload the updated project to GitHub

Use the **updated** source folder containing this guide. Publish its contents at the root of a GitHub repository; do not publish a parent folder containing several project copies. See [GITHUB_UPLOAD.md](GITHUB_UPLOAD.md) if needed.

The repository must contain:

```text
README.md
pyproject.toml
uv.lock
alembic.ini
alembic/
config/
src/triagedesk/
ui/app.py
ui/account.py
ui/community_app.py
ui/requirements.txt
```

`ui/community_app.py` is the new cloud entrypoint. It starts one private FastAPI process on loopback, applies database migrations, waits for readiness, then opens the existing dashboard. It caches that backend across visitors and reruns. Only the Streamlit interface is public. GitHub authentication and repository permission checks still run in the API.

`ui/requirements.txt` installs the project's base Python dependencies. Community Cloud searches the entrypoint directory before the repository root, so this file selects the small base installation rather than optional PyTorch/semantic dependencies. The existing locked Docker/development workflow remains available separately.

Keep `.env`, `.streamlit/secrets.toml`, backups, provider credentials, and generated datasets/models outside Git. Only the unfilled `.streamlit/secrets.toml.example` template belongs in the source repository.

### 2. Create a free PostgreSQL database

1. Open [Neon](https://neon.com/) and create an account.
2. Select the **Free** plan and create a project, for example `triagedesk-demo`.
3. Keep the database and role created for this project. Open **Connect** and copy the PostgreSQL connection string. A direct connection is sufficient for this single-instance demo; use it for the automatic migrations too.
4. Keep the SSL query parameters provided by Neon. The URL will resemble:

   ```text
   postgresql://USER:PASSWORD@YOUR-NEON-HOST/DATABASE?sslmode=require
   ```

5. Save the real connection string privately for the next step. Do not paste it into a README or commit it.

Neon's current Free plan is **$0, without a credit card**, with **1 GB storage and 100 CU-hours per project per month**. Its compute can scale to zero after inactivity, so an initial request can take longer. Check usage in Neon and keep this a small demo. [Official pricing](https://neon.com/pricing); [connection instructions](https://neon.com/docs/connect/connect-from-any-app).

TriageDesk accepts Neon's `postgresql://` string and selects its installed psycopg driver automatically. You do not need to create tables by hand.

### 3. Generate an application encryption secret

Run this on your own computer:

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Copy the generated value privately. It encrypts GitHub credentials stored in the database. Keep the same value across reboots and source updates. It is separate from your database password, a GitHub token, and a GitHub App Client ID.

### 4. Create the free Streamlit app

1. Open [Streamlit Community Cloud](https://share.streamlit.io/) and sign in. Link the GitHub account that owns the source repository.
2. Choose **Create app**, then choose to deploy an existing app from GitHub.
3. Select your repository and branch.
4. Set **Main file path** to **`ui/community_app.py`**. Using `ui/app.py` alone will not start the API on this host.
5. Optionally choose an available app subdomain.
6. Open **Advanced settings** and select **Python 3.12**. This project requires Python 3.12.
7. Paste the following into **Secrets**, replacing both placeholders with the private values from steps 2 and 3:

   ```toml
   DATABASE_URL = "postgresql://USER:PASSWORD@YOUR-NEON-HOST/DATABASE?sslmode=require"
   AUTH_ENCRYPTION_KEY = "YOUR_RANDOM_SECRET_FROM_STEP_3"
   GITHUB_CLIENT_ID = ""
   ```

   Keep these settings at the top level, without a `[section]` header. Leave the optional Client ID empty for the first deployment.
8. Save the settings and select **Deploy**.
9. Wait for package installation and startup. Open the app's assigned `https://...streamlit.app` URL.

Community Cloud is a free hosting service. Its deployment interface lets you select the source repository, entrypoint, Python version, and private secrets. [Service](https://streamlit.io/cloud); [deployment instructions](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy); [secret settings](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management).

The helper enforces `MODE=real`, `AUTH_MODE=github`, individual GitHub sessions, and no shared reviewer/provider token. You do not need Docker, a public API service, or the local fixture `.env` on Community Cloud. Creating a Streamlit hosting account does not automatically sign a visitor into TriageDesk.

### 5. Sign in as a maintainer

For the first demo, use the existing fine-grained GitHub-token option; no GitHub App registration is required:

1. In GitHub, create a fine-grained personal access token for a public repository you own or maintain.
2. Grant **Metadata: read** and **Issues: read**. Select the intended repository and complete any required organization approval.
3. Open the hosted dashboard and expand **Sign in with a fine-grained GitHub token**.
4. Enter your token into the password field and choose **Verify GitHub identity**.

The API verifies the account through GitHub. Repository maintainership is checked separately when connecting or writing: personal ownership or a GitHub-confirmed triage, write, maintain, or admin role is required. Knowing a public repository URL or having read access alone does not grant maintainer rights.

Each visitor signs in with their own account credential. Do not add a maintainer's personal token to the app-wide secrets. The API encrypts provider credentials, stores application-session digests, expires sessions, and rechecks repository permissions. This application reads GitHub and saves decisions in its own database; it does not modify GitHub labels or issues.

### 6. Connect a public repository and sort its actual issues

1. Open **Connect repository**.
2. Paste `your-account/your-repository` or its canonical GitHub URL.
3. Start with a fetch cap of **100–200** response objects to keep the free demo small.
4. Choose **Verify maintainer and import issues** and watch progress.
5. Select the connected repository. Open **Review queue** and filter by **bug**, **enhancement**, or **question**.
6. Accept or correct a suggestion, save a note, and inspect its review history.

Pull requests are excluded; capped imports are partial. Clear source labels and text rules supply suggestions when no compatible trained classifier is installed. Ambiguous reports remain for manual categorization. These suggestions have no fabricated ML accuracy or probability. The default free setup uses TF-IDF related-issue search; it does not download MiniLM or train a classifier at startup.

Later, use **Synchronize changes to an already connected repository** in the connection form. To extend a partial historical import, increase the cap and run another full import. Only one import/index job runs at a time. Synchronization is manual, not a GitHub webhook subscription.

### 7. Optional: Enable the GitHub sign-in button

After the token-based demo works:

1. Register a **GitHub App**. Set its homepage to the real Streamlit app URL.
2. Enable **device flow**, with repository **Metadata: read** and **Issues: read** permissions.
3. Install the App on the public repositories you want to connect. Make its installation availability appropriate for the accounts you intend to serve; organizations may require approval.
4. Copy the App's **Client ID**, not its numeric App ID.
5. In Community Cloud, open your app's **Settings → Secrets**, fill `GITHUB_CLIENT_ID`, save, and **Reboot** the app.
6. Use **Sign in with GitHub**, open GitHub's verification page, approve the displayed code, and return to the dashboard.

This implementation uses device authorization and needs no callback route, client secret, or App private key. It does not retain refresh tokens. A browser refresh or application restart may require signing in again. [GitHub's device-flow documentation](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app#using-the-device-flow-to-generate-a-user-access-token).

### Free-demo persistence and limits

- **Issues, snapshots, predictions, review history, and job progress:** stored in Neon and retained across app reboots, as long as you keep the database/project. Back up important data; the free allowance is finite.
- **Credentials:** remain encrypted in Neon. Preserve `AUTH_ENCRYPTION_KEY`; changing it makes existing encrypted credentials unreadable and requires a new sign-in.
- **Browser sign-in state:** may reset after refresh, sleep, or restart. Sign in again.
- **Search indexes and any uploaded models:** live in a temporary directory and can disappear when the backend restarts. Re-run a connection synchronization/full import to rebuild TF-IDF search from database issues. Historical evaluation artifacts are not bundled into this deployment.
- **Interrupted import:** committed pages remain in PostgreSQL. After the three-minute job lease expires, retry from the connection form. Sleep/restart does not automatically restart a worker.
- **Capacity:** one Streamlit app and one private API process share free capacity. Start with a small backlog, avoid the optional semantic dependencies, and avoid training or benchmarking in the cloud app. Availability and resource limits belong to the providers; this is a small demonstration setup.

### Check your hosted demo

Open the actual public URL in a fresh browser session. Confirm the sign-in screen appears; sign in as a real maintainer; import a small public repository; save a review. Reboot the app and confirm the review remains after signing in again. A different account without maintainer rights should be refused when connecting that repository. Check related search again after rebuilding an index if needed.

These owner-account checks complete the live deployment verification. Local automated checks do not prove that your Neon connection, Streamlit account, or real GitHub credential has been configured correctly.

## Option B: A free temporary link from your laptop

Use this when the project already runs locally and you only need a link during a demonstration. There is no separate cloud database or hosting account to set up. The laptop remains the server.

### 1. Start verified GitHub mode locally

If a verified local installation already runs, keep it running and skip directly to step 2 using its current dashboard port. Otherwise, in the project root, with Docker Desktop running:

```sh
python3 scripts/setup-github-local.py
docker compose up --build -d --wait
```

Open `http://localhost:8501` and verify that you see GitHub sign-in. The setup helper preserves existing settings and creates a private encryption key. Use the token sign-in flow from option A, or set `GITHUB_CLIENT_ID` locally for the optional App flow.

If port 8501 is occupied, choose a separate set of ports with `--db-port`, `--api-port`, and `--ui-port`; use the chosen UI port in the tunnel command too. The earlier connected installation in this workspace used `http://localhost:18510`; check your own running installation rather than assuming that port exists on another computer.

### 2. Install and start Cloudflare's tunnel client

Install `cloudflared` using the [official downloads](https://developers.cloudflare.com/tunnel/downloads/). With Homebrew on macOS:

```sh
brew install cloudflared
```

Then start a Quick Tunnel to **the dashboard port only**:

```sh
cloudflared tunnel --url http://localhost:8501
```

If using the earlier local dashboard port, use `http://localhost:18510` instead. Open the actual `https://...trycloudflare.com` URL printed by the client. Do not publish the API port or the PostgreSQL port.

Quick Tunnels provide a temporary address without a Cloudflare account or domain. The address ends when the tunnel stops and can change on the next run. [Official Quick Tunnel instructions](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

### 3. Share, then stop the demo

Share the generated HTTPS link. Visitors still need their own GitHub sign-in and maintainer permissions inside TriageDesk. Keep the computer awake, Docker running, internet connected, and the tunnel terminal open. Closing the laptop or stopping the tunnel makes the public link unavailable.

Press **Ctrl+C** in the tunnel terminal to remove the public link. You can then stop the local services with `docker compose stop`. Local named volumes retain data; deleting volumes removes that storage.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Missing `triagedesk` package | Publish `pyproject.toml`, `src/`, and `ui/requirements.txt`; deploy `ui/community_app.py` from the project root. |
| Python version rejected | Select **3.12** in Community Cloud's Advanced settings. |
| Required-secret error | Add both top-level secrets and replace the example placeholders, then reboot. |
| Database startup fails | Copy Neon's real connection URL, including its database name/password/SSL query. Check the project is available and within its free allowance. |
| Cannot reach the API on Community Cloud | Deploy **`ui/community_app.py`**, not the separate-service `ui/app.py`. Reboot after updating secrets. |
| Sign-in button is missing | Token login works first. Add a real GitHub App Client ID and enable its device flow for the optional button. |
| Identity verified but repository refused | Confirm actual maintainer rights, token/App repository selection, Issues: read, and any organization approval. |
| Empty review queue | Check the repository has issues, the import completed, and the filters/repository selection match. |
| Related search unavailable after reboot | Sign in and run repository synchronization/full import to rebuild the temporary index. |
| Import interrupted or busy | Wait for the three-minute lease to expire and retry; completed pages remain saved. |
| GitHub quota exhausted | Wait for GitHub's reset, then retry the import. |
| Free app stops or is slow | Open/wake or reboot it, inspect the hosting logs, reduce the backlog, and check Neon usage. |
| Tunnel address fails | Confirm the local dashboard works, match its UI port, keep the laptop awake, and use the latest generated URL. |

For backup and recovery details, see [DEPLOYMENT.md](DEPLOYMENT.md). For evaluation limits, see [EVALUATION.md](EVALUATION.md).

## Checks recorded for this update

The full local suite passed **74 tests**, including **eight PostgreSQL integration tests** (`evidence/free-hosting-tests.xml`). A separate Linux container check ran `ui/community_app.py` against actual PostgreSQL, rendered the token sign-in page, confirmed `MODE=real` and `AUTH_MODE=github`, rejected unauthenticated workspace data with HTTP 401, and reused the same private backend for two simulated visitors (`evidence/free-hosting-smoke.json`). Lint, formatting, and Alembic drift checks passed.

These checks used local PostgreSQL, not a live Neon project or Community Cloud deployment. Real provider-account setup and maintainer sign-in remain the final verification steps in your accounts.
