from __future__ import annotations

from typing import Any, Dict

from core.downloader import progress as _progress


__all__ = [
    "_map_mojang_type_to_category",
    "_map_manifest_entry_to_category",
    "_format_mojang_version_entry",
    "_get_installing_map_from_progress",
]


def _map_mojang_type_to_category(mojang_type: str) -> str:
    t = (mojang_type or "").lower()
    if t.startswith("old_"):
        t = t[len("old_"):]
    if t == "release":
        return "Release"
    if t == "snapshot":
        return "Snapshot"
    if t == "beta":
        return "Beta"
    if t == "alpha":
        return "Alpha"
    return t.capitalize()


def _map_manifest_entry_to_category(version_id: str, version_type: str, source: str) -> str:
    src = (source or "").strip().lower()
    vid = (version_id or "").strip()
    vtype = (version_type or "").strip().lower()

    if src != "omniarchive":
        return _map_mojang_type_to_category(vtype)

    vid_lower = vid.lower()

    if vid_lower.startswith("inf-"):
        return "OA-infdev"
    if vid_lower.startswith("in-"):
        return "OA-indev"
    if vid_lower.startswith("c0"):
        return "OA-classic"
    if vid_lower.startswith("a1"):
        return "OA-alpha"
    if vid_lower.startswith("b1"):
        return "OA-beta"
    if vtype == "special":
        return "OA-special"

    return "OA-other"


def _format_mojang_version_entry(manifest_entry: Dict[str, Any], source: str) -> Dict[str, Any]:
    vid = manifest_entry.get("id")
    vtype = manifest_entry.get("type", "")
    resolved_source = manifest_entry.get("source") or source or "mojang"
    category = _map_manifest_entry_to_category(vid, vtype, resolved_source)
    display = vid

    return {
        "display": display,
        "category": category,
        "folder": vid,
        "launch_disabled": False,
        "launch_disabled_message": "",
        "is_remote": True,
        "source": resolved_source,
    }


def _get_installing_map_from_progress() -> Dict[str, Dict[str, Any]]:
    installing: Dict[str, Dict[str, Any]] = {}
    try:
        for vkey, prog in _progress.list_progress_files():
            if not isinstance(prog, dict):
                continue
            if str(vkey).startswith(("addons/", "worlds/")):
                continue
            status = (prog.get("status") or "").lower()
            if status in ("downloading", "installing", "running", "starting", "paused"):
                installing[vkey] = prog
    except (IOError, OSError, ValueError, KeyError):
        pass
    return installing
