from __future__ import annotations

import json
from pathlib import Path


def next_iteration(counter_path: Path, *, today_key: str) -> int:
    """Return a strictly-increasing iteration number. Increments on every run."""
    payload: dict[str, object] = {}
    if counter_path.exists():
        try:
            loaded = json.loads(counter_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except json.JSONDecodeError:
            payload = {}

    last_count = int(payload.get("count", 0) or 0)
    next_count = last_count + 1
    counter_path.parent.mkdir(parents=True, exist_ok=True)
    counter_path.write_text(
        json.dumps({"count": next_count, "date": today_key}, ensure_ascii=True),
        encoding="utf-8",
    )
    return next_count
