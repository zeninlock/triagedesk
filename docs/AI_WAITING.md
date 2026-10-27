# Issues stay “Waiting for AI”

For completed high-confidence results displaying **Choose labels in review**, follow [the version-0.3.4 label-reference fix](AI_LABEL_REFERENCES.md).

Imported issues and completed AI analyses are separate stages. A Groq key being loaded confirms configuration presence; the provider can still reject a request, enforce a quota, or be unreachable. Before version 0.3.2, the issue table displayed all these cases as **Waiting for AI**, and automatic synchronization errors were suppressed. Provider failures were saved in PostgreSQL without a corresponding application warning in the logs.

Version **0.3.3** also fixes a successful-response rejection loop: questionable suggestions are cached for review, and unusable responses stop regenerating automatically. Read [validation recovery](AI_VALIDATION_FIX.md) when API call counts rise without saved analyses.

## Use the updated workflow

1. Upload the latest version-0.3.3 source contents to the GitHub branch used by Streamlit, then reboot the app. Keep **`ui/community_app.py`**, Python **3.12**, the existing database, and your private secrets. No database reset or new migration is needed.
2. Sign in and select the connected repository. The workspace now displays **AI progress**: reports queued, currently analyzing, and failed attempts. It also shows the selected model.
3. If a provider request failed, read the warning and retry time. A failed issue shows **AI needs attention**, with a safe explanation in **AI details**; selecting the issue shows the recovery guidance too.
4. Choose **Run AI now** to analyze pending reports directly. This verifies maintainer access and uses the shared background-job slot, but skips fetching GitHub issues and rebuilding the search index. Saved successful analyses and human decisions are reused.
5. Keep the workspace open. The issue table refreshes when analysis state changes, even when a short job finished between polling checks.

The retry button is disabled while a job is active or a provider cooldown applies. A very recent pass also has a short server-side retry interval. Wait for the displayed delay instead of repeatedly clicking. Automatic GitHub synchronization continues separately through the existing refresh workflow.

## Understand the wait

The defaults are **five reports per pass**, with **10 seconds between provider requests**. Five eligible reports therefore include about **40 seconds of deliberate spacing**, plus provider response and database time. Temporary network/provider failures normally use a **five-minute retry delay**; rate-limit headers can specify a different delay. Before version 0.3.3, rejected model responses also retried every five minutes. Those responses now pause for an explicit retry instead of making repeated calls automatically.

Do not reduce `AI_REQUEST_INTERVAL` or increase `AI_BATCH_SIZE` until you know your Groq account's current request and token allowances. More simultaneous requests can make a free-plan backlog worse. See [Groq rate limits](https://console.groq.com/docs/rate-limits).

## What each warning means

| Warning | Next step |
|---|---|
| API key rejected (401) | Replace the key in Streamlit Secrets, save, reload, then choose Run AI now. |
| Access denied (403) | Check project/model permissions in the Groq account. |
| Model unavailable | Check `AI_MODEL` spelling, availability, and account access. |
| Request rejected (400/422) | Confirm that the configured model supports strict JSON-schema output. |
| Request/token limit reached | Wait for the displayed retry time; the button cannot bypass provider limits. |
| Provider unavailable / connection failed | Wait for the scheduled retry and check hosting/provider availability. |
| Questionable label/evidence suggestions | Supported labels are saved as uncertain; open Needs review. The completed result is reused. |
| Malformed response / old invalid_output failure | Automatic retries are paused. Use Run AI now for one explicit fresh attempt or review manually. |

The default Qwen model remains supported for strict structured output according to [Groq's model support list](https://console.groq.com/docs/structured-outputs). Merely changing model names does not establish the cause of a failed request.

**Run AI now** resets retry delays only for correctable failures in the selected repository's current analysis configuration. It preserves successful analyses, active claims, rate-limit backoff, network backoff, and other repositories' rows. Requests and token limits shared by the installation remain effective across repositories.

## Safe logs and verification

New provider failures emit a structured `ai_analysis_failed` event with an issue ID, a fixed reason code, and retry delay. It contains no key, request body, issue text, or raw provider error message. A successful test with mocked responses does not establish a successful request from the hosted app to Groq.

The regression checks exercise a five-issue direct pass through the authenticated API and actual request-building/response-validation code using a simulated provider, then verify that the next pass makes no additional model calls. Other checks cover current progress, failed versus queued rows, PostgreSQL recovery, permissions, retained quota backoff, and UI retry behavior. No live production key is used.
