from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import Settings
from models import DigestSummary, RawDigestData
from utils.logging import JsonLogger
from utils.retries import retry_call


def _parse_schedule_line(line: str) -> tuple[str, str]:
    pattern = r"^\s*([0-2]?\d:\d{2})(?:\s*-\s*[0-2]?\d:\d{2})?\s*[:\-]\s*(.+?)\s*$"
    match = re.match(pattern, line)
    if match:
        return match.group(1), match.group(2)
    return "", line.strip()


def _build_event_description(summary: DigestSummary, raw_data: RawDigestData, digest_link: str) -> str:
    schedule_lines = summary.schedule or [f"{event.start_local}  {event.title}" for event in raw_data.calendar[:10]]
    parsed_schedule = [_parse_schedule_line(line) for line in schedule_lines]
    schedule_block = "\n".join(
        f"{time_value}  {title}" if time_value else title for time_value, title in parsed_schedule[:10]
    )
    if not schedule_block:
        schedule_block = "(No events)"

    inbox_lines = summary.emails or [f"{email.sender} — {email.subject}" for email in raw_data.emails[:10]]
    inbox_block = "\n".join(inbox_lines[:10]) if inbox_lines else "(No priority emails)"

    if raw_data.ranked_news:
        top_stories = [f"• {item.title}" for item in raw_data.ranked_news[:4]]
    else:
        top_stories = [f"• {item.title}" for item in raw_data.news[:4]]
    top_stories_block = "\n".join(top_stories) if top_stories else "• (No stories)"

    return (
        f"📅 SCHEDULE ({len(parsed_schedule)} events today)\n"
        f"{schedule_block}\n\n"
        f"📬 INBOX ({len(inbox_lines)} priority emails)\n"
        f"{inbox_block}\n\n"
        f"📰 TOP STORIES\n"
        f"{top_stories_block}\n\n"
        f"🔗 Full digest: {digest_link}"
    )


def _find_existing_event(
    service: Any,
    calendar_id: str,
    digest_date: date,
) -> str | None:
    """Search for an existing Morning Digest event on the given date.

    Returns the event ID if found, or None otherwise.
    """
    day_start = datetime(digest_date.year, digest_date.month, digest_date.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    events_result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            q="Morning Digest",
            singleEvents=True,
            fields="items(id)",
        )
        .execute()
    )
    items = events_result.get("items", [])
    if items:
        return items[0]["id"]
    return None


def create_digest_calendar_event(
    *,
    settings: Settings,
    credentials: Credentials,
    digest_date: date,
    summary: DigestSummary,
    raw_data: RawDigestData,
    digest_link: str,
    logger: JsonLogger,
) -> str:
    started = perf_counter()
    timezone = ZoneInfo(settings.timezone_name)
    start_dt = datetime(
        digest_date.year,
        digest_date.month,
        digest_date.day,
        settings.digest_event_hour,
        settings.digest_event_minute,
        tzinfo=timezone,
    )
    end_dt = start_dt + timedelta(minutes=30)
    title = "☀ Morning Digest"
    description = _build_event_description(summary, raw_data, digest_link)

    event_body = {
        "summary": title,
        "description": description,
        "colorId": "8",  # Sage
        "start": {"dateTime": start_dt.isoformat(), "timeZone": settings.timezone_name},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": settings.timezone_name},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 10}]},
    }

    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    if settings.drive_overwrite_mode:
        # Overwrite mode: search for an existing event for today and update it
        existing_event_id = _find_existing_event(service, settings.digest_calendar_id, digest_date)

        if existing_event_id:
            result = retry_call(
                lambda: service.events()
                .update(
                    calendarId=settings.digest_calendar_id,
                    eventId=existing_event_id,
                    body=event_body,
                    sendUpdates="none",
                )
                .execute(),
                attempts=3,
                base_delay_seconds=1.0,
            )
            event_id = result.get("id", "")
            action = "updated"
        else:
            result = retry_call(
                lambda: service.events()
                .insert(
                    calendarId=settings.digest_calendar_id,
                    body=event_body,
                    sendUpdates="none",
                )
                .execute(),
                attempts=3,
                base_delay_seconds=1.0,
            )
            event_id = result.get("id", "")
            action = "created"
    else:
        # Historical mode: always insert a new event
        result = retry_call(
            lambda: service.events()
            .insert(
                calendarId=settings.digest_calendar_id,
                body=event_body,
                sendUpdates="none",
            )
            .execute(),
            attempts=3,
            base_delay_seconds=1.0,
        )
        event_id = result.get("id", "")
        action = "created"

    logger.info(
        f"calendar_event_{action}",
        step="distribution_calendar",
        event_id=event_id,
        latency=perf_counter() - started,
    )
    return str(event_id)
