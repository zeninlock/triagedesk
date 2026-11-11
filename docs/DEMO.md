# Interview demo: preparation and a five-minute walkthrough

Deploy first using [HOSTING.md](HOSTING.md). Rehearse against the hosted Streamlit URL, using the same repository and token you plan to use in the interview.

## Prepare a small real GitHub repository

Create a public repository you own, enable **Issues**, and give it a short README describing a simple web app with a frontend, backend, and REST API. Create the following eight open GitHub issues through GitHub's browser UI. These are deliberately written demonstration reports, not claims about production incidents. Existing GitHub labels can remain empty so you can demonstrate classification from issue text.

### 1. Checkout endpoint fails for every customer

> Since yesterday's release, POST /api/checkout returns HTTP 500 for every request. All customers are unable to place orders. There is no workaround. Expected: a successful checkout should return an order ID.

Likely: **type: bug**, **priority: high**, **area: api**. The explicit affected population and blocked checkout justify urgency; a short report does not make this a beginner task.

### 2. Add a filter for completed tasks

> The task list currently shows all tasks. Add an optional Completed filter beside the existing status controls so users can focus on completed work. The current list remains usable; this is a requested UI improvement rather than broken behavior.

Likely: **type: feature or enhancement**, **area: frontend**. Priority depends on inferred impact and may be low or medium; do not promise a particular priority for every enhancement.

### 3. Correct a misspelled README heading

> In README.md, the installation heading says "Instalation". Change only that heading to "Installation". No behavior or code should change. This is a small, isolated documentation fix suitable for a new contributor.

Likely: **type: docs**, **priority: low**, **help wanted**, **good first issue**. Area can remain unassigned because documentation alone does not identify an application team.

### 4. Remove an unused server logging helper

> server/utils/logging.py defines an unused format_log_line function. Remove the helper and its unused import. Keep the existing logging output and behavior unchanged. This is internal server maintenance, not a feature request.

Likely: **type: chore or refactor**, **priority: low**, **area: backend**, with contributor tags if the model judges the scope sufficiently clear.

### 5. How do I authenticate API requests?

> Is the Authorization header expected to use "Bearer" or "Token" for GET /api/tasks? I am asking for clarification about the existing API, not requesting a code change.

Likely: **type: question**, **priority: low**, **area: api**. Support questions need not receive contributor tags.

### 6. Save button is clipped at mobile width

> At a viewport width of 375 px, the task editor's Save button is clipped by the right edge of the form. Desktop layout works, and rotating the phone is a workaround. Expected: the entire button should be visible without horizontal scrolling.

Likely: **type: bug**, **area: frontend**. Priority reflects the reported impact and workaround, rather than treating every bug as high.

### 7. Investigate occasional synchronization problems

> Sometimes synchronization does not feel right. I have not yet collected logs, steps to reproduce, or information about which component is affected. Please investigate.

Likely: low priority when impact cannot be inferred, with low confidence/uncertainty and no good-first-issue tag. The model may put it in **Needs review**; this is intentionally ambiguous, so routing is not guaranteed. If it auto-sorts, you can still demonstrate manual correction using **Adjust labels**.

### 8. Background importer silently drops records

> The nightly server import drops roughly 10% of valid records before writing them to PostgreSQL. The missing records are permanently lost because the source feed expires after import. This affects every nightly run; no recovery or workaround exists. Expected: every valid source record is persisted.

Likely: **type: bug**, **priority: high**, **area: backend**. Data-loss semantics support the priority even without words such as "urgent".

LLM suggestions can vary. Present these as intended interpretations and review the actual saved results before the interview. Human corrections are a product feature, not a failed demo.

## Rehearse ahead of time

