# Morning Digest (GitHub Actions + DeepSeek)

Automated daily digest at **08:00 UTC+8**:
1. Collects Google Calendar events, Gmail threads, and news feeds.
2. Uses DeepSeek only for news ranking + summary.
3. Generates a clean PDF (`reportlab`).
4. Uploads PDF to Google Drive and creates a Google Calendar event with the PDF link.

## Project structure

```text
morning-digest/
├── main.py
├── config.py
├── models.py
├── auth/google_oauth.py
├── collectors/
│   ├── calendar.py
│   ├── gmail.py
│   └── news.py
├── ai/deepseek_client.py
├── pdf/generator.py
├── distribution/
│   ├── drive.py
│   └── calendar_event.py
├── utils/
│   ├── logging.py
│   └── retries.py
├── requirements.txt
└── .github/workflows/digest.yml
```

## Local run

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

For offline validation with no external calls:

```bash
MOCK_MODE=true python main.py
```

This validates collectors → AI fallback behavior → PDF generation in a safe local path.

## Required environment variables

### Google OAuth (headless refresh-token flow)
- `CLIENT_ID`
- `CLIENT_SECRET`
- `REFRESH_TOKEN`
- Optional: `GOOGLE_TOKEN_URI` (default: `https://oauth2.googleapis.com/token`)

### Google destinations
- `DRIVE_FOLDER_ID`
- `DIGEST_CALENDAR_ID` (default: `primary`)

### Gmail filters
- `GMAIL_LABEL_IDS` (comma-separated label IDs)
- `GMAIL_KEYWORDS` (comma-separated keywords)
- Optional: `GMAIL_MAX_THREADS` (default: `20`)

### News sources
- News collection is category-driven (`TECHNOLOGY`, `SOUTHEAST ASIA`, `HONG KONG`) and only keeps **headline + lede/snippet** candidates.
- Sources are constrained to curated priority outlets per category (Reuters/AP/Bloomberg/etc., plus CISA advisories and HK government press releases where applicable).
- Collector targets **6-8 candidates per category** before AI ranking.

### DeepSeek
- `DEEPSEEK_API_KEY`
- Optional: `DEEPSEEK_BASE_URL` (default `https://api.deepseek.com`)
- Optional: `DEEPSEEK_MODEL` (default `deepseek-chat`)

### Runtime/cost controls
- `TIMEZONE_NAME` (default `Asia/Hong_Kong`)
- `OUTPUT_DIR` (default `output`)
- `NEWS_CACHE_PATH` (default `/tmp/morning_digest_news_cache.json`)
- `NEWS_CACHE_TTL_SECONDS` (default `43200`, 12 hours)
- `TOKEN_SPEND_PATH` (default `/tmp/morning_digest_token_spend.json`)
- `DAILY_TOKEN_WARN_THRESHOLD` (default `50000`)
- `DIGEST_PDF_ENGINE` (`auto`, `reportlab`, or `weasyprint`; default `auto`, which tries WeasyPrint first and falls back to ReportLab on failure)
- `WEASYPRINT_DLL_DIRECTORIES` (Windows only; semicolon-separated directories containing GTK/Pango DLLs such as `libgobject-2.0-0.dll`)
- `WEASYPRINT_WINDOWS_EXE` (Windows optional; explicit path to standalone `weasyprint.exe`)
- `WEASYPRINT_WINDOWS_CACHE_DIR` (Windows optional; cache folder for downloaded standalone WeasyPrint zip)
- `WEASYPRINT_WINDOWS_ZIP_URL` (Windows optional; override URL for standalone WeasyPrint zip)

### WeasyPrint on Windows (native libraries)
- Root cause of the common startup error is missing GTK/Pango runtime DLLs (`libgobject-2.0-0.dll`).
- Install a GTK runtime (for example MSYS2 UCRT64 runtime), then set `WEASYPRINT_DLL_DIRECTORIES` to the runtime `bin` folder (or add it to `PATH`).
- If GTK is unavailable, this project automatically falls back to the official standalone WeasyPrint Windows binary (`weasyprint-windows.zip`) and still renders with WeasyPrint.

## OAuth refresh token setup guide

1. In Google Cloud Console, create OAuth client credentials for a Desktop app.
2. Enable APIs: Gmail API, Calendar API, Drive API.
3. Generate an initial refresh token once (local interactive flow).
4. Store these in GitHub repository secrets:
   - `CLIENT_ID`
   - `CLIENT_SECRET`
   - `REFRESH_TOKEN`
5. Runtime uses `google.oauth2.credentials.Credentials` and refreshes access tokens automatically.

## GitHub Actions

Workflow: `.github/workflows/digest.yml`
- Runs daily at `0 0 * * *` (UTC), which is **08:00 UTC+8**.
- Supports manual trigger (`workflow_dispatch`).
- Uploads generated PDF as an artifact each run.

## Reliability and observability

- Structured JSON logs include `run_id`, `step`, `tokens_used`, and `latency`.
- Never logs secrets or full email bodies (metadata + snippets only).
- Gmail inbox data never leaves the local runtime for AI calls; DeepSeek only receives news items.
- All external calls are wrapped with retry + exponential backoff.
- News feed responses are cached for 12 hours.
- Daily token spend is tracked and warnings emitted above threshold.
- If AI fails or token budget is exceeded, PDF still generates with:
  - `⚠️ AI unavailable` warning banner
  - Raw-data fallback digest content
