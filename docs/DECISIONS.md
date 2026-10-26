# Decision log

| Decision | Reason and cost |
|---|---|
| Python 3.12, uv lock, pinned container digests | Supported security release, compatible CPU scientific wheels; intentionally one minor version. Refresh locks/digests deliberately. |
| PostgreSQL with SQLAlchemy/Alembic | Transactions, useful constraints and native SQL aggregates; requires a service unlike SQLite. SQLite is only for fast unit tests. |
| TF-IDF + logistic regression and majority baseline | Cheap, understandable, GPU/API independent. Words and short phrases work well as a defensible first experiment; context and noisy categories remain difficult. |
| Three small configurations, temporal split | Validation controls settings and uncertainty cutoff; test results are sealed once. No broad search to improve a headline. |
| Semantic retrieval separate from classification | Pretrained text similarity can help find related reports without changing classification features or treating scores as duplicate proof. Adds a one-time optional download. |
| Shared reviewer token checked by backend | Small MVP authentication with public read-only default. Owner controls a single audit identity; individual account attribution is future work. |
| Immutable snapshots and append-only reviews | Edited issues cannot silently change past experiments; extra storage is modest at a few thousand issues. |
| Optimistic review concurrency | A stale form cannot overwrite a newer decision. The reviewer must refresh and inspect a conflict. |
| Keep unsupported labels out of supervision | Missing labels are not questions. Conflicting class labels are counted and excluded, while those reports remain reviewable. |
| Reject the Streamlit historical sample for three-class training | 1,165 imported issues produced no eligible questions. Collecting more or choosing a better-mapped repository is honest; relabeling unsupported examples is not. |
| Select VS Code after checking its actual `*question` convention | Standard label names cannot be assumed; issue-type support and snapshots matter more than popularity. Source/temporal sampling bias is documented. |
| Streamlit over a separate JS app | Appropriate two-to-three-week scope, built-in accessible widgets/charts; less layout and navigation control. |
| Render preparation, no automatic purchase | Two containers, managed PostgreSQL and a persistent artifact disk are concrete. Paid memory/storage requirements and actual hosted verification remain explicit. |
| No automatic retraining from reviews | Prevents accidental evaluation leakage. A deliberate future-label export excludes held-out GitHub issue identities across every saved manifest. |

These are engineering choices and hypotheses, not claims derived from interviews. See the validation protocol for how to test them with maintainers.
