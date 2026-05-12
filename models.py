from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


def truncate_text(value: str | None, limit: int = 500) -> str:
    if not value:
        return ""
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


class CalendarEvent(BaseModel):
    title: str
    start_local: str
    end_local: str
    location: str = ""
    description: str = ""
    attendees: list[str] = Field(default_factory=list)


class GmailThread(BaseModel):
    sender: str
    subject: str
    snippet: str
    labels: list[str] = Field(default_factory=list)


class NewsItem(BaseModel):
    title: str
    url: HttpUrl
    source: str
    published_at: datetime | None = None
    snippet: str


class RankedNewsItem(BaseModel):
    title: str
    url: HttpUrl
    source: str
    published_at: datetime | None = None
    snippet: str
    relevance: int = Field(default=50, ge=0, le=100)
    reason: str = ""
    category: str = ""
    tag: str = ""
    ai_summary: str = ""
    is_developing: bool = False


class WeatherHour(BaseModel):
    hour_label: str
    temperature_c: float
    feels_like_c: float | None = None
    precipitation_chance: int = Field(default=0, ge=0, le=100)
    weather_code: int = 0
    weather_label: str = ""
    icon: str = ""


class WeatherSnapshot(BaseModel):
    city: str
    high_c: float | None = None
    low_c: float | None = None
    sunrise: str = ""
    sunset: str = ""
    hours: list[WeatherHour] = Field(default_factory=list)
    summary: str = ""


class DigestSummary(BaseModel):
    schedule: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)


class CategorizedNews(BaseModel):
    technology: list[NewsItem] = Field(default_factory=list)
    southeast_asia: list[NewsItem] = Field(default_factory=list)
    hong_kong: list[NewsItem] = Field(default_factory=list)


class RawDigestData(BaseModel):
    calendar: list[CalendarEvent] = Field(default_factory=list)
    emails: list[GmailThread] = Field(default_factory=list)
    news: list[NewsItem] = Field(default_factory=list)
    ranked_news: list[RankedNewsItem] = Field(default_factory=list)
    categorized_news: CategorizedNews = Field(default_factory=CategorizedNews)
    weather: WeatherSnapshot | None = None
