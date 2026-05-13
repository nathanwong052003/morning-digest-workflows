from __future__ import annotations

from datetime import datetime, time, timedelta
from time import perf_counter
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import Settings
from models import CalendarEvent, truncate_text
from utils.logging import JsonLogger
from utils.retries import retry_call

GOOGLE_CALENDAR_COLORS = {
    "1": "#46d6db",
    "2": "#7ae7bf",
    "3": "#dbadff",
    "4": "#ffb878",
    "5": "#fbd75b",
    "6": "#ff887c",
    "7": "#a4bdfc",
    "8": "#e1e1e1",
    "9": "#5484ed",
    "10": "#51b749",
    "11": "#dc2127",
}


def _collect_mock(now_local: datetime) -> list[CalendarEvent]:
    start = datetime.combine(now_local.date(), time(9, 0), now_local.tzinfo)
    end = start + timedelta(minutes=30)
    return [
        CalendarEvent(
            title="Daily Planning",
            start_local=start.isoformat(),
            end_local=end.isoformat(),
            location="Home Office",
            description="Review priorities and blockers.",
            attendees=["self@example.com"],
            color="#9fe1e9",
        )
    ]


def collect_calendar_events(
    *,
    settings: Settings,
    credentials: Credentials | None,
    logger: JsonLogger,
) -> list[CalendarEvent]:
    step_start = perf_counter()
    now_local = settings.now_local()
    if settings.mock_mode:
        events = _collect_mock(now_local)
        logger.info(
            "calendar_collected_mock",
            step="calendar",
            item_count=len(events),
            latency=perf_counter() - step_start,
        )
        return events

    if credentials is None:
        raise ValueError("Google credentials are required for live calendar collection.")

    timezone = ZoneInfo(settings.timezone_name)
    start_of_day = datetime.combine(now_local.date(), time.min, timezone)
    end_of_day = datetime.combine(now_local.date(), time.max, timezone)

    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    events_result = retry_call(
        lambda: service.events()
        .list(
            calendarId=settings.digest_calendar_id,
            timeMin=start_of_day.isoformat(),
            timeMax=end_of_day.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=100,
        )
        .execute(),
        attempts=3,
        base_delay_seconds=1.0,
    )

    normalized: list[CalendarEvent] = []
    for item in events_result.get("items", []):
        if item.get("status") == "cancelled":
            continue
        start_raw = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date", "")
        end_raw = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date", "")
        attendees = [
            attendee.get("email", "")
            for attendee in item.get("attendees", [])
            if attendee.get("email")
        ]
        color_id = item.get("colorId", "1")
        color = GOOGLE_CALENDAR_COLORS.get(color_id, "#9fe1e9")
        normalized.append(
            CalendarEvent(
                title=item.get("summary", "(No title)"),
                start_local=start_raw,
                end_local=end_raw,
                location=item.get("location", ""),
                description=truncate_text(item.get("description", ""), limit=500),
                attendees=attendees,
                color=color,
            )
        )

    logger.info(
        "calendar_collected",
        step="calendar",
        item_count=len(normalized),
        latency=perf_counter() - step_start,
    )
    return normalized
