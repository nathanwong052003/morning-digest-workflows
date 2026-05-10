from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import Settings
from utils.logging import JsonLogger
from utils.retries import retry_call


def _find_existing_file(
    service: Any,
    folder_id: str,
    file_name: str,
) -> str | None:
    """Search for an existing file by name in the given folder.

    Returns the file ID if found, or None otherwise.
    """
    query = f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
    results = (
        service.files()
        .list(
            q=query,
            fields="files(id)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    return None


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

    drive_file_name = settings.drive_file_name or pdf_path.name
    media = MediaFileUpload(str(pdf_path), mimetype="application/pdf", resumable=False)

    if settings.drive_overwrite_mode:
        # Overwrite mode: use the date-stamped filename so each day gets its own file,
        # but re-runs on the same day overwrite the existing one.
        drive_file_name = pdf_path.name
        existing_file_id = _find_existing_file(service, settings.drive_folder_id, drive_file_name)

        if existing_file_id:
            updated = retry_call(
                lambda: service.files()
                .update(
                    fileId=existing_file_id,
                    media_body=media,
                    fields="id,webViewLink",
                    supportsAllDrives=True,
                )
                .execute(),
                attempts=3,
                base_delay_seconds=1.0,
            )
            file_id = updated.get("id")
            action = "updated"
        else:
            # No existing file found — create a new one
            metadata = {"name": drive_file_name, "parents": [settings.drive_folder_id]}
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
            action = "created"

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
    else:
        # Historical mode: always create a new file with a unique name
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
        action = "created"

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

    if not file_id:
        raise RuntimeError("Drive upload succeeded but file ID was missing.")

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
        f"drive_{action}",
        step="distribution_drive",
        file_id=file_id,
        latency=perf_counter() - started,
    )
    return str(link)
