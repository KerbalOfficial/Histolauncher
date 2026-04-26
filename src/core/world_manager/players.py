from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from core.nbt_editor import (
    TAG_BYTE,
    TAG_COMPOUND,
    TAG_DOUBLE,
    TAG_END,
    TAG_FLOAT,
    TAG_INT,
    TAG_LIST,
    TAG_LONG,
    TAG_STRING,
    compound_child as _compound_child,
    compound_tag_value as _compound_tag_value,
    int_value as _int_value,
    read_nbt_file as _read_level_dat,
    set_compound_tag as _set_compound_tag,
    tag_value as _tag_value,
)
from core.settings import load_global_settings

from core.world_manager._constants import (
    EMBEDDED_WORLD_PLAYER_ID,
    MINECRAFT_USERCACHE_PATH,
)
from core.world_manager._helpers import (
    _clone_nbt,
    _data_value_from_root,
    _remove_compound_tag,
    _uuid_from_int_array,
    _world_primary_player_uuid,
    _world_storage_paths,
)


def _normalize_uuid_string(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return raw if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", raw) else ""


def _uuid_from_long_pair(most: Any, least: Any) -> str:
    try:
        most_value = int(most)
        least_value = int(least)
    except Exception:
        return ""

    most_unsigned = most_value & ((1 << 64) - 1)
    least_unsigned = least_value & ((1 << 64) - 1)
    try:
        import uuid as _uuid_mod
        return str(_uuid_mod.UUID(int=(most_unsigned << 64) | least_unsigned))
    except Exception:
        return ""


def _player_uuid_from_value(player_value: Any) -> str:
    if not isinstance(player_value, dict):
        return ""

    direct_uuid = _normalize_uuid_string(_tag_value(player_value, "uuid", _tag_value(player_value, "UUID", "")))
    if direct_uuid:
        return direct_uuid

    int_array_uuid = _uuid_from_int_array(_tag_value(player_value, "UUID", None))
    if int_array_uuid:
        return int_array_uuid

    long_pair_uuid = _uuid_from_long_pair(
        _tag_value(player_value, "UUIDMost", None),
        _tag_value(player_value, "UUIDLeast", None),
    )
    if long_pair_uuid:
        return long_pair_uuid

    return ""


def _launcher_account_identity() -> Tuple[str, str]:
    try:
        settings = load_global_settings()
    except Exception:
        return "", ""

    username = str(settings.get("username") or "").strip()
    account_uuid = _normalize_uuid_string(settings.get("uuid"))
    return username, account_uuid


def _load_usercache_names() -> Dict[str, str]:
    if not os.path.isfile(MINECRAFT_USERCACHE_PATH):
        return {}
    try:
        with open(MINECRAFT_USERCACHE_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {}

    out: Dict[str, str] = {}
    for entry in payload if isinstance(payload, list) else []:
        if not isinstance(entry, dict):
            continue
        player_uuid = _normalize_uuid_string(entry.get("uuid"))
        player_name = str(entry.get("name") or "").strip()
        if player_uuid and player_name and player_uuid not in out:
            out[player_uuid] = player_name
    return out


def _candidate_player_data_dirs(world_dir: str) -> List[str]:
    candidates = [
        os.path.join(world_dir, "players", "data"),
        os.path.join(world_dir, "playerdata"),
    ]
    return [path for path in candidates if os.path.isdir(path)]


def _world_player_file_entries(world_dir: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for base_dir in _candidate_player_data_dirs(world_dir):
        try:
            filenames = sorted(os.listdir(base_dir))
        except Exception:
            continue
        for filename in filenames:
            if not filename.lower().endswith(".dat") or filename.lower().endswith(".dat_old"):
                continue
            player_uuid = _normalize_uuid_string(filename[:-4])
            if not player_uuid or player_uuid in out:
                continue
            out[player_uuid] = {
                "player_id": player_uuid,
                "uuid": player_uuid,
                "path": os.path.join(base_dir, filename),
                "source": "file",
            }
    return out


def _list_world_player_entries(world_dir: str, root_tag: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
    data_value = _data_value_from_root(root_tag)
    usercache_names = _load_usercache_names()
    primary_uuid = _world_primary_player_uuid(root_tag)
    embedded_player = _compound_tag_value(_compound_child(data_value, "Player"))
    embedded_uuid = _player_uuid_from_value(embedded_player)
    file_entries = _world_player_file_entries(world_dir)
    storage_paths = _world_storage_paths(world_dir, root_tag)
    launcher_username, launcher_uuid = _launcher_account_identity()

    if primary_uuid and primary_uuid not in file_entries and (storage_paths.get("has_modern_world_storage") or not isinstance(embedded_player, dict)):
        for base_dir in _candidate_player_data_dirs(world_dir):
            file_entries[primary_uuid] = {
                "player_id": primary_uuid,
                "uuid": primary_uuid,
                "path": os.path.join(base_dir, f"{primary_uuid}.dat"),
                "source": "file",
            }
            break

    embedded_is_primary = not primary_uuid or (embedded_uuid == primary_uuid and bool(embedded_uuid))
    embedded_match_uuid = ""
    if embedded_uuid and embedded_uuid in file_entries:
        embedded_match_uuid = embedded_uuid
    elif (
        isinstance(embedded_player, dict)
        and not storage_paths.get("has_modern_world_storage")
        and file_entries
    ):
        if launcher_uuid and launcher_uuid in file_entries:
            embedded_match_uuid = launcher_uuid
        elif launcher_username:
            normalized_username = launcher_username.strip().lower()
            username_matches = [
                player_uuid
                for player_uuid in sorted(file_entries)
                if str(usercache_names.get(player_uuid) or "").strip().lower() == normalized_username
            ]
            if len(username_matches) == 1:
                embedded_match_uuid = username_matches[0]

    if embedded_match_uuid:
        embedded_uuid = embedded_uuid or embedded_match_uuid
        file_entries.pop(embedded_match_uuid, None)
    elif (
        isinstance(embedded_player, dict)
        and not storage_paths.get("has_modern_world_storage")
        and not embedded_uuid
        and len(file_entries) == 1
    ):
        lone_player_uuid = next(iter(file_entries.keys()))
        embedded_uuid = lone_player_uuid
        file_entries.pop(lone_player_uuid, None)

    entries: List[Dict[str, Any]] = []
    if isinstance(embedded_player, dict):
        embedded_name = usercache_names.get(embedded_uuid, "") if embedded_uuid else ""
        embedded_label = embedded_name or ("Primary Player" if embedded_is_primary else "Embedded World Player")
        entries.append({
            "player_id": EMBEDDED_WORLD_PLAYER_ID,
            "uuid": embedded_uuid or primary_uuid,
            "label": embedded_label,
            "source": "embedded",
            "path": "",
            "is_primary": embedded_is_primary,
        })

    for player_uuid in sorted(file_entries):
        entry = file_entries[player_uuid]
        name = usercache_names.get(player_uuid, "")
        label = name or player_uuid
        if player_uuid == primary_uuid:
            label = f"{label} (Primary)"
        entries.append({
            "player_id": entry["player_id"],
            "uuid": player_uuid,
            "label": label,
            "source": "file",
            "path": entry["path"],
            "is_primary": player_uuid == primary_uuid,
        })

    selected_player_id = ""
    if primary_uuid and any(entry.get("player_id") == primary_uuid for entry in entries):
        selected_player_id = primary_uuid
    elif any(entry.get("player_id") == EMBEDDED_WORLD_PLAYER_ID for entry in entries):
        selected_player_id = EMBEDDED_WORLD_PLAYER_ID
    elif entries:
        selected_player_id = str(entries[0].get("player_id") or "")

    return entries, selected_player_id


def _resolve_world_player_entry(world_dir: str, root_tag: Dict[str, Any], player_id: str = "") -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], str]:
    entries, default_player_id = _list_world_player_entries(world_dir, root_tag)
    requested_player_id = str(player_id or "").strip()
    selected_player_id = requested_player_id if requested_player_id else default_player_id

    selected_entry = None
    for entry in entries:
        if str(entry.get("player_id") or "") == selected_player_id:
            selected_entry = entry
            break

    if selected_entry is None and entries:
        selected_entry = entries[0]
        selected_player_id = str(selected_entry.get("player_id") or "")

    return selected_entry, entries, selected_player_id


def _load_world_player_root(selected_entry: Optional[Dict[str, Any]], root_tag: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(selected_entry, dict):
        return None

    source = str(selected_entry.get("source") or "")
    if source == "embedded":
        player_value = _compound_tag_value(_compound_child(_data_value_from_root(root_tag), "Player"))
        if isinstance(player_value, dict):
            return {"type": TAG_COMPOUND, "name": "", "value": _clone_nbt(player_value)}
        return None

    player_path = str(selected_entry.get("path") or "")
    if player_path and os.path.isfile(player_path):
        player_root, _compression = _read_level_dat(player_path)
        if player_root:
            return player_root

    return {"type": TAG_COMPOUND, "name": "", "value": {}}


def _list_tag_payload(compound: Any, key: str) -> Optional[Dict[str, Any]]:
    list_tag = _compound_child(compound, key)
    if not list_tag:
        return None

    try:
        if int(list_tag.get("type", TAG_END) or TAG_END) != TAG_LIST:
            return None
    except Exception:
        return None

    list_value = list_tag.get("value", {})
    return list_value if isinstance(list_value, dict) else None


def _item_list_from_player(player_value: Any, list_key: str) -> List[Dict[str, Any]]:
    list_value = _list_tag_payload(player_value, list_key)
    if not isinstance(list_value, dict):
        return []

    try:
        if int(list_value.get("list_type", TAG_END) or TAG_END) not in {TAG_COMPOUND, TAG_END}:
            return []
    except Exception:
        return []

    items = []
    for entry in list(list_value.get("items", [])):
        if not isinstance(entry, dict):
            continue

        slot = _int_value(_tag_value(entry, "Slot", None), None)
        item_id = str(_tag_value(entry, "id", "") or "").strip()
        count = _int_value(_tag_value(entry, "Count", _tag_value(entry, "count", None)), None)
        if slot is None:
            continue
        items.append({
            "slot": slot,
            "item_id": item_id,
            "count": max(1, min(127, count or 1)),
            "has_extra_data": any(key not in {"Slot", "id", "Count", "count"} for key in entry.keys()),
        })

    items.sort(key=lambda item: (item.get("slot", 0), item.get("item_id", "")))
    return items


def _inventory_items_from_player(player_value: Any) -> List[Dict[str, Any]]:
    return _item_list_from_player(player_value, "Inventory")


def _ender_items_from_player(player_value: Any) -> List[Dict[str, Any]]:
    return _item_list_from_player(player_value, "EnderItems")


def _position_from_player(player_value: Any, key: str = "Pos") -> Tuple[Optional[float], Optional[float], Optional[float]]:
    list_value = _list_tag_payload(player_value, key)
    if not isinstance(list_value, dict):
        return None, None, None

    try:
        list_type = int(list_value.get("list_type", TAG_END) or TAG_END)
    except Exception:
        list_type = TAG_END

    if list_type not in {TAG_DOUBLE, TAG_FLOAT, TAG_LONG, TAG_INT}:
        return None, None, None

    values = list(list_value.get("items", []))
    out = []
    for index in range(3):
        raw = values[index] if index < len(values) else None
        if raw in (None, ""):
            out.append(None)
            continue
        try:
            out.append(float(raw))
        except Exception:
            out.append(None)
    return out[0], out[1], out[2]


def _set_player_item_list(player_value: Dict[str, Any], list_key: str, inventory_items: List[Dict[str, Any]]) -> None:
    existing_tag = _compound_child(player_value, list_key)
    existing_by_slot: Dict[int, Dict[str, Any]] = {}
    use_modern_count = False

    if existing_tag and int(existing_tag.get("type", TAG_END) or TAG_END) == TAG_LIST:
        existing_value = existing_tag.get("value", {})
        if isinstance(existing_value, dict):
            for entry in list(existing_value.get("items", [])):
                if not isinstance(entry, dict):
                    continue
                if _compound_child(entry, "count"):
                    use_modern_count = True
                slot = _int_value(_tag_value(entry, "Slot", None), None)
                if slot is None:
                    continue
                existing_by_slot[slot] = entry

    items = []
    for item in inventory_items:
        slot = int(item.get("slot", 0))
        entry = existing_by_slot.get(slot, {})
        if not isinstance(entry, dict):
            entry = {}
        _set_compound_tag(entry, "Slot", TAG_BYTE, slot)
        _set_compound_tag(entry, "id", TAG_STRING, str(item.get("item_id") or ""))
        stack_count = int(item.get("count") or 1)
        if use_modern_count or _compound_child(entry, "count"):
            _set_compound_tag(entry, "count", TAG_INT, stack_count)
            _remove_compound_tag(entry, "Count")
        else:
            _set_compound_tag(entry, "Count", TAG_BYTE, stack_count)
            _remove_compound_tag(entry, "count")
        items.append(entry)

    player_value[list_key] = {
        "type": TAG_LIST,
        "value": {
            "list_type": TAG_COMPOUND,
            "items": items,
        },
    }


def _set_player_inventory(player_value: Dict[str, Any], inventory_items: List[Dict[str, Any]]) -> None:
    _set_player_item_list(player_value, "Inventory", inventory_items)


def _set_player_ender_items(player_value: Dict[str, Any], inventory_items: List[Dict[str, Any]]) -> None:
    _set_player_item_list(player_value, "EnderItems", inventory_items)


def _set_player_position(
    player_value: Dict[str, Any],
    x_value: Optional[float],
    y_value: Optional[float],
    z_value: Optional[float],
) -> None:
    if x_value is None or y_value is None or z_value is None:
        return

    existing_value = _list_tag_payload(player_value, "Pos") or {}
    try:
        list_type = int(existing_value.get("list_type", TAG_DOUBLE) or TAG_DOUBLE)
    except Exception:
        list_type = TAG_DOUBLE
    if list_type not in {TAG_DOUBLE, TAG_FLOAT}:
        list_type = TAG_DOUBLE

    player_value["Pos"] = {
        "type": TAG_LIST,
        "value": {
            "list_type": list_type,
            "items": [float(x_value), float(y_value), float(z_value)],
        },
    }


__all__ = [
    "_normalize_uuid_string",
    "_uuid_from_long_pair",
    "_player_uuid_from_value",
    "_launcher_account_identity",
    "_load_usercache_names",
    "_candidate_player_data_dirs",
    "_world_player_file_entries",
    "_list_world_player_entries",
    "_resolve_world_player_entry",
    "_load_world_player_root",
    "_list_tag_payload",
    "_item_list_from_player",
    "_inventory_items_from_player",
    "_ender_items_from_player",
    "_position_from_player",
    "_set_player_item_list",
    "_set_player_inventory",
    "_set_player_ender_items",
    "_set_player_position",
]
