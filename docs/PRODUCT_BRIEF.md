# TriageDesk product brief

**Primary user:** a maintainer of a student or open-source project. **Problem:** scattered reports and inconsistent labels make it hard to decide what to review and spot repeated concerns. Current assumed workflow: read GitHub reports, search old issues, apply labels, track decisions mentally or in a spreadsheet. This is a hypothesis, not a finding from interviews.

**Proposed workflow:** import public issues → inspect category and potentially related issues → accept, correct, defer, or skip → use filtered aggregates to plan follow-up. Source labels, model scores, and human decisions stay distinct. No writes to GitHub.

## User stories and acceptance criteria

| Story | Acceptance criterion |
|---|---|
| Maintainer imports public issues | Valid owner/repository only; both states; pagination; PR exclusion; rerun creates no duplicates; persisted UTC checkpoint |
| Reviewer finds waiting issues | Filter/search, bounded pages, creation dates and score ordering; latest accepted/corrected snapshot leaves waiting queue |
| Reviewer inspects suggestions | Full text, source attribution, three class scores or explicit unavailable state, up to five related reports excluding self |
| Reviewer decides | Accept/correct/defer/skip and optional note; manual category without a model; audit preserved; stale saves return a conflict; repeated request returns original result |
| Coordinator sees concerns | SQL-scoped volume/state/review/category/time aggregates agree with filtered issue IDs; predicted and reviewed charts separate |
| Visitor explores safely | Fixture banner; public writes disabled unless backend and token authorize; text cannot execute HTML; no import/training HTTP endpoint |

## MVP and non-goals

MVP: one GitHub repository at a time, fixed three-category mapping, chronological retrospective classifier evaluation, TF-IDF and optional CPU semantic retrieval, local reviews, dashboard, reproducible jobs, Docker, deployment preparation. Non-goals: automatic duplicate closure, posting comments or labels, LLMs, vector database, enterprise identity, campus app, distributed infrastructure.

## Assumptions to validate

Maintainers find these three categories useful; text alone is sufficient for useful suggestions; review effort is acceptable; potentially related issues help; novices understand uncalibrated scores. Edited snapshots and noisy labels limit evaluation. A campus-feedback adaptation could replace GitHub ingestion and mapping, retaining the review workflow; it is not built here.

## Success measures and risks

Engineering targets: clean fixture startup, durable reviews, no duplicate imports, useful errors, subsecond classification and about one-second retrieval on a few thousand issues (targets, not measured claims). ML: macro-F1 versus majority baseline, per-class support and review coverage; no required score predetermined. Product: completion, time, confusion and usefulness in an exploratory 3–5 person study. Validation is pending. Main tradeoffs: simple interpretable baseline versus context; Streamlit speed versus layout/state control; bounded local exact retrieval versus scaling; shared reviewer secret versus individual identity.
