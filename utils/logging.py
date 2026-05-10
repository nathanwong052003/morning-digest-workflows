from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any


class JsonLogger:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._logger = logging.getLogger("morning_digest")
        self._logger.setLevel(logging.INFO)
        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
        self._logger.propagate = False

    def info(self, event: str, *, step: str, **kwargs: Any) -> None:
        self._emit("INFO", event, step=step, **kwargs)

    def warning(self, event: str, *, step: str, **kwargs: Any) -> None:
        self._emit("WARNING", event, step=step, **kwargs)

    def error(self, event: str, *, step: str, **kwargs: Any) -> None:
        self._emit("ERROR", event, step=step, **kwargs)

    def _emit(self, level: str, event: str, *, step: str, **kwargs: Any) -> None:
        payload: dict[str, Any] = {
            "level": level,
            "event": event,
            "run_id": self.run_id,
            "step": step,
            "timestamp": time.time(),
        }
        payload.update(kwargs)
        self._logger.log(logging.INFO, json.dumps(payload, ensure_ascii=True, default=str))
