from __future__ import annotations

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

import requests
from pydantic import ValidationError

from config import Settings
from models import NewsItem, truncate_text
from utils.logging import JsonLogger
from utils.retries import retry_call

CACHE_VERSION = 3
CATEGORY_TARGET_MAX = 12

BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"

CATEGORY_QUERIES: dict[str, str] = {
    "TECHNOLOGY": "technology AI cybersecurity software hardware robotics innovation",
    "HONG KONG": "Hong Kong news economy finance policy",
    "SOUTHEAST ASIA": "Southeast Asia ASEAN Singapore Indonesia Malaysia Thailand Philippines Vietnam",
}

SOURCE_ALIASES: dict[str, str] = {
    "associated press": "AP",
    "ap news": "AP",
    "bbc news": "BBC",
    "cna": "Channel NewsAsia",
    "channel news asia": "Channel NewsAsia",
    "financial times": "Financial Times",
    "ft": "Financial Times",
    "hong kong free press": "HK Free Press",
    "ieee spectrum": "IEEE Spectrum",
    "mit tech review": "MIT Technology Review",
    "nikkei": "Nikkei Asia",
    "nikkei asia": "Nikkei Asia",
    "scmp": "South China Morning Post",
    "south china morning post": "South China Morning Post",
    "the associated press": "AP",
    "the straits times": "The Straits Times",
    "the verge": "The Verge",
    "wall street journal": "Wall Street Journal",
    "wsj": "Wall Street Journal",
    "the standard": "The Standard",
    "ming pao": "Ming Pao",
    "hk01": "HK01",
    "ej insight": "EJ Insight",
    "asia times": "Asia Times",
}


