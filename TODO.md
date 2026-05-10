# TODO — Morning Digest Workflows

## 1. Promotional Emails Need to Be Ignored

**Problem:** The Gmail collector currently fetches all threads matching `GMAIL_KEYWORDS` (e.g., `urgent,invoice,meeting`) and `GMAIL_LABEL_IDS` (e.g., `INBOX,IMPORTANT`). Promotional/bulk emails can still slip through.

**Required changes:**

- [ ] Add a `GMAIL_EXCLUDED_LABELS` config option (e.g., `CATEGORY_PROMOTIONS, SOCIAL, FORUM`) to filter out threads with those labels.
- [ ] In [`collectors/gmail.py`](collectors/gmail.py), after fetching thread details, skip threads whose `labelIds` contain any excluded label.
- [ ] Add `GMAIL_EXCLUDED_LABELS` to [`config.py`](config.py:62) `Settings` dataclass and [`load_settings()`](config.py:109).
- [ ] Add `GMAIL_EXCLUDED_LABELS` to [`.env.example`](.env.example) with a sensible default (e.g., `CATEGORY_PROMOTIONS,CATEGORY_SOCIAL,CATEGORY_FORUM`).

---

## 2. Blocked List of Emails to Exclude from Digest

**Problem:** There is no mechanism to block specific senders or email addresses from appearing in the digest.

**Required changes:**

- [ ] Add a `GMAIL_BLOCKED_SENDERS` config option (comma-separated email addresses or domains).
- [ ] In [`collectors/gmail.py`](collectors/gmail.py), after extracting the sender, skip threads whose sender matches any blocked sender (exact match or domain suffix match).
- [ ] Add `GMAIL_BLOCKED_SENDERS` to [`config.py`](config.py:62) `Settings` dataclass and [`load_settings()`](config.py:109).
- [ ] Add `GMAIL_BLOCKED_SENDERS` to [`.env.example`](.env.example) (e.g., `newsletters@example.com,marketing@example.com`).

---

## 3. News Tag Needs to Be More Specific

**Problem:** The `tag` field on news items is often generic (e.g., `"News"` as the fallback in [`pdf/generator.py`](pdf/generator.py:322) and [`pdf/generator.py`](pdf/generator.py:492)). The AI ranking in [`ai/deepseek_client.py`](ai/deepseek_client.py:313-315) defines tags per category, but the fallback in the PDF generator always uses `"News"`.

**Required changes:**

- [ ] In [`pdf/generator.py`](pdf/generator.py), update the `_to_ranked()` function (line 322) to infer a more specific tag from the item's title/snippet/source instead of hardcoding `"News"`.
- [ ] In [`pdf/generator.py`](pdf/generator.py), update the `_render_news_groups()` function (line 492) to use a better fallback tag when `row.tag` is empty — consider inferring from the item's content or category.
- [ ] Consider adding a tag inference helper function (similar to `_infer_category`) that maps keywords to specific tags like `AI`, `Cybersecurity`, `Finance`, `Policy`, etc.

---

## 4. News Filtering — Cybersecurity in Wrong Category

**Problem:** Cybersecurity news is appearing in the "Southeast Asia & Hong Kong" tab when it should be in "Technology". The root cause is in [`pdf/generator.py`](pdf/generator.py:288-309) `_infer_category()`: it checks for Hong Kong/SEA keywords **before** checking for technology keywords, so a cybersecurity article mentioning "Hong Kong" gets miscategorized.

**Required changes:**

- [ ] In [`pdf/generator.py`](pdf/generator.py), refactor `_infer_category()` (line 288) to check for **TECHNOLOGY** keywords first (AI, cybersecurity, software, hardware, etc.) before falling through to geography-based checks.
- [ ] Alternatively, respect the AI-assigned `category` from [`RankedNewsItem.category`](models.py:49) when available, and only fall back to `_infer_category()` when the category is empty or unrecognized.
- [ ] Review the `_split_news()` function (line 327) which currently overrides AI-assigned categories with `_infer_category()` — this may need to be reversed so AI categories take precedence.

---

## 5. Remove Unnecessary Code

**Problem:** Several pieces of dead/unused code exist throughout the project.

### Identified candidates:

