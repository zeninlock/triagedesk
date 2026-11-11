# Deploy TriageDesk using only your browser

You need a GitHub account, a Neon account, a Streamlit Community Cloud account, and an OpenAI API key with API billing available. Your Mac can be turned off after deployment. Everything runs on Streamlit and Neon.

## 1. Put the updated source on GitHub

If you received `triagedesk-cloud-ready.zip`, unzip it. The enclosed folder contains the complete cleaned source; do not upload the ZIP itself.

For the easiest clean deployment, create a new GitHub repository, such as `triagedesk-cloud`. In **Add file → Upload files**, upload the folder's **contents** at the repository root. Check that these paths appear directly at the root:

- `pyproject.toml`, `uv.lock`, `alembic.ini`, and `README.md`
- `ui/community_app.py` and `ui/requirements.txt`
- `src/triagedesk/` and `alembic/versions/`

The root must not be an extra enclosing `triagedesk-cloud-ready/` directory. Include hidden `.streamlit/config.toml` for the theme, and `.gitignore` if uploading using a tool that supports hidden files. In Finder, **Command+Shift+.** shows hidden files. The app works without the theme file if the uploader omits it.

To update an existing repository, replace its source with this cleaned version and remove old files listed in `docs/DATABASE.md`. Uploading new files does not remove obsolete files from GitHub. A fresh repository avoids that cleanup step. Keep `alembic/versions/0001` through `0004`: existing databases need the complete upgrade history.

Do not upload `.env`, populated `secrets.toml`, API keys, or database passwords. The prepared archive excludes private settings.

## 2. Create or select the Neon database

