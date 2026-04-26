from __future__ import annotations

import copy
import os
import struct
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.nbt_editor import (
    TAG_COMPOUND,
    TAG_INT,
    TAG_INT_ARRAY,
    compound_child as _compound_child,
    ensure_compound_value as _ensure_compound_value,
    ensure_root_value as _ensure_root_value,
    int_value as _int_value,
    read_nbt_file as _read_level_dat,
    set_compound_tag as _set_compound_tag,
    tag_value as _tag_value,
)

from core.world_manager._constants import (
    DIFFICULTY_ID_TO_NAME,
    DIFFICULTY_NAME_TO_ID,
)


def _clone_nbt(value: Any) -> Any:
    return copy.deepcopy(value)


def _uuid_from_int_array(values: Any) -> str:
    if not isinstance(values, list) or len(values) != 4:
        return ""
    try:
        return str(uuid.UUID(bytes=struct.pack(">iiii", *(int(value) for value in values))))
    except Exception:
        return ""


def _data_value_from_root(root_tag: Dict[str, Any]) -> Dict[str, Any]:
    return _ensure_compound_value(_ensure_root_value(root_tag), "Data")


def _world_primary_player_uuid(root_tag: Dict[str, Any]) -> str:
    data_value = _data_value_from_root(root_tag)
    return _uuid_from_int_array(_tag_value(data_value, "singleplayer_uuid", None))


def _world_storage_paths(world_dir: str, root_tag: Dict[str, Any]) -> Dict[str, Any]:
    data_value = _data_value_from_root(root_tag)
    minecraft_data_dir = os.path.join(world_dir, "data", "minecraft")
    has_split_data_dir = os.path.isdir(minecraft_data_dir)
    has_modern_world_storage = has_split_data_dir or bool(_compound_child(data_value, "singleplayer_uuid"))

    return {
        "has_modern_world_storage": has_modern_world_storage,
        "weather_path": os.path.join(minecraft_data_dir, "weather.dat") if has_modern_world_storage else "",
        "game_rules_path": os.path.join(minecraft_data_dir, "game_rules.dat") if has_modern_world_storage else "",
        "world_clocks_path": os.path.join(minecraft_data_dir, "world_clocks.dat") if has_modern_world_storage else "",
        "uses_modern_spawn": bool(_compound_child(data_value, "spawn")),
        "uses_modern_difficulty": bool(_compound_child(data_value, "difficulty_settings")),
    }


def _load_aux_root(path: str) -> Tuple[Optional[Dict[str, Any]], str]:
    if not path or not os.path.isfile(path):
        return None, "gzip"
    root_tag, compression = _read_level_dat(path)
    return root_tag, compression or "gzip"


def _create_aux_root(data_version: Any = None) -> Dict[str, Any]:
    root_tag = {"type": TAG_COMPOUND, "name": "", "value": {}}
    if data_version is not None:
        _set_compound_tag(root_tag["value"], "DataVersion", TAG_INT, _int_value(data_version, 0) or 0)
    return root_tag


def _replace_compound_tag(compound: Dict[str, Any], key: str, value: Optional[Dict[str, Any]]) -> None:
    if value is None:
        compound.pop(key, None)
        return
    compound[key] = {"type": TAG_COMPOUND, "value": _clone_nbt(value)}


def _replace_list_of_ints_tag(compound: Dict[str, Any], key: str, values: List[int]) -> None:
    compound[key] = {"type": TAG_INT_ARRAY, "value": [int(value) for value in values]}


def _remove_compound_tag(compound: Dict[str, Any], key: str) -> None:
    if isinstance(compound, dict):
        compound.pop(key, None)


def _difficulty_name_from_value(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in DIFFICULTY_NAME_TO_ID:
            return normalized
    try:
        return DIFFICULTY_ID_TO_NAME.get(int(value), "normal")
    except Exception:
        return "normal"


def _difficulty_id_from_value(value: Any) -> int:
    if isinstance(value, str):
        return DIFFICULTY_NAME_TO_ID.get(value.strip().lower(), 1)
    try:
        return int(value)
    except Exception:
        return 1


__all__ = [
    "_clone_nbt",
    "_uuid_from_int_array",
    "_data_value_from_root",
    "_world_primary_player_uuid",
    "_world_storage_paths",
    "_load_aux_root",
    "_create_aux_root",
    "_replace_compound_tag",
    "_replace_list_of_ints_tag",
    "_remove_compound_tag",
    "_difficulty_name_from_value",
    "_difficulty_id_from_value",
]
