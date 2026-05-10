from __future__ import annotations

from pathlib import Path
from time import perf_counter

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import Settings
from utils.logging import JsonLogger
from utils.retries import retry_call


def upload_pdf_to_drive(
    *,
    settings: Settings,
    credentials: Credentials,
    pdf_path: Path,
    logger: JsonLogger,
) -> str:
    if not settings.drive_folder_id:
        raise ValueError("DRIVE_FOLDER_ID is required for Drive upload.")
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    started = perf_counter()
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    media = MediaFileUpload(str(pdf_path), mimetype="application/pdf", resumable=False)
    metadata = {"name": pdf_path.name, "parents": [settings.drive_folder_id]}

    created = retry_call(
        lambda: service.files()
        .create(
            body=metadata,
            media_body=media,
            fields="id,webViewLink",
            supportsAllDrives=True,
        )
        .execute(),
        attempts=3,
        base_delay_seconds=1.0,
    )
    file_id = created.get("id")
    if not file_id:
        raise RuntimeError("Drive upload succeeded but file ID was missing.")

    retry_call(
        lambda: service.permissions()
        .create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            fields="id",
            supportsAllDrives=True,
        )
        .execute(),
        attempts=3,
        base_delay_seconds=1.0,
    )

    fetched = retry_call(
        lambda: service.files()
        .get(
            fileId=file_id,
            fields="webViewLink",
            supportsAllDrives=True,
        )
        .execute(),
        attempts=3,
        base_delay_seconds=1.0,
    )
    link = fetched.get("webViewLink")
    if not link:
        raise RuntimeError("Drive webViewLink missing after upload.")

    logger.info(
        "drive_uploaded",
        step="distribution_drive",
        file_id=file_id,
        latency=perf_counter() - started,
    )
    return str(link)
