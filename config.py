from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return []


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, value.strip())


@dataclass(frozen=True)
class Settings:
    timezone_name: str
    run_id: str
    mock_mode: bool

    client_id: str
    client_secret: str
    refresh_token: str
    google_token_uri: str

    gmail_user_id: str
    gmail_label_ids: list[str]
    gmail_keywords: list[str]
    gmail_max_threads: int

    news_rss_urls: list[str]
    news_api_urls: list[str]
    news_cache_path: str
    news_cache_ttl_seconds: int
    max_news_items: int

    drive_folder_id: str
    digest_calendar_id: str
    digest_event_hour: int
    digest_event_minute: int

    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    deepseek_temperature: float
    deepseek_max_tokens: int
    ai_retry_attempts: int

    token_spend_path: str
    daily_token_warn_threshold: int
    output_dir: str

    @property
    def google_scopes(self) -> list[str]:
        return [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/drive.file",
        ]

    def now_local(self) -> datetime:
        try:
            return datetime.now(ZoneInfo(self.timezone_name))
        except ZoneInfoNotFoundError as err:
            if self.timezone_name == "Asia/Hong_Kong":
                # Windows/Python builds without IANA tzdata can still represent HKT as fixed UTC+8.
                return datetime.now(timezone(timedelta(hours=8), name="Asia/Hong_Kong"))
            raise RuntimeError(
                f"Timezone '{self.timezone_name}' is unavailable. Install tzdata or set TIMEZONE_NAME to a supported timezone."
            ) from err


def load_settings() -> Settings:
    _load_dotenv(Path(".env"))
    return Settings(
        timezone_name=os.getenv("TIMEZONE_NAME", "Asia/Hong_Kong"),
        run_id=os.getenv("RUN_ID", os.getenv("GITHUB_RUN_ID", str(uuid.uuid4()))),
        mock_mode=_parse_bool(os.getenv("MOCK_MODE")),
        client_id=os.getenv("CLIENT_ID", ""),
        client_secret=os.getenv("CLIENT_SECRET", ""),
        refresh_token=os.getenv("REFRESH_TOKEN", ""),
        google_token_uri=os.getenv("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token"),
        gmail_user_id=os.getenv("GMAIL_USER_ID", "me"),
        gmail_label_ids=_split_csv(os.getenv("GMAIL_LABEL_IDS")),
        gmail_keywords=_split_csv(os.getenv("GMAIL_KEYWORDS")),
        gmail_max_threads=int(os.getenv("GMAIL_MAX_THREADS", "20")),
        news_rss_urls=_split_csv(os.getenv("NEWS_RSS_URLS")),
        news_api_urls=_parse_json_list(os.getenv("NEWS_API_URLS_JSON")),
        news_cache_path=os.getenv("NEWS_CACHE_PATH", "/tmp/morning_digest_news_cache.json"),
        news_cache_ttl_seconds=int(os.getenv("NEWS_CACHE_TTL_SECONDS", "43200")),
        max_news_items=int(os.getenv("MAX_NEWS_ITEMS", "30")),
        drive_folder_id=os.getenv("DRIVE_FOLDER_ID", ""),
        digest_calendar_id=os.getenv("DIGEST_CALENDAR_ID", "primary"),
        digest_event_hour=int(os.getenv("DIGEST_EVENT_HOUR", "8")),
        digest_event_minute=int(os.getenv("DIGEST_EVENT_MINUTE", "0")),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        deepseek_temperature=float(os.getenv("DEEPSEEK_TEMPERATURE", "0.2")),
        deepseek_max_tokens=int(os.getenv("DEEPSEEK_MAX_TOKENS", "1500")),
        ai_retry_attempts=int(os.getenv("AI_RETRY_ATTEMPTS", "3")),
        token_spend_path=os.getenv("TOKEN_SPEND_PATH", "/tmp/morning_digest_token_spend.json"),
        daily_token_warn_threshold=int(os.getenv("DAILY_TOKEN_WARN_THRESHOLD", "50000")),
        output_dir=os.getenv("OUTPUT_DIR", "output"),
    )
