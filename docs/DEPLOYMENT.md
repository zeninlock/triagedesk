# Render deployment — prepared, not deployed

No resources have been purchased, no account has been modified, and no hosted URL has been verified. `render.yaml` passed the current [Render Blueprint schema](https://render.com/schema/render.yaml.json). Local container execution is verified separately; schema validity is not a cloud smoke test.

## Prepared topology and cost assumptions

One public Streamlit web service calls one private FastAPI service on port 8000 in Singapore. PostgreSQL 17 is managed, with public database access disabled. A 1 GB paid disk at `/var/data` stores artifacts; the API uses `/var/data/artifacts`. The default Blueprint hosts the synthetic demo read-only. Runtime commands migrate and seed fixtures only; real mode seeds nothing and never trains/downloads weights at startup.

Planning estimate checked against [Render pricing](https://render.com/pricing) on 26 October 2026: two 512 MB services at about $7/month each, small paid PostgreSQL at about $6/month, and a 1 GB artifact disk at $0.25/month: approximately **$20–21/month**, allowing for database storage billing. This is a low-traffic TF-IDF/fixture configuration, not a demonstrated semantic-host memory budget. Use a 2 GB API plan for semantic serving or larger artifacts: roughly **$38–40/month** total under the same assumptions. Taxes, extra bandwidth, larger disks, workspace upgrades and build usage can add cost. Verify the checkout estimate before creating services. [Compute plan IDs](https://render.com/docs/compute-plans) identify RAM/CPU; do not assume free plans provide durable disks or permanent databases.

## Deploy steps requiring the owner

1. Review the code and publish the project folder to a GitHub repository you control. CI is configured but has not run on GitHub until you push it. In Render, connect that repository and create a Blueprint from `render.yaml`; review and approve the paid resources before provisioning.
2. Set a new random `REVIEWER_TOKEN` using Render’s secret environment control; do not reuse the documented local demo token. Keep `READ_ONLY=true` for public exploration. `REVIEWER_NAME` is the installation’s audit identity. UI containers receive neither database credentials nor the reviewer token.
3. Apply the Blueprint. The API command `sh scripts/start-api.sh` runs `alembic upgrade head` before listening. With a single API instance this avoids concurrent startup migrations. For future incompatible migrations, use a separate maintenance migration and backup plan. The artifact disk is not available to Render pre-deploy instances, so artifact provisioning must target the running service, not a pre-deploy job.
4. Inspect startup logs and use the API’s running Shell to check `test -w "$ARTIFACT_DIR"`. The image precreates owned artifact directories for UID 10001; verify actual mounted-disk ownership on Render. If the mount is not writable, correct ownership through the provider’s admin mechanism before proceeding. Cloud disk permissions remain unverified without an account.
5. Visit the public UI, verify the synthetic banner, overview, queue and unavailable-model states. Private services use Render’s TCP health probe; from the running UI/API Shell, request `http://<private-api-host>:8000/health/ready` to verify SQL/migrations. The UI has HTTP health path `/_stcore/health`. Source: [Render health checks](https://render.com/docs/health-checks).

## Provision real artifacts deliberately

Train on your local machine, not during ordinary hosted startup. Use the exact lock and a new immutable model version. Provision only trusted project-generated artifacts. The image includes a shell and a permissioned `.ssh` directory for the app user, following [Render’s Docker SSH requirements](https://render.com/docs/ssh).

Use the actual SSH destination supplied by Render’s Connect dialog; no destination is fabricated here. You can transfer an owner-generated tar archive through standard input to the **running API service**:

```sh
# Local: include the chosen model folder; optional embedding-model/cache directories reduce downloads.
tar -czf trusted-model.tar.gz -C artifacts models
# Replace the destination with the exact Connect command for your service.
ssh <RENDER_SSH_DESTINATION> 'cd /app && python scripts/provision_artifacts.py' < trusted-model.tar.gz
```

The helper safely extracts under `ARTIFACT_DIR` and refuses to replace different existing files. It does not activate a model. In the API’s running Shell, set `MODE=real`, import the chosen repository using the private CLI and optional `GITHUB_TOKEN`, run `triagedesk activate <version>`, `triagedesk predict`, then `triagedesk index`. A fresh import has different internal IDs, so **rebuild retrieval mappings on the destination database**, even if cached vectors are copied. The saved evaluation remains evidence for its frozen collection, not for newly downloaded/edited reports.

For semantic retrieval, set `INSTALL_SEMANTIC=true` on the API service before rebuilding (Render makes matching nonsecret environment variables available as build arguments). Upgrade API memory, then run `triagedesk index --semantic --allow-download` once from the running service. Subsequent requests use local weights. The lock chooses CPU-only Linux PyTorch wheels. Ensure disk space for weights/cache (the compact weights are about 90 MB; dependency images and tokenizer files add storage). The TF-IDF fallback remains explicitly labeled if weights are missing.

## Enable a reviewer and perform the hosted smoke test

When ready, set API `READ_ONLY=false` while retaining the new secret token. Visitors without the token still cannot write. Enter it in the UI password field over HTTPS; a shared token grants reviewer capability and one configured audit identity. Keep administrative jobs private. A public rate limit or managed proxy is a possible later addition if traffic measurements justify it; there is no HTTP import/training endpoint.

Record the actual hosted URL, timestamp, version and results only after: loading the UI; checking private API readiness; filtering a queue; inspecting current text/model/source attribution; saving a synthetic review through authorized access; confirming history/count changes; confirming an unauthorized write fails; restarting the API and checking persistence; verifying model-unavailable and semantic-fallback behavior where applicable. For the real production dataset, use a designated demonstration report or keep it read-only. Do not run the fixture smoke script on real data.

## Backups, restore and rollback

Take a PostgreSQL custom-format logical backup before migrations or replacing an environment. Locally:

```sh
docker compose exec -T db pg_dump -U triagedesk -d triagedesk -Fc > triagedesk.dump
```

On Render, use its logical export/PITR tools or `pg_dump` against an explicitly authorized private connection. [Paid PostgreSQL backups](https://render.com/docs/postgresql-backups) provide recovery support; free databases do not. Keep an additional off-provider backup and a matching copy of model folders, all split manifests, active checksum manifest, vector mapping and cache configuration. Database and artifact backups form one provenance set.

Restore into a **new empty staging database** with `pg_restore --no-owner --no-acl -d <STAGING_DATABASE_URL> triagedesk.dump`; verify issue/review counts, current snapshots, foreign keys and readiness before changing the service connection. Do not restore over a live database. Rebuild the index if IDs or text hashes change. Restore trusted model folders and activate the appropriate version. Validate a restore periodically; a backup that has not been restored is not verified recovery. To roll back a model, activate a previous saved version and regenerate batch suggestions; retain review history. Schema rollback is a separate reviewed operation, not automatic startup behavior.

Persistent disks prevent horizontal scaling and can entail downtime during deploys; this MVP accepts one API instance. See [Render disks](https://render.com/docs/disks) and [deployment commands](https://render.com/docs/deploys). No high-availability or zero-downtime claim is made.