Open [Neon Console](https://console.neon.tech/). Create a project named `triagedesk`, or select the project you already use. Select a database and role; the defaults are suitable for a new project.

Click **Connect**. Copy the PostgreSQL connection string twice:

- With **Connection pooling enabled**: use this as `DATABASE_URL`.
- With **Connection pooling disabled**: use this as `MIGRATION_DATABASE_URL`.

Both must refer to the **same branch, database, and role**. The pooled hostname normally includes `-pooler`. Preserve the query parameters Neon supplies, including `sslmode=require` and, if present, `channel_binding=require`. Copy only the connection URL, without a surrounding `psql` command or shell quotes. [Neon connection pooling documentation](https://neon.com/docs/connect/connection-pooling).

For an existing database, create a backup branch in Neon before deploying this upgrade. The app will apply migration `0004` automatically. It consolidates old reviews, removes the retired classifier tables, and adds work status. See `docs/DATABASE.md` before upgrading a database you want to preserve.

## 3. Generate the encryption secret in Neon

This secret encrypts saved GitHub credentials. It is separate from both your OpenAI key and your database password.

In Neon's **SQL Editor**, run:

```sql
SELECT replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '')
       AS auth_encryption_key;
```

Copy the resulting 64-character value into your private settings for the next step. Keep it stable when redeploying. If you already have a deployed TriageDesk database, retain its existing `AUTH_ENCRYPTION_KEY` instead of generating a replacement; otherwise existing sessions will require users to sign in again.

## 4. Check your OpenAI API project

Open your [OpenAI API project](https://platform.openai.com/). Make sure the API key belongs to the project you intend to use, API billing/credits are available, and the key can call the Responses API with `gpt-4.1-mini`.

The app uses the official SDK and strict structured output. `gpt-4.1-mini` supports this workflow; the model is configurable in secrets. Changing models can trigger new analysis, so use the default for your initial deployment and rehearsal. [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [model documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini).

## 5. Create the Streamlit app

Open [Streamlit Community Cloud](https://share.streamlit.io/) and connect your GitHub account. Choose **Create app**, then use the existing-app option. Select:

| Setting | Value |
| --- | --- |
| Repository | Your cleaned source repository, e.g. `YOUR-ACCOUNT/triagedesk-cloud` |
| Branch | The branch containing the uploaded source, usually `main` |
| Main file path | `ui/community_app.py` |
| Python version, under Advanced settings | **3.12** |

Choose a memorable app URL if available. [Streamlit deployment instructions](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).

## 6. Paste the app secrets

Under **Advanced settings → Secrets**, paste this and replace all placeholders:

```toml
DATABASE_URL = "postgresql://USER:PASSWORD@YOUR-HOST-pooler.neon.tech/neondb?sslmode=require"
MIGRATION_DATABASE_URL = "postgresql://USER:PASSWORD@YOUR-HOST.neon.tech/neondb?sslmode=require"
AUTH_ENCRYPTION_KEY = "YOUR_64_CHARACTER_VALUE_FROM_STEP_3"
OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"
AI_MODEL = "gpt-4.1-mini"
AI_CONFIDENCE_THRESHOLD = 0.85
AI_BATCH_SIZE = 5
AI_REQUEST_INTERVAL = 1
AUTO_SYNC_SECONDS = 60
GITHUB_CLIENT_ID = ""
```

Use your actual Neon strings, including their original query parameters. Keep these as **top-level TOML values**, with each key on one line. Do not add a `[secrets]` heading. `GITHUB_CLIENT_ID` can remain empty; token sign-in works without a GitHub App.

Save and click **Deploy**. Streamlit installs the pinned dependencies, runs the database upgrades using the direct Neon URL, starts the private backend, and shows the sign-in screen. No manual SQL schema creation or separate API deployment is needed.

You can change secrets later in the app's settings. Save, reboot the app if needed, then refresh it. Restarting the backend requeues saved authentication failures using the current key. You can also choose **Run AI now** inside the workspace; it records the retry even if a synchronization pass is already running. [Streamlit Secrets management](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management).

## 7. Create a GitHub sign-in token

In GitHub, open **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.

Choose the account that owns your demo repository as resource owner, set an expiration after your interview, and select that public repository. Grant repository permissions **Metadata: read** and **Issues: read**. A repository you own personally is the simplest demonstration setup; organization access can require approval or additional permission visibility.

Copy the token once and keep it private. In TriageDesk, expand **Sign in with a fine-grained GitHub token**, paste it into **GitHub token**, and choose **Verify GitHub identity**. It belongs in this form, not in Streamlit's app-wide secrets. TriageDesk encrypts it in Neon and returns an opaque application session to the UI.

GitHub must confirm your account owns the repository or has triage, write, maintain, or admin access. A token that can read someone else's public issues does not grant maintainer access. [GitHub token instructions](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).

## 8. Import and verify

In **Connect repository**, enter `YOUR-ACCOUNT/YOUR-REPOSITORY`. For the interview, start with 6–10 open issues in a public repository you own. Leave the fetch limit at 500 and choose **Verify maintainer and import issues**.

Wait for **Imported and organized**. Select the repository in the sidebar and open **Issues**. The first pass handles up to five issues; keep the workspace open for subsequent passes, or choose **Run AI now** when available. The UI shows analysis errors and retry delays if a provider is unavailable.

Verify these before the interview:

1. Issues have exactly one type and priority, and an area where inferable.
2. A simple docs/UI fix can show **help wanted** and **good first issue**; uncertain tasks can remain untagged.
3. Select a row, set **Issue work status** to **in progress**, and save.
4. Refresh, sign back in if needed, and confirm the saved status is still visible.
5. Change one label, save the reviewed labels, and confirm it appears in **Reviewed**.
6. Open **Overview** and **Label guide** to check counts and the color legend.
7. Reopen an already analyzed issue: it should display its saved analysis without a new API request.

The [demo walkthrough](DEMO.md) provides prepared issue text, an interview sequence, and recovery steps.

## Optional: browser sign-in

After token sign-in works, you can register a GitHub App with read access to Issues and Metadata, enable its device flow, and add its **Client ID** as `GITHUB_CLIENT_ID` in Streamlit Secrets. Install/authorize it for your demo repository. Reboot, then use **Sign in with GitHub**. No client secret or callback server is needed for the device-code exchange. [GitHub device flow](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app#using-the-device-flow-to-generate-a-user-access-token).

## Troubleshooting

| What you see | What to do |
| --- | --- |
| Startup failed / database unavailable | Recopy both Neon URLs from the same branch and database, confirm the role can create tables, retain TLS parameters, and reboot. |
| Missing module during deployment | Confirm `src/`, `pyproject.toml`, `ui/requirements.txt`, and the entrypoint are at the documented paths, and Python is 3.12. |
| OpenAI key not loaded | Add `OPENAI_API_KEY` at the top level of Streamlit Secrets, save, and reboot. |
| OpenAI 401 | Replace the invalid key, save, reboot, then choose Run AI now. |
| Billing / credits error | Check your API project's billing, available credits, and usage limits, then explicitly retry. |
| OpenAI 429 | Wait until the displayed retry time; repeated clicks do not bypass provider limits. |
| Model unavailable | Confirm `AI_MODEL = "gpt-4.1-mini"` and the project's model access. |
| Response refused / invalid / truncated | Review that issue manually or choose Run AI now once; automatic repeated calls are paused. |
| Repository access denied | Use the token of its owner/maintainer, select the repository in token permissions, and confirm Issues and Metadata read permissions. |
| Sign-in expired | Sign in again. Issues, labels, reviews, and work statuses remain in Neon. |
| Empty queue | Confirm GitHub Issues are enabled and the repository has open issues; pull requests are excluded. |
| Saved form conflicts | Another change or source update occurred. Refresh, inspect the current value, and submit again. |
| App is asleep | Open it before the interview and let Streamlit wake it. New analysis/sync require an active workspace. |

Use one Streamlit app instance for this setup. A sleeping app or closed browser does not run a permanent background worker. Cached results remain in Neon. Keep provider dashboards available privately during rehearsal, and do not display credentials during the demo.


## Authentication recovery and GPT-5 nano

An authentication warning represents a saved request failure, not a live test of the key currently in Secrets. After changing the key, rebooting the backend permits a fresh attempt and retains all completed analyses. Run AI now also clears retryable failures when it joins an active sync or waits for its short scheduling interval.

Keep OPENAI_API_KEY different from AUTH_ENCRYPTION_KEY: the first comes from OpenAI; the second is the random value used to encrypt GitHub credentials. The app now rejects identical values before making a provider request.

For the original GPT-5, GPT-5 mini, and GPT-5 nano models, the app requests minimal reasoning and reserves a 4,096-token output budget. Reasoning consumes part of the output limit, so a small budget with the default reasoning setting can end before JSON is returned. The model selection remains configurable; no model change is needed to recover from a saved 401. See [OpenAI's GPT-5 parameter documentation](https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_new_params_and_tools) and [reasoning token limits](https://developers.openai.com/api/docs/guides/reasoning).
