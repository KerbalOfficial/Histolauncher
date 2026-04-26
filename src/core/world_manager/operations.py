from __future__ import annotations

import os
import shutil
from typing import Any, Dict

from core.nbt_editor import (
    compound_child as _compound_child,
    read_nbt_file as _read_level_dat,
    write_nbt_file as _write_level_dat,
)

from core.world_manager._constants import MAX_WORLD_TITLE_LENGTH
from core.world_manager.metadata import _world_metadata_from_dir
from core.world_manager.storage import _validate_world_id, _world_dir


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_WORLD_ICON_BYTES = 4 * 1024 * 1024
_WORLD_ICON_SIZE = 64


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if not isinstance(payload, (bytes, bytearray)) or len(payload) < 24:
        return 0, 0
    if not bytes(payload).startswith(_PNG_SIGNATURE):
        return 0, 0
    if bytes(payload[12:16]) != b"IHDR":
        return 0, 0
    return int.from_bytes(payload[16:20], "big"), int.from_bytes(payload[20:24], "big")


def update_world(
    storage_target: str,
    world_id: str,
    *,
    custom_path: str = "",
    new_world_id: str = "",
    new_title: str = "",
) -> Dict[str, Any]:
    world_dir, resolved = _world_dir(storage_target, world_id, custom_path=custom_path)
    if not resolved.get("ok"):
        return {"ok": False, "error": resolved.get("error") or "Failed to resolve world directory."}
    if not os.path.isdir(world_dir):
        return {"ok": False, "error": "World was not found."}

    requested_id = str(new_world_id or world_id).strip() or world_id
    requested_title = str(new_title or "").strip()
    if len(requested_title) > MAX_WORLD_TITLE_LENGTH:
        return {"ok": False, "error": f"World title must be <= {MAX_WORLD_TITLE_LENGTH} characters."}
    if not _validate_world_id(requested_id):
        return {"ok": False, "error": "Invalid world id."}

    level_dat_path = os.path.join(world_dir, "level.dat")
    if requested_title:
        root_tag, compression = _read_level_dat(level_dat_path)
        data_tag = _compound_child((root_tag or {}).get("value"), "Data")
        data_value = (data_tag or {}).get("value", {})
        level_name_tag = _compound_child(data_value, "LevelName")
        if not data_tag or not isinstance(data_value, dict) or not level_name_tag:
            return {"ok": False, "error": "World metadata could not be updated because level.dat is missing expected fields."}
        level_name_tag["value"] = requested_title
        if not _write_level_dat(level_dat_path, root_tag, compression or "gzip"):
            return {"ok": False, "error": "Failed to save updated world title."}

    target_world_dir = world_dir
    if requested_id != world_id:
        saves_dir = str(resolved.get("saves_dir") or "")
        target_world_dir = os.path.join(saves_dir, requested_id)
        if os.path.exists(target_world_dir):
            return {"ok": False, "error": "A world with that id already exists."}
        try:
            os.replace(world_dir, target_world_dir)
        except Exception as e:
            return {"ok": False, "error": f"Failed to rename world folder: {e}"}

    detail = _world_metadata_from_dir(target_world_dir, storage_label=str(resolved.get("storage_label") or ""))
    detail.update({"ok": True, "storage_target": storage_target})
    return detail


def delete_world(storage_target: str, world_id: str, *, custom_path: str = "") -> Dict[str, Any]:
    world_dir, resolved = _world_dir(storage_target, world_id, custom_path=custom_path)
    if not resolved.get("ok"):
        return {"ok": False, "error": resolved.get("error") or "Failed to resolve world directory."}
    if not os.path.isdir(world_dir):
        return {"ok": False, "error": "World was not found."}
    try:
        shutil.rmtree(world_dir)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def open_world_folder(storage_target: str, world_id: str, *, custom_path: str = "") -> Dict[str, Any]:
    world_dir, resolved = _world_dir(storage_target, world_id, custom_path=custom_path)
    if not resolved.get("ok"):
        return {"ok": False, "error": resolved.get("error") or "Failed to resolve world directory."}
    if not os.path.isdir(world_dir):
        return {"ok": False, "error": "World was not found."}
    try:
        if os.name == "nt":
            os.startfile(world_dir)
        else:
            import subprocess
            if shutil.which("open"):
                subprocess.Popen(["open", world_dir])
            else:
                subprocess.Popen(["xdg-open", world_dir])
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def replace_world_icon(
    storage_target: str,
    world_id: str,
    *,
    custom_path: str = "",
    image_data: bytes = b"",
) -> Dict[str, Any]:
    world_dir, resolved = _world_dir(storage_target, world_id, custom_path=custom_path)
    if not resolved.get("ok"):
        return {"ok": False, "error": resolved.get("error") or "Failed to resolve world directory."}
    if not os.path.isdir(world_dir):
        return {"ok": False, "error": "World was not found."}
    if not isinstance(image_data, (bytes, bytearray)) or not image_data:
        return {"ok": False, "error": "No PNG image data was provided."}
    if len(image_data) > _MAX_WORLD_ICON_BYTES:
        return {"ok": False, "error": "World icon PNG is too large."}
    payload = bytes(image_data)
    if not payload.startswith(_PNG_SIGNATURE):
        return {"ok": False, "error": "World icon must be a PNG file."}
    width, height = _png_dimensions(payload)
    if width != _WORLD_ICON_SIZE or height != _WORLD_ICON_SIZE:
        return {"ok": False, "error": "World icon PNG must be exactly 64x64 pixels."}

    icon_path = os.path.join(world_dir, "icon.png")
    try:
        with open(icon_path, "wb") as f:
            f.write(payload)
    except Exception as e:
        return {"ok": False, "error": f"Failed to save world icon: {e}"}

    detail = _world_metadata_from_dir(world_dir, storage_label=str(resolved.get("storage_label") or ""))
    detail.update({"ok": True, "storage_target": storage_target})
    return detail


__all__ = ["update_world", "delete_world", "open_world_folder", "replace_world_icon"]
