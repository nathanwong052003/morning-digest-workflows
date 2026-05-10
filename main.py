from __future__ import annotations

import sys
from pathlib import Path

from ai.deepseek_client import DeepSeekClient, DeepSeekError
from auth.google_oauth import get_google_credentials
from collectors.calendar import collect_calendar_events
from collectors.gmail import collect_gmail_threads
from collectors.news import collect_news_items
from config import Settings, load_settings
from distribution.calendar_event import create_digest_calendar_event
from distribution.drive import upload_pdf_to_drive
from models import DigestSummary, RawDigestData
from pdf.generator import generate_digest_pdf
from utils.logging import JsonLogger


def build_fallback_summary(data: RawDigestData) -> DigestSummary:
    schedule = [
        f"{event.start_local} - {event.end_local}: {event.title}"
        for event in data.calendar[:10]
    ]
    emails = [f"{email.sender} - {email.subject}" for email in data.emails[:10]]
    if data.ranked_news:
        news = [
            (
                f"{item.ai_summary} ({item.source})"
                if item.ai_summary
                else f"{item.title} ({item.source})"
            )
            for item in data.ranked_news[:10]
        ]
    else:
        news = [f"{item.title} ({item.source})" for item in data.news[:10]]
    action_items = [
        "Review top calendar conflicts and prioritize today's meetings.",
        "Reply to urgent inbox threads first.",
        "Skim top-ranked news links during breaks.",
    ]
    return DigestSummary(
        schedule=schedule,
        emails=emails,
        news=news,
        action_items=action_items,
    )


def build_mock_ai_summary(data: RawDigestData) -> DigestSummary:
    return DigestSummary(
        schedule=[f"{item.start_local} {item.title}" for item in data.calendar[:5]],
        emails=[f"{item.subject} ({item.sender})" for item in data.emails[:5]],
        news=[f"{item.title} [{item.source}] - {item.url}" for item in data.news[:5]],
        action_items=[
            "Confirm top two priorities before first meeting.",
            "Respond to highest-impact inbox thread.",
            "Read the most relevant news link and note implications.",
        ],
    )


def run(settings: Settings) -> int:
    logger = JsonLogger(run_id=settings.run_id)
    logger.info("digest_started", step="startup")

    now_local = settings.now_local()
    digest_date = now_local.date()
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"digest_{digest_date.strftime('%Y%m%d')}.pdf"

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
    news_items = collect_news_items(settings=settings, logger=logger)
    ranked_news = []

    raw_data = RawDigestData(
        calendar=calendar_events,
        emails=gmail_threads,
        news=news_items,
        ranked_news=ranked_news,
    )

    warning_banner: str | None = None
    summary: DigestSummary
    if settings.mock_mode and not settings.deepseek_api_key:
        summary = build_mock_ai_summary(raw_data)
        logger.info("ai_mock_summary", step="ai")
    elif settings.deepseek_api_key:
        try:
            deepseek = DeepSeekClient(settings=settings, logger=logger)
            ranked_news = deepseek.rank_news(news_items)
            ranked_news = deepseek.refine_news_summaries(ranked_news)
            raw_data.ranked_news = ranked_news
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

    generate_digest_pdf(
        summary=summary,
        raw_data=raw_data,
        output_path=output_path,
        digest_date=digest_date,
        timezone_name=settings.timezone_name,
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
        summary=summary,
        raw_data=raw_data,
        digest_link=drive_link,
        logger=logger,
    )

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
