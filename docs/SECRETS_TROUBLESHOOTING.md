# Groq key added, but AI still says it needs a key

Version **0.3.1** fixes two problems in the Community Cloud setup:

- The private backend was cached without checking for changes to Streamlit Secrets. It could keep running with the settings it received before the Groq key was added.
- The connection screen used the AI setup flag saved with an earlier import. That historical result could keep saying a key was missing even after the backend had loaded one.

The updated helper checks supported settings on each full app run. When they change, it stops the old backend and starts one replacement with the new settings. Concurrent visitors still share one backend. Configuration fingerprints remain inside the server; credentials are never sent to the browser or printed by this check.

The connection screen now uses the backend's **current** setup status. Its analysis counts are explicitly marked **During this import**, so an old count of zero does not describe current background progress.

## Update an existing hosted app

1. Upload the updated project contents to the same GitHub repository and branch used by Streamlit. Keep your deployment entrypoint **`ui/community_app.py`** and Python **3.12**. For the runtime fix, the changed files are `src/triagedesk/community.py`, `ui/community_app.py`, and `ui/account.py`; the full source package also includes tests, version metadata, and this guide.
2. In **Streamlit → App settings → Secrets**, keep the database URL and encryption key unless you are intentionally rotating exposed credentials. Add or check this top-level entry, before any `[section]` header:

   ```toml
   GROQ_API_KEY = "YOUR_NEW_GROQ_KEY"
   AI_CONFIDENCE_THRESHOLD = 0.85
   ```

   Use your actual private key in the app settings. Put each assignment on one line. Do not put the key in GitHub source files, screenshots, or chat. Visual line wrapping in the editor alone does not imply an invalid value. [Streamlit's secret settings](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management).

3. Save the secrets. Reboot the hosted app once after installing this update, then reload the page. Reboot also provides an immediate workaround for the old backend cache before updating the source.
4. Sign in, select your connected repository, and open **Connect repository**. Look for **“Groq key loaded by the backend.”** This confirms that the key reached the API; it does not verify provider acceptance, model availability, or remaining quota.
5. Leave the selected workspace open. New and pending issues continue automatically in bounded batches. Check **Issues → Waiting for AI** and the Overview counts. Completed analyses remain in PostgreSQL and are reused.

No database reset or new migration is needed for this patch. Changing the Groq key alone does not invalidate completed analysis results.

## If the key is loaded but issues still wait

An imported issue count is separate from an AI analysis count. One pass processes up to `AI_BATCH_SIZE` reports (default five). The selected workspace schedules further passes roughly every minute while open, and provider backoff can delay them. A completed human review is also reused instead of generating another AI analysis.

Check that your selected model supports the app's strict JSON-schema output, the key is active in your Groq account, and the account has available quota. A loaded key can still be rejected by the provider. Do not reset the database or assume the key is missing because a historical import says **0 analyzed**.

The red **“The service could not complete this request”** message is a separate API error; the screenshots alone do not establish its cause. If it remains after updating and rebooting, inspect the corresponding app logs and share only the error type/message with credentials and connection strings removed.

## Credentials visible in a screenshot

If credentials were exposed, replace the Groq key and database password in their provider consoles and update the saved database URL. Rotate the application encryption key too when it was exposed; existing encrypted GitHub credentials then require a fresh sign-in. Keep the existing database itself. Do not reuse exposed values in the updated deployment.

## Verification scope

Regression checks cover changed secrets, shared/concurrent visitors, failed and crashed backend recovery, safe key validation, and all combinations of current versus historical import setup status. An isolated PostgreSQL smoke check also exercises the actual Streamlit entrypoint and private API without contacting Groq. No production secret is used, and this does not claim a successful request from your hosted app to the live provider.
