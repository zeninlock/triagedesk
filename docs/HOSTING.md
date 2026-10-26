# Host TriageDesk with verified GitHub maintainers

This guide deploys the updated application: sign in → verify repository permissions → import actual public issues → prepare suggestions/search → review locally. It uses the Docker-based Render blueprint included in this repository. No hosted URL or live OAuth registration is claimed by the source package.

## What is deployed

| Resource | Purpose | Exposure |
|---|---|---|
| `triagedesk-ui` | Streamlit dashboard and account/connection screens | Public HTTPS web service |
| `triagedesk-api` | GitHub identity checks, authorization, imports, classification, SQL, and reviews | Private service, reached by the UI |
| `triagedesk-db` | Issues, snapshots, reviews, sessions, repository grants, and import jobs | Private managed PostgreSQL |
| API artifact disk | Saved classifiers and search indexes | Mounted only into the backend |

The blueprint uses paid compute, database, and disk resources. Review the current resource list and total shown by Render before choosing **Deploy Blueprint**. No resources are purchased by running the local project or reading this guide.

## 1. Publish this updated source to GitHub

Publish the directory containing this README, Dockerfile, and `render.yaml`, with those files at the repository root. See [the upload guide](GITHUB_UPLOAD.md). If you already published an older copy, commit and push the updated files to that same repository.

Local settings and generated credentials must stay outside Git. `.env.example`, `uv.lock`, migrations, and the GitHub workflow belong in the repository. The large real snapshot bundle is not needed for a fresh deployment: maintainers can import their actual public issues from the dashboard.

## 2. Create the Render deployment

