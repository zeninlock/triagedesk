# Offline evaluation reports

This directory contains aggregate reports from the optional offline classifier and retrieval experiments.

- `classification-evaluation.json`: classifier and baseline metrics, split details, and error examples.
- `dataset-summary.json`: supervised dataset counts and exclusions.
- `benchmark-real.json`: local latency measurements and hardware context.
- Repository audits and label-availability reports: source selection and label mappings.
- `retrieval-pool-summary.json`: retrieval comparison pool size and evaluation status.

These reports describe the offline scikit-learn and retrieval pipelines, rather than the Groq multi-label workflow. Raw datasets, generated model files, database backups, and local test reports are excluded from Git.

See [the evaluation report](../docs/EVALUATION.md), [data card](../docs/DATA_CARD.md), and [model card](../docs/MODEL_CARD.md).
