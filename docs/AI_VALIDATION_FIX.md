# Successful API calls but issues still wait

Version **0.3.3** fixes a response-validation and retry loop. It includes the earlier secrets and progress fixes.

For high-confidence results that still lost every label because of the quotation check, use **version 0.3.4** and [the reference-based label upgrade](AI_LABEL_REFERENCES.md). That version includes this retry fix and removes the need for model-written quotations.

The previous classifier discarded the entire response when any proposed label had an unknown name/group, a repeated label, or evidence that did not match the issue text exactly. It saved `invalid_output`, waited five minutes, then asked the model again. The model request used temperature zero and the same input, so another request could reproduce the same rejected suggestion indefinitely. A successful provider HTTP response therefore did not imply a saved analysis.

## Result handling now

- Equivalent whitespace, Unicode composition, typographic quotes, and Markdown code formatting are normalized when checking evidence. Paraphrased or invented evidence is still rejected.
- Labels without support, invalid label/group combinations, and duplicates are removed. Supported labels, the model explanation, and a validation note are saved as a **complete, uncertain** analysis. The report goes to **Needs review**, even if its numeric confidence exceeds the cutoff. Reopening the workspace reuses this saved decision.
- If all suggestions are removed, the report still goes to **Needs review** with a prompt to choose labels. It does not claim a confident classification.
- A fully fenced JSON response is accepted only when its complete content is valid and passes the same checks. Arbitrary prose surrounding JSON is not silently ignored.
- Invalid JSON, invalid required fields or scores, empty responses, truncation, and refusals pause automatic retries. The issue shows **AI needs attention** with the specific reason. **Run AI now** can request one explicit new attempt; another unusable response pauses again.
- Existing `invalid_output` failures are also paused. This stops the old loop immediately after deployment. Rate-limit, temporary provider, and network backoff are preserved.

Completed accepted analyses and human reviews keep the same cache identity. The prompt, model, label taxonomy, and confidence cutoff are unchanged; successful results do not need regeneration. No database reset or additional migration is required.

## Apply to an existing Streamlit deployment

1. Upload the updated version-0.3.3 project contents to the branch used by Streamlit.
2. Reboot the hosted app so the private backend loads the new code. Keep Python **3.12**, the **`ui/community_app.py`** entrypoint, and your existing database and secrets.
3. Sign in, select the repository, and choose **Run AI now once**. The old failed rows did not retain their rejected response bodies, so those reports need one fresh response. The action reuses existing successful analyses and completed human reviews.
4. Check **Issues** and **Needs review**. Supported outputs can be auto-sorted under the existing rules; questionable suggestions are cached for review. If a response is unusable, the reason appears without another automatic model call.

Source changes are local until published and the hosted app is restarted. Tests use simulated provider responses; they do not establish that the live deployment has already processed the affected reports.