1. In the hosted app, sign in and import the eight issues.
2. Keep the workspace open until **Waiting for AI** reaches zero, or resolve provider errors shown there. The default pass analyzes up to five issues; further passes run while the workspace stays open.
3. Verify the sidebar repository selector, colored columns, area filters, and type tabs.
4. Select one issue; save **in progress**, then **blocked**, and then return it to **open**. Confirm the status history appears and the label classification remains unchanged.
5. Save a label correction with a short review note. Confirm **Reviewed** and the Overview label counts update.
6. Refresh and sign in again if required. Confirm saved labels, review history, and work status persist.
7. For a live AI demonstration, optionally create a ninth issue shortly before the interview. Keep at least the original eight already analyzed so the main demonstration does not depend on provider latency.
8. Save the Streamlit URL as a bookmark. Keep your GitHub token available privately in case the application session expires. Do not screen-share the token, secrets panel, or API-key page.

## About fifteen minutes before the interview

- Open the hosted app and let it wake up. Check Neon connectivity and the issue list.
- Sign in if needed; sessions expire after eight hours by default.
- Confirm there are no key, billing, rate-limit, or migration errors.
- Load Overview and one prepared issue. Take a few screenshots of the real deployed app for a presentation fallback.
- Keep the browser tab open. Avoid changing `AI_MODEL`, secrets, or the deployment during the interview.

## A five-minute sequence

**0:00–0:40 — Explain the problem.** Open Overview. "This organizes an issue backlog into type, priority, code area, and contributor suitability. High-confidence issues are auto-sorted; uncertain ones can be reviewed."

**0:40–1:40 — Show semantic tagging.** Open Issues. Compare the checkout failure with the README typo. Point out that the serious failure receives high priority because it blocks all users, while a simple typo is low priority and suitable for a first contribution. Open an issue to show its short AI explanation.

**1:40–2:20 — Show team routing.** Open the Area tabs and filter **area: frontend**, **area: backend**, and **area: api**. Explain that unsupported areas remain unassigned rather than being invented.

**2:20–3:00 — Show ownership of work status.** Select an issue, change **open → in progress**, save, and refresh. Show the unchanged AI labels and persisted status. Change to **blocked** if you want to show the red status badge and history.

**3:00–4:00 — Show human correction.** Open Needs review if it has an issue, or use Adjust labels on any issue. Correct its type or priority, select **help wanted** if appropriate, add a brief note, and save. Show it in Reviewed. The AI review state and work status remain separate.

**4:00–5:00 — Explain reliability and efficiency.** "One structured OpenAI response supplies all tags. Neon caches analysis by issue snapshot and model/policy version. Reopening completed work or editing status does not call the model. Repository permissions are checked, credentials are encrypted, and synchronization reads GitHub without changing its labels."

Optional: show a newly created issue arriving during synchronization, but do not make the main demo depend on real-time external calls.

## If something interrupts the demo

| Situation | Recovery |
| --- | --- |
| AI provider is slow or limited | Demonstrate the already saved issues, statuses, and review workflow. Explain the visible pending queue and backoff. |
| A prediction differs from your expectation | Show the explanation and correct it. Explain that self-reported confidence is not a guarantee of correctness. |
| No issue is in Needs review | Use Adjust labels on an existing issue; do not claim an uncertain issue exists. |
| Session expired | Sign back in privately; Neon still holds all decisions. |
| Streamlit or Neon is temporarily unreachable | Use screenshots captured from the hosted deployment and the architecture explanation. Do not claim the offline view is a live application. |

## Points to be precise about

- Labels and work statuses are saved in **TriageDesk/Neon**; they are not written back to GitHub.
- Work status belongs to users, while the LLM supplies type/priority/area/contributor suggestions.
- Help wanted means actionable work for a contributor; good first issue additionally requires clearly simple, bounded, low-risk scope.
- No separate trained classifier, embedding model, GPU, or model artifact download is required.
- Synchronization and analysis progress while the workspace is open and hosted compute is awake. This is not an always-running distributed task worker.
- Area and priority labels are inferred from issue text. The separate, explicitly requested contributor guide reads selected repository excerpts and checks citations; it does not verify production impact or prove a fix correct.

For the contributor-guide walkthrough, prepare a saved guide and follow [CONTRIBUTOR_GUIDES.md](CONTRIBUTOR_GUIDES.md#interview-demonstration). It needs real repository files; reports describing an imaginary app cannot establish code references.
