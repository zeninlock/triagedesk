# Contributor guides

Open an issue in **Issues**, **Needs review**, or **Reviewed**, select its row, and scroll to **Contributor guide**. Choose **Generate contributor guide**. The card updates while the backend reads repository files and drafts a starting plan. You can continue browsing during generation.

The card can show relevant files, prerequisites, investigation steps, existing tests/testing instructions, completion checks, documented commands, and missing information. Empty sections mean the retrieved excerpts did not establish that information. **More context needed** is a valid result; the model must not invent a plan to fill the card.

Each item links to a checked quote. File links include a commit SHA and original line numbers. Notebook links open the notebook at that commit; the label identifies the cell number and lines within that cell, without presenting them as raw JSON file lines. **Source checked** means that quote exists in the retrieved source at that version. It does not prove an explanation, diagnosis, fix, or command correct or safe. Review the context before choosing **Approve contributor guide**. Approval is separate from label review and work status and can be removed.

## Cloud setup and upgrades

1. Push the updated source to the GitHub repository used by your existing Streamlit deployment.
2. Let Streamlit rebuild. If it keeps the previous backend running, use **Manage app → Reboot app**. Normal cloud startup applies migration `0005` automatically. No separate server or database command is required.
3. Keep the existing Neon URLs, encryption key, OpenAI key, and `AI_MODEL` in Streamlit Secrets. No new secret or dependency is needed.
4. Source retrieval uses the signed-in maintainer's GitHub credential. For a fine-grained token, enable **Contents: Read-only**, alongside **Issues: Read-only** and **Metadata: Read-only**, for the selected public repository. Sign in again after changing or replacing the token. GitHub App/device-flow installations need repository contents read access as well.
5. Open an issue describing a real file or behavior and generate a guide. Expand a quote, open its source link, and compare it with the linked code. Approve only after review.

If source retrieval fails, the card shows an error and offers an explicit retry. GitHub remains read-only. Repository code, commands, notebooks, and tests are never executed by this feature.

## Cost and saved versions

- Generation is explicit. Imports, issue browsing, label analysis, and work-status updates do not generate guides.
- A new supported guide uses at most one OpenAI request, without automatic SDK retries. No usable source context can return missing-information guidance without an AI request.
- Completed guides are saved in Neon. Opening them and ordinary repeat submissions reuse saved results.
- **Check for updates** resolves the default branch again. Matching issue snapshot, commit, selected evidence, model, and guide version reuse the saved analysis and approval. A changed commit can require one new AI request even if relevant files appear similar.
- File indexes and up to 64 retrieved text blobs are cached per repository commit. Other issues can reuse those downloads.
- Changed issues or guide/model configurations are marked outdated and need a current draft before approval. Repository freshness is checked on request; the displayed commit identifies the version actually covered.
- Rate limits and outages produce a visible delay. Configuration failures and invalid citations need an explicit retry. Failed retries retain earlier completed database rows, although the card shows the latest attempt.

## Retrieval and validation limits

Retrieval searches eligible paths using issue terms, includes contribution/setup documentation, and retrieves related source/test files. It reads at most 10 UTF-8 blobs of at most 100 KB each, or at most 1 MB for notebooks, supplying at most 10 excerpts of up to 2,400 characters. Issue input is capped at 500 title characters and 10,000 body characters. Original source lines are preserved.

Jupyter v4 notebooks are parsed for code and markdown cell sources only. Outputs, images, attachments, execution counts, and other metadata are discarded before caching or AI analysis. Cells are ranked against issue terms; cell numbers refer to their positions in the original notebook, including skipped cells. Empty/invalid notebooks are skipped. Up to five small notebooks can be searched when paths do not name the affected function. Notebook sources are capped at 100,000 characters per notebook, and notebooks are never executed.

Retrieval skips symlinks, submodules, binaries, credentials/secrets filenames, environment files, generated/vendor directories, lock files, and datasets. Bounded path/cell matching can miss implementations in large repositories. Truncated indexes, time limits, unsupported encodings, and truncated issue inputs are disclosed. Every guide uses selected excerpts and must not claim exhaustive analysis.

Python builds a catalog of citation blocks before the AI request. Each section's schema restricts references to eligible catalog IDs: a file recommendation cannot cite the issue report, and a completion check must cite it. The model chooses IDs; it does not invent line numbers, quotes, or URLs. Python rejects unknown/wrong-kind references, copies original source lines, and builds permanent links. Missing required sections produce a clearly marked incomplete guide, rather than a misleading source-reference error. Recognized shell commands are extracted directly from cited documentation; the model cannot supply a command field. Accepted citations establish source membership, not semantic correctness of every claim. Repository and issue content are explicitly untrusted model input.

The v2 guide version invalidates earlier AI caches and approval eligibility without removing historical attempts. If an old failed guide is visible after upgrading, choose **Generate current guide** once.

One guide generates at a time per repository. Persisted leases expire after five minutes so host restarts cannot leave a guide permanently busy. No billable generation restarts automatically. Reopening the issue exposes a retry after expiry. GitHub issue closure removes local guide records during synchronization. Reusable repository caches are pruned after thirty days; saved guide excerpts remain with the issue.

## Interview demonstration

Prepare a saved guide so the main demo does not depend on provider latency. Use an issue with a clear expected outcome and files that actually exist.

1. Open the issue and explain its expected behavior.
2. Show starting files and the first investigation step.
3. Expand a quote and follow its commit-pinned link.
4. Explain the difference between a checked source and an AI suggestion.
5. Approve the guide, reopen the issue, and show the saved approval.
6. Choose **Check for updates** without changing the repository and show **Saved analysis reused**.
7. Optionally demonstrate missing-information questions on a vague issue.

This is a starting aid, not an autonomous repair agent or a guarantee that an issue is beginner-friendly.
