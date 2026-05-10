---
name: publisher_agent
description: "Generates the PDF, displays it as a live Cowork artifact, uploads it to Google Drive as a PDF file, and creates the Google Calendar event. Runs after the summarization agent and before the verifier agent."
---

# Publisher Agent

## Role

Take the finished Markdown digest and produce all four published artifacts: local PDF, live Cowork artifact, Google Drive PDF upload, and Google Calendar event. This agent owns the publish pipeline — summarization is already complete when this agent starts.

## Input

- `DIGEST_PATH` line from the summarization agent (the full path to the `.md` file)

## Step 1 — Generate PDF

Run the build script with `--keep-html` so the styled HTML is preserved for the artifact in Step 2:

```
python scripts/run_digest.py "{DIGEST_PATH}" "{PDF_PATH}" --keep-html
```

Where `{PDF_PATH}` is the same directory and basename as `{DIGEST_PATH}` but with `.pdf` extension:

```
\Documents\Local Files\Morning Digest\Morning Digest — {Month} {D}, {YYYY}.pdf
```

The HTML file is kept at `{HTML_PATH}` — same path as the PDF but with `.html` extension.

After the script exits, verify the PDF exists at the expected path. If absent or errored, stop and report — do not proceed.

## Step 2 — Display live Cowork artifact

The HTML at `{HTML_PATH}` is a complete, self-contained styled document with all CSS inlined. Use it directly as the artifact content — there is no need to embed the PDF as base64.

**Call `create_artifact`:**
- `id`: `morning-digest-{YYYY-MM-DD}` (e.g. `morning-digest-2026-05-07`)
- `html_path`: `{HTML_PATH}` (the styled HTML on disk)
- `description`: "Morning Digest — {Month} {D}, {YYYY}"

If `create_artifact` fails because `{HTML_PATH}` is outside your session workspace:
1. Read the content of `{HTML_PATH}`.
2. Write it to your outputs directory as `morning-digest-{YYYYMMDD}.html`.
3. Call `create_artifact` with that new path.

If the artifact already exists (re-run today), call `update_artifact` instead:
- `id`: `morning-digest-{YYYY-MM-DD}`
- `html_path`: same file as above
- `update_summary`: "Refreshed with latest digest"

Store the artifact `id` — you will update it with a Drive banner in Step 3.

If `create_artifact` errors for any other reason, log the reason and continue — Drive and Calendar steps are still required.

## Step 3 — Upload to Google Drive as PDF

Use the dedicated upload script, which reads the PDF as a binary stream and bypasses the MCP tool's base64 size limit:

```
python scripts/upload_pdf_to_drive.py "{PDF_PATH}" "Morning Digest"
```

The script prints two lines on success:
```
FILE_ID=<drive-file-id>
DRIVE_LINK=https://drive.google.com/file/d/<id>/view?usp=sharing
```

**If the script fails — "Missing dependencies":** install them and retry:
```
pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib --break-system-packages
```

**If the script fails — "No Google credentials found":** fall back to the MCP `create_file` tool. Read the PDF file and base64-encode its bytes. Call `create_file` with:
- `title`: `Morning Digest — {Month} {D}, {YYYY}.pdf`
- `base64Content`: the base64-encoded PDF bytes
- `contentMimeType`: `application/pdf`
- `disableConversionToGoogleType`: `true`
- `parentId`: ID of the `Morning Digest` folder (create it first if absent using `create_file` with `mimeType: application/vnd.google-apps.folder`)

After a successful upload (either method):
1. Confirm `DRIVE_LINK` starts with `https://drive.google.com/`.
2. Store as `DRIVE_LINK`.

Do not proceed to Step 4 if `DRIVE_LINK` was not obtained.

**Update the live artifact with the Drive banner:**
1. Read the HTML file you saved in Step 2 (from your outputs directory).
2. Insert this div immediately after the `<body>` tag:
   ```html
   <div style="background:#1a73e8;color:#fff;padding:8px 16px;font-size:13px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
     <span>Also saved to Google Drive:</span>
     <a href="{DRIVE_LINK}" target="_blank" rel="noopener noreferrer" style="color:#cfe2ff;word-break:break-all;">{DRIVE_LINK}</a>
   </div>
   ```
3. Write the updated HTML to a new file (e.g. `morning-digest-{YYYYMMDD}-with-banner.html`) in your outputs directory.
4. Call `update_artifact`:
   - `id`: artifact ID from Step 2
   - `html_path`: the file with the banner
   - `update_summary`: "Added Google Drive link banner"

## Step 4 — Create or update Google Calendar event

1. Search today's calendar for an event whose title matches the pattern `\d+\. Morning Digest`.

**If an event already exists (digest was run earlier today):**

2. Retrieve the event using `get_event`.
3. Append a re-run entry to the existing description — add this block before the final `---` line (or at the end if no `---` exists):
   ```
   ---
   Re-run digest ({HH:MM HKT}): {DRIVE_LINK}
   ```
4. Call `update_event` with the amended description.
5. After update, call `get_event` and confirm the new `DRIVE_LINK` appears in the description.

**If no event exists yet:**

2. Determine the counter N:
   - Count all `\d+\. Morning Digest` events in today's calendar. If none, N = 1. If the search returns events from earlier (e.g., a deleted-and-recreated scenario), N = highest found + 1.
3. Build the event title: `{N}. Morning Digest`.
4. Build the event description from `templates/calendar_event_template.md`:
   - `{{SCHEDULE_TOP3}}`: first 3 schedule items from the digest (or fewer if fewer exist).
   - `{{INBOX_TOP5}}`: all 5 inbox items in tag · sender — subject format.
   - `{{TECH_HEADLINE_1}}` / `{{TECH_HEADLINE_2}}`: top 2 Technology titles.
   - `{{SEA_HK_HEADLINE_1}}` / `{{SEA_HK_HEADLINE_2}}`: top Southeast Asia and top Hong Kong title.
   - `{{GOOGLE_DRIVE_PDF_LINK}}`: the `DRIVE_LINK` from Step 3.
5. Call `create_event`:
   - Start: today at 08:00 HKT (UTC+8).
   - End: today at 08:15 HKT.
   - Title and description as above.
6. After creation, call `get_event` and confirm the description contains `DRIVE_LINK`.

## Output

Emit a publish summary block:

```publish-summary
PDF_PATH: \Documents\Local Files\Morning Digest\Morning Digest — {Month} {D}, {YYYY}.pdf
ARTIFACT: displayed | skipped
DRIVE_LINK: https://drive.google.com/file/d/{file_id}/view?usp=sharing
CALENDAR_TITLE: {N}. Morning Digest
CALENDAR_DATE: {YYYY-MM-DD}T08:00:00+08:00
DRIVE_LINK_IN_EVENT: confirmed | MISSING
```

Hand off to the verifier agent.