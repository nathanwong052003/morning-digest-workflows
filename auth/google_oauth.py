from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from config import Settings
from utils.logging import JsonLogger
from utils.retries import retry_call


def get_google_credentials(settings: Settings, logger: JsonLogger) -> Credentials:
    missing = [
        name
        for name, value in (
            ("CLIENT_ID", settings.client_id),
            ("CLIENT_SECRET", settings.client_secret),
            ("REFRESH_TOKEN", settings.refresh_token),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required Google OAuth env vars: {', '.join(missing)}")

    credentials = Credentials(
        token=None,
        refresh_token=settings.refresh_token,
        token_uri=settings.google_token_uri,
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        scopes=settings.google_scopes,
    )
    retry_call(
        lambda: credentials.refresh(Request()),
        attempts=3,
        base_delay_seconds=1.0,
        retry_on=lambda _: True,
    )
    logger.info("oauth_refreshed", step="auth")
    return credentials
