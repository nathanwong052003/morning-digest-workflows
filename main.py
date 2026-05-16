from __future__ import annotations

import sys
from pathlib import Path

from ai.deepseek_client import DeepSeekClient, DeepSeekError
from auth.google_oauth import get_google_credentials
from collectors.calendar import collect_calendar_events
from collectors.gmail import collect_gmail_threads
from collectors.news import collect_news_by_category, collect_news_items
from collectors.weather import collect_weather
from config import Settings, load_settings
from distribution.calendar_event import create_digest_calendar_event
from distribution.drive import upload_pdf_to_drive
from distribution.email import send_digest_email
from models import CategorizedNews, DigestSummary, RankedCategorizedNews, RankedNewsItem, RawDigestData
from pdf.generator import generate_digest_pdf
from utils.digest_counter import next_iteration
from utils.logging import JsonLogger
from utils.news_history import apply_news_diff


def build_fallback_summary(data: RawDigestData) -> DigestSummary:
    schedule = [
        f"{event.start_local} - {event.end_local}: {event.title}"
        for event in data.calendar[:10]
    ]
    emails = [f"{email.sender} - {email.subject}" for email in data.emails[:10]]
    return DigestSummary(schedule=schedule, emails=emails)


def run(settings: Settings) -> int:
    logger = JsonLogger(run_id=settings.run_id)
    logger.info("digest_started", step="startup")

    now_local = settings.now_local()
    digest_date = now_local.date()
    iteration = next_iteration(
        Path(settings.digest_counter_path),
        today_key=digest_date.isoformat(),
    )
    digest_title = (
        f"{iteration}. Morning Digest — "
        f"{digest_date.strftime('%B')} {digest_date.day}, {digest_date.year}"
    )
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{digest_title}.pdf"

    credentials = None
    if not settings.mock_mode:
        credentials = get_google_credentials(settings, logger)

    calendar_events = collect_calendar_events(
        settings=settings,
        credentials=credentials,
        logger=logger,
    )
    gmail_threads = collect_gmail_threads(
        settings=settings,
        credentials=credentials,
        logger=logger,
    )

    # Collect news per category — each category gets its own RSS-fetched pool
    categorized_news = collect_news_by_category(settings=settings, logger=logger)
    news_items = collect_news_items(settings=settings, logger=logger)
    ranked_news = []

    weather_snapshot = collect_weather(settings=settings, logger=logger)

    raw_data = RawDigestData(
        calendar=calendar_events,
        emails=gmail_threads,
        news=news_items,
        ranked_news=ranked_news,
        categorized_news=CategorizedNews(
            technology=categorized_news.get("TECHNOLOGY", []),
            southeast_asia=categorized_news.get("SOUTHEAST ASIA", []),
            hong_kong=categorized_news.get("HONG KONG", []),
        ),
        weather=weather_snapshot,
    )

    warning_banner: str | None = None
    summary: DigestSummary
    if settings.mock_mode and not settings.deepseek_api_key:
        summary = build_fallback_summary(raw_data)
        logger.info("ai_mock_summary", step="ai")
    elif settings.deepseek_api_key:
        try:
            deepseek = DeepSeekClient(settings=settings, logger=logger)

            ranked_by_cat: dict[str, list[RankedNewsItem]] = {}
            all_ranked: list[RankedNewsItem] = []
            for cat_name, cat_items in [
                ("TECHNOLOGY", categorized_news.get("TECHNOLOGY", [])),
                ("SOUTHEAST ASIA", categorized_news.get("SOUTHEAST ASIA", [])),
                ("HONG KONG", categorized_news.get("HONG KONG", [])),
            ]:
                if not cat_items:
                    continue
                cat_ranked = deepseek.rank_news(cat_items, category=cat_name)
                ranked_by_cat[cat_name] = cat_ranked
                all_ranked.extend(cat_ranked)

            all_ranked.sort(key=lambda item: item.relevance, reverse=True)
            raw_data.ranked_news = all_ranked
            raw_data.ranked_categorized_news = RankedCategorizedNews(
                technology=ranked_by_cat.get("TECHNOLOGY", []),
                southeast_asia=ranked_by_cat.get("SOUTHEAST ASIA", []),
                hong_kong=ranked_by_cat.get("HONG KONG", []),
            )
            summary = build_fallback_summary(raw_data)
            if deepseek.is_budget_exceeded():
                warning_banner = "⚠️ AI unavailable: token budget exceeded. Raw fallback used."
                summary = build_fallback_summary(raw_data)
        except DeepSeekError as err:
            warning_banner = f"⚠️ AI unavailable: {err}. Raw fallback used."
            logger.warning("ai_failed", step="ai", error=str(err))
            summary = build_fallback_summary(raw_data)
    else:
        warning_banner = "⚠️ AI unavailable: DEEPSEEK_API_KEY not configured. Raw fallback used."
        summary = build_fallback_summary(raw_data)
        logger.warning("ai_missing_key", step="ai")

    developing_items: list[RankedNewsItem] = []
    if raw_data.ranked_news and not settings.mock_mode:
        fresh, developing_items = apply_news_diff(
            ranked_news=raw_data.ranked_news,
            history_path=Path(settings.news_history_path),
            now=now_local,
        )
        raw_data.ranked_news = fresh
        logger.info(
            "news_diff_applied",
            step="news_diff",
            fresh_count=len(fresh),
            developing_count=len(developing_items),
        )

    generate_digest_pdf(
        summary=summary,
        raw_data=raw_data,
        output_path=output_path,
        digest_date=digest_date,
        warning_banner=warning_banner,
    )
    logger.info("pdf_generated", step="pdf", output_path=str(output_path))

    if settings.mock_mode:
        logger.info(
            "distribution_skipped_mock",
            step="distribution",
            message="Mock mode enabled; skipped Drive upload and Calendar event creation.",
        )
        print(str(output_path))
        return 0

    if credentials is None:
        logger.error("credentials_missing", step="distribution")
        return 1

    drive_link = upload_pdf_to_drive(
        settings=settings,
        credentials=credentials,
        pdf_path=output_path,
        logger=logger,
    )
    create_digest_calendar_event(
        settings=settings,
        credentials=credentials,
        digest_date=digest_date,
        iteration=iteration,
        summary=summary,
        raw_data=raw_data,
        digest_link=drive_link,
        logger=logger,
    )

    try:
        send_digest_email(
            settings=settings,
            credentials=credentials,
            digest_date=digest_date,
            iteration=iteration,
            summary=summary,
            raw_data=raw_data,
            pdf_path=output_path,
            warning_banner=warning_banner,
            developing=developing_items,
            logger=logger,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("email_send_failed", step="distribution_email", error=str(exc))

    logger.info("digest_completed", step="done", drive_link=drive_link)
    print(str(output_path))
    print(drive_link)
    return 0


def main() -> None:
    settings = load_settings()
    exit_code = run(settings)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
