from __future__ import annotations

import base64
import html
import mimetypes
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from time import perf_counter

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import Settings
from models import DigestSummary, RankedNewsItem, RawDigestData, WeatherSnapshot
from utils.logging import JsonLogger
from utils.retries import retry_call


HKT = timezone(timedelta(hours=8), name="HKT")

# Inline pill colors (kept minimal — email clients strip most CSS).
TAG_COLORS: dict[str, tuple[str, str]] = {
    "AI":             ("#EDE9FE", "#5B21B6"),
    "CYBERSECURITY":  ("#FEE2E2", "#991B1B"),
    "FINANCE":        ("#FEF3C7", "#92400E"),
    "POLICY":         ("#E0F2FE", "#0369A1"),
    "SECURITY":       ("#FEE2E2", "#991B1B"),
    "BUSINESS":       ("#F3F4F6", "#1F2937"),
    "SOCIETY":        ("#FCE7F3", "#9D174D"),
    "STARTUPS":       ("#FDF4FF", "#86198F"),
    "SOFTWARE":       ("#D1FAE5", "#065F46"),
    "HARDWARE":       ("#F3E8FF", "#6B21A8"),
    "SCIENCE":        ("#D1FAE5", "#065F46"),
    "SPACE":          ("#F0F9FF", "#0C4A6E"),
    "ROBOTICS":       ("#F0FDF4", "#166534"),
    "ENERGY":         ("#FFF7ED", "#9A3412"),
    "ENVIRONMENT":    ("#ECFDF5", "#065F46"),
    "TRADE":          ("#FEF9C3", "#713F12"),
    "NEWS":           ("#DBEAFE", "#1E40AF"),
}


def _esc(value: str) -> str:
    return html.escape(value or "", quote=True)


def _greeting(now: datetime) -> str:
    hour = now.hour
    if hour < 12:
        return "Good morning."
    if hour < 18:
        return "Good afternoon."
    return "Good evening."


def _weather_block(weather: WeatherSnapshot | None) -> str:
    if not weather or not weather.hours:
        return ""
    cell_width_pct = 100 // len(weather.hours) if weather.hours else 25
    cells = []
    for hour in weather.hours:
        precip_html = (
            f'<div style="font-size:10px;color:#999;margin-top:2px;">💧 {hour.precipitation_chance}%</div>'
            if hour.precipitation_chance >= 20 else ""
        )
        cells.append(
            f'<td align="center" style="padding:14px 6px;width:{cell_width_pct}%;border-right:1px solid #f0f0f0;">'
            f'<div style="font-size:11px;font-weight:600;color:#888;letter-spacing:0.04em;text-transform:uppercase;">{_esc(hour.hour_label)}</div>'
            f'<div style="font-size:24px;line-height:1.1;margin:6px 0 4px 0;">{_esc(hour.icon)}</div>'
            f'<div style="font-size:16px;font-weight:600;color:#111;">{round(hour.temperature_c)}°</div>'
            f'{precip_html}'
            f'</td>'
        )
    # Drop the last border to avoid trailing line
    rendered_cells = "".join(cells).rsplit('border-right:1px solid #f0f0f0;', 1)
    cells_html = "border-right:none;".join(rendered_cells)

    high_low = ""
    if weather.high_c is not None and weather.low_c is not None:
        high_low = (
            f' · <span style="color:#666;">High {round(weather.high_c)}° / Low {round(weather.low_c)}°</span>'
        )
    sun = ""
    if weather.sunrise and weather.sunset:
        sun = f' · <span style="color:#888;">↑{_esc(weather.sunrise)} ↓{_esc(weather.sunset)}</span>'

    return (
        '<tr><td style="padding:20px 36px 8px 36px;">'
        '<div style="font-size:12px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#999999;margin-bottom:10px;">Weather</div>'
        f'<div style="font-size:13px;color:#444;margin-bottom:10px;">{_esc(weather.summary)}{high_low}{sun}</div>'
        '<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color:#fafaf7;border-radius:10px;border:1px solid #efefe9;">'
        f'<tr>{cells_html}</tr>'
        '</table>'
        '</td></tr>'
    )


