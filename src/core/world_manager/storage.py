from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from core.settings import (
    get_default_minecraft_dir,
    get_versions_profile_dir,
    load_global_settings,
    normalize_custom_storage_directory,
    normalize_storage_directory_mode,
    validate_custom_storage_directory,
)
from core.version_manager import scan_categories

from core.world_manager._constants import MAX_WORLD_ID_LENGTH


def _version_components(value: Any) -> Tuple[int, ...]:
    match = re.search(r"\d+(?:\.\d+)+", str(value or "").strip())
    if not match:
        return ()
    try:
        return tuple(int(part) for part in match.group(0).split("."))
    except Exception:
        return ()


def _version_at_least(version_value: Any, minimum_value: str) -> bool:
    version_parts = _version_components(version_value)
    minimum_parts = _version_components(minimum_value)
    if not version_parts or not minimum_parts:
        return False
    padded_version = version_parts + (0,) * max(0, len(minimum_parts) - len(version_parts))
    padded_minimum = minimum_parts + (0,) * max(0, len(version_parts) - len(minimum_parts))
    return padded_version >= padded_minimum


def _format_version_storage_label(entry: Dict[str, Any]) -> str:
    folder = str((entry or {}).get("folder") or "").strip()
    display = str((entry or {}).get("display_name") or folder).strip() or folder or "Unknown"
    return f"{display} (Version)"


def _match_version_entry(version_key: str) -> Optional[Dict[str, Any]]:
    normalized_key = str(version_key or "").strip()
    if not normalized_key:
        return None
    for entry in scan_categories().get("* All", []):
        category = str((entry or {}).get("category") or "").strip()
        folder = str((entry or {}).get("folder") or "").strip()
        if category and folder and f"{category}/{folder}".lower() == normalized_key.lower():
            return entry
    return None


def _version_entry_dir(entry: Dict[str, Any]) -> str:
    category = str((entry or {}).get("category") or "").strip()
    folder = str((entry or {}).get("folder") or "").strip()
    return os.path.join(get_versions_profile_dir(), category, folder)


def list_storage_options() -> List[Dict[str, str]]:
    options = [
        {"value": "default", "label": "Default"},
        {"value": "global", "label": "Global"},
    ]

    for entry in scan_categories().get("* All", []):
        version_dir = _version_entry_dir(entry)
        data_dir = os.path.join(version_dir, "data")
        if not os.path.isdir(data_dir):
            continue
        category = str((entry or {}).get("category") or "").strip()
        folder = str((entry or {}).get("folder") or "").strip()
        if not category or not folder:
            continue
        options.append({
            "value": f"version:{category}/{folder}",
            "label": _format_version_storage_label(entry),
        })

    options.append({"value": "custom", "label": "Custom"})
    return options


def list_version_options() -> List[Dict[str, str]]:
    options = []
    seen_versions = set()

    for entry in scan_categories().get("* All", []):
        version_value = str((entry or {}).get("folder") or "").strip()
        if not version_value or version_value in seen_versions:
            continue
        seen_versions.add(version_value)
        options.append({
            "category": str((entry or {}).get("category") or "").strip(),
            "folder": version_value,
            "display": str((entry or {}).get("display_name") or version_value).strip() or version_value,
            "version": version_value,
        })

    options.sort(key=lambda item: item.get("version", ""), reverse=True)
    return options


