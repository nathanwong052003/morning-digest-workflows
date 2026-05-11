from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlparse, urlsplit, urlunsplit

import feedparser
import requests
from pydantic import ValidationError

from config import Settings
from models import NewsItem, truncate_text
from utils.logging import JsonLogger
from utils.retries import retry_call

CACHE_VERSION = 2
CATEGORY_TARGET_MAX = 8


def _source_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


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

SOURCE_HOMEPAGES: dict[str, str] = {
    "AP": "https://apnews.com",
    "Ars Technica": "https://arstechnica.com",
    "Asia Times": "https://asiatimes.com",
    "Bangkok Post": "https://www.bangkokpost.com",
    "BBC": "https://www.bbc.com",
    "Bloomberg": "https://www.bloomberg.com",
    "Channel NewsAsia": "https://www.channelnewsasia.com",
    "EJ Insight": "https://www.ejinsight.com",
    "Financial Times": "https://www.ft.com",
    "HK Free Press": "https://hongkongfp.com",
    "HK01": "https://www.hk01.com",
    "HKSAR Government": "https://www.info.gov.hk",
    "IEEE Spectrum": "https://spectrum.ieee.org",
    "Jakarta Post": "https://www.thejakartapost.com",
    "Ming Pao": "https://www.mingpao.com",
    "Nikkei Asia": "https://asia.nikkei.com",
    "Philippine Star": "https://www.philstar.com",
    "Reuters": "https://www.reuters.com",
    "RTHK": "https://news.rthk.hk",
    "South China Morning Post": "https://www.scmp.com",
    "The Standard": "https://www.thestandard.com.hk",
    "The Straits Times": "https://www.straitstimes.com",
    "The Verge": "https://www.theverge.com",
    "Wall Street Journal": "https://www.wsj.com",
    "Wired": "https://www.wired.com",
}

CATEGORY_RSS_FEEDS: dict[str, tuple[str, ...]] = {
    "TECHNOLOGY": (
        "https://news.google.com/rss/search?q=(technology+OR+ai+OR+cybersecurity)+when:2d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=(technology+OR+ai+OR+cybersecurity)+when:2d+(source:Reuters+OR+source:AP+OR+source:Bloomberg+OR+source:BBC+OR+source:Financial+Times+OR+source:The+Verge+OR+source:Ars+Technica+OR+source:MIT+Technology+Review+OR+source:Wired+OR+source:IEEE+Spectrum)&hl=en-US&gl=US&ceid=US:en",
    ),
    "SOUTHEAST ASIA": (
        "https://news.google.com/rss/search?q=(Southeast+Asia+OR+ASEAN+OR+Singapore+OR+Indonesia+OR+Malaysia+OR+Thailand+OR+Philippines+OR+Vietnam)+when:2d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=(Southeast+Asia+OR+ASEAN)+when:2d+(source:Reuters+OR+source:AP+OR+source:Bloomberg+OR+source:Financial+Times+OR+source:Nikkei+Asia+OR+source:Channel+NewsAsia+OR+source:Bangkok+Post+OR+source:Philippine+Star+OR+source:Jakarta+Post+OR+source:The+Straits+Times+OR+source:South+China+Morning+Post)&hl=en-US&gl=US&ceid=US:en",
    ),
    "HONG KONG": (
        "https://news.google.com/rss/search?q=(Hong+Kong+OR+HKSAR+OR+LegCo+OR+Hang+Seng)+when:2d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=(Hong+Kong+OR+HKSAR)+when:2d+(source:Reuters+OR+source:AP+OR+source:Bloomberg+OR+source:Financial+Times+OR+source:South+China+Morning+Post+OR+source:RTHK+OR+source:Hong+Kong+Free+Press+OR+source:Wall+Street+Journal)&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=(Hong+Kong+economy+OR+Hong+Kong+property+OR+Hong+Kong+finance+OR+Hong+Kong+stock+market)+when:2d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=(Hong+Kong+OR+Hong+Kong+technology+OR+Hong+Kong+startup+OR+Hong+Kong+business)+when:2d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=(Hong+Kong+politics+OR+Hong+Kong+policy+OR+Hong+Kong+government+OR+Hong+Kong+regulation)+when:2d&hl=en-US&gl=US&ceid=US:en",
    ),
}

CATEGORY_ALLOWED_SOURCES: dict[str, tuple[str, ...]] = {
    "TECHNOLOGY": (
        "Reuters",
        "AP",
        "Bloomberg",
        "BBC",
        "Financial Times",
        "The Verge",
        "Ars Technica",
        "MIT Technology Review",
        "Wired",
        "IEEE Spectrum",
    ),
    "SOUTHEAST ASIA": (
        "Reuters",
        "AP",
        "Bloomberg",
        "Financial Times",
        "Nikkei Asia",
        "Channel NewsAsia",
        "Bangkok Post",
        "Philippine Star",
        "Jakarta Post",
        "The Straits Times",
        "South China Morning Post",
    ),
    "HONG KONG": (
        "Reuters",
        "AP",
        "Bloomberg",
        "Financial Times",
        "South China Morning Post",
        "RTHK",
        "HK Free Press",
        "Wall Street Journal",
        "GovHK",
        "HKSAR Government",
        "The Standard",
        "Ming Pao",
        "HK01",
        "EJ Insight",
        "Asia Times",
    ),
}

