# Interview preparation

## Explain the product in 30 seconds

“Maintainers have to read reports, choose categories and look for repeated concerns. TriageDesk imports public GitHub issues, suggests a category and potentially related issues, and lets a person accept, correct or defer a suggestion. The database preserves both the input snapshot and review history. I compare a cheap text model against a majority baseline and disclose the limitations of edited historical issues.” Use ‘I built’ only after personally reviewing and understanding the implementation; AI assistance is disclosed below.

## Questions to practice

**Why macro-F1?** Each of bug, enhancement and question contributes equally. Accuracy can look good when bug reports dominate. Show the confusion matrix and small minority-class support before interpreting a headline.

**How did you avoid leakage?** Only snapshot title/body are features. The Pipeline fits vocabulary on training data; chronological validation chooses configuration and threshold. Newer exact/near duplicates are excluded without moving them earlier. Collected text and labels may have been edited or assigned later, so this is retrospective, not a strict historical simulation.

**Why logistic regression?** Sparse TF-IDF is cheap on CPU and easy to inspect. The majority baseline makes ‘better than always predicting the largest class’ explicit. A higher-capacity model needs enough trustworthy examples and an evaluation reason.

**Are scores probabilities?** `predict_proba` provides model scores summing to one, but calibration has not been assessed. The UI calls them scores. A validation-selected threshold controls review workload; overall metrics still include flagged reports.

**Why keep three forms of category?** Repository labels are noisy supervision, model suggestions are estimates, and human decisions are local review outcomes. Combining them silently would conceal disagreements and corrupt experiments.

**How does duplicate detection work?** Classification data deduplication keeps earliest normalized exact or very high char-hash cosine matches. Retrieval ranks text similarity and explicitly calls results potentially related. Human judgments distinguish related, duplicate, unrelated and uncertain. Neither mechanism proves semantic equivalence.

**What SQL did you write?** A shared filtered scope joins the latest current-snapshot prediction and review. Aggregates count state, review completion, category and UTC creation month in PostgreSQL. Explain why an append-only review table must be reduced to the latest applicable decision before counting.

**What if two reviewers save?** An atomic update checks snapshot and expected revision. One succeeds, the other gets 409; unique submission keys make transport retries safe. History is retained. A shared token does not establish individual identities.

**How is synchronization safe?** `since` is update time, with overlap. A page’s upserts and checkpoint are one transaction. PR objects are excluded. Interrupted imports resume without duplicate records. Caps and sampling bias are disclosed.

**Why no vector database?** Exact search over a few thousand cached vectors is simple and measurable. Use observed memory and p95 under concurrency to decide whether approximate search is warranted.

**What happens in deployment?** Streamlit calls a private API; managed PostgreSQL persists decisions; a paid disk holds artifacts. Migrate before listening. Provision trusted models outside ordinary startup. Missing models remain visible as unavailable or a labeled TF-IDF fallback. The actual hosted app must be smoke-tested before claiming deployment.

**What would you improve next?** Genuine maintainer feedback, adjudicated retrieval relevance, more representative current data, calibration assessment and individual access tokens if needed. Prioritize evidence over adding infrastructure.

## AI assistance and personal review checklist

Codex generated the implementation, tests, deployment files and initial documentation; it executed local checks and inspected the running UI. The user has not yet personally reviewed the work or validated it with maintainers. Before presenting this as a portfolio project, read the source, rerun the commands, inspect real-data errors and label mappings, explain the SQL/concurrency behavior without a script, verify licensing and hosting costs, and conduct the study. Automated checks are not a substitute for personal authorship or product validation. Record the files and decisions you actually reviewed in the progress log.
