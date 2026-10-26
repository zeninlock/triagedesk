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
