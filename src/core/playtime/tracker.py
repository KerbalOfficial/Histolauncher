from __future__ import annotations

from typing import Any

from core.logger import colorize_log
from core.playtime.storage import append_session

__all__ = ["record_session"]

_MIN_DURATION_S: float = 3.0


def record_session(
    profile_id: str,
    *,
    version_identifier: str,
    start_time: float,
    end_time: float,
    loader: str | None = None,
) -> None:
    try:
        duration_s = max(0.0, end_time - start_time)
        if duration_s < _MIN_DURATION_S:
            return

        if "/" in version_identifier:
            category, folder = version_identifier.split("/", 1)
        else:
            category = ""
            folder = version_identifier

        session: dict[str, Any] = {
            "started_at": int(start_time),
            "ended_at": int(end_time),
            "duration_s": round(duration_s, 1),
            "version": folder,
            "category": category,
        }
        if loader:
            session["loader"] = str(loader).strip().lower()

        append_session(profile_id, session)
    except Exception as exc:
        print(colorize_log(f"[playtime] Failed to record session: {exc}"))
