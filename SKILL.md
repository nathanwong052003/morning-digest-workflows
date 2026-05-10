---
name: morning-digest
description: "Create a daily morning digest from calendar events, top 5 important emails, and news (Technology, Southeast Asia, Hong Kong), then publish it as a local PDF, display it inline in the chat as an artifact, upload it to Google Drive, and create a Google Calendar event with a summary and link. Use for: morning briefings, daily digests, scheduled personal brief reports, Gmail/Google Calendar/Google Drive digest workflows, news-quality validation, and inline PDF artifact display."
---
 
# Morning Digest
 
Produce a daily morning briefing PDF in a clean, professional layout covering schedule, inbox, and regional news. Run the five agents below in order. Each agent emits a compact handoff document for the next — do not carry raw API responses forward between agents.
 
## Agent call order
 
The `orchestrator_agent` coordinates the pipeline. See `agents/orchestrator_agent.md` for sequencing rules, failure handling, and cross-agent constraints.
 
```
0. orchestrator_agent  → gates each step; owns completion report
1. collection_agent    → collection-handoff
2. news_agent          → news-handoff
3. summarization_agent → DIGEST_PATH + .md file on disk
4. publisher_agent     → publish-summary (PDF + artifact + Drive + Calendar)
5. verifier_agent      → verification report
```
 
Full instructions for each agent are in `agents/`.
 
## Default artifacts
 
| Artifact | Requirement |
| --- | --- |
| Local PDF | `\Documents\Local Files\Morning Digest\Morning Digest — {Month} {D}, {YYYY}.pdf` |
| Chat artifact | Live Cowork artifact showing the styled digest HTML, displayed immediately after PDF generation. Drive banner link added once upload completes. |
| Google Drive | Upload to folder `Morning Digest` (create if absent). Retrieve shareable link before proceeding. |
| Calendar event | 8:00 AM event titled `{N}. Morning Digest` (counter increments each day). Description includes digest extract and Drive link. |
 
## Filename convention
 
`Morning Digest — {Month} {D}, {YYYY}.pdf` — em dash, full month name, no leading zero, four-digit year.
 
## Digest structure
 
The digest follows `templates/digest_template.md` exactly, in this order:
 
1. Today's Schedule
2. Priority Inbox (top 5 emails)
3. Technology News (4–5 articles)
4. Southeast Asia News (4–5 articles)
5. Hong Kong News (4–5 articles)
## Success criteria
 
All seven checks must pass (verified by the verifier agent) before reporting completion:
 
| # | Check |
| --- | --- |
| 1 | PDF exists at the correct local path |
| 2 | Filename follows the convention |
| 3 | All five template sections present, every article has a tag and link, every inbox item has a tag |
| 4 | Chat artifact displayed as a live Cowork artifact showing the styled digest |
| 5 | Drive shareable link obtained and valid (`https://drive.google.com/…`) and file is a PDF (not a Google Doc) |
| 6 | Calendar event exists at 08:00 HKT with correct incremented title |
| 7 | Drive link appears verbatim in the calendar event description |