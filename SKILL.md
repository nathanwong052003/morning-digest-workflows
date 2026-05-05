---
name: morning-digest
description: "Create a daily morning digest from calendar events, top 5 important emails, and news (Technology, Southeast Asia, Hong Kong), then publish it as a local PDF, upload it to Google Drive, and create a Google Calendar event with a summary and link. Use for: morning briefings, daily digests, scheduled personal brief reports, Gmail/Google Calendar/Google Drive digest workflows, and news-quality validation."
---

# Morning Digest

Use this skill to create a **daily morning briefing PDF** that matches the user's preferred format: a clean, professional layout with specific sections for schedule, inbox, and regional news.

## Default outcome

Produce all of the following artifacts unless the user asks otherwise:

| Artifact | Default requirement |
| --- | --- |
| Local PDF | Save a date-stamped PDF in a local workspace, such as `\Documents\Local Files\Morning Digest — May 1, 2026.pdf`. |
| Google Drive upload | Upload the PDF to a Drive folder named `Morning Digest`; create the folder if it does not exist. |
| Calendar event | Create an 8:00 AM Google Calendar event titled `1. Morning Digest`, `2. Morning Digest`, and so on (incrementing each day), with a concise extract and the Drive link in the description. |

## Required structure

The digest MUST follow this exact sequence:

1. **Today's Schedule**: Chronological list of all-day and timed events.
2. **Inbox (Top 5 important mail)**: Summarize the 5 most relevant unread emails.
3. **Technology News (4-5 articles)**: Global tech developments with source links.
4. **Southeast Asia News (4-5 articles)**: Regional news covering ASEAN countries.
5. **Hong Kong News (4-5 articles)**: Local news specific to Hong Kong.

## Daily workflow

1. **Create a dated workspace.** Use `\Documents\Local Files\Morning Digest`.
2. **Collect calendar events.** Retrieve all events for the current day.
3. **Collect top 5 emails.** Retrieve unread messages and select the 5 most important based on sender and subject.
4. **Collect news.** Gather 4-5 articles for each category: Technology, Southeast Asia, and Hong Kong. Prioritize high-quality sources per `references/news_quality.md`.
5. **Write the digest.** Use `templates/digest_template.md`. Ensure every news item includes a source link.
6. **Generate the PDF.** Use `scripts/build_digest_pdf.py`. The output must match the clean, professional style of the user's sample.
7. **Publish to Google Drive.** Upload to the `Morning Digest` folder and get the link.
8. **Create the 8:00 AM event.** Add the event with the extract and Drive link. Follow the template per 'templates/calendar_event_template.md'.

## Writing standards

- **Conciseness**: Keep summaries brief and actionable.
- **Links**: Every news article MUST have a clickable source link.
- **Visuals**: Maintain the professional header and section styling defined in the PDF script.