1. Sign in at the [Render dashboard](https://dashboard.render.com/).
2. Choose **New → Blueprint** and connect the GitHub repository containing this project.
3. Select the branch containing the updated source and use `render.yaml` at its root.
4. Review the private API, public UI, database, persistent disk, region, and paid plans.
5. Choose **Deploy Blueprint** when you are ready to provision those resources.
6. Wait for the resources to become available. Open the public URL listed for **triagedesk-ui**.

Render supplies the internal database URL, private API hostname, and a generated encryption secret through the blueprint. Startup applies Alembic migration `0002`; `MODE=real` means synthetic fixtures are not loaded into the workspace.

The first working sign-in option is a fine-grained GitHub token. The browser/device sign-in button can be enabled with the optional GitHub App setup below.

Official reference: [Render Blueprints](https://render.com/docs/infrastructure-as-code).

## 3. Enable the preferred browser sign-in

Register a **GitHub App** owned by you or your organization. Configure:

- Homepage: the actual public dashboard URL obtained from Render.
- Repository permissions: **Metadata: read** and **Issues: read**.
- Device flow: enabled.
- Installation access: allow the accounts/repositories you intend to serve. For multiple maintainers, make the App available to the relevant other accounts.
- Install the App on the public repositories that will be connected. Organization policy may require an owner to approve it.

Copy the App's **Client ID**, which is different from its numeric App ID. Add `GITHUB_CLIENT_ID` to the **triagedesk-api** service's environment on Render, save it, and redeploy that service. No client secret or private-key file is required by this device-flow implementation.

Keep the generated `AUTH_ENCRYPTION_KEY` unchanged across routine deployments. The API uses it to read encrypted provider credentials already stored in the database. If it is rotated, existing sessions become unreadable and users must sign in again.

After the API restarts, the dashboard shows **Sign in with GitHub**. The user receives a short-lived code, opens GitHub in another tab, approves the App, and returns to the still-open dashboard. The app polls GitHub at the permitted interval and verifies the identity with `GET /user`. The provider token stays out of browser URLs and is encrypted in backend storage. Refresh tokens are not retained; a new sign-in is required after expiry.

The device flow avoids a redirect callback between the separate Streamlit and private API services. A browser refresh may reset the Streamlit session and require signing in again; normal in-app navigation retains it. This MVP does not implement persistent browser login cookies.

Optional: once browser sign-in is configured and checked, set `ALLOW_TOKEN_LOGIN=false` to remove token entry from the interface.

Official reference: [GitHub App device flow](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app#using-the-device-flow-to-generate-a-user-access-token).

## 4. Fine-grained token sign-in

This option works without registering the optional GitHub App:

1. The maintainer creates a fine-grained personal access token for the selected public repository, with **Metadata: read** and **Issues: read**. An organization may need to approve the token.
2. In the dashboard, expand **Sign in with a fine-grained GitHub token** and submit it to **Verify GitHub identity**.
3. The API checks `GET /user` and creates an expiring application session. A submitted username is never accepted as proof of identity.

The token is a GitHub credential, not the old local reviewer-demo token. It is sent through the HTTPS UI, verified by the API, and encrypted in the backend database. Do not put a token in a repository URL or send it through chat. The app's opaque session token is held in the UI's server-side session; only its digest is persisted by the API.

Official reference: [Creating fine-grained personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).

## 5. Connect and organize real issues

After signing in:

1. Open **Connect repository**.
2. Enter `owner/repository` or its canonical `https://github.com/owner/repository` URL.
3. Select a fetch cap, up to 3,000 GitHub response objects.
4. Choose **Verify maintainer and import issues**.
5. Watch the progress stages: verify access, fetch issues, categorize, build search, ready to review.
6. Select the repository and open the review queue. Use the category filter to inspect bugs, enhancements, and questions.

Authentication and maintainership are separate checks. The API accepts verified personal repository owners or a GitHub-confirmed triage, write, maintain, or admin role. A read-only collaborator is refused even when their token can read public issues. Repository identity is checked by numeric GitHub IDs, not only by names. Maintainer access is rechecked before imports/syncs and every review or relationship-judgment write. Connected-workspace reads refresh their permission check at least every five minutes and fail closed if GitHub no longer confirms access.

Production reads are scoped to the signed-in user's connected workspaces. The API requires a connected repository selection for issue lists, dashboards, and text searches. The old shared reviewer token cannot authorize production requests.

Only public repositories with an enabled issue tracker are supported. GitHub labels and source text are preserved. Pull requests are excluded, repeated imports update existing records, and source changes get new snapshots.

### How categories are produced

- A compatible active classifier trained for that repository is used when available.
- Otherwise, recognized GitHub category labels provide explicit **source-label** suggestions.
- Remaining text may receive an unscored **rule-based** suggestion.
- Ambiguous or unsupported reports remain for manual categorization rather than being forced into a category.

The UI identifies each suggestion's method. Source-label and rule-based suggestions carry no ML probability or measured accuracy; all require human review. They are excluded from the recorded trained-classifier evaluation. Saved human decisions take precedence. No remote GitHub labels are changed.

### Updating later

Open **Connect repository** again, enter the same repository, select **Synchronize changes to an already connected repository**, and submit. The job fetches updates, prepares current suggestions, and rebuilds search. Capped imports are partial. Synchronization fetches updates from the saved checkpoint; it does not prove the initial history is complete. To extend a partial historical collection, increase the cap and run another full import. This is manual synchronization, not a webhook subscription or background schedule.

## 6. Runtime settings

| Setting | Production value or purpose |
|---|---|
| `MODE` | `real` |
| `AUTH_MODE` | `github`; the demo shared token is ignored |
| `AUTH_ENCRYPTION_KEY` | Random secret of at least 32 characters; generated by the blueprint |
| `READ_ONLY` | `false` for verified imports/reviews; `true` disables both |
| `GITHUB_CLIENT_ID` | Optional GitHub App client ID for device sign-in |
| `ALLOW_TOKEN_LOGIN` | `true` enables fine-grained token sign-in; can be disabled after App setup |
| `SESSION_HOURS` | 8 by default, configurable from 1 to 24; provider expiry can shorten it |
| `DATABASE_URL` | Private PostgreSQL URL supplied by Render |
| `ARTIFACT_DIR` | `/var/data/artifacts` on the persistent API disk |
| `API_HOST`, `API_PORT` | Private backend address supplied to the UI |

The API remains a single instance. A database-enforced unique active slot permits one import/index job per installation. Jobs retain progress in SQL and renew a three-minute lease. If a process stops, a status check or later submission marks an expired lease failed and frees the slot; retry continues from persisted GitHub page checkpoints. This is not a distributed durable worker queue. Avoid running separate administrative indexing jobs concurrently with web imports.

## 7. Verify the actual hosted installation

A schema-valid blueprint does not prove a deployment works. After provisioning, check:

- The public URL serves the sign-in screen over HTTPS, without a shared reviewer-token prompt.
- An actual maintainer can sign in, connect their public repository, and see real imported issues and suggestion provenance.
- A different signed-in account with only read access is denied connection/review rights.
- A saved decision has the verified GitHub identity in its history and survives a service restart.
- Sign-out invalidates that application's session; revoked GitHub permissions prevent subsequent writes.
- The deployment logs contain request routes/statuses, not tokens or issue bodies.

Recorded automated tests mock GitHub identity/permission responses and exercise actual PostgreSQL separately. Completing real sign-in with your own GitHub App/token and checking your hosted URL require your account setup. No fake user or live OAuth result is presented as evidence.

## Troubleshooting

| Symptom | Action |
|---|---|
| Browser sign-in button is missing | Add the GitHub App Client ID to the API service and restart it. Token sign-in can remain available. |
| GitHub reports device flow disabled | Enable it on the GitHub App registration, then start a new sign-in attempt. |
| Signed in, but connection is refused | Check the actual repository role, App installation/token repository selection, and any organization approval. |
| Issues fetch is denied after identity verification | The credential also needs Issues: read for that repository. |
| Queue is empty | Check whether the repository has issues, the import completed, and the active filters match. |
| GitHub quota exhausted | Wait for GitHub's reset and retry; completed import pages remain saved. |
| Import was interrupted | Retry after its lease expires; one active job is allowed per installation. |
| Encryption configuration error | Supply a generated secret of at least 32 characters. Do not use a public demonstration value. |
| Authenticated text classification unavailable | A trained classifier is optional. Imported reports still use labeled/rule suggestions and manual review. |
| Semantic search unavailable | The default image uses TF-IDF. Optional semantic dependencies and weights require a separate build and more memory. |

See [deployment operations](DEPLOYMENT.md) for backups and [the README](../README.md) for model evaluation limits.
