# Morning Digest (GitHub Actions + DeepSeek)

Automated daily digest at **08:00 UTC+8**:
1. Collects Google Calendar events, Gmail threads, news feeds, and Hong Kong weather.
2. Uses DeepSeek only for news ranking + summary.
3. Detects "developing" stories (topic overlap vs. recent days) and dedupes exact repeats.
4. Generates a clean PDF (WeasyPrint / ReportLab fallback).
5. Uploads PDF to Google Drive, creates a Google Calendar event, and emails the digest to you with the PDF attached.

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
├── collectors/weather.py
├── pdf/generator.py
├── distribution/
│   ├── drive.py
│   ├── calendar_event.py
│   ├── email.py
│   └── email_template.html
├── utils/
│   ├── logging.py
│   ├── retries.py
│   └── news_history.py
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
- `DIGEST_EMAIL_TO` (recipient for the morning email; default `nathanwongshihhao@gmail.com`)

### Weather (Open-Meteo, no API key required)
- `WEATHER_LATITUDE` (default `22.3193` — Hong Kong)
- `WEATHER_LONGITUDE` (default `114.1694` — Hong Kong)
- `WEATHER_TIMEZONE` (default `Asia/Hong_Kong`)
- `WEATHER_CITY_LABEL` (default `Hong Kong`)
- Forecast covers 7am / 12pm / 5pm / 9pm cross-section for the day.

### News diff (developing stories)
- `NEWS_HISTORY_PATH` (default `/tmp/morning_digest_news_history.json`)
- Stores the previous 3 days of news URLs + headlines.
- Exact-URL repeats from prior days are silently dropped.
- Stories whose title/snippet share significant keywords with a prior-day item are flagged `CONTINUING` and surfaced in a "Developing stories" block.

### Digest iteration counter
- `DIGEST_COUNTER_PATH` (default `/tmp/morning_digest_counter.json`)
- Tracks an integer that increments by 1 each new day. The PDF filename, email subject, and calendar event title are all prefixed with the current iteration (e.g. `42. Morning Digest — May 12, 2026`).
- Re-running on the same day reuses the same number.
- Persisted across GitHub Actions runs via the `digest-counter-` cache key.

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
- Optional: `DEEPSEEK_AUDIT_LOG_PATH` (default `output/deepseek_requests_<RUN_ID>.jsonl`)

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
   - `DIGEST_EMAIL_TO`
5. Runtime uses `google.oauth2.credentials.Credentials` and refreshes access tokens automatically.

> **Scope change:** The pipeline now sends an email each morning, which requires the `gmail.send` scope. **If you set up your refresh token before this change, re-run `python get_refresh_token.py` and update the `REFRESH_TOKEN` secret** — the existing token does not include the send scope and the email step will fail until the new token is in place.

## GitHub Actions

Workflow: `.github/workflows/digest.yml`
- Runs daily at `00 00 * * *` (UTC), which is **08:00 UTC+8**.
- Supports manual trigger (`workflow_dispatch`).
- Manual trigger supports `mock_mode=true` to run without external APIs.
- Uploads generated PDF as an artifact each run.
- Uploads DeepSeek request/response audit logs as `deepseek-audit-log` artifact.
- Caches the news-history JSON across runs (key prefix `news-history-`) so developing-story detection persists.

## Reliability and observability

- Structured JSON logs include `run_id`, `step`, `tokens_used`, and `latency`.
- Never logs secrets or full email bodies (metadata + snippets only).
- Gmail inbox data never leaves the local runtime for AI calls; DeepSeek only receives news items.
- All external calls are wrapped with retry + exponential backoff.
- News feed responses are cached for 12 hours.
- Daily token spend is tracked and warnings emitted above threshold.
- If AI fails or token budget is exceeded, PDF still generates with:
  - `⚠ AI unavailable` warning banner
  - Raw-data fallback digest content
- Email send is wrapped in a try/except — if Gmail send fails for any reason, the Drive upload + Calendar event still complete.