# Offline model evaluation

These results cover the optional scikit-learn classifier and related-issue retrieval experiments, collected on 26 October 2026. They do not measure the Groq multi-label workflow. Machine-readable reports are in [evidence/](../evidence/). Synthetic demo scores are excluded.

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

## Run an offline experiment

With Python dependencies installed, PostgreSQL running, migrations applied, and `MODE=real`, use the CLI to collect issues and train a separate model version:

```sh
uv run triagedesk import microsoft/vscode --limit 3000
uv run triagedesk prepare microsoft/vscode --out data/dataset.json
uv run triagedesk train data/dataset.json --version vscode-experiment-1
uv run triagedesk evaluate vscode-experiment-1
uv run triagedesk activate vscode-experiment-1
uv run triagedesk predict
uv run triagedesk index
uv run triagedesk benchmark --requests 100
```

Use a separate experimental database rather than an active connected workspace. Imports, dataset preparation, training, and indexing are administrative jobs. A new GitHub download can contain changed issue text or labels and must receive a new dataset and model version; it will not necessarily reproduce the recorded numbers.

Optional semantic retrieval requires `uv sync --frozen --extra semantic`, followed by `uv run triagedesk index --semantic --allow-download`. This explicitly downloads the pinned encoder. The default app does not require these dependencies or model weights.

## Automated checks

The tests cover authentication, repository permissions, import pagination and retries, AI response validation, caching, uncertainty routing, human reviews, issue closure, and related-issue filtering. Unit tests use simulated provider responses; PostgreSQL integration tests require a separate `TEST_DATABASE_URL`.

Run them with the development commands in the [README](../README.md). GitHub Actions publishes current test results as workflow artifacts; generated local test reports are excluded from source control.

## Limitations

This is a chronological retrospective evaluation using collected snapshots. Text and labels may have changed after issue creation, and the import is a capped, oldest-update-time sample. Source labels are noisy, scores are uncalibrated, and cross-project performance is unknown. Retrieval quality needs human relevance judgments. The classifier metrics above do not establish accuracy or time savings for the current Groq workflow.
