# Verified-maintainer update

Implemented GitHub App device sign-in, fine-grained token identity verification, encrypted backend credentials, expiring/revocable application sessions, per-repository role checks, scoped workspaces, a dashboard connection form, observable bounded import/sync jobs, source-label/rule fallback categorization, and the production Render blueprint. Current automated local run: 68 passing tests including eight PostgreSQL integration cases. See `evidence/hosted-upgrade-tests.xml` after verification and [HOSTING.md](HOSTING.md) for setup.

Owner actions remain: publish the updated source, provision Render resources, register/install an optional GitHub App and add its client ID (or use fine-grained token sign-in), and verify a real maintainer session against the hosted URL. Human retrieval judgments and a maintainer usability study also remain pending. No live OAuth or cloud-deployment success is claimed.

---

# Milestones and handoff — 26 October 2026

## 1. Runnable foundation — locally verified

Started in an empty workspace; no applicable AGENTS.md was found. Defined product assumptions/stories/acceptance criteria. Added PostgreSQL schema, frozen Alembic migration, typed FastAPI routes, Streamlit views, fixture seeding, persistent volumes, health checks and protected writes. Docker Compose reached healthy API/UI states. Browser inspection showed the actual synthetic dashboard. No bulk download or model weights are required for fixture startup.

## 2. Real issue pipeline — implemented and exercised

Audited six candidates rather than assuming popularity meant suitable labels. A 1,165-issue Streamlit pilot lacked question examples and was rejected for classification. Verified VS Code’s actual `*question` convention, collected 3,000 REST objects and persisted 2,999 issues, excluding one PR. Anonymous quota was respected; the connected GitHub plugin supplied a serial capped REST export for the final collection. No token was extracted. Normal CLI import/sync remains direct REST with optional environment token, pagination links, metadata ETag, bounded retries and atomic page checkpoints. Reimport, overlap and failed-page rollback were verified with mocked responses on PostgreSQL.

## 3. Classification — real evaluation sealed

Frozen dataset `dataset-66cb4613b0925284`: 1,123 usable examples, 786/168/169 chronological split, all classes supported. Majority baseline and three Pipeline settings evaluated; validation selected the balanced unigram model and threshold 0.55. Model `vscode-tfidf-v1` saved/reload-verified and activated. Test macro-F1 0.5446 versus 0.2847 majority; accuracy 0.6923 versus 0.7456 majority. Minority-class weakness and retrospective snapshot limitations documented. 2,999 source-repository predictions persisted. No test-driven retuning performed.

## 4. Retrieval and review — locally verified

TF-IDF and pinned Apache-2.0 MiniLM indexes generated for 4,164 real issues. Cache/hash reuse, changed text, same-repository filtering, self-exclusion, stale/unavailable records and historical candidate dates checked. API served five real semantic candidates. A browser review save displayed human category and audit history. HTTP protected writes, manual category without a model, repeated submissions, stale saves, concurrent reviewer conflicts and filtered dashboard updates passed. Saved fixture review survived database/API restart and container recreation with the same volume. A frozen 39-query comparison pool is ready; relevance judgments are pending and no retrieval quality metric is invented.

## 5. Verification and delivery — locally verified

46 tests passed locally, including five PostgreSQL integration tests; lint, formatting, migration drift and Render schema validation passed. Both default and optional CPU Docker images build. The optional Linux CPU container served the real classifier and five semantic candidates from a read-only artifact mount. The delivered real-data backup and artifacts were restored into a separate empty database; original/restored counts and model availability matched. Native real-data latency measured for 100 requests per operation; hardware, p50/p95 and cold loading recorded in `evidence/benchmark-real.json`. Browser screenshots are from the actual application. CI configuration, Render deployment/runbook, study materials, demo script, interview answers and evidence-based résumé drafts are included.

Engineering QA improvements: queue Inspect button now navigates directly to details; retrieval fetches current metadata in bounded ranked batches; external GitHub IDs protect future review exports across restored/remapped internal IDs; Linux semantic wheels are CPU-only. These came from development checks, not user research.

## Remaining evidence and owner actions

- Push to a repository you control and observe an actual remote CI run; local test success is not a hosted CI result.
- Review the generated code and decisions personally before presenting it as your own portfolio work.
- Complete genuine relevance judgments in the separate frozen pool, adjudicate uncertainty, and run `evaluate-retrieval`. Do not enter invented judgments.
- Recruit 3–5 intended users yourself using the prepared protocol; record observations and implement one justified improvement with follow-up. No people were contacted and no user findings exist.
- Review hosting costs, connect your Render/GitHub account, create the paid Blueprint resources, verify disk ownership and provision trusted real artifacts if desired. Smoke-test the actual hosted app before adding a URL or claiming deployment. No spending or account changes were made.
- New imports can use your optional GITHUB_TOKEN; no credentials are required for the existing fixture demo or already collected local evidence.

