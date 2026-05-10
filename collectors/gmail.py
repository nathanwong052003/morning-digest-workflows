from __future__ import annotations

from email.header import decode_header
from datetime import datetime, timedelta
from time import perf_counter

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import Settings
from models import GmailThread, truncate_text
from utils.logging import JsonLogger
from utils.retries import retry_call


def _build_query(settings: Settings) -> str:
    base = "newer_than:1d"
    if not settings.gmail_keywords:
        return base
    keywords = " OR ".join(f'"{term}"' for term in settings.gmail_keywords)
    return f"{base} ({keywords})"


def _get_header(headers: list[dict[str, str]], name: str) -> str:
    lowered = name.lower()
    for header in headers:
        if header.get("name", "").lower() == lowered:
            return header.get("value", "")
    return ""


def _decode_mime_header(value: str) -> str:
    if not value:
        return ""
    decoded_parts: list[str] = []
    for part, charset in decode_header(value):
        if isinstance(part, bytes):
            enc = charset or "utf-8"
            try:
                decoded_parts.append(part.decode(enc))
            except (LookupError, UnicodeDecodeError):
                decoded_parts.append(part.decode("utf-8", errors="replace"))
        else:
            decoded_parts.append(part)
    return "".join(decoded_parts).strip()


def _collect_mock(now_local: datetime) -> list[GmailThread]:
    _ = now_local - timedelta(hours=2)
    return [
        GmailThread(
            sender="alerts@example.com",
            subject="Daily Ops Summary",
            snippet="Service health remains stable. One minor warning needs review.",
            labels=["INBOX", "IMPORTANT"],
        )
    ]


def collect_gmail_threads(
    *,
    settings: Settings,
    credentials: Credentials | None,
    logger: JsonLogger,
) -> list[GmailThread]:
    step_start = perf_counter()
    if settings.mock_mode:
        threads = _collect_mock(settings.now_local())
        logger.info(
            "gmail_collected_mock",
            step="gmail",
            item_count=len(threads),
            latency=perf_counter() - step_start,
        )
        return threads

    if credentials is None:
        raise ValueError("Google credentials are required for live Gmail collection.")

    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    query = _build_query(settings)

    list_resp = retry_call(
        lambda: service.users()
        .threads()
        .list(
            userId=settings.gmail_user_id,
            q=query,
            labelIds=settings.gmail_label_ids or None,
            maxResults=settings.gmail_max_threads,
        )
        .execute(),
        attempts=3,
        base_delay_seconds=1.0,
    )

    threads: list[GmailThread] = []
    for thread_item in list_resp.get("threads", []):
        thread_id = thread_item.get("id")
        if not thread_id:
            continue
        detail = retry_call(
            lambda: service.users()
            .threads()
            .get(
                userId=settings.gmail_user_id,
                id=thread_id,
                format="metadata",
                metadataHeaders=["From", "Subject"],
            )
            .execute(),
            attempts=3,
            base_delay_seconds=1.0,
        )

        messages = detail.get("messages", [])
        if not messages:
            continue
        first = messages[0]
        headers = first.get("payload", {}).get("headers", [])
        sender = _decode_mime_header(_get_header(headers, "From")) or "(Unknown sender)"
        subject = _decode_mime_header(_get_header(headers, "Subject")) or "(No subject)"
        snippet = truncate_text(detail.get("snippet", ""), limit=500)
        labels = first.get("labelIds", [])

        threads.append(
            GmailThread(
                sender=sender,
                subject=subject,
                snippet=snippet,
                labels=labels,
            )
        )

    logger.info(
        "gmail_collected",
        step="gmail",
        item_count=len(threads),
        latency=perf_counter() - step_start,
    )
    return threads