def _clean_snippet(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*\[\s*(?:\.\.\.|…)\s*\]\s*$", "", text)
    return text.strip()


def _read_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")


def _source_from_url(url: str) -> str:
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or "unknown"


def _canonical_source(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "unknown"
    alias = SOURCE_ALIASES.get(raw.lower())
    if alias:
        return alias
    return raw


def _normalize_news_url(raw_url: str) -> str:
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


def _parse_published(raw_published: Any) -> datetime | None:
    if isinstance(raw_published, datetime):
        return raw_published
    if isinstance(raw_published, str) and raw_published.strip():
        value = raw_published.strip()
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return None
    return None


def _fetch_brave_category(category: str, *, api_key: str) -> list[dict[str, Any]]:
    query = CATEGORY_QUERIES[category]
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params: dict[str, Any] = {
        "q": query,
        "count": 20,
        "freshness": "pd",
        "search_lang": "en",
    }
    try:
        response = retry_call(
            lambda: requests.get(BRAVE_NEWS_URL, headers=headers, params=params, timeout=15),
            attempts=3,
            base_delay_seconds=1.0,
            retry_on=lambda exc: isinstance(exc, requests.RequestException),
        )
    except requests.RequestException:
        return []
    if response.status_code >= 400:
        return []
    try:
        data = response.json()
    except ValueError:
        return []

    now = datetime.utcnow()
    rows: list[dict[str, Any]] = []
    for i, result in enumerate(data.get("results", [])):
        source_obj = result.get("source") or {}
        source_name = source_obj.get("name", "") or _source_from_url(result.get("url", ""))
        rows.append({
            "title": result.get("title", "(Untitled)"),
            "url": result.get("url", ""),
            "source": source_name,
            # Assign synthetic timestamps to preserve Brave's result order (newest first)
            "published_at": now - timedelta(minutes=i),
            "snippet": (result.get("description", "") or "").strip(),
        })
    return rows


def _normalize(rows: list[dict[str, Any]]) -> list[NewsItem]:
    items: list[NewsItem] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for row in rows:
        url = str(row.get("url", "")).strip()
        normalized_url = _normalize_news_url(url)
        title_key = re.sub(r"[^a-z0-9]+", " ", str(row.get("title", "")).lower()).strip()
        if not url:
            continue
        if normalized_url and normalized_url in seen_urls:
            continue
        if title_key and title_key in seen_titles:
            continue
        if normalized_url:
            seen_urls.add(normalized_url)
        if title_key:
            seen_titles.add(title_key)
        published_at = _parse_published(row.get("published_at"))
        try:
            item = NewsItem(
                title=str(row.get("title", "(Untitled)")).strip(),
                url=url,
                source=_canonical_source(str(row.get("source", "unknown")).strip()),
                published_at=published_at,
                snippet=truncate_text(_clean_snippet(str(row.get("snippet", ""))), limit=500),
            )
        except ValidationError:
            continue
        items.append(item)
    items.sort(
        key=lambda x: x.published_at.timestamp() if x.published_at else 0.0,
        reverse=True,
    )
    return items


def _collect_mock() -> list[NewsItem]:
    return [
        NewsItem(title="DeepSeek releases optimization update", url="https://example.com/deepseek-update", source="example.com", published_at=datetime.utcnow(), snippet="DeepSeek introduced lower-cost inference optimizations for daily workflows."),
        NewsItem(title="Cloud platform launches new scheduler", url="https://example.com/cloud-scheduler", source="example.com", published_at=datetime.utcnow(), snippet="A new scheduler API improves cron reliability for GitHub Action pipelines."),
    ]


def _collect_mock_sea() -> list[NewsItem]:
    return [
        NewsItem(title="Singapore unveils expanded digital trade framework with ASEAN partners", url="https://example.com/sg-digital-trade", source="The Straits Times", published_at=datetime.utcnow(), snippet="Singapore signed a new digital economy agreement covering cross-border data flows and e-commerce standards with six ASEAN member states."),
        NewsItem(title="Vietnam posts record Q1 exports as manufacturing diversification accelerates", url="https://example.com/vietnam-exports", source="Reuters", published_at=datetime.utcnow(), snippet="Vietnam's export figures hit a quarterly record, driven by electronics and textiles as global firms continue shifting supply chains away from China."),
        NewsItem(title="Indonesia raises interest rates to defend rupiah amid dollar strength", url="https://example.com/indonesia-rates", source="Bloomberg", published_at=datetime.utcnow(), snippet="Bank Indonesia lifted its benchmark rate by 25 basis points, citing pressure on the rupiah and rising import costs as the Fed holds rates steady."),
    ]


def _collect_mock_hk() -> list[NewsItem]:
    return [
        NewsItem(title="Hong Kong Monetary Authority holds base rate as Fed signals extended pause", url="https://example.com/hkma-rate", source="South China Morning Post", published_at=datetime.utcnow(), snippet="The HKMA kept its base rate unchanged following the Federal Reserve's decision to hold, with officials noting Hong Kong's economy remains resilient."),
        NewsItem(title="Hang Seng Index climbs 1.4% on mainland stimulus optimism", url="https://example.com/hang-seng-rally", source="Reuters", published_at=datetime.utcnow(), snippet="Hong Kong equities rose broadly after Beijing signalled additional fiscal measures to support domestic consumption, lifting financials and property stocks."),
        NewsItem(title="Government launches HK$2 billion tech hub fund targeting deep-tech startups", url="https://example.com/hk-tech-fund", source="HK Free Press", published_at=datetime.utcnow(), snippet="Hong Kong's Innovation and Technology Bureau announced a new co-investment fund aimed at attracting AI, biotech, and semiconductor startups to the city."),
    ]


def collect_news_by_category(*, settings: Settings, logger: JsonLogger) -> dict[str, list[NewsItem]]:
    """Collect news per category using parallel Brave Search API agents."""
    step_start = perf_counter()
    if settings.mock_mode:
        tech = _collect_mock()
        sea = _collect_mock_sea()
        hk = _collect_mock_hk()
        logger.info(
            "news_collected_mock",
            step="news",
            item_count=len(tech) + len(sea) + len(hk),
            latency=perf_counter() - step_start,
        )
        return {"TECHNOLOGY": tech, "SOUTHEAST ASIA": sea, "HONG KONG": hk}

    if not settings.brave_api_key:
        logger.warning("brave_api_key_missing", step="news")
        return {"TECHNOLOGY": [], "SOUTHEAST ASIA": [], "HONG KONG": []}

    cache_path = Path(settings.news_cache_path)
    cache = _read_cache(cache_path)
    now = datetime.utcnow()
    fetched_at_raw = cache.get("fetched_at")
    fetched_at = None
    if isinstance(fetched_at_raw, str):
        try:
            fetched_at = datetime.fromisoformat(fetched_at_raw)
        except ValueError:
            pass

    if (
        cache.get("version") == CACHE_VERSION
        and fetched_at
        and now - fetched_at < timedelta(seconds=settings.news_cache_ttl_seconds)
        and cache.get("category_counts")
    ):
        cached_flat = _normalize(cache.get("items", []))
        counts = cache.get("category_counts", {})
        categorized: dict[str, list[NewsItem]] = {}
        offset = 0
        for cat in ("TECHNOLOGY", "SOUTHEAST ASIA", "HONG KONG"):
            n = counts.get(cat, 0)
            categorized[cat] = cached_flat[offset : offset + n]
            offset += n
        logger.info(
            "news_cache_hit",
            step="news",
            item_count=len(cached_flat),
            latency=perf_counter() - step_start,
        )
        return categorized

    categories = ("TECHNOLOGY", "SOUTHEAST ASIA", "HONG KONG")
    raw_by_category: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_fetch_brave_category, cat, api_key=settings.brave_api_key): cat
            for cat in categories
        }
        for future in as_completed(futures):
            cat = futures[future]
            try:
                raw_by_category[cat] = future.result()
            except Exception:  # noqa: BLE001
                raw_by_category[cat] = []

    categorized = {}
    category_counts: dict[str, int] = {}
    seen_urls: set[str] = set()

    for category in categories:
        cat_items = _normalize(raw_by_category.get(category, []))
        picked: list[NewsItem] = []
        for item in cat_items:
            url = str(item.url)
            if url in seen_urls:
                continue
            picked.append(item)
            seen_urls.add(url)
            if len(picked) >= CATEGORY_TARGET_MAX:
                break
        category_counts[category] = len(picked)
        categorized[category] = picked

    all_items = [item for cat in categories for item in categorized[cat]]
    _write_cache(
        cache_path,
        {
            "version": CACHE_VERSION,
            "fetched_at": now.isoformat(),
            "items": [item.model_dump(mode="json") for item in all_items],
            "category_counts": category_counts,
        },
    )
    logger.info(
        "news_collected",
        step="news",
        item_count=sum(len(v) for v in categorized.values()),
        technology_count=category_counts.get("TECHNOLOGY", 0),
        southeast_asia_count=category_counts.get("SOUTHEAST ASIA", 0),
        hong_kong_count=category_counts.get("HONG KONG", 0),
        latency=perf_counter() - step_start,
        cache_path=str(cache_path),
    )
    return categorized


def collect_news_items(*, settings: Settings, logger: JsonLogger) -> list[NewsItem]:
    """Flat collection — returns all news items deduplicated across categories."""
    categorized = collect_news_by_category(settings=settings, logger=logger)
    result: list[NewsItem] = []
    seen_urls: set[str] = set()
    for cat_items in categorized.values():
        for item in cat_items:
            url = str(item.url)
            if url not in seen_urls:
                seen_urls.add(url)
                result.append(item)
    return result
