# Data card — collected 26 October 2026 (India time)

**Primary supervised source:** [microsoft/vscode](https://github.com/microsoft/vscode/issues). Version: `dataset-66cb4613b0925284`. This is a partial, oldest-update-time collection, not a random sample or a current repository census. Collection URLs and counts are in `evidence/vscode-audit.json` and `evidence/vscode-import.json`. Full immutable inputs and split membership are in the separate local artifact bundle, outside the code repository.

## Repository selection

Six small audits were needed because several plausible projects did not cover the categories consistently. Issue-only counts below came from GitHub search; labels can overlap, so these columns do not sum to repository totals. Sample cohorts used at most 100 earliest-updated and 100 newest-created REST response objects, excluding PRs.

| Repository | Available issue count observed | Bug label | Enhancement label | Question label | Decision |
|---|---:|---:|---:|---:|---|
| fastapi/fastapi | 3,556 | 121 | 0 | 3,125 | Sample dominated by PRs; weak enhancement coverage |
| streamlit/streamlit | 6,171 | 3,090 | 2,494 | 35 | Historical import had no eligible questions; rejected for three-class training |
| pallets/flask | 2,767 | 36 | 0 | 0 | Insufficient mapped categories |
| textualize/rich | 1,547 | 74 | 36 | 1 | Too few mapped questions |
| jupyter-widgets/ipywidgets | 2,079 | 141 | 18 | 23 | Sparse mapped coverage; other labels such as feature request require a separate mapping audit |
| microsoft/vscode | Not collected as a repository-wide issue total | 46,879 | 28,961 | 6,735 | Chosen after verifying the actual `*question` convention and three-class support |

The exact mappings are versioned in `config/labels.v1.yaml`: `bug` → bug, `feature-request` → enhancement, `*question` → question for VS Code. Plain `question` returned zero; the actual asterisk is part of the label name. Multiple labels mapping to one class are compatible; labels mapping to different classes are conflicting and excluded. Unsupported labels are not converted to questions. Unlabeled/ambiguous issues remain available for inference and human review.

Current-label and cohort differences suggest different labeling practices, but do not prove when conventions changed. The current Streamlit label count alone did not predict coverage in its oldest-update sample. VS Code’s question label also reflects the maintainer’s policy of redirecting usage questions to Stack Overflow, which is part of the target definition.

## Actual primary dataset counts

| Stage | Count |
|---|---:|
| REST response objects collected (fixed cap) | 3,000 |
| Pull requests excluded | 1 |
| Real issues persisted | 2,999 |
| Unsupported or unlabeled | 1,872 |
| Conflicting categories | 4 |
| Eligible supervised examples | 1,123 |
| Too-short eligible examples excluded | 0 |
| Later exact/near text duplicates excluded | 0 |
| Final supervised examples | 1,123 |

Class counts: **666 bug, 305 enhancement, 152 question**. Target size was approximately 1,000–5,000 usable labeled issues; this collection reaches the lower end. Do not substitute the raw count of 2,999 for the supervised size.

Chronology is assigned before duplicate removal: 786 training, 168 validation, 169 test. Training supports: 430/267/89; validation: 110/24/34; test: 126/14/29, ordered bug/enhancement/question. Creation dates span November 2015–October 2017, even though the snapshots were downloaded in October 2026. The update-time collection cap is a further selection bias. Split dates are recorded exactly in the evaluation report.

## Other data kept distinct

The unsuccessful Streamlit pilot imported 2,500 response objects: 1,165 issues, 1,335 excluded PRs. Its 911 eligible examples became 882 after duplicate filtering, with **zero questions**. No classifier was trained or test score reported for that pilot. The real retrieval index includes both public corpora: **4,164 issues**. Classification batch suggestions are restricted to the model’s VS Code training repository.

The default demo uses 24 hand-written synthetic campus-software issues and illustrative scores. Those are not observations, do not train the classifier, and never contribute to reported classification or retrieval quality. Human relevance judgments in the UI use `purpose=ui`; frozen retrieval evaluation judgments use `purpose=evaluation` and remain pending.

## Provenance, text policy and limitations

Only source identity, number, title/body, labels, state, source links and necessary UTC timestamps are stored; author profiles, comments, assignees and reactions are not collected as features. Each source revision has immutable text/label/hash/update-time provenance. Dataset manifests preserve the actual input, not just issue numbers. No bulk raw REST export is committed to the code repository.

Text cleaning removes HTML comments and narrow explicit type/category lines and checkboxes, including `Type: ...`; ordinary author-written category words are retained. The primary eligible data contained zero fields matching that narrow detector; that does not establish absence of all shortcuts. Audit titles and representative error reports are English software discussions, but there is no comprehensive language detector or verified language census. Non-English/mixed reports may remain.

**A newly downloaded historical GitHub issue may contain edited text and labels assigned after its creation date.** This is a chronological retrospective evaluation using collected snapshots. Historical text availability and training-label availability at the simulated cutoff are not established. Source labels are noisy, project-specific supervision rather than independently adjudicated ground truth. Older closed issues need not represent today’s incoming reports.

Issue authors retain their rights. GitHub links provide attribution; the MIT license on this project covers its code, not a blanket relicensing of issue text. MiniLM’s separate model license is Apache-2.0.
