from __future__ import annotations

from datetime import datetime, timedelta
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from config import Settings
from models import WeatherHour, WeatherSnapshot
from utils.logging import JsonLogger
from utils.retries import retry_call


OPEN_METEO_ENDPOINT = "https://api.open-meteo.com/v1/forecast"

WMO_LABELS: dict[int, tuple[str, str]] = {
    0: ("Clear sky", "☀️"),
    1: ("Mainly clear", "🌤️"),
    2: ("Partly cloudy", "⛅️"),
    3: ("Overcast", "☁️"),
    45: ("Fog", "🌫️"),
    48: ("Depositing rime fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Moderate drizzle", "🌦️"),
    55: ("Dense drizzle", "🌧️"),
    56: ("Light freezing drizzle", "🌧️"),
    57: ("Dense freezing drizzle", "🌧️"),
    61: ("Light rain", "🌦️"),
    63: ("Moderate rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    66: ("Light freezing rain", "🌧️"),
    67: ("Heavy freezing rain", "🌧️"),
    71: ("Light snow", "🌨️"),
    73: ("Moderate snow", "🌨️"),
    75: ("Heavy snow", "❄️"),
    77: ("Snow grains", "❄️"),
    80: ("Light showers", "🌦️"),
    81: ("Moderate showers", "🌧️"),
    82: ("Violent showers", "⛈️"),
    85: ("Light snow showers", "🌨️"),
    86: ("Heavy snow showers", "🌨️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm w/ hail", "⛈️"),
    99: ("Severe thunderstorm", "⛈️"),
}

KEY_HOURS = (7, 10, 13, 16, 19, 22)


def _label_for(code: int) -> tuple[str, str]:
    return WMO_LABELS.get(code, ("Unknown", "•"))


def _format_hour(hour: int) -> str:
    suffix = "am" if hour < 12 else "pm"
    h = hour % 12 or 12
    return f"{h}{suffix}"


def _format_clock(value: str | None, tz: ZoneInfo) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    else:
        dt = dt.astimezone(tz)
    suffix = "am" if dt.hour < 12 else "pm"
    h = dt.hour % 12 or 12
    return f"{h}:{dt.minute:02d}{suffix}"


def _build_mock() -> WeatherSnapshot:
    hours = [
        WeatherHour(hour_label="7am",  temperature_c=23.0, feels_like_c=23.5, precipitation_chance=5,  weather_code=1, weather_label="Mainly clear",  icon="🌤️"),
        WeatherHour(hour_label="10am", temperature_c=26.0, feels_like_c=27.0, precipitation_chance=10, weather_code=2, weather_label="Partly cloudy", icon="⛅️"),
        WeatherHour(hour_label="1pm",  temperature_c=28.5, feels_like_c=30.5, precipitation_chance=20, weather_code=2, weather_label="Partly cloudy", icon="⛅️"),
        WeatherHour(hour_label="4pm",  temperature_c=28.0, feels_like_c=30.0, precipitation_chance=30, weather_code=3, weather_label="Overcast",       icon="☁️"),
        WeatherHour(hour_label="7pm",  temperature_c=26.5, feels_like_c=27.5, precipitation_chance=15, weather_code=1, weather_label="Mainly clear",  icon="🌤️"),
        WeatherHour(hour_label="10pm", temperature_c=24.5, feels_like_c=25.0, precipitation_chance=5,  weather_code=0, weather_label="Clear sky",      icon="☀️"),
    ]
    return WeatherSnapshot(
        city="Hong Kong",
        high_c=29.0,
        low_c=22.0,
        sunrise="6:04am",
        sunset="7:09pm",
        hours=hours,
        summary="Partly cloudy through the day; high 29°C.",
    )


def _resolve_tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def collect_weather(*, settings: Settings, logger: JsonLogger) -> WeatherSnapshot | None:
    started = perf_counter()

    if settings.mock_mode:
        snapshot = _build_mock()
        logger.info("weather_mock", step="weather", city=snapshot.city, latency=perf_counter() - started)
        return snapshot

    params = {
        "latitude": settings.weather_latitude,
        "longitude": settings.weather_longitude,
        "hourly": "temperature_2m,apparent_temperature,precipitation_probability,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,sunrise,sunset",
        "timezone": settings.weather_timezone,
        "forecast_days": 1,
    }
    try:
        response = retry_call(
            lambda: requests.get(OPEN_METEO_ENDPOINT, params=params, timeout=15),
            attempts=3,
            base_delay_seconds=1.0,
            retry_on=lambda exc: isinstance(exc, requests.RequestException),
        )
    except requests.RequestException as exc:
        logger.warning("weather_request_failed", step="weather", error=str(exc))
        return None

    if response.status_code >= 400:
        logger.warning("weather_request_failed", step="weather", status_code=response.status_code)
        return None

    payload: dict[str, Any] = response.json()
    hourly = payload.get("hourly", {})
    daily = payload.get("daily", {})

    times = hourly.get("time", []) or []
    temps = hourly.get("temperature_2m", []) or []
    feels = hourly.get("apparent_temperature", []) or []
    precip = hourly.get("precipitation_probability", []) or []
    codes = hourly.get("weather_code", []) or []

    tz = _resolve_tz(settings.weather_timezone)
    today_local = datetime.now(tz).date()

    hour_map: dict[int, int] = {}
    for idx, raw in enumerate(times):
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        else:
            dt = dt.astimezone(tz)
        if dt.date() != today_local:
            continue
        hour_map[dt.hour] = idx

    rendered_hours: list[WeatherHour] = []
    for target_hour in KEY_HOURS:
        idx = hour_map.get(target_hour)
        if idx is None or idx >= len(temps):
            continue
        code = int(codes[idx]) if idx < len(codes) else 0
        label, icon = _label_for(code)
        rendered_hours.append(
            WeatherHour(
                hour_label=_format_hour(target_hour),
                temperature_c=float(temps[idx]),
                feels_like_c=float(feels[idx]) if idx < len(feels) else None,
                precipitation_chance=int(precip[idx]) if idx < len(precip) else 0,
                weather_code=code,
                weather_label=label,
                icon=icon,
            )
        )

    if not rendered_hours:
        logger.warning("weather_empty_hours", step="weather")
        return None

    high = daily.get("temperature_2m_max", [None])[0]
    low = daily.get("temperature_2m_min", [None])[0]
    sunrise = daily.get("sunrise", [""])[0] if daily.get("sunrise") else ""
    sunset = daily.get("sunset", [""])[0] if daily.get("sunset") else ""

    # Headline: midday condition + high temp + rain hint.
    midday = next((h for h in rendered_hours if "12" in h.hour_label or "1pm" in h.hour_label), rendered_hours[0])
    summary_bits = [midday.weather_label.lower()]
    if high is not None:
        summary_bits.append(f"high {round(float(high))}°C")
    max_precip = max((h.precipitation_chance for h in rendered_hours), default=0)
    if max_precip >= 50:
        summary_bits.append(f"{max_precip}% rain chance")

    snapshot = WeatherSnapshot(
        city=settings.weather_city_label or "Hong Kong",
        high_c=float(high) if high is not None else None,
        low_c=float(low) if low is not None else None,
        sunrise=_format_clock(sunrise, tz),
        sunset=_format_clock(sunset, tz),
        hours=rendered_hours,
        summary=", ".join(summary_bits).capitalize() + ".",
    )

    logger.info(
        "weather_collected",
        step="weather",
        city=snapshot.city,
        hour_count=len(snapshot.hours),
        latency=perf_counter() - started,
    )
    return snapshot
