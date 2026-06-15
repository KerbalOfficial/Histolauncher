from __future__ import annotations

import json
import os
import threading
from typing import Any

__all__ = [
    "MAX_STORED_SESSIONS",
    "load_playtime_data",
    "save_playtime_data",
    "append_session",
    "get_playtime_path",
]

MAX_STORED_SESSIONS: int = 10_000

_lock = threading.Lock()


def _playtime_dir() -> str:
    from core.settings.paths import get_base_dir

    path = os.path.join(get_base_dir(), "profiles", "settings", "playtime")
    os.makedirs(path, exist_ok=True)
    return path


def get_playtime_path(profile_id: str) -> str:
    safe = str(profile_id or "default").strip().lower()
    safe = "".join(c for c in safe if c.isalnum() or c in "-_") or "default"
    return os.path.join(_playtime_dir(), f"{safe}.json")


def load_playtime_data(profile_id: str) -> dict[str, Any]:
    from core.logger import safe_print

    path = get_playtime_path(profile_id)
    if not os.path.isfile(path):
        return {"sessions": []}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {"sessions": []}
        if not isinstance(data.get("sessions"), list):
            data["sessions"] = []
        return data
    except Exception as exc:
        safe_print(f"[playtime] Could not parse {path}: {exc}")
        try:
            os.replace(path, path + ".corrupt")
            safe_print(f"[playtime] Moved unreadable file to {path}.corrupt")
        except OSError:
            pass
        return {"sessions": []}


def save_playtime_data(profile_id: str, data: dict[str, Any]) -> None:
    path = get_playtime_path(profile_id)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def append_session(profile_id: str, session: dict[str, Any]) -> None:
    with _lock:
        data = load_playtime_data(profile_id)
        sessions: list[dict[str, Any]] = data.get("sessions") or []
        sessions.append(session)
        if len(sessions) > MAX_STORED_SESSIONS:
            sessions = sessions[-MAX_STORED_SESSIONS:]
        data["sessions"] = sessions
        save_playtime_data(profile_id, data)
