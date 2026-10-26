# Evaluation report — actual local measurements

Collected and tested 26 October 2026 (India time). Classification uses real VS Code snapshots. Fixture scores are excluded. Full machine-readable reports are in `evidence/`. No cloud or user-validation results are claimed.

## Frozen classification evaluation

Model `vscode-tfidf-v1`, dataset `dataset-66cb4613b0925284`. Exactly 786 training, 168 validation and 169 test issues. Three settings were compared only on validation data; the balanced unigram configuration won. No refit on validation and no retuning after the sealed test. See the model/data cards for exact UTC boundaries, class supports and exclusions.

| Metric, all 169 test predictions | TF-IDF + logistic regression | Majority baseline |
|---|---:|---:|
| Macro-F1 (main metric) | 0.5446 | 0.2847 |
| Accuracy | 0.6923 | 0.7456 |

The model improves macro-F1 and loses to the baseline on accuracy. That is consistent with treating minority categories as meaningful instead of maximizing dominant-class accuracy. It is not an overall accuracy improvement.

| Class | Precision | Recall | F1 | Test support |
|---|---:|---:|---:|---:|
| bug | 0.8739 | 0.7698 | 0.8186 | 126 |
| enhancement | 0.2222 | 0.7143 | 0.3390 | 14 |
| question | 0.7692 | 0.3448 | 0.4762 | 29 |

Confusion matrix: rows actual, columns predicted; bug, enhancement, question.

```text
                    bug  enhancement  question
bug                 97       27           2
enhancement          3       10           1
question            11        8          10
```

## Uncertainty and coverage

Threshold 0.55 was chosen on validation data to maximize coverage with ≥0.85 accuracy and ≥10 unflagged examples; the target was met (75 unflagged validation examples, 0.8533 accuracy). No calibration assessment has been performed.

All test predictions: macro-F1 0.5446 and accuracy 0.6923. **55.03%** are flagged for extra review. The remaining **76/169** have accuracy **0.8816** and macro-F1 **0.6923**. These easier-subset values are reported separately and are not the model’s overall performance.

## Error analysis

Question recall is 10/29 (0.3448): 11 questions become bugs and 8 become enhancements. Enhancement precision is 10/45 (0.2222), despite recall 10/14. Twenty-seven bug reports become enhancements. Training bug prevalence is 54.7%, compared with 74.6% in test; changing prevalence and language can affect behavior. The 14-example enhancement test support makes conclusions fragile.

Representative source-label disagreements (not independently adjudicated label errors):