- [ ] [`pdf/generator.py`](pdf/generator.py:23-27) — `_pdf_engine()` function and the entire ReportLab code path (`_generate_pdf_with_reportlab`, lines 576-642) if WeasyPrint is the only engine actually used. The `DIGEST_PDF_ENGINE` env var and related logic may be removable.
- [ ] [`pdf/generator.py`](pdf/generator.py:563-565) — `_ = summary` and `_ = warning_banner` are no-op assignments.
- [ ] [`pdf/generator.py`](pdf/generator.py:667) — `_ = perf_counter() - started` is an unused variable.
- [ ] [`pdf/generator.py`](pdf/generator.py:691) — Same unused `_ = perf_counter() - started`.
- [ ] [`pdf/generator.py`](pdf/generator.py:655) — `_ = timezone_name` is an unused parameter in `generate_digest_pdf()`.
- [ ] [`collectors/gmail.py`](collectors/gmail.py:49) — `_ = now_local - timedelta(hours=2)` is a no-op.
- [ ] [`ai/deepseek_client.py`](ai/deepseek_client.py:453-475) — `summarize()` method is defined but never called anywhere in the codebase.
- [ ] [`config.py`](config.py:24-33) — `_parse_json_list()` helper is only used for `NEWS_API_URLS_JSON` which is always `[]` in `.env.example` and may be unused.
- [ ] [`config.py`](config.py:67) — `news_api_urls` field and its env var `NEWS_API_URLS_JSON` — if never actually used in news collection, remove both.

---

## 6. Remove Unnecessary Environment Variables

**Problem:** Several env vars in [`.env.example`](.env.example) and [`config.py`](config.py) may be unused or redundant.

### Candidates for removal:

- [ ] `NEWS_API_URLS_JSON` — if the JSON-based news API path is unused.
- [ ] `DIGEST_PDF_ENGINE` — if only WeasyPrint is used.
- [ ] `WEASYPRINT_DLL_DIRECTORIES`, `WEASYPRINT_WINDOWS_EXE`, `WEASYPRINT_WINDOWS_CACHE_DIR`, `WEASYPRINT_WINDOWS_ZIP_URL` — Windows-specific WeasyPrint config that could be documented elsewhere.
- [ ] `GOOGLE_TOKEN_URI` — unlikely to change from the default.
- [ ] `DEEPSEEK_AUDIT_LOG_PATH` — if audit logging is not needed.
- [ ] `TOKEN_SPEND_PATH` — if token tracking is not critical.

---

## 7. Remove Unnecessary Libraries

**Problem:** [`requirements.txt`](requirements.txt) may include libraries that are no longer needed.

### Candidates for removal:

- [ ] `reportlab` — if the ReportLab code path is removed (see item 5).
- [ ] `openai` — if the DeepSeek client is the only AI integration and it uses the OpenAI-compatible SDK, this is still needed. Verify if `openai` is the correct package or if a lighter alternative exists.
- [ ] `tzdata` — verify if this is needed on Windows or if the fallback in `config.py` line 101-103 handles it.

---

## 8. Replace Existing Drive PDF & Calendar Event Instead of Adding New Ones

**Problem:** Every digest run uploads a new PDF to Google Drive and creates a new calendar event, accumulating clutter over time. These should replace the previous versions instead.

**Required changes:**

- [ ] In [`distribution/drive.py`](distribution/drive.py), modify `upload_pdf_to_drive()` to first search for an existing file with a consistent name (e.g., `Morning Digest - Latest.pdf`) in the configured `DRIVE_FOLDER_ID`, and delete or update it instead of always creating a new file.
- [ ] Use a fixed/consistent filename (e.g., `Morning Digest - Latest.pdf`) and overwrite it on each run, keeping only a single "latest" file in Drive.
- [ ] In [`distribution/calendar_event.py`](distribution/calendar_event.py), modify `create_digest_calendar_event()` to search for an existing digest event for today's date and update it (via `events().update()`) instead of always inserting a new one.
- [ ] Add a config option (e.g., `DRIVE_FILE_NAME` or `DRIVE_OVERWRITE_MODE`) to control this behavior — whether to always replace or keep historical files.
- [ ] Update [`.env.example`](.env.example) with any new config variables.
- [ ] Update [`config.py`](config.py) `Settings` dataclass and `load_settings()` with any new config fields.
