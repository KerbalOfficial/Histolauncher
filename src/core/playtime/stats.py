from __future__ import annotations

from typing import Any

from core.playtime.storage import load_playtime_data

__all__ = ["compute_stats"]


def _format_duration(total_seconds: float) -> str:
    total_s = int(total_seconds)
    hours, remainder = divmod(total_s, 3600)
    minutes = remainder // 60
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def compute_stats(profile_id: str) -> dict[str, Any]:
    data = load_playtime_data(profile_id)
    sessions: list[dict[str, Any]] = data.get("sessions") or []

    if not sessions:
        return {
            "has_data": False,
            "total_sessions": 0,
            "total_duration_s": 0,
            "total_duration_formatted": "0m",
            "average_session_s": 0,
            "average_session_formatted": "0m",
            "longest_session_s": 0,
            "longest_session_formatted": "0m",
            "most_played_version": None,
            "most_played_version_duration_s": 0,
            "most_played_version_formatted": "0m",
            "by_version": [],
        }

    total_duration = sum(float(s.get("duration_s") or 0) for s in sessions)
    longest = max(float(s.get("duration_s") or 0) for s in sessions)
    average = total_duration / len(sessions) if sessions else 0.0

    # Aggregate per version
    version_totals: dict[str, float] = {}
    for s in sessions:
        v = str(s.get("version") or "Unknown").strip() or "Unknown"
        version_totals[v] = version_totals.get(v, 0.0) + float(s.get("duration_s") or 0)

    by_version = sorted(
        [{"version": v, "duration_s": d, "duration_formatted": _format_duration(d)}
         for v, d in version_totals.items()],
        key=lambda x: x["duration_s"],
        reverse=True,
    )

    most_played = by_version[0] if by_version else None

    return {
        "has_data": True,
        "total_sessions": len(sessions),
        "total_duration_s": round(total_duration, 1),
        "total_duration_formatted": _format_duration(total_duration),
        "average_session_s": round(average, 1),
        "average_session_formatted": _format_duration(average),
        "longest_session_s": round(longest, 1),
        "longest_session_formatted": _format_duration(longest),
        "most_played_version": most_played["version"] if most_played else None,
        "most_played_version_duration_s": most_played["duration_s"] if most_played else 0,
        "most_played_version_formatted": most_played["duration_formatted"] if most_played else "0m",
        "by_version": by_version[:10],  # top 10 versions
    }