def _schedule_block(raw_data: RawDigestData, summary: DigestSummary) -> str:
    events = raw_data.calendar[:8]
    if not events:
        if summary.schedule:
            rows = "".join(
                f'<div style="padding:8px 0;border-bottom:1px solid #f3f3f3;font-size:14px;color:#222;">{_esc(line)}</div>'
                for line in summary.schedule[:8]
            )
            return rows
        return '<div style="font-size:14px;color:#888;padding:8px 0;">Nothing scheduled today.</div>'

    rows = []
    for ev in events:
        time_label = ev.start_local
        # Try to extract just the time portion if it's an ISO datetime
        if "T" in time_label:
            try:
                dt = datetime.fromisoformat(time_label.replace("Z", "+00:00"))
                hour = dt.hour % 12 or 12
                suffix = "am" if dt.hour < 12 else "pm"
                time_label = f"{hour}{':' + str(dt.minute).zfill(2) if dt.minute else ''}{suffix}"
            except ValueError:
                pass
        loc = f' <span style="color:#888;">· {_esc(ev.location)}</span>' if ev.location else ""
        rows.append(
            '<div style="padding:10px 0;border-bottom:1px solid #f3f3f3;">'
            f'<div style="font-size:12px;font-weight:600;color:#666;letter-spacing:0.02em;">{_esc(time_label)}</div>'
            f'<div style="font-size:14px;color:#111;margin-top:2px;">{_esc(ev.title)}{loc}</div>'
            '</div>'
        )
    return "".join(rows)


def _inbox_block(raw_data: RawDigestData, summary: DigestSummary) -> str:
    threads = raw_data.emails[:6]
    if not threads:
        if summary.emails:
            rows = "".join(
                f'<div style="padding:8px 0;border-bottom:1px solid #f3f3f3;font-size:14px;color:#222;">{_esc(line)}</div>'
                for line in summary.emails[:6]
            )
            return rows
        return '<div style="font-size:14px;color:#888;padding:8px 0;">No priority emails.</div>'

    rows = []
    for thread in threads:
        rows.append(
            '<div style="padding:10px 0;border-bottom:1px solid #f3f3f3;">'
            f'<div style="font-size:13px;font-weight:600;color:#111;">{_esc(thread.sender)}</div>'
            f'<div style="font-size:13px;color:#555;margin-top:2px;">{_esc(thread.subject)}</div>'
            '</div>'
        )
    return "".join(rows)


def _tag_pill(tag: str) -> str:
    label = (tag or "NEWS").upper()
    bg, fg = TAG_COLORS.get(label, TAG_COLORS["NEWS"])
    return (
        f'<span style="display:inline-block;font-size:10px;font-weight:700;letter-spacing:0.06em;'
        f'padding:2px 7px;border-radius:3px;background-color:{bg};color:{fg};">{_esc(label)}</span>'
    )


def _news_item(item: RankedNewsItem, *, show_developing: bool = False) -> str:
    body = (item.ai_summary or item.snippet or "").strip()
    developing_badge = ""
    if show_developing and item.is_developing:
        developing_badge = (
            ' <span style="display:inline-block;font-size:10px;font-weight:700;letter-spacing:0.06em;'
            'padding:2px 7px;border-radius:3px;background-color:#fff7ed;color:#9a3412;">CONTINUING</span>'
        )
    safe_url = _esc(str(item.url))
    return (
        '<div style="padding:12px 0;border-bottom:1px solid #f3f3f3;">'
        f'<div style="margin-bottom:6px;">{_tag_pill(item.tag or "NEWS")}{developing_badge}</div>'
        f'<a href="{safe_url}" style="font-size:15px;font-weight:600;color:#111;text-decoration:none;line-height:1.35;">{_esc(item.title)}</a>'
        f'<div style="font-size:13px;color:#555;line-height:1.5;margin-top:6px;">{_esc(body)}</div>'
        f'<div style="font-size:11px;color:#999;margin-top:6px;">{_esc(item.source)}</div>'
        '</div>'
    )


def _developing_block(developing: list[RankedNewsItem]) -> str:
    if not developing:
        return ""
    rows = "".join(_news_item(item, show_developing=True) for item in developing[:4])
    return (
        '<tr><td style="padding:8px 36px 12px 36px;">'
        '<div style="font-size:12px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#9a3412;margin-bottom:14px;">Developing stories</div>'
        f'<div style="background-color:#fffaf3;border-left:3px solid #fb923c;padding:6px 14px;border-radius:4px;">{rows}</div>'
        '</td></tr>'
    )


def _news_block(ranked_news: list[RankedNewsItem]) -> str:
    items = ranked_news[:8]
    if not items:
        return '<div style="font-size:14px;color:#888;padding:8px 0;">No top stories.</div>'
    return "".join(_news_item(item) for item in items)


def _resolve_email_news(raw_data: RawDigestData) -> list[RankedNewsItem]:
    if raw_data.ranked_news:
        return raw_data.ranked_news
    rcat = raw_data.ranked_categorized_news
    return rcat.technology + rcat.southeast_asia + rcat.hong_kong


def _warning_banner(warning_banner: str | None) -> str:
    if not warning_banner:
        return ""
    return (
        '<tr><td style="padding:14px 36px 0 36px;">'
        f'<div style="background-color:#fef3c7;color:#92400e;font-size:13px;padding:10px 14px;border-radius:6px;">{_esc(warning_banner)}</div>'
        '</td></tr>'
    )


