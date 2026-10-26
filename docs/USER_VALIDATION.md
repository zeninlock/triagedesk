# Exploratory maintainer study — pending

No participants have been recruited or contacted. No usability findings or productivity gains are claimed. Aim for 3–5 people who maintain a student or open-source software project. Recruit outside the development team where possible. Do not collect private repository data for this study.

## Recruitment message (user sends it)

Hi! I’m building TriageDesk, a small tool that suggests issue categories and potentially related reports while keeping a maintainer in control. If you help maintain a student or open-source project, would you try a 20–30 minute session with public or synthetic issues? I’d like to learn where the workflow is useful or confusing. Participation is optional; this is exploratory student project research, not a performance evaluation. Reply if you’re interested and I’ll share the consent details and arrange a time.

## Consent and data use

Explain before beginning: “We’ll ask you to triage example issues and discuss the interface. We will record task completion, approximate time, errors, anonymous notes and your feedback. No audio/screen recording unless you separately agree. Do not enter credentials, personal data, or private project information. You may skip any task or stop at any point without a reason. We will use anonymized observations to improve a student portfolio project. We will retain notes for 90 days, then delete them. You can request removal by contacting the student researcher through the channel used to arrange this session.”

Record participant code, date, consent yes/no, recording consent yes/no, and preferred withdrawal contact method without publishing contact information. Only proceed with consent. Store raw notes outside the code repository and do not identify participants in the public report.

## Session script

1. Explain the purpose without teaching the interface. Ask what project the participant maintains and how they currently triage public issues. Mark answers as volunteered context.
2. Give a brief neutral scenario: “You coordinate a project and have reports to organize. Work as you normally would. Please think aloud. Suggestions may be wrong.”
3. Assign five tasks without giving click paths: find an issue awaiting review; inspect and correct a category; inspect a potentially related candidate and judge the relationship; identify a recurring category using the dashboard; explain what the model score means.
4. For each task, start timing after reading the prompt. Stop at completion or after 3 minutes; ask permission before giving help. Record help separately, along with errors, missed steps and confusion.
5. Ask the feedback questions below, then clarify that scores are uncalibrated and similarity does not establish duplication.

## Optional manual versus assisted comparison

Before recruitment, freeze two comparable sets A and B (e.g. six issues each, similar text length, categories and ambiguity) and a maintainer-adjudicated reference. Keep these separate from classification test data and the retrieval evaluation pool. Do not reuse identical reports in both conditions. Participant 1: manual A → assisted B; participant 2: assisted A → manual B; participant 3: manual B → assisted A; participant 4: assisted B → manual A; participant 5: choose the least-used order. Manual condition: source text and ordinary search, no category/similarity suggestions. Assisted condition: TriageDesk. Keep instructions and time budget equal. Record correctness against the agreed reference and uncertainty, not just speed. Report individual descriptive results; a few participants do not establish a statistically reliable gain.

## Feedback form

- Were you able to finish each task? What blocked you?
- Ease of finding the next issue, 1–5, and why?
- Usefulness of category suggestions, 1–5, and an example?
- Usefulness of related issues, 1–5, and an example?
- What does a score of 0.73 mean? Does similarity prove a duplicate?
- Was source label versus model suggestion versus human decision clear?
- Did you notice uncertainty or a stale-save conflict? What did you expect?
- What specific change would most improve your workflow?
- Would you use this on your project? Under which conditions?

## Results template — fill only with genuine observations

| Participant code | Order | Task | Completion / assistance | Seconds | Errors/missed steps | Exact observation | Usefulness | Requested change |
|---|---|---|---|---|---|---|---|---|
| Pending | | | | | | | | |

Report recruitment criteria, actual sample size, task sets, dates, missing values and limitations. Distinguish quotes from the facilitator’s interpretations. Avoid claims of established productivity improvement.

## Iteration log

| Date | Observation and evidence | Decision | Implemented change | Follow-up task and result |
|---|---|---|---|---|
| Pending genuine feedback | No study conducted | Await observations | None attributed to users | Pending |

After feedback, choose at least one supported improvement. Preserve the chain: observation → decision → change → follow-up result. Developer/browser QA fixes belong in the engineering progress log and must not be presented as user validation.
