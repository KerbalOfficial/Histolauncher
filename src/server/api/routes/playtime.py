from __future__ import annotations

import datetime

from core.playtime.stats import compute_stats
from core.playtime.storage import load_playtime_data
from core.settings import get_active_profile_id

__all__ = ["api_playtime_stats", "api_playtime_sessions"]

_MAX_DISPLAY_SESSIONS = 500


def _fmt_dur(total_seconds: float) -> str:
    total_s = int(total_seconds)
    hours, remainder = divmod(total_s, 3600)
    minutes = remainder // 60
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def api_playtime_stats(data):
    profile_id = None
    if isinstance(data, dict):
        profile_id = str(data.get("profile_id") or "").strip() or None

    if not profile_id:
        profile_id = get_active_profile_id() or "default"

    stats = compute_stats(profile_id)
    return {"ok": True, "stats": stats}


def api_playtime_sessions(data):
    profile_id = None
    if isinstance(data, dict):
        profile_id = str(data.get("profile_id") or "").strip() or None

    if not profile_id:
        profile_id = get_active_profile_id() or "default"

    raw = load_playtime_data(profile_id)
    all_sessions = list(reversed(raw.get("sessions") or []))

    versions = sorted({str(s.get("version") or "Unknown") for s in all_sessions})

    formatted = []
    for s in all_sessions[:_MAX_DISPLAY_SESSIONS]:
        started_at = s.get("started_at")
        try:
            date_str = datetime.datetime.fromtimestamp(int(started_at)).strftime("%m/%d/%Y %H:%M")
        except Exception:
            date_str = "—"
        formatted.append({
            "date_formatted": date_str,
            "started_at": int(started_at) if started_at else 0,
            "duration_formatted": _fmt_dur(float(s.get("duration_s") or 0)),
            "duration_s": round(float(s.get("duration_s") or 0), 1),
            "loader": s.get("loader") or None,
            "version": str(s.get("version") or "Unknown"),
        })

    return {"ok": True, "versions": versions, "sessions": formatted, "total": len(all_sessions)}
