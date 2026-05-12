from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from models import RankedNewsItem


HISTORY_RETENTION_DAYS = 3
DEVELOPING_OVERLAP_THRESHOLD = 0.45
DEVELOPING_MIN_TOKENS = 2

STOPWORDS = {
    "a", "an", "and", "as", "at", "be", "but", "by", "for", "from", "has",
    "have", "in", "into", "is", "it", "its", "of", "on", "or", "over", "say",
    "says", "said", "that", "the", "to", "up", "was", "were", "will", "with",
    "after", "amid", "new", "today", "this", "year", "years", "amid", "off",
    "than", "then", "those", "these", "their", "they", "his", "her", "she",
    "he", "we", "you", "i", "us", "our", "your", "what", "when", "where",
    "who", "why", "how", "vs", "via",
}


def _normalize_url(raw_url: str) -> str:
    stripped = (raw_url or "").strip()
    if not stripped:
        return ""
    parts = urlsplit(stripped)
    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in {
            "gclid", "fbclid", "igshid", "mc_cid", "mc_eid", "ref", "ref_src",
        }:
            continue
        query_pairs.append((key, value))
    query_pairs.sort(key=lambda row: row[0].lower())
    normalized = parts._replace(
        scheme=parts.scheme.lower(),
        netloc=parts.netloc.lower(),
        path=(parts.path.rstrip("/") or "/"),
        query=urlencode(query_pairs, doseq=True),
        fragment="",
    )
    return urlunsplit(normalized)


def _tokens(text: str) -> set[str]:
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", (text or "").lower())
    return {tok for tok in cleaned.split() if tok and tok not in STOPWORDS and len(tok) > 2}


def _topic_signature(item: dict[str, str] | RankedNewsItem) -> set[str]:
    if isinstance(item, RankedNewsItem):
        title = item.title
        snippet = item.snippet or item.ai_summary or ""
    else:
        title = item.get("title", "")
        snippet = item.get("snippet", "")
    return _tokens(f"{title} {snippet}")


def load_history(path: Path) -> dict[str, list[dict[str, str]]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(k): list(v) for k, v in payload.items() if isinstance(v, list)}


def _prune_history(history: dict[str, list[dict[str, str]]], today: datetime) -> dict[str, list[dict[str, str]]]:
    cutoff = (today.date() - timedelta(days=HISTORY_RETENTION_DAYS)).isoformat()
    return {date_key: items for date_key, items in history.items() if date_key >= cutoff}


def _previous_items(history: dict[str, list[dict[str, str]]], today_key: str) -> list[dict[str, str]]:
    flat: list[dict[str, str]] = []
    for date_key, items in history.items():
        if date_key == today_key:
            continue
        flat.extend(items)
    return flat


def apply_news_diff(
    *,
    ranked_news: list[RankedNewsItem],
    history_path: Path,
    now: datetime,
) -> tuple[list[RankedNewsItem], list[RankedNewsItem]]:
    """Drop exact repeats and flag developing stories.

    Returns (fresh_items, developing_items). developing_items is a subset of fresh_items
    where the topic significantly overlaps a prior-day item — these get is_developing=True.
    """
    today_key = now.date().isoformat()
    history = _prune_history(load_history(history_path), now)

    previous = _previous_items(history, today_key)
    previous_urls = {entry.get("url", "") for entry in previous if entry.get("url")}
    previous_topics = [(_topic_signature(entry), entry) for entry in previous]

    fresh: list[RankedNewsItem] = []
    developing: list[RankedNewsItem] = []
    today_entries: list[dict[str, str]] = []

    for item in ranked_news:
        normalized = _normalize_url(str(item.url))
        if normalized and normalized in previous_urls:
            continue
        today_entries.append({
            "url": normalized,
            "title": item.title,
            "snippet": (item.ai_summary or item.snippet or "")[:280],
            "category": item.category,
        })

        topic = _topic_signature(item)
        if len(topic) >= DEVELOPING_MIN_TOKENS:
            for prev_topic, _prev_entry in previous_topics:
                if not prev_topic:
                    continue
                overlap = len(topic & prev_topic)
                denom = min(len(topic), len(prev_topic))
                if denom == 0:
                    continue
                if overlap / denom >= DEVELOPING_OVERLAP_THRESHOLD and overlap >= DEVELOPING_MIN_TOKENS:
                    item.is_developing = True
                    developing.append(item)
                    break

        fresh.append(item)

    history[today_key] = today_entries
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, ensure_ascii=True), encoding="utf-8")

    return fresh, developing
