# Confident results with no labels

Version **0.3.4** fixes the free-form quotation requirement that could remove every label from an otherwise clear classification.

In the observed example, the model explained that issue #4 requested an enhancement and reported 95% confidence. Its free-form supporting quotation did not match the source text, so version 0.3.3 removed that label and cached an empty Needs review result. Stopping repeated requests did not resolve that classification problem.

## The revised response contract

The backend now gives the model:

- A list of allowed label IDs, each mapped to one exact label name and group.
- Numbered excerpts copied from the issue title, description, and existing labels. Each excerpt contains at most 300 characters.

The model returns `label_id`, `evidence_id`, and confidence. For example, `type:1` selects **enhancement**, while `source:1` points to a supplied body excerpt. The backend inserts the actual excerpt text into the saved evidence. The model does not need to copy or paraphrase a quotation.

Both ID fields are restricted to supplied values in the strict JSON schema. The backend also validates those references. An unsupported reference still requires review. Selecting a valid ID establishes which source text the model used; semantic correctness still depends on the model and remains subject to the existing confidence/uncertainty policy.

The default categories have clearer descriptions. Optional module, contributor, priority, and workflow labels are omitted when evidence does not support them. A clear request does not need an unrelated module label to receive its primary type.

**The cutoff remains 0.85.** A valid result at or above the configured cutoff is auto-sorted when the model does not mark it uncertain. Low-confidence or explicitly uncertain classifications still require review.

For results that do require review, **AI details** now gives the reason: uncertainty, a score below the cutoff, or supporting details that could not be verified.

## Existing results and deployment

1. Upload the version-0.3.4 project contents to the GitHub branch used by Streamlit, then reboot the app.
2. Keep Python **3.12**, **`ui/community_app.py`**, the existing database, and your private secrets. No new key or database migration is required.
3. Sign in and select the repository. The new prompt identity makes old quote-rejected or empty analyses eligible for one new analysis automatically. **Run AI now** can start that pass directly.
4. Valid older analyses with a supported primary type and matching evidence are reused under the new cache identity without another provider call. Completed human reviews are preserved. Old analysis records remain available.
5. Browse **Issues** for the saved labels and **Needs review** for genuinely uncertain results.

The new identity is `multi-label-v2-evidence-ids`. After a result is saved, later page refreshes and logins reuse it as before. A changed issue, model, or taxonomy still invalidates the appropriate cache entry.

## Verification

The local suite passed **149 tests**, including **15 PostgreSQL cases** (`evidence/evidence-id-tests.xml`). New checks cover high-confidence label retention, schema enums, invalid references, bounded excerpts, automatic recovery of old empty results, and reuse of valid older cache entries.

One live check in the Groq playground used the same Qwen model and the new reference-based instructions for issue #4. It returned **enhancement**, **0.95 confidence**, `uncertain: false`, and `source:1`, with a reported **451 ms** latency. Replaying that observed response through the new parser with the actual source excerpts preserved the label and passed the 0.85 cutoff (`evidence/evidence-id-live-check.json`).

The playground used JSON-object mode with the schema included in its instructions; the application sends the schema through strict JSON-schema mode. This verifies one live reference-based response, not a measured accuracy rate or an end-to-end deployment check. Other issue-specific live results were not confirmed. The hosted application still needs this source update and a reboot.