def resolve_storage_target(
    storage_target: str = "default",
    *,
    custom_path: str = "",
    create_saves_dir: bool = False,
) -> Dict[str, Any]:
    target = str(storage_target or "default").strip() or "default"
    target_lower = target.lower()
    game_dir = ""
    label = "Default"
    error = ""
    source_kind = "default"

    if target_lower == "default":
        settings = load_global_settings() or {}
        mode = normalize_storage_directory_mode(settings.get("storage_directory"))
        if mode == "custom":
            validation = validate_custom_storage_directory(settings.get("custom_storage_directory"))
            if not validation.get("ok"):
                error = validation.get("error") or "Custom storage directory is invalid."
            else:
                game_dir = str(validation.get("path") or "")
                label = "Default -> Custom"
        elif mode == "version":
            selected_version = str(settings.get("selected_version") or "").strip()
            entry = _match_version_entry(selected_version)
            if not entry:
                error = "Default storage points to Version mode, but no selected version could be resolved."
            else:
                data_dir = os.path.join(_version_entry_dir(entry), "data")
                if not os.path.isdir(data_dir):
                    error = "Default storage points to a version that does not contain a data folder yet."
                else:
                    game_dir = data_dir
                    label = f"Default -> {_format_version_storage_label(entry)}"
        else:
            game_dir = get_default_minecraft_dir()
            label = "Default -> Global"
    elif target_lower == "global":
        game_dir = get_default_minecraft_dir()
        label = "Global"
        source_kind = "global"
    elif target_lower == "custom":
        normalized_path = normalize_custom_storage_directory(custom_path)
        validation = validate_custom_storage_directory(normalized_path)
        if not validation.get("ok"):
            error = validation.get("error") or "Custom storage directory is invalid."
        else:
            game_dir = str(validation.get("path") or "")
            label = "Custom"
        source_kind = "custom"
    elif target_lower.startswith("version:"):
        version_key = target.split(":", 1)[1]
        entry = _match_version_entry(version_key)
        if not entry:
            error = "Selected version storage directory was not found."
        else:
            data_dir = os.path.join(_version_entry_dir(entry), "data")
            if not os.path.isdir(data_dir):
                error = "Selected version does not contain a data folder yet."
            else:
                game_dir = data_dir
                label = _format_version_storage_label(entry)
        source_kind = "version"
    else:
        error = "Unknown worlds storage target."

    if error:
        return {
            "ok": False,
            "storage_target": target,
            "storage_kind": source_kind,
            "storage_label": label,
            "game_dir": "",
            "saves_dir": "",
            "error": error,
        }

    saves_dir = os.path.join(game_dir, "saves")
    if create_saves_dir:
        os.makedirs(saves_dir, exist_ok=True)

    return {
        "ok": True,
        "storage_target": target,
        "storage_kind": source_kind,
        "storage_label": label,
        "game_dir": game_dir,
        "saves_dir": saves_dir,
        "error": "",
    }


def _validate_world_id(world_id: str) -> bool:
    if not isinstance(world_id, str):
        return False
    value = world_id.strip()
    if not value or len(value) > MAX_WORLD_ID_LENGTH:
        return False
    if os.path.basename(value) != value:
        return False
    if value in (".", "..") or "/" in value or "\\" in value:
        return False
    if any(ord(ch) < 32 for ch in value):
        return False
    if any(ch in value for ch in '<>:"|?*'):
        return False
    return True


def _sanitize_world_id(name: str, fallback: str = "world") -> str:
    value = str(name or "").strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value)
    value = value.strip(" .")
    if not value:
        value = fallback
    return value[:MAX_WORLD_ID_LENGTH]


def _pick_unique_world_id(saves_dir: str, desired_name: str) -> str:
    base = _sanitize_world_id(desired_name)
    candidate = base
    suffix = 2
    while os.path.exists(os.path.join(saves_dir, candidate)):
        candidate = _sanitize_world_id(f"{base} ({suffix})")
        suffix += 1
    return candidate


def _world_dir(storage_target: str, world_id: str, *, custom_path: str = "") -> Tuple[str, Dict[str, Any]]:
    resolved = resolve_storage_target(storage_target, custom_path=custom_path, create_saves_dir=False)
    if not resolved.get("ok"):
        return "", resolved
    if not _validate_world_id(world_id):
        return "", {
            **resolved,
            "ok": False,
            "error": "Invalid world id.",
        }

    saves_dir = str(resolved.get("saves_dir") or "")
    world_dir = os.path.join(saves_dir, world_id)
    try:
        real_saves = os.path.realpath(saves_dir)
        real_world = os.path.realpath(world_dir)
        if os.path.commonpath([real_saves, real_world]) != real_saves:
            return "", {
                **resolved,
                "ok": False,
                "error": "Invalid world path.",
            }
    except Exception:
        return "", {
            **resolved,
            "ok": False,
            "error": "Invalid world path.",
        }

    return world_dir, resolved


__all__ = [
    "list_storage_options",
    "list_version_options",
    "resolve_storage_target",
    "_validate_world_id",
    "_sanitize_world_id",
    "_pick_unique_world_id",
    "_world_dir",
    "_version_at_least",
    "_format_version_storage_label",
    "_match_version_entry",
    "_version_entry_dir",
]
