---
name: verifier_agent
description: "Runs all success criteria checks against the publisher agent's output. Fixes failures before reporting completion to the user."
---

# Verifier Agent

## Role

Independently verify every deliverable. Do not trust that prior agents succeeded — inspect each artifact directly. If a check fails, attempt the fix and re-verify before reporting to the user.

## Input

- `publish-summary` block from the publisher agent
- Access to local filesystem, Google Drive, and Google Calendar

## Checklist

Run all seven checks. Record `PASS` or `FAIL` for each.

### Check 1 — PDF exists

- Confirm the file at `PDF_PATH` from the publish summary exists on disk.
- Confirm the file size is > 0 bytes.

**Fix if failed:** Re-run `scripts/run_digest.py` with the digest Markdown path and PDF path.

---

### Check 2 — Filename convention

- Parse the filename from `PDF_PATH`.
- Confirm it matches: `Morning Digest — {Month} {D}, {YYYY}.pdf`
  - Em dash `—` present (not a hyphen `-`).
  - Month is the full English name (January … December).
  - Day has no leading zero.
  - Year is four digits.

**Fix if failed:** Rename the file to the correct convention; re-upload to Drive if already uploaded under the wrong name.

---

### Check 3 — Output files valid (fast spot-check — do NOT re-run scripts)

Do not re-run `render_digest.py` or `build_digest_pdf.py`. Instead, verify the files the publisher already produced using these lightweight checks:

#### 3a — HTML spot-check

```
python -c "
import pathlib, sys
p = pathlib.Path(r'{HTML_PATH}')
if not p.exists() or p.stat().st_size == 0:
    sys.exit('FAIL: HTML missing or empty')
t = p.read_text(encoding='utf-8')
for s in ['TODAY\'S SCHEDULE','PRIORITY INBOX','TECHNOLOGY','SOUTHEAST ASIA','HONG KONG']:
    if s not in t:
        sys.exit(f'FAIL: section missing: {s}')
if '{{' in t:
    sys.exit('FAIL: unfilled placeholders found')
print('PASS')
"
```

**PASS** if the script prints `PASS`. **FAIL** if any section is missing, the file is absent, or raw `{{...}}` placeholders remain.

**Fix if failed:** Re-run `render_digest.py` once:
```
python scripts/render_digest.py "{DIGEST_PATH}" "{HTML_PATH}"
```
Common causes: `ModuleNotFoundError: markdown` → `pip install markdown --break-system-packages`; `FileNotFoundError` → confirm `DIGEST_PATH` is correct.

#### 3b — PDF spot-check

```
python -c "
import pathlib, sys
p = pathlib.Path(r'{PDF_PATH}')
if not p.exists():
    sys.exit('FAIL: PDF missing')
size = p.stat().st_size
if size < 30_000:
    sys.exit(f'FAIL: PDF too small ({size} bytes) — likely render error')
sig = p.read_bytes()[:4]
if sig != b'%PDF':
    sys.exit(f'FAIL: not a valid PDF (got {sig!r})')
print('PASS')
"
```

**PASS** if the script prints `PASS`. Size threshold is **30 KB** (WeasyPrint produces compressed PDFs; 30 KB is the correct lower bound).

**Fix if failed:** Re-run `build_digest_pdf.py` once:
```
python scripts/build_digest_pdf.py "{HTML_PATH}" "{PDF_PATH}"
```
Common causes: `ImportError: weasyprint` → `pip install weasyprint --break-system-packages`; `FileNotFoundError` on HTML → fix 3a first.

---

### Check 4 — Chat artifact displayed

- Confirm `ARTIFACT` in the publish summary is `displayed` (not `skipped`).
- If `skipped`, note the reason but do not treat it as a blocking failure — proceed to Check 5.

**Fix if failed:** The artifact should be the styled digest HTML (not a PDF data URI). Call `create_artifact` with:
- `id`: `morning-digest-{YYYY-MM-DD}`
- `html_path`: the HTML file at `{HTML_PATH}` (re-run `render_digest.py` to regenerate it if absent)
- `description`: `Morning Digest — {Month} {D}, {YYYY}`

If the artifact already exists, call `update_artifact` instead.

---

### Check 5 — Google Drive upload confirmed

1. First confirm the PDF file exists at `PDF_PATH` on disk (independent of Check 1 — do not skip even if Check 1 passed). If the PDF is absent, run `python scripts/run_digest.py "{DIGEST_PATH}" "{PDF_PATH}"` before attempting to upload.
2. Confirm `DRIVE_LINK` in the publish summary starts with `https://drive.google.com/`. If `DRIVE_LINK` is missing or invalid, treat this as a FAIL even if the publisher reported success.
3. Call `get_file_metadata` for the file ID embedded in `DRIVE_LINK` and confirm the API returns a valid file record. Check all three of the following — **FAIL** if any do not match:
   - `mimeType` is `application/pdf` (not `text/plain`, `text/markdown`, `application/vnd.google-apps.document`, or anything else).
   - `name` ends with `.pdf` (not `.md`, `.html`, or any other extension).
   - `name` matches the filename convention: `Morning Digest — {Month} {D}, {YYYY}.pdf`.

**Fix if failed:**
- Delete any wrongly uploaded file from Drive first (use `delete_file` if available, or skip deletion and upload a fresh copy).
- Upload the correct file using the dedicated script: `python scripts/upload_pdf_to_drive.py "{PDF_PATH}"`. This uploads the binary PDF and avoids the base64 size limit.
- If the script is unavailable or fails with "No Google credentials found", fall back to the MCP `create_file` tool with: `base64Content` (base64-encoded PDF bytes), `contentMimeType: application/pdf`, `disableConversionToGoogleType: true`, `title: Morning Digest — {Month} {D}, {YYYY}.pdf`.
- After re-upload, reconstruct `DRIVE_LINK` as `https://drive.google.com/file/d/{new_file_id}/view?usp=sharing` and re-run the metadata check before proceeding.

---

### Check 6 — Calendar event created

- Search today's calendar for an event matching `CALENDAR_TITLE` from the publish summary.
- Confirm the event start time is 08:00 HKT.

**Fix if failed:** Create the event using the publisher agent's Step 4 procedure.

---

### Check 7 — Drive link in Calendar event

- Retrieve the calendar event found in Check 6.
- Inspect the `description` field.
- Confirm `DRIVE_LINK` appears verbatim in the description.

**Fix if failed:** Update the event description to include `DRIVE_LINK` on its own line labelled `Full Digest: {DRIVE_LINK}`.

---

## Output

Report the final status to the user:

```
Morning Digest — {Month} {D}, {YYYY} — Verification Report

[PASS/FAIL] 1. PDF created at {PDF_PATH}
[PASS/FAIL] 2. Filename convention correct
[PASS/FAIL] 3. Output files valid (spot-check)
             3a. HTML present — 5 sections, no placeholders
             3b. PDF present — >30 KB, %PDF signature
[PASS/FAIL] 4. Chat artifact displayed inline
[PASS/FAIL] 5. Drive upload confirmed — {DRIVE_LINK}
[PASS/FAIL] 6. Calendar event "{CALENDAR_TITLE}" at 08:00 HKT
[PASS/FAIL] 7. Drive link present in calendar event description

Status: ALL CHECKS PASSED ✓ | {N} CHECK(S) FAILED — see above
```

Only report `ALL CHECKS PASSED` after all seven checks show `PASS` (Check 4 may be noted as skipped without blocking overall pass). If any other check remains `FAIL` after the fix attempt, report the failure with the reason and stop.