def _render_html(
    *,
    summary: DigestSummary,
    raw_data: RawDigestData,
    digest_date: date,
    iteration: int,
    warning_banner: str | None,
    developing: list[RankedNewsItem],
    city_label: str,
) -> str:
    template_path = Path(__file__).with_name("email_template.html")
    template = template_path.read_text(encoding="utf-8")
    display_date = f"{digest_date.strftime('%A, %B')} {digest_date.day}, {digest_date.year}"
    now = datetime.now(HKT)
    generated_at = now.strftime("%I:%M %p").lstrip("0").lower().replace("am", "AM").replace("pm", "PM") + " HKT"

    return (
        template.replace("{{ITERATION}}", str(iteration))
        .replace("{{DIGEST_DATE}}", _esc(display_date))
        .replace("{{GREETING}}", _esc(_greeting(now)))
        .replace("{{CITY}}", _esc(city_label))
        .replace("{{GENERATED_AT}}", _esc(generated_at))
        .replace("{{WARNING_BANNER_HTML}}", _warning_banner(warning_banner))
        .replace("{{WEATHER_BLOCK_HTML}}", _weather_block(raw_data.weather))
        .replace("{{SCHEDULE_BLOCK_HTML}}", _schedule_block(raw_data, summary))
        .replace("{{INBOX_BLOCK_HTML}}", _inbox_block(raw_data, summary))
        .replace("{{DEVELOPING_BLOCK_HTML}}", _developing_block(developing))
        .replace("{{NEWS_BLOCK_HTML}}", _news_block(_resolve_email_news(raw_data)))
    )


def _plain_text_fallback(*, digest_date: date, raw_data: RawDigestData) -> str:
    lines = [f"Morning Digest — {digest_date.isoformat()}", ""]
    if raw_data.weather and raw_data.weather.hours:
        lines.append(f"Weather ({raw_data.weather.city}): {raw_data.weather.summary}")
        for h in raw_data.weather.hours:
            lines.append(f"  {h.hour_label}: {round(h.temperature_c)}°C {h.weather_label}")
        lines.append("")
    if raw_data.calendar:
        lines.append("Today's schedule:")
        for ev in raw_data.calendar[:8]:
            lines.append(f"  - {ev.start_local}: {ev.title}")
        lines.append("")
    if raw_data.emails:
        lines.append("Priority inbox:")
        for t in raw_data.emails[:6]:
            lines.append(f"  - {t.sender}: {t.subject}")
        lines.append("")
    if raw_data.ranked_news:
        lines.append("Top stories:")
        for item in raw_data.ranked_news[:8]:
            lines.append(f"  - {item.title} ({item.source}) — {item.url}")
    lines.append("")
    lines.append("Full digest attached as PDF.")
    return "\n".join(lines)


def send_digest_email(
    *,
    settings: Settings,
    credentials: Credentials,
    digest_date: date,
    iteration: int,
    summary: DigestSummary,
    raw_data: RawDigestData,
    pdf_path: Path,
    warning_banner: str | None,
    developing: list[RankedNewsItem],
    logger: JsonLogger,
) -> str:
    if not settings.digest_email_to:
        raise ValueError("DIGEST_EMAIL_TO is required to send the digest email.")

    started = perf_counter()
    city_label = settings.weather_city_label or "Hong Kong"
    html_body = _render_html(
        summary=summary,
        raw_data=raw_data,
        digest_date=digest_date,
        iteration=iteration,
        warning_banner=warning_banner,
        developing=developing,
        city_label=city_label,
    )
    text_body = _plain_text_fallback(digest_date=digest_date, raw_data=raw_data)

    message = EmailMessage()
    subject_date = f"{digest_date.strftime('%B')} {digest_date.day}, {digest_date.year}"
    message["Subject"] = f"{iteration}. Morning Digest — {subject_date}"
    message["To"] = settings.digest_email_to
    message["From"] = settings.digest_email_to  # send-as-self
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    if pdf_path.exists():
        mime_type, _ = mimetypes.guess_type(str(pdf_path))
        if not mime_type:
            mime_type = "application/pdf"
        maintype, subtype = mime_type.split("/", 1)
        message.add_attachment(
            pdf_path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=pdf_path.name,
        )

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    result = retry_call(
        lambda: service.users().messages().send(
            userId="me",
            body={"raw": raw, "labelIds": ["IMPORTANT"]},
        ).execute(),
        attempts=3,
        base_delay_seconds=1.0,
    )
    message_id = result.get("id", "")
    logger.info(
        "email_sent",
        step="distribution_email",
        message_id=message_id,
        to=settings.digest_email_to,
        attachment=str(pdf_path.name),
        latency=perf_counter() - started,
    )
    return str(message_id)
