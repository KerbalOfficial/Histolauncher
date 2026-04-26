from __future__ import annotations

import base64
import os
from typing import Any, Dict

from core.nbt_editor import (
    bool_value as _bool_value,
    compound_child as _compound_child,
    compound_tag_value as _compound_tag_value,
    read_nbt_file as _read_level_dat,
    tag_value as _tag_value,
)

from core.world_manager._helpers import _difficulty_id_from_value
from core.world_manager.storage import _world_dir, resolve_storage_target


def _dir_size_bytes(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            try:
                total += os.path.getsize(file_path)
            except OSError:
                continue
    return total


def _image_data_url(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "rb") as f:
            payload = f.read()
        encoded = base64.b64encode(payload).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception:
        return ""


def _game_mode_label(value: Any) -> str:
    mapping = {
        0: "Survival",
        1: "Creative",
        2: "Adventure",
        3: "Spectator",
    }
    try:
        return mapping.get(int(value), "Unknown")
    except Exception:
        return "Unknown"


def _difficulty_label(value: Any) -> str:
    mapping = {
        0: "Peaceful",
        1: "Easy",
        2: "Normal",
        3: "Hard",
    }
    try:
        return mapping.get(int(value), "Unknown")
    except Exception:
        return "Unknown"


def _world_metadata_from_dir(world_dir: str, *, storage_label: str = "") -> Dict[str, Any]:
    world_id = os.path.basename(world_dir)
    level_dat_path = os.path.join(world_dir, "level.dat")
    root_tag, _compression = _read_level_dat(level_dat_path)
    data_tag = _compound_child((root_tag or {}).get("value"), "Data")
    data_value = (data_tag or {}).get("value", {})
    version_tag = _compound_child(data_value, "Version")
    version_value = (version_tag or {}).get("value", {})

    title = str(_tag_value(data_value, "LevelName", world_id) or world_id).strip() or world_id
    last_played = _tag_value(data_value, "LastPlayed", 0) or 0
    game_type = _tag_value(data_value, "GameType", -1)
    difficulty_settings = _compound_tag_value(_compound_child(data_value, "difficulty_settings"))
    difficulty = _tag_value(data_value, "Difficulty", _tag_value(difficulty_settings, "difficulty", -1))
    allow_commands = _bool_value(_tag_value(data_value, "allowCommands", 0))
    hardcore = _bool_value(_tag_value(data_value, "hardcore", _tag_value(difficulty_settings, "hardcore", 0)))
    version_name = str(_tag_value(version_value, "Name", "") or "").strip()
    data_version = _tag_value(data_value, "DataVersion", None)
    size_on_disk = _tag_value(data_value, "SizeOnDisk", 0) or 0

    try:
        modified_at = int(os.path.getmtime(level_dat_path if os.path.isfile(level_dat_path) else world_dir) * 1000)
    except Exception:
        modified_at = 0

    try:
        created_at = int(os.path.getctime(world_dir) * 1000)
    except Exception:
        created_at = 0

    world_size_bytes = _dir_size_bytes(world_dir)
    icon_url = _image_data_url(os.path.join(world_dir, "icon.png"))

    summary_parts = []
    if game_type is not None and int(game_type) >= 0:
        summary_parts.append(_game_mode_label(game_type))
    if version_name:
        summary_parts.append(version_name)
    if storage_label:
        summary_parts.append(storage_label)

    return {
        "world_id": world_id,
        "title": title,
        "display_name": title,
        "description": " | ".join(summary_parts),
        "summary": " | ".join(summary_parts),
        "icon_url": icon_url,
        "modified_at": modified_at,
        "created_at": created_at,
        "last_played": int(last_played) if last_played else 0,
        "game_mode": _game_mode_label(game_type),
        "difficulty": _difficulty_label(_difficulty_id_from_value(difficulty)),
        "allow_commands": allow_commands,
        "hardcore": hardcore,
        "version_name": version_name,
        "minecraft_version": version_name,
        "data_version": data_version,
        "size_on_disk": int(size_on_disk) if size_on_disk else 0,
        "size_bytes": world_size_bytes,
        "storage_label": storage_label,
        "has_icon": bool(icon_url),
    }


def list_worlds(storage_target: str = "default", *, custom_path: str = "") -> Dict[str, Any]:
    resolved = resolve_storage_target(storage_target, custom_path=custom_path, create_saves_dir=False)
    if not resolved.get("ok"):
        return {
            "ok": False,
            "storage_label": resolved.get("storage_label", "Default"),
            "worlds": [],
            "error": resolved.get("error") or "Failed to resolve worlds storage directory.",
        }

    saves_dir = str(resolved.get("saves_dir") or "")
    if not os.path.isdir(saves_dir):
        return {
            "ok": True,
            "storage_label": resolved.get("storage_label", "Default"),
            "worlds": [],
            "error": "",
        }

    worlds = []
    try:
        for entry in sorted(os.listdir(saves_dir), key=lambda value: value.lower()):
            world_dir = os.path.join(saves_dir, entry)
            if not os.path.isdir(world_dir):
                continue
            if not os.path.isfile(os.path.join(world_dir, "level.dat")):
                continue
            worlds.append(_world_metadata_from_dir(world_dir, storage_label=str(resolved.get("storage_label") or "")))
    except Exception as e:
        return {
            "ok": False,
            "storage_label": resolved.get("storage_label", "Default"),
            "worlds": [],
            "error": str(e),
        }

    return {
        "ok": True,
        "storage_label": resolved.get("storage_label", "Default"),
        "storage_path": resolved.get("game_dir") or "",
        "worlds": worlds,
        "error": "",
    }


def get_world_detail(storage_target: str, world_id: str, *, custom_path: str = "") -> Dict[str, Any]:
    world_dir, resolved = _world_dir(storage_target, world_id, custom_path=custom_path)
    if not resolved.get("ok"):
        return {
            "ok": False,
            "error": resolved.get("error") or "Failed to resolve world directory.",
        }
    if not os.path.isdir(world_dir):
        return {"ok": False, "error": "World was not found."}

    detail = _world_metadata_from_dir(world_dir, storage_label=str(resolved.get("storage_label") or ""))
    detail.update({
        "ok": True,
        "path": world_dir,
        "game_dir": resolved.get("game_dir") or "",
        "storage_target": storage_target,
    })
    return detail


__all__ = [
    "list_worlds",
    "get_world_detail",
    "_world_metadata_from_dir",
    "_dir_size_bytes",
    "_image_data_url",
    "_game_mode_label",
    "_difficulty_label",
]
