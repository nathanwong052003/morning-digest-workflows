---
mode: agent
description: "Run the complete Morning Digest pipeline for today. Invokes all five agents in order and publishes the digest as a local PDF, inline chat artifact, Google Drive upload, and Google Calendar event."
---

Run the Morning Digest pipeline for today using the `morning-digest` skill.

Today's date is {{today}}.
Timezone: HKT (UTC+8). User location: Hong Kong.

Invoke the orchestrator agent (`agents/orchestrator_agent.md`) to execute all five agents in strict order:

1. `collection_agent` — pull today's Google Calendar events and top 5 priority emails
2. `news_agent` — fetch and score Technology, Southeast Asia, and Hong Kong news
3. `summarization_agent` — fill `templates/digest_template.md` and write the `.md` file to disk
4. `publisher_agent` — generate the PDF via `scripts/run_digest.py`, display it as an inline artifact, upload to Google Drive, and create the Google Calendar event
5. `verifier_agent` — run all seven checks; attempt fixes for any failures

Enforce all cross-agent constraints from `agents/orchestrator_agent.md`: sequential execution, no invented content, no raw data forwarded between agents, halt and report on unrecoverable failure.

When all checks pass, report:
```
✓ Morning Digest {Month} {D}, {YYYY} published successfully.
PDF: {PDF_PATH}
Drive: {DRIVE_LINK}
```