The stronger portfolio version remains incomplete until those external/human evidence steps occur. Exact frozen model inputs and retrieval-pool text stay in the separate artifact/data deliverable, not the source repository.


## Version 0.3 — 27 October 2026

Implemented automatic Groq multi-label classification, PostgreSQL cache/claims, per-repository taxonomies, label distribution charts, hierarchical tabs, uncertainty-only review, and a separate Reviewed view. Active workspaces poll for source changes and continue bounded AI batches. Confirmed closures purge the issue and its local dependent records. Initial live imports request recently updated open issues; historical CLI imports retain open/closed behavior.

Verified 101 local tests including 12 PostgreSQL cases, migration preservation, and synthetic browser navigation. The source update requires deployment and an owner-supplied GROQ_API_KEY for actual provider calls. No new classification accuracy or live provider success is claimed.

## Version 0.3.1 — 27 October 2026

Fixed the Community Cloud helper retaining a private backend with obsolete secrets. One thread-safe manager now checks supported configuration on each full app run, stops the previous child before replacement, and shares the current child across visitors. The connection notice reads current API setup status instead of the flag recorded by an earlier import; counts are explicitly historical.

Verified 118 local tests including 12 PostgreSQL cases. A separate entrypoint smoke check uses actual API processes and isolated PostgreSQL to verify adding, replacing, and removing dummy keys, threshold updates, process reuse, and cleanup. Live Groq calls and the user's hosted deployment were not tested. The owner must publish the updated source and reboot the hosted app once.

## Version 0.3.2 — 27 October 2026

Added visible queued/running/failed AI progress, fixed provider reason codes and safe warning logs, retry times, per-issue failure details, and an authenticated direct-analysis action. That action skips GitHub issue fetching and search rebuilding, reuses completed analyses, and retains quota/network backoff. Ready reports are selected before applying the batch limit, so blocked rows do not prevent eligible reports from being analyzed. Workspace rows refresh when analysis state changes even if a job completed between polling checks.

Verified 133 local tests including 13 PostgreSQL cases. The five-issue API workflow uses actual request/response-validation code with a simulated provider. PostgreSQL checks cover failed-analysis visibility and successful retry/cache reuse. No live Groq success or hosted latency improvement is claimed; the screenshot does not establish the production cause of waiting. The GitHub repository's default branch was read and contained version 0.3.1; the Streamlit deployment's selected branch was not inspected.

## Version 0.3.3 — 27 October 2026

Read the provider dashboard and queried the hosted database with SELECT during the subsequent investigation. The recorded calls succeeded quickly, while three current issue analyses were failed with `invalid_output`. The running installation remained at 0.3.1. No production credential was retrieved or used and no hosted data or source was changed.

Fixed the classifier discarding an entire usable response and retrying indefinitely. Evidence formatting is normalized conservatively; unsupported suggestions are removed and the result is saved as uncertain for human review. Invalid response structures pause automatic retries. The cache identity and existing successful/human decisions remain unchanged. The exact offending field in historical responses is unavailable because those bodies were discarded.

Verified 140 local tests including 14 PostgreSQL cases. A PostgreSQL regression reproduces two reviewed reports beside three legacy invalid_output failures, explicitly retries those three, then verifies saved Needs review results and zero further provider calls on repeated passes. Provider responses in these regression tests are simulated; the updated hosted behavior still requires deployment and verification.

## Version 0.3.4 — 27 October 2026

Confirmed in the running UI that the model explained issue #4 as an enhancement at 95% confidence, while the quotation validator removed its label. Replaced model-written quotations with constrained label IDs and numbered source excerpts. The backend inserts the actual source text. The confidence cutoff and explicit uncertainty routing remain unchanged.

Added a new prompt identity, automatic fresh analysis of old empty/quote-rejected results, and reuse of valid older analyses without another provider call. Human decisions and old analysis records remain intact; no schema migration is required.

Verified 149 local tests including 15 PostgreSQL cases. One observed live Qwen playground response selected enhancement for #4 at 0.95 confidence with uncertain=false and source:1; replay through the new parser retained the label and met the cutoff. The playground used JSON-object mode with the schema in its instructions, while the application uses strict JSON-schema mode. Further live issue results and the updated hosted application were not confirmed. No production source or database change was made.