CATEGORY_ALLOWED_DOMAINS: dict[str, tuple[str, ...]] = {
    "TECHNOLOGY": (
        "reuters.com",
        "apnews.com",
        "bloomberg.com",
        "bbc.com",
        "ft.com",
        "theverge.com",
        "arstechnica.com",
        "technologyreview.com",
        "wired.com",
        "spectrum.ieee.org",
    ),
    "SOUTHEAST ASIA": (
        "reuters.com",
        "apnews.com",
        "bloomberg.com",
        "ft.com",
        "asia.nikkei.com",
        "channelnewsasia.com",
        "bangkokpost.com",
        "philstar.com",
        "thejakartapost.com",
        "straitstimes.com",
        "scmp.com",
    ),
    "HONG KONG": (
        "reuters.com",
        "apnews.com",
        "bloomberg.com",
        "ft.com",
        "scmp.com",
        "news.rthk.hk",
        "rthk.hk",
        "hongkongfp.com",
        "wsj.com",
        "info.gov.hk",
        "news.gov.hk",
        "thestandard.com.hk",
        "mingpao.com",
        "hk01.com",
        "ejinsight.com",
        "asiatimes.com",
    ),
}


def _clean_snippet(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*\[\s*(?:\.\.\.|…)\s*\]\s*$", "", text)
    text = re.sub(r"\s*\[\s*&?#8230;\s*\]\s*$", "", text, flags=re.IGNORECASE)
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
            "gclid",
            "fbclid",
            "igshid",
            "mc_cid",
            "mc_eid",
            "ref",
            "ref_src",
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


def _is_google_news_url(raw_url: str) -> bool:
    host = urlparse((raw_url or "").strip()).netloc.lower()
    return host == "news.google.com" or host.endswith(".news.google.com")


def _extract_direct_url_candidate(raw_url: str) -> str:
    value = (raw_url or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and not _is_google_news_url(value):
        return value
    query = parse_qs(parsed.query)
    for key in ("url", "u", "q"):
        first = next(iter(query.get(key, [])), "").strip()
        if not first:
            continue
        decoded = unquote(first)
        candidate = decoded if decoded.startswith(("http://", "https://")) else first
        if candidate.startswith(("http://", "https://")) and not _is_google_news_url(candidate):
            return candidate
    return ""


def _extract_summary_links(entry: dict[str, Any]) -> list[str]:
    summary = str(entry.get("summary", "")).strip()
    if not summary:
        return []
    links = re.findall(r'href=[\'"]([^\'"]+)[\'"]', summary, flags=re.IGNORECASE)
    return [link.strip() for link in links if link.strip()]


def _resolve_source_url(entry: dict[str, Any], raw_url: str) -> str:
    candidates: list[str] = []
    candidates.append(raw_url)
    source_obj = entry.get("source")
    if isinstance(source_obj, dict):
        source_href = str(source_obj.get("href", "")).strip()
        if source_href:
            candidates.append(source_href)
    raw_links = entry.get("links")
    if isinstance(raw_links, list):
        for link_row in raw_links:
            if isinstance(link_row, dict):
                href = str(link_row.get("href", "")).strip()
                if href:
                    candidates.append(href)
    candidates.extend(_extract_summary_links(entry))

    for candidate in candidates:
        direct = _extract_direct_url_candidate(candidate)
        if direct:
            return direct
    if _is_google_news_url(raw_url):
        source_name = _extract_source(entry, raw_url)
        homepage = SOURCE_HOMEPAGES.get(source_name)
        if homepage:
            return homepage
    return raw_url


def _extract_source(entry: dict[str, Any], url: str) -> str:
    raw_source = ""
    source_obj = entry.get("source")
    if isinstance(source_obj, dict):
        raw_source = str(source_obj.get("title", "")).strip()
    if not raw_source:
        raw_source = str(entry.get("author", "")).strip()
    if not raw_source:
        title = str(entry.get("title", "")).strip()
        if " - " in title:
            possible = title.rsplit(" - ", 1)[-1].strip()
            if len(possible) <= 80:
                raw_source = possible
    if not raw_source:
        raw_source = _source_from_url(url)
    return _canonical_source(raw_source)


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


def _from_rss_feed(url: str) -> list[dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        response = retry_call(
            lambda: requests.get(url, timeout=15, headers=headers),
            attempts=3,
            base_delay_seconds=1.0,
            retry_on=lambda exc: isinstance(exc, requests.RequestException),
        )
    except requests.RequestException:
        return []

    if response.status_code >= 400:
        return []

    parsed = feedparser.parse(response.text)
    rows: list[dict[str, Any]] = []
    for entry in parsed.entries:
        entry_link = str(entry.get("link", "")).strip()
        resolved_link = _resolve_source_url(entry, entry_link)
        rows.append(
            {
                "title": entry.get("title", "(Untitled)"),
                "url": resolved_link,
                "source": _extract_source(entry, resolved_link),
                "published_at": entry.get("published") or entry.get("updated"),
                "snippet": entry.get("summary", ""),
            }
        )
    return rows


def _is_allowed_source(*, category: str, source: str, url: str) -> bool:
    source_key = _source_key(source)
    allowed_source_keys = {
        _source_key(_canonical_source(name))
        for name in CATEGORY_ALLOWED_SOURCES.get(category, ())
    }
    if source_key in allowed_source_keys:
        return True
    source_tokens = set(source_key.split())
    for allowed_key in allowed_source_keys:
        allowed_tokens = set(allowed_key.split())
        if allowed_tokens and allowed_tokens.issubset(source_tokens):
            return True
    domain = _source_from_url(url)
    for allowed_domain in CATEGORY_ALLOWED_DOMAINS.get(category, ()):
        if domain == allowed_domain or domain.endswith(f".{allowed_domain}"):
            return True
    return False


def _collect_category_rows(category: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feed_url in CATEGORY_RSS_FEEDS.get(category, ()):
        rows.extend(_from_rss_feed(feed_url))
    return [
        row
        for row in rows
        if _is_allowed_source(
            category=category,
            source=str(row.get("source", "")),
            url=str(row.get("url", "")),
        )
    ]


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
        NewsItem(
            title="DeepSeek releases optimization update",
            url="https://example.com/deepseek-update",
            source="example.com",
            published_at=datetime.utcnow(),
            snippet="DeepSeek introduced lower-cost inference optimizations for daily workflows.",
        ),
        NewsItem(
            title="Cloud platform launches new scheduler",
            url="https://example.com/cloud-scheduler",
            source="example.com",
            published_at=datetime.utcnow(),
            snippet="A new scheduler API improves cron reliability for GitHub Action pipelines.",
        ),
    ]


def collect_news_by_category(*, settings: Settings, logger: JsonLogger) -> dict[str, list[NewsItem]]:
    """Collect news items grouped by category.

    Returns a dict like {"TECHNOLOGY": [...], "SOUTHEAST ASIA": [...], "HONG KONG": [...]}
    with global deduplication across categories.
    """
    step_start = perf_counter()
    if settings.mock_mode:
        items = _collect_mock()
        logger.info(
            "news_collected_mock",
            step="news",
            item_count=len(items),
            latency=perf_counter() - step_start,
        )
        return {"TECHNOLOGY": items, "SOUTHEAST ASIA": [], "HONG KONG": []}

    cache_path = Path(settings.news_cache_path)
    cache = _read_cache(cache_path)
    now = datetime.utcnow()
    fetched_at_raw = cache.get("fetched_at")
    if isinstance(fetched_at_raw, str):
        try:
            fetched_at = datetime.fromisoformat(fetched_at_raw)
        except ValueError:
            fetched_at = None
    else:
        fetched_at = None

    cache_version = cache.get("version")
    if (
        cache_version == CACHE_VERSION
        and fetched_at
        and now - fetched_at < timedelta(seconds=settings.news_cache_ttl_seconds)
    ):
        cached_items = _normalize(cache.get("items", []))
        logger.info(
            "news_cache_hit",
            step="news",
            item_count=len(cached_items),
            latency=perf_counter() - step_start,
        )
        # When cache is hit, we still need categorized data.
        # Re-collect to get proper categorization since cache is flat.
        pass  # Fall through to re-collect

    category_counts: dict[str, int] = {}
    categorized: dict[str, list[NewsItem]] = {
        "TECHNOLOGY": [],
        "SOUTHEAST ASIA": [],
        "HONG KONG": [],
    }
    seen_urls: set[str] = set()

    for category in ("TECHNOLOGY", "SOUTHEAST ASIA", "HONG KONG"):
        category_items = _normalize(_collect_category_rows(category))
        picked: list[NewsItem] = []
        for item in category_items:
            item_url = str(item.url)
            if item_url in seen_urls:
                continue
            picked.append(item)
            seen_urls.add(item_url)
            if len(picked) >= CATEGORY_TARGET_MAX:
                break
        category_counts[category] = len(picked)
        categorized[category] = picked

    # Flatten for cache (backward-compatible cache format)
    all_items: list[NewsItem] = []
    for cat_items in categorized.values():
        all_items.extend(cat_items)
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
    """Legacy flat collection — returns all news items deduplicated."""
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
