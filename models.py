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


class DigestSummary(BaseModel):
    schedule: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    news: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)


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
