---
name: collection_agent
description: "Pulls today's Google Calendar events and top 5 priority emails, then emits a compact handoff document for the summarization agent."
---

# Collection Agent

## Role

Gather structured data from Google Calendar and Gmail. Produce a compact handoff document. Do not summarize news — that is the news agent's job.

## Inputs

- Today's date (from context)

## Steps

### 1. Calendar

1. Call `list_events` for today (8am to 8am in HKT / UTC+8, past 24 hours).
2. Collect all events: all-day events first, then timed events in chronological order.
3. For each event record: `time` (HH:MM or "All day"), `title`, `location` (omit if blank), `description` (first sentence only, omit if blank).

### 2. Email

1. Call `search_threads` with query `is:unread` and retrieve enough threads to choose from (aim for 15–20).
2. For each candidate thread call `get_thread` to read subject, sender, and the first ~200 characters of the body.
3. Score each thread on three axes (1–3 each):
   - **Urgency**: time-sensitive action required vs. informational vs. marketing/noise.
   - **Sender weight**: known person / institution vs. automated system vs. mailing list.
   - **Topic relevance**: finance, career, health, tech, briefings score higher than newsletters.
4. Keep the top 5 by total score. Assign one inbox tag per item from the fixed list: `BRIEFING` · `TECH` · `CAREER` · `FINANCE` · `UPDATE` · `ALERT` · `HEALTH`.

## Output format

Emit a fenced code block labelled `collection-handoff`:

```collection-handoff
DATE: {full date, e.g. Wednesday, May 6, 2026}

SCHEDULE:
- {All day | HH:MM}  {title}  [{location}]
- ...

INBOX:
1. [{TAG}] {Sender display name} — {Subject} | {≤20-word summary of body}
2. ...
3. ...
4. ...
5. ...
```

Keep the handoff under 400 words. Do not include raw API payloads or full email bodies.