- [Settings button does not support touch](https://github.com/microsoft/vscode/issues/34678): source bug → enhancement; only 163 text characters. Limited context may contribute, but no causal ablation established that.
- [Allow user to create Tasks with the Windows Jump List](https://github.com/microsoft/vscode/issues/34705): source bug → enhancement; request-like wording overlaps the category boundary.
- [Feature Request: bold-face for language keywords](https://github.com/microsoft/vscode/issues/34759): source question → enhancement; author framing and maintainer category differ.
- [Display unique directory label for quickopen files](https://github.com/microsoft/vscode/issues/34718): source enhancement → bug, illustrating ambiguous requested behavior.

Template sensitivity: zero eligible examples matched the narrow explicit type-field detector. The nonmatching test subset therefore contains all 169 examples and has the same 0.5446 macro-F1; this provides no informative template contrast. HTML comments are removed, but headings and author category phrasing may remain. This limitation is disclosed rather than claiming templates were fully eliminated. Exact/near duplicate screening found zero exclusions in this primary collection; that does not establish no semantic duplicates. The failed Streamlit pilot did yield 29 duplicate exclusions.

## Retrieval assessment — pending human relevance judgments

Both TF-IDF and pinned CPU MiniLM are implemented and tested. The frozen pool contains **39 query issues** and rankings from both methods. Queries are deterministic chronological quantiles outside all classification manifests, with a minimum text length and five TF-IDF candidates. Each method uses the same available same-repository, creation-time-bounded candidate pool; self is excluded. Candidate text/snapshot IDs and rankings are frozen for reproducibility. UI relationship judgments remain separate.

No Precision@5 or MRR quality score is reported because genuine judgments have not been supplied. Fill the pooled reviewer/judgment fields and run `evaluate-retrieval`; uncertain pairs must be adjudicated. Planned metrics are Precision@5 and reciprocal rank within the top five. Recall@5 is not supported because the complete relevant set is unknown.

Historical caveats: candidate creation time is filtered, but edited text may not reflect the historical state; the TF-IDF index vocabulary/IDF uses the collected corpus, and pretrained MiniLM postdates these old queries. This is retrospective candidate filtering, not a historical deployment simulation.

## Measured latency

Hardware: macOS-15.3-arm64-arm-64bit, arm64, 8 logical CPUs. Native macOS Python, PostgreSQL in a local Docker VM. 4,164 real issues in the index/database; query retrieval filters to 2,999 VS Code issues. Each row uses 100 sequential warm requests; classifier/retrieval cycle through up to 20 actual reports. No concurrency/load test or cloud extrapolation is claimed.

| Operation | p50 ms | p95 ms | Requests |
|---|---:|---:|---:|
| classification | 0.239 | 0.367 | 100 |
| retrieval_tfidf | 3.868 | 5.482 | 100 |
| retrieval_semantic | 10.989 | 17.310 | 100 |
| api_issues | 13.879 | 16.669 | 100 |
| api_dashboard | 27.208 | 30.735 | 100 |
| api_issues_1190 | 4.832 | 6.543 | 100 |

First artifact-loading calls measured separately: classifier 28.9 ms; TF-IDF index/retrieval 119.3 ms; semantic model/retrieval 3274.1 ms. Package startup may already be partly warm. Semantic warm latency includes query encoding; corpus embedding generation is excluded. API measurements include local HTTP, SQL and serialization. These measurements meet the initial warm-latency targets in this environment; they do not establish performance on other hardware or under concurrent traffic.

## Verification and reproducibility

46 automated tests passed locally, including five PostgreSQL integration tests, mocked GitHub failures/rate limits, chronological leakage guards, save/load consistency, stale/repeated/concurrent reviews, retrieval caching/self-exclusion and filtered SQL. CI is configured without live APIs or model downloads; no remote CI success is claimed. Docker fixture startup and protected save/history/dashboard changes passed. Saved fixture reviews survived database/API restart and a container recreation with the same volume. The real-data delivery was also restored into a new isolated database with matching table counts and verified model availability/read-only behavior (`evidence/backup-restore.json`). The Linux arm64 CPU image also served the real classifier and five semantic candidates as UID 10001 with a read-only artifact mount (`evidence/semantic-container-smoke.json`).

Use README commands to import, freeze, train/evaluate and benchmark. Exact source snapshots, membership, mapping, seed, configuration and original dependency lock are persisted in the model artifact. A new GitHub download may differ and must receive a new dataset/model version. Do not rerun a changed test split to improve this headline.

## Limits of the evidence

The main result is a **chronological retrospective evaluation using collected snapshots**. Text and labels may have changed after creation; historical training-label availability is not established. The import is a biased oldest-update-time slice of an old project period. Labels are noisy, model scores are uncalibrated, and cross-project/current-data performance is unknown. Retrieval quality, actual hosted availability, intended-user usability and feedback-driven improvement remain pending.


## Version 0.2 authentication and repository connection verification

The new GitHub-backed session, repository-role, scoped-workspace, import-job, and UI flows are tested separately from the historical classifier above. The current suite has 68 passing tests including eight PostgreSQL integration tests; see `evidence/hosted-upgrade-tests.xml`. Identity and permission responses are mocked in automated tests. Real hosted OAuth and owner-account verification remain pending owner setup.

An additional read-only live API check fetched 50 VS Code response objects into an isolated database: 49 issues persisted and one PR was excluded. Source-label/text-rule suggestions categorized 33 reports (11 bug, 19 enhancement, 3 question); 16 remained for manual categorization. This is a functionality check, not an accuracy assessment. Twenty-three suggestions came from GitHub labels and ten from text rules, with no fabricated probability scores. Related search returned five candidates and excluded self. See `evidence/live-public-import-v02.json`.

The current production blueprint was validated against Render's official schema. The new local installation serves the sign-in screen and rejects unauthenticated workspace data requests. No cloud URL, user time saving, rule accuracy, or genuine relevance judgment is claimed.


## Free temporary hosting update

The free Community Cloud entrypoint runs the API on loopback in the same installation as Streamlit, while an external PostgreSQL database supplies durable storage. It forces real/GitHub mode and excludes inherited shared provider/reviewer tokens. The full local suite now has 74 passing tests, including eight PostgreSQL integration tests (`evidence/free-hosting-tests.xml`). A separate non-root Linux container check with actual PostgreSQL rendered the sign-in UI for two simulated visitors, reused a single private backend, and returned HTTP 401 for unauthenticated workspace data (`evidence/free-hosting-smoke.json`). Lint, formatting, and migration-drift checks passed.

No live Streamlit Community Cloud, Neon connection, new GitHub sign-in, or cloud performance result is claimed by these local checks. Follow HOSTING.md to configure the owner's accounts and complete hosted verification. Historical classifier and retrieval measurements above are unchanged.
