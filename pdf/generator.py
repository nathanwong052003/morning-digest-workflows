from __future__ import annotations

import html
import re
from datetime import date, datetime, time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from build_digest_pdf import convert as convert_html_to_pdf
from models import DigestSummary, NewsItem, RankedNewsItem, RawDigestData


def _escape(text: str) -> str:
    return html.escape(text, quote=True)


def _clean_display_text(text: str) -> str:
    cleaned = html.unescape(text or "").strip()
    cleaned = re.sub(r"\s*\[\s*(?:\.\.\.|…)\s*\]\s*$", "", cleaned)
    cleaned = re.sub(r"\s*\[\s*&?#8230;\s*\]\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    if cleaned and cleaned[-1] not in ".!?":
        sentence_endings = [cleaned.rfind("."), cleaned.rfind("!"), cleaned.rfind("?")]
        last_end = max(sentence_endings)
        if last_end >= 0:
            cleaned = cleaned[: last_end + 1].strip()
    return cleaned


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


def _news_identity(*, title: str, url: str) -> str:
    normalized_url = _normalize_news_url(url)
    if normalized_url:
        return f"url:{normalized_url}"
    title_key = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
    return f"title:{title_key}"


def _parse_schedule_line(line: str) -> tuple[str, str]:
    pattern = r"^\s*([0-2]?\d:\d{2})(?:\s*-\s*[0-2]?\d:\d{2})?\s*[:\-]\s*(.+?)\s*$"
    match = re.match(pattern, line)
    if match:
        return match.group(1), match.group(2)
    return "", line.strip()


def _parse_iso_datetime(raw: str) -> datetime | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_ampm(dt: datetime) -> str:
    hour = dt.hour % 12
    if hour == 0:
        hour = 12
    suffix = "am" if dt.hour < 12 else "pm"
    return f"{hour}{suffix}"


def _format_schedule_display(line: str, digest_date: date) -> str:
    text = (line or "").strip()
    if not text:
        return ""

    title = text
    dt: datetime | None = None

    if ": " in text:
        prefix, possible_title = text.rsplit(": ", 1)
        if " - " in prefix:
            start_raw = prefix.split(" - ", 1)[0].strip()
            parsed = _parse_iso_datetime(start_raw)
            if parsed:
                dt = parsed
                title = possible_title.strip()

    if dt is None:
        start_time, parsed_title = _parse_schedule_line(text)
        title = parsed_title
        if start_time:
            try:
                hour_str, minute_str = start_time.split(":", 1)
                dt = datetime.combine(digest_date, time(hour=int(hour_str), minute=int(minute_str)))
            except ValueError:
                dt = None

    if dt is None:
        return title

    date_label = f"{dt.strftime('%B')} {dt.day}, {dt.year}"
    return f"{date_label} {_format_ampm(dt)}: {title}"


def _split_inbox_line(line: str) -> tuple[str, str]:
    text = (line or "").strip()
    for sep in (" - ", " — "):
        if sep in text:
            sender, summary = text.split(sep, 1)
            return sender.strip(), summary.strip()
    return text, ""


def _inbox_label(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("ai", "openai", "anthropic", "machine learning", "llm", "deepseek")):
        return "AI"
    if any(token in lowered for token in ("cyber", "security alert", "breach", "vulnerability", "malware", "ransomware")):
        return "CYBERSECURITY"
    if any(token in lowered for token in ("tax", "ipo", "market", "finance", "gdp", "bank", "money", "hsbc", "payment", "debit")):
        return "FINANCE"
    if any(token in lowered for token in ("briefing", "china", "policy", "geopolitic", "south china morning post", "scmp")):
        return "BRIEFING"
    if any(token in lowered for token in ("tech", "software", "cloud", "developer", "google", "microsoft", "apple", "github")):
        return "TECH"
    if any(token in lowered for token in ("space", "nasa", "spacex", "rocket", "satellite")):
        return "SPACE"
    if any(token in lowered for token in ("job", "hiring", "career", "glassdoor", "recruit")):
        return "BUSINESS"
    if any(token in lowered for token in ("order", "delivery", "meal", "food")):
        return "SOCIETY"
    return "BRIEFING"


def _infer_category(item: RankedNewsItem | NewsItem) -> str:
    haystack = f"{item.title} {item.snippet} {item.source}".lower()
    # Check TECHNOLOGY keywords FIRST so cybersecurity, AI, etc. don't get
    # miscategorized into geography buckets just because they mention a location.
    tech_tokens = (
        "ai",
        "artificial intelligence",
        "cyber",
        "cybersecurity",
        "security alert",
        "breach",
        "vulnerability",
        "malware",
        "ransomware",
        "software",
        "hardware",
        "cloud",
        "developer",
        "openai",
        "anthropic",
        "deepseek",
        "llm",
        "machine learning",
        "github",
        "microsoft",
        "apple",
        "google",
        "nasa",
        "spacex",
        "rocket",
        "satellite",
        "robot",
        "startup",
        "encryption",
        "data",
        "algorithm",
        "blockchain",
        "quantum",
        "chip",
        "semiconductor",
        "nvidia",
        "intel",
        "amd",
        "tsmc",
        "5g",
        "6g",
        "internet",
        "server",
        "database",
        "api",
        "sdk",
        "framework",
        "python",
        "javascript",
        "rust",
        "docker",
        "kubernetes",
        "linux",
        "windows",
        "macos",
        "iphone",
        "android",
        "samsung",
        "tesla",
        "meta",
        "amazon",
        "aws",
        "azure",
        "gcp",
    )
    if any(token in haystack for token in tech_tokens):
        return "TECHNOLOGY"
    if any(token in haystack for token in ("hong kong", " hk ", "hk$", "hang seng", "legco", "hksar")):
        return "HONG KONG"
    sea_tokens = (
        "southeast asia",
        "asean",
        "vietnam",
        "malaysia",
        "singapore",
        "indonesia",
        "thailand",
        "philippines",
        "cambodia",
        "laos",
        "myanmar",
        "brunei",
        "timor-leste",
    )
    if any(token in haystack for token in sea_tokens):
        return "SOUTHEAST ASIA"
    return "TECHNOLOGY"


def _infer_tag(item: RankedNewsItem | NewsItem) -> str:
    """Infer a specific tag from the item's title, snippet, and source."""
    haystack = f"{item.title} {item.snippet} {item.source}".lower()
    # Technology tags
    if any(token in haystack for token in ("ai", "artificial intelligence", "openai", "anthropic", "deepseek", "llm", "machine learning", "gpt", "chatgpt", "claude", "gemini", "neural", "transformer")):
        return "AI"
    if any(token in haystack for token in ("cyber", "cybersecurity", "security alert", "breach", "vulnerability", "malware", "ransomware", "hack", "phishing", "zero-day", "exploit", "firewall", "encryption", "data leak", "ransom")):
        return "CYBERSECURITY"
    if any(token in haystack for token in ("software", "app", "application", "api", "sdk", "framework", "python", "javascript", "rust", "docker", "kubernetes", "linux", "windows", "macos", "github", "gitlab", "devops", "agile", "code", "programming", "developer")):
        return "SOFTWARE"
    if any(token in haystack for token in ("hardware", "chip", "semiconductor", "nvidia", "intel", "amd", "tsmc", "processor", "gpu", "cpu", "memory", "storage", "ssd", "motherboard", "circuit", "sensor")):
        return "HARDWARE"
    if any(token in haystack for token in ("space", "nasa", "spacex", "rocket", "satellite", "orbit", "astronaut", "mars", "moon", "lunar", "galaxy", "telescope", "james webb", "hubble")):
        return "SPACE"
    if any(token in haystack for token in ("robot", "robotics", "automation", "drone", "autonomous", "self-driving", "lidar")):
        return "ROBOTICS"
    if any(token in haystack for token in ("science", "research", "study", "discovery", "biology", "chemistry", "physics", "genetic", "dna", "vaccine", "clinical", "laboratory", "experiment")):
        return "SCIENCE"
    if any(token in haystack for token in ("startup", "venture", "funding", "series a", "series b", "seed", "ipo", "unicorn", "yc ", "y combinator", "accelerator", "incubator")):
        return "STARTUPS"
    # Finance tags
    if any(token in haystack for token in ("finance", "market", "stock", "bank", "hsbc", "money", "payment", "debit", "credit", "tax", "gdp", "inflation", "interest rate", "bond", "etf", "crypto", "bitcoin", "blockchain", "trading", "investment", "portfolio", "dividend", "earnings", "revenue", "profit")):
        return "FINANCE"
    # Policy tags
    if any(token in haystack for token in ("policy", "regulation", "law", "legislation", "government", "parliament", "congress", "senate", "bill", "compliance", "sanction", "tariff", "trade war", "data privacy", "gdpr", "ai act", "antitrust", "monopoly")):
        return "POLICY"
    # Security / Defense
    if any(token in haystack for token in ("security", "defense", "military", "army", "navy", "air force", "weapon", "missile", "drone strike", "intelligence", "spy", "surveillance", "nato", "cyberattack", "cyber war")):
        return "SECURITY"
    # Business
    if any(token in haystack for token in ("business", "corporate", "ceo", "executive", "merger", "acquisition", "layoff", "hiring", "job", "career", "glassdoor", "recruit", "workforce", "salary", "wage", "economy", "economic")):
        return "BUSINESS"
    # Energy
    if any(token in haystack for token in ("energy", "oil", "gas", "renewable", "solar", "wind", "nuclear", "coal", "electricity", "power grid", "battery", "ev", "electric vehicle", "tesla", "charging", "green", "carbon", "emission", "climate")):
        return "ENERGY"
    # Society / Culture
    if any(token in haystack for token in ("society", "culture", "education", "school", "university", "health", "hospital", "medical", "covid", "pandemic", "food", "delivery", "meal", "order", "travel", "tourism", "sport", "entertainment", "movie", "music", "art", "museum")):
        return "SOCIETY"
    # Environment
    if any(token in haystack for token in ("environment", "climate", "weather", "storm", "flood", "earthquake", "tsunami", "hurricane", "typhoon", "pollution", "conservation", "wildlife", "forest", "ocean", "biodiversity", "sustainable")):
        return "ENVIRONMENT"
    # Trade
    if any(token in haystack for token in ("trade", "export", "import", "supply chain", "logistics", "shipping", "port", "cargo", "tariff", "customs")):
        return "TRADE"
    return "NEWS"


def _to_ranked(item: NewsItem, category: str) -> RankedNewsItem:
    tag = _infer_tag(item)
    return RankedNewsItem(
        title=item.title,
        url=item.url,
        source=item.source,
        published_at=item.published_at,
        snippet=item.snippet,
        relevance=50,
        reason="Fallback category mapping",
        category=category,
        tag=tag,
        ai_summary="",
    )


def _split_news(raw_data: RawDigestData) -> tuple[list[RankedNewsItem], list[RankedNewsItem], list[RankedNewsItem]]:
    ranked = list(raw_data.ranked_news[:18])

    buckets: dict[str, list[RankedNewsItem]] = {
        "TECHNOLOGY": [],
        "SOUTHEAST ASIA": [],
        "HONG KONG": [],
    }
    seen_keys: set[str] = set()

    def _add_to_bucket(category: str, row: RankedNewsItem) -> bool:
        if category not in buckets or len(buckets[category]) >= 3:
            return False
        key = _news_identity(title=row.title, url=str(row.url))
        if key in seen_keys:
            return False
        seen_keys.add(key)
        buckets[category].append(row)
        return True

    # AI-assigned categories take precedence. Only fall back to _infer_category()
    # when the AI did not assign a recognized category.
    for row in ranked:
        category = row.category if row.category in buckets else _infer_category(row)
        _add_to_bucket(category, row)

    for item in raw_data.news:
        inferred = _infer_category(item)
        _add_to_bucket(inferred, _to_ranked(item, inferred))

    # Ensure each section remains populated while preserving global dedupe.
    for category in ("TECHNOLOGY", "SOUTHEAST ASIA", "HONG KONG"):
        if len(buckets[category]) >= 3:
            continue
        for item in raw_data.news:
            if _add_to_bucket(category, _to_ranked(item, category)) and len(buckets[category]) >= 3:
                break

    return (
        buckets["TECHNOLOGY"][:3],
        buckets["SOUTHEAST ASIA"][:3],
        buckets["HONG KONG"][:3],
    )


def _label_colors(label: str) -> tuple[str, str]:
    palette = {
        "NEWS": ("#DBEAFE", "#1E40AF"),
        "TECH": ("#D1FAE5", "#065F46"),
        "AI": ("#EDE9FE", "#5B21B6"),
        "CYBERSECURITY": ("#FEE2E2", "#991B1B"),
        "FINANCE": ("#FEF3C7", "#92400E"),
        "BRIEFING": ("#E0E7FF", "#3730A3"),
        "TRADE": ("#FEF9C3", "#713F12"),
        "BUSINESS": ("#F3F4F6", "#1F2937"),
        "SOCIETY": ("#FCE7F3", "#9D174D"),
        "POLICY": ("#E0F2FE", "#0369A1"),
        "SECURITY": ("#FEE2E2", "#991B1B"),
        "SCIENCE": ("#D1FAE5", "#065F46"),
        "HARDWARE": ("#F3E8FF", "#6B21A8"),
        "SOFTWARE": ("#D1FAE5", "#065F46"),
        "ROBOTICS": ("#F0FDF4", "#166534"),
        "SPACE": ("#F0F9FF", "#0C4A6E"),
        "STARTUPS": ("#FDF4FF", "#86198F"),
        "ENERGY": ("#FFF7ED", "#9A3412"),
        "ENVIRONMENT": ("#ECFDF5", "#065F46"),
        "CULTURE": ("#FFF1F2", "#9F1239"),
        "EDUCATION": ("#F0FDF4", "#166534"),
    }
    return palette.get(label.upper(), ("#F3F4F6", "#1F2937"))


def _pill_html(label: str) -> str:
    bg, fg = _label_colors(label)
    return (
        f'<font backcolor="{bg}" color="{fg}">'
        f"<b>&nbsp;{_escape(label.upper())}&nbsp;</b>"
        "</font>"
    )




def _schedule_items_html(summary: DigestSummary, raw_data: RawDigestData, digest_date: date) -> str:
    lines = [f"{event.start_local} - {event.end_local}: {event.title}" for event in raw_data.calendar[:12]] or summary.schedule
    if not lines:
        return "<li>Free!</li>"
    return "\n".join([f"<li><strong>{_escape(_format_schedule_display(line, digest_date))}</strong></li>" for line in lines])


def _inbox_items_html(summary: DigestSummary, raw_data: RawDigestData) -> str:
    lines = [f"{email.sender} - {email.subject}" for email in raw_data.emails[:10]] or summary.emails
    if not lines:
        return "<li>Free!</li>"
    rows = []
    for line in lines:
        label = _inbox_label(line)
        sender, summary_text = _split_inbox_line(line)
        tag_bg, tag_fg = _label_colors(label)
        first_line = (
            f'<div class="inbox-primary">'
            f'<span class="inbox-tag" style="background-color:{tag_bg};color:{tag_fg};">{_escape(label)}</span>'
            f' {_escape(sender)}'
            f'</div>'
        )
        second_line = f'<div class="inbox-secondary">{_escape(summary_text)}</div>' if summary_text else ""
        rows.append(f"<li>{first_line}{second_line}</li>")
    return "\n".join(rows)


def _news_blocks_html(items: list[RankedNewsItem]) -> str:
    if not items:
        return ""
    blocks = []
    for row in items:
        safe_url = _escape(str(row.url))
        tag = row.tag.strip() or _infer_tag(row)
        tag_bg, tag_fg = _label_colors(tag)
        body = _clean_display_text((row.ai_summary or row.snippet or "").strip())
        blocks.append(
            "<div class=\"item\">\n"
            f"<div class=\"headline-row\">"
            f"<span class=\"tag-colored\" style=\"background-color:{tag_bg};color:{tag_fg};\">{_escape(tag)}</span>"
            f"<a class=\"headline headline-link\" href=\"{safe_url}\">{_escape(row.title)}</a>"
            f"</div>\n"
            f"<p class=\"body-text\">{_escape(body)}</p>\n"
            "</div>"
        )
    return "\n".join(blocks)


def _warning_banner_html(warning_banner: str | None) -> str:
    if not warning_banner:
        return ""
    return f'<div class="warning-banner">{_escape(warning_banner)}</div>'


def _render_html(*, summary: DigestSummary, raw_data: RawDigestData, digest_date: date, warning_banner: str | None) -> str:
    template_path = Path(__file__).with_name("template.html")
    template = template_path.read_text(encoding="utf-8")
    display_date = f"{digest_date.strftime('%B')} {digest_date.day}, {digest_date.year}"
    tech_news, sea_news, hk_news = _split_news(raw_data)
    sea_hk = sea_news + hk_news
    return (
        template.replace("{{DIGEST_DATE}}", _escape(display_date))
        .replace("{{WARNING_BANNER_HTML}}", _warning_banner_html(warning_banner))
        .replace("{{SCHEDULE_ITEMS_HTML}}", _schedule_items_html(summary, raw_data, digest_date))
        .replace("{{INBOX_ITEMS_HTML}}", _inbox_items_html(summary, raw_data))
        .replace("{{TECHNOLOGY_ITEMS_HTML}}", _news_blocks_html(tech_news))
        .replace("{{SEA_HK_ITEMS_HTML}}", _news_blocks_html(sea_hk))
    )


def generate_digest_pdf(
    *,
    summary: DigestSummary,
    raw_data: RawDigestData,
    output_path: Path,
    digest_date: date,
    warning_banner: str | None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rendered_html = _render_html(
        summary=summary,
        raw_data=raw_data,
        digest_date=digest_date,
        warning_banner=warning_banner,
    )
    html_output_path = output_path.with_suffix(".html")
    html_output_path.write_text(rendered_html, encoding="utf-8")
    convert_html_to_pdf(html_output_path, output_path)
