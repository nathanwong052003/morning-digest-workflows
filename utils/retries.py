from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


def _extract_status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
    resp = getattr(exc, "resp", None)
    if resp is not None:
        status = getattr(resp, "status", None)
        if isinstance(status, int):
            return status
    return None


def is_retryable_exception(exc: Exception) -> bool:
    status = _extract_status_code(exc)
    if status is None:
        return False
    return status == 429 or 500 <= status < 600


def retry_call(
    func: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay_seconds: float = 1.0,
    retry_on: Callable[[Exception], bool] | None = None,
) -> T:
    checker = retry_on or is_retryable_exception
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= attempts or not checker(exc):
                raise
            time.sleep(base_delay_seconds * (2 ** (attempt - 1)))
    if last_error is not None:
        raise last_error
    raise RuntimeError("retry_call ended unexpectedly")
