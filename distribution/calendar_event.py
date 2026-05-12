from __future__ import annotations

from datetime import date, datetime, timedelta
from time import perf_counter
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import Settings
from models import DigestSummary, RawDigestData
from utils.logging import JsonLogger
from utils.retries import retry_call


def _build_event_description(summary: DigestSummary, raw_data: RawDigestData, digest_link: str) -> str:
    weather = raw_data.weather
    if weather and weather.hours:
        high_low = ""
        if weather.high_c is not None and weather.low_c is not None:
            high_low = f"High {round(weather.high_c)}° / Low {round(weather.low_c)}°"
        sun = ""
        if weather.sunrise and weather.sunset:
            sun = f"Sunrise {weather.sunrise} / Sunset {weather.sunset}"
        weather_lines = [f"{weather.city}: {weather.summary}"]
        if high_low:
            weather_lines.append(f"  {high_low}")
        if sun:
            weather_lines.append(f"  {sun}")
        weather_lines.append("")
        for h in weather.hours[:6]:
            precip = f" 💧{h.precipitation_chance}%" if h.precipitation_chance >= 20 else ""
            weather_lines.append(f"  {h.hour_label}  {h.icon}  {round(h.temperature_c)}°{precip}")
        weather_block = "\n".join(weather_lines)
    else:
        weather_block = "(No weather data)"

    inbox_lines = summary.emails or [f"{email.sender} — {email.subject}" for email in raw_data.emails[:10]]
    inbox_block = "\n".join(inbox_lines[:10]) if inbox_lines else "(No priority emails)"

    if raw_data.ranked_news:
        top_stories = [f"• {item.title}" for item in raw_data.ranked_news[:4]]
    else:
        top_stories = [f"• {item.title}" for item in raw_data.news[:4]]
    top_stories_block = "\n".join(top_stories) if top_stories else "• (No stories)"

    return (
        f"🌤 WEATHER\n"
        f"{weather_block}\n\n"
        f"📬 INBOX ({len(inbox_lines)} priority emails)\n"
        f"{inbox_block}\n\n"
        f"📰 TOP STORIES\n"
        f"{top_stories_block}\n\n"
        f"🔗 Full digest: {digest_link}"
    )


def create_digest_calendar_event(
    *,
    settings: Settings,
    credentials: Credentials,
    digest_date: date,
    iteration: int,
    summary: DigestSummary,
    raw_data: RawDigestData,
    digest_link: str,
    logger: JsonLogger,
) -> str:
    started = perf_counter()
    tz = ZoneInfo(settings.timezone_name)
    start_dt = datetime(
        digest_date.year,
        digest_date.month,
        digest_date.day,
        settings.digest_event_hour,
        settings.digest_event_minute,
        tzinfo=tz,
    )
    end_dt = start_dt + timedelta(minutes=30)
    title = f"{iteration}. ☀ Morning Digest"
    description = _build_event_description(summary, raw_data, digest_link)

    event_body = {
        "summary": title,
        "description": description,
        "colorId": "2",  # Sage
        "start": {"dateTime": start_dt.isoformat(), "timeZone": settings.timezone_name},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": settings.timezone_name},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 0}]},
    }

    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
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

    logger.info(
        "calendar_event_created",
        step="distribution_calendar",
        event_id=event_id,
        latency=perf_counter() - started,
    )
    return str(event_id)
