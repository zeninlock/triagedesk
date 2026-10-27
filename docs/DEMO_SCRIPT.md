# Current version-0.3 demo

1. Deploy the updated source, configure a Groq Free key in hosting secrets, and sign in as a real public-repository maintainer. Use AI_LABELS.md for activation.
2. Connect a small public repository with open reports. Watch import/AI progress and open Overview to inspect Auto-sorted, Needs review, Reviewed, and Waiting for AI counts.
3. Open Issues, choose a group such as Type or Module, and select a label tab. Select a report row to see its text, AI explanation, confidence, and exact supporting quotations.
4. Inspect a genuinely uncertain result in Needs review. Save a checked label decision and confirm the report leaves that queue and appears in Reviewed. If none are uncertain, explain the cutoff instead of inventing an evaluation result.
5. Refresh/log in again and show the saved result. Explain that PostgreSQL caches each snapshot/model/prompt/taxonomy analysis and that optional labels can be omitted when evidence is absent.
6. If demonstrating closure, close only an issue you are authorized to close on GitHub, keep the workspace open, and wait for the next synchronization to remove its local records. The application itself never closes an issue on GitHub.

Provider requests can be delayed by free quotas. No new multi-label accuracy or productivity result is claimed. Screenshots marked synthetic use invented label values purely for UI verification.

## Historical version-0.2 demonstration notes

# Three-to-five-minute demonstration

0:00–0:35 — Explain the maintainer’s assumed problem and the import → suggestion → review workflow. Point out fixture versus real mode. Describe discovery as hypotheses until the study occurs.

0:35–1:10 — Show the overview, partial-import note, source state, awaiting count, UTC issue arrivals and separate model/human category charts. Change one filter and explain that SQL scopes every metric consistently.

1:10–2:15 — Open the queue, search ‘export’ in fixture mode, inspect an issue. Read the report before the model suggestion. Distinguish repository label, model scores and reviewed category. Inspect the similar attendance-export report. Say ‘potentially related’, not ‘automatically duplicate’.

2:15–2:55 — With the installation’s reviewer token entered privately, accept/correct a suggestion and add a note. Show audit history, changed queue/dashboard and optional stale-save conflict from a second tab. Mention manual categorization works when prediction is unavailable.

2:55–3:45 — In real mode, show the model evaluation page and saved report: actual supports, macro-F1 versus majority baseline, minority-class weaknesses, flagged fraction and unflagged performance. Explain that edited historical snapshots prevent a strict historical deployment simulation. If a component is unavailable, show that state instead of inventing a number.

3:45–4:30 — Briefly show the private CLI workflow for read-only import, frozen dataset, training, activation, cached embeddings and batch prediction. Describe p50/p95 with actual corpus/request count and hardware. Show retrieval quality as pending until genuine judgments exist.

4:30–5:00 — State what was locally verified, what is prepared for cloud hosting, and what requires maintainer participants and credentials. Discuss one engineering tradeoff and invite questions. Do not claim a live cloud URL or user improvement until actually verified.
