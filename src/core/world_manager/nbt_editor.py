from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from core.nbt_editor import (
    TAG_BYTE,
    TAG_COMPOUND,
    TAG_END,
    TAG_FLOAT,
    TAG_INT,
    TAG_LONG,
    TAG_STRING,
    bool_value as _bool_value,
    compound_child as _compound_child,
    compound_tag_value as _compound_tag_value,
    ensure_compound_value as _ensure_compound_value,
    ensure_root_value as _ensure_root_value,
    float_value as _float_value,
    int_value as _int_value,
    nbt_root_from_json_safe as _nbt_root_from_json_safe,
    nbt_root_to_json_safe as _nbt_root_to_json_safe,
    read_nbt_file as _read_level_dat,
    set_compound_tag as _set_compound_tag,
    tag_value as _tag_value,
    write_nbt_file as _write_level_dat,
)

from core.world_manager._constants import OVERWORLD_CLOCK_ID
from core.world_manager._helpers import (
    _clone_nbt,
    _create_aux_root,
    _data_value_from_root,
    _difficulty_id_from_value,
    _difficulty_name_from_value,
    _load_aux_root,
    _remove_compound_tag,
    _replace_compound_tag,
    _replace_list_of_ints_tag,
    _world_storage_paths,
)
from core.world_manager.metadata import get_world_detail
from core.world_manager.players import (
    _ender_items_from_player,
    _inventory_items_from_player,
    _list_tag_payload,
    _load_world_player_root,
    _position_from_player,
    _resolve_world_player_entry,
    _set_player_ender_items,
    _set_player_inventory,
    _set_player_position,
)
from core.world_manager.storage import _version_at_least, _world_dir


def _parse_int_field(
    payload: Dict[str, Any],
    key: str,
    label: str,
    *,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
    default: Optional[int] = None,
) -> Optional[int]:
    raw = payload.get(key, default)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except Exception as exc:
        raise ValueError(f"{label} must be a whole number.") from exc
    if min_value is not None and value < min_value:
        raise ValueError(f"{label} must be at least {min_value}.")
    if max_value is not None and value > max_value:
        raise ValueError(f"{label} must be at most {max_value}.")
    return value


def _parse_float_field(
    payload: Dict[str, Any],
    key: str,
    label: str,
    *,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    default: Optional[float] = None,
) -> Optional[float]:
    raw = payload.get(key, default)
    if raw in (None, ""):
        return default
    try:
        value = float(raw)
    except Exception as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if min_value is not None and value < min_value:
        raise ValueError(f"{label} must be at least {min_value}.")
    if max_value is not None and value > max_value:
        raise ValueError(f"{label} must be at most {max_value}.")
    return value


def _parse_bool_field(payload: Dict[str, Any], key: str, default: bool = False) -> bool:
    if key not in payload:
        return default

    raw = payload.get(key)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(int(raw))

    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_weather_duration(*values: Any, default: int = 6000) -> int:
    for value in values:
        parsed = _int_value(value, None)
        if parsed is not None and int(parsed) > 1:
            return int(parsed)
    return int(default)


def _parse_inventory_items(
    value: Any,
    *,
    item_label: str = "Inventory item",
    min_slot: int = 0,
    max_slot: int = 255,
) -> Optional[List[Dict[str, Any]]]:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("Inventory items must be a list.")

    normalized_by_slot: Dict[int, Dict[str, Any]] = {}
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise ValueError(f"{item_label} #{index + 1} is invalid.")

        raw_slot = entry.get("slot")
        raw_item_id = str(entry.get("item_id") or entry.get("id") or "").strip()
        raw_count = entry.get("count")

        if raw_slot in (None, "") and not raw_item_id and raw_count in (None, ""):
            continue

        slot = _parse_int_field(
            entry,
            "slot",
            f"{item_label} #{index + 1} slot",
            min_value=min_slot,
            max_value=max_slot,
        )
        if slot is None:
            raise ValueError(f"{item_label} #{index + 1} slot is required.")

        count = _parse_int_field(
            entry,
            "count",
            f"{item_label} #{index + 1} count",
            min_value=0,
            max_value=127,
            default=1,
        )
        if slot in normalized_by_slot:
            raise ValueError(f"{item_label} slot {slot} is duplicated.")

        if not raw_item_id or not count:
            continue

        normalized_by_slot[slot] = {
            "slot": slot,
            "item_id": raw_item_id,
            "count": count,
        }

    return [normalized_by_slot[slot] for slot in sorted(normalized_by_slot)]


def _simple_world_nbt_payload(root_tag: Dict[str, Any]) -> Dict[str, Any]:
    data_value = _ensure_compound_value(_ensure_root_value(root_tag), "Data")
    player_value = _compound_tag_value(_compound_child(data_value, "Player"))
    player_x, player_y, player_z = _position_from_player(player_value) if isinstance(player_value, dict) else (None, None, None)

    return {
        "world_title": str(_tag_value(data_value, "LevelName", "") or ""),
        "game_mode": _int_value(_tag_value(data_value, "GameType", 0), 0),
        "difficulty": _int_value(_tag_value(data_value, "Difficulty", 1), 1),
        "allow_commands": _bool_value(_tag_value(data_value, "allowCommands", 0)),
        "hardcore": _bool_value(_tag_value(data_value, "hardcore", 0)),
        "raining": _bool_value(_tag_value(data_value, "raining", 0)),
        "thundering": _bool_value(_tag_value(data_value, "thundering", 0)),
        "time": _int_value(_tag_value(data_value, "Time", 0), 0),
        "day_time": _int_value(_tag_value(data_value, "DayTime", _tag_value(data_value, "Time", 0)), 0),
        "rain_time": _int_value(_tag_value(data_value, "rainTime", 0), 0),
        "thunder_time": _int_value(_tag_value(data_value, "thunderTime", 0), 0),
        "clear_weather_time": _int_value(_tag_value(data_value, "clearWeatherTime", 0), 0),
        "spawn_x": _int_value(_tag_value(data_value, "SpawnX", 0), 0),
        "spawn_y": _int_value(_tag_value(data_value, "SpawnY", 0), 0),
        "spawn_z": _int_value(_tag_value(data_value, "SpawnZ", 0), 0),
        "has_player_data": isinstance(player_value, dict),
        "health": _float_value(_tag_value(player_value, "Health", None), None) if isinstance(player_value, dict) else None,
        "food_level": _int_value(_tag_value(player_value, "foodLevel", None), None) if isinstance(player_value, dict) else None,
        "food_saturation": _float_value(_tag_value(player_value, "foodSaturationLevel", None), None) if isinstance(player_value, dict) else None,
        "xp_level": _int_value(_tag_value(player_value, "XpLevel", None), None) if isinstance(player_value, dict) else None,
        "xp_total": _int_value(_tag_value(player_value, "XpTotal", None), None) if isinstance(player_value, dict) else None,
        "selected_item_slot": _int_value(_tag_value(player_value, "SelectedItemSlot", None), None) if isinstance(player_value, dict) else None,
        "player_x": player_x,
        "player_y": player_y,
        "player_z": player_z,
        "inventory_items": _inventory_items_from_player(player_value) if isinstance(player_value, dict) else [],
        "ender_items": _ender_items_from_player(player_value) if isinstance(player_value, dict) else [],
    }


def _load_world_nbt(storage_target: str, world_id: str, *, custom_path: str = "") -> Dict[str, Any]:
    world_dir, resolved = _world_dir(storage_target, world_id, custom_path=custom_path)
    if not resolved.get("ok"):
        return {"ok": False, "error": resolved.get("error") or "Failed to resolve world directory."}
    if not os.path.isdir(world_dir):
        return {"ok": False, "error": "World was not found."}

    level_dat_path = os.path.join(world_dir, "level.dat")
    root_tag, compression = _read_level_dat(level_dat_path)
    if not root_tag:
        return {"ok": False, "error": "Failed to read level.dat for this world."}

    return {
        "ok": True,
        "resolved": resolved,
        "world_dir": world_dir,
        "level_dat_path": level_dat_path,
        "root_tag": root_tag,
        "compression": compression or "gzip",
    }


def _modernize_editor_root(
    loaded: Dict[str, Any],
    *,
    player_id: str = "",
) -> Dict[str, Any]:
    editor_root = _clone_nbt(loaded.get("root_tag") or {})
    data_value = _data_value_from_root(editor_root)
    original_root = loaded.get("root_tag") or {}
    world_dir = str(loaded.get("world_dir") or "")
    storage_paths = _world_storage_paths(world_dir, original_root)
    selected_player_entry, player_entries, selected_player_id = _resolve_world_player_entry(
        world_dir,
        original_root,
        player_id,
    )

    player_root = _load_world_player_root(selected_player_entry, original_root)
    if isinstance((player_root or {}).get("value"), dict):
        _replace_compound_tag(data_value, "Player", player_root.get("value"))

    difficulty_settings = _compound_tag_value(_compound_child(data_value, "difficulty_settings"))
    if isinstance(difficulty_settings, dict):
        _set_compound_tag(
            data_value,
            "Difficulty",
            TAG_BYTE,
            _difficulty_id_from_value(_tag_value(difficulty_settings, "difficulty", 1)),
        )
        _set_compound_tag(
            data_value,
            "hardcore",
            TAG_BYTE,
            1 if _bool_value(_tag_value(difficulty_settings, "hardcore", 0)) else 0,
        )

    spawn_value = _compound_tag_value(_compound_child(data_value, "spawn"))
    spawn_pos = _tag_value(spawn_value, "pos", None) if isinstance(spawn_value, dict) else None
    if isinstance(spawn_pos, list) and len(spawn_pos) >= 3:
        _set_compound_tag(data_value, "SpawnX", TAG_INT, _int_value(spawn_pos[0], 0) or 0)
        _set_compound_tag(data_value, "SpawnY", TAG_INT, _int_value(spawn_pos[1], 0) or 0)
        _set_compound_tag(data_value, "SpawnZ", TAG_INT, _int_value(spawn_pos[2], 0) or 0)

    weather_root, _weather_compression = _load_aux_root(str(storage_paths.get("weather_path") or ""))
    weather_value = _compound_tag_value(_compound_child((weather_root or {}).get("value"), "data"))
    if isinstance(weather_value, dict):
        _set_compound_tag(data_value, "raining", TAG_BYTE, 1 if _bool_value(_tag_value(weather_value, "raining", 0)) else 0)
        _set_compound_tag(data_value, "thundering", TAG_BYTE, 1 if _bool_value(_tag_value(weather_value, "thundering", 0)) else 0)
        _set_compound_tag(data_value, "rainTime", TAG_INT, _int_value(_tag_value(weather_value, "rain_time", 0), 0) or 0)
        _set_compound_tag(data_value, "thunderTime", TAG_INT, _int_value(_tag_value(weather_value, "thunder_time", 0), 0) or 0)
        _set_compound_tag(
            data_value,
            "clearWeatherTime",
            TAG_INT,
            _int_value(_tag_value(weather_value, "clear_weather_time", 0), 0) or 0,
        )

    game_rules_root, _game_rules_compression = _load_aux_root(str(storage_paths.get("game_rules_path") or ""))
    game_rules_value = _compound_tag_value(_compound_child((game_rules_root or {}).get("value"), "data"))
    if isinstance(game_rules_value, dict):
        _replace_compound_tag(data_value, "GameRules", game_rules_value)

    world_clocks_root, _world_clocks_compression = _load_aux_root(str(storage_paths.get("world_clocks_path") or ""))
    world_clock_data = _compound_tag_value(_compound_child((world_clocks_root or {}).get("value"), "data"))
    overworld_clock = _compound_tag_value(_compound_child(world_clock_data, OVERWORLD_CLOCK_ID))
    if isinstance(overworld_clock, dict):
        _set_compound_tag(
            data_value,
            "DayTime",
            TAG_LONG,
            _int_value(_tag_value(overworld_clock, "total_ticks", _tag_value(data_value, "Time", 0)), 0) or 0,
        )

    return {
        "root_tag": editor_root,
        "player_entries": player_entries,
        "selected_player_id": selected_player_id,
        "selected_player_entry": selected_player_entry,
        "storage_paths": storage_paths,
    }


def _normalize_player_item_stacks(player_value: Any, *, use_modern_format: bool) -> None:
    if not isinstance(player_value, dict):
        return

    for list_key in ("Inventory", "EnderItems"):
        list_value = _list_tag_payload(player_value, list_key)
        if not isinstance(list_value, dict):
            continue
        try:
            if int(list_value.get("list_type", TAG_END) or TAG_END) not in {TAG_COMPOUND, TAG_END}:
                continue
        except Exception:
            continue

        for entry in list(list_value.get("items", [])):
            if not isinstance(entry, dict):
                continue
            count_value = _int_value(_tag_value(entry, "count", _tag_value(entry, "Count", 1)), 1) or 1
            if use_modern_format:
                _set_compound_tag(entry, "count", TAG_INT, count_value)
                _remove_compound_tag(entry, "Count")
            else:
                _set_compound_tag(entry, "Count", TAG_BYTE, count_value)
                _remove_compound_tag(entry, "count")


def _write_editor_root(
    loaded: Dict[str, Any],
    editor_root: Dict[str, Any],
    *,
    player_id: str = "",
) -> Tuple[bool, str]:
    level_root = _clone_nbt(editor_root)
    data_value = _data_value_from_root(level_root)
    original_root = loaded.get("root_tag") or {}
    original_data_value = _data_value_from_root(original_root)
    world_dir = str(loaded.get("world_dir") or "")
    storage_paths = _world_storage_paths(world_dir, original_root)
    selected_player_entry, _player_entries, selected_player_id = _resolve_world_player_entry(
        world_dir,
        original_root,
        player_id,
    )
    world_data_version = _int_value(_tag_value(data_value, "DataVersion", _tag_value(original_data_value, "DataVersion", 0)), 0) or 0
    version_value = _compound_tag_value(_compound_child(data_value, "Version"))
    original_version_value = _compound_tag_value(_compound_child(original_data_value, "Version"))
    version_name = _tag_value(version_value, "Name", _tag_value(original_version_value, "Name", ""))
    use_modern_item_format = _version_at_least(version_name, "1.20.5")

    player_tag = _compound_child(data_value, "Player")
    selected_player_value = _compound_tag_value(player_tag)
    if isinstance(selected_player_value, dict):
        _normalize_player_item_stacks(selected_player_value, use_modern_format=use_modern_item_format)

    if isinstance(selected_player_entry, dict) and str(selected_player_entry.get("source") or "") == "file":
        player_path = str(selected_player_entry.get("path") or "")
        player_root, player_compression = _load_aux_root(player_path)
        if not player_root:
            player_root = _create_aux_root(world_data_version)
        player_root["value"] = _clone_nbt(selected_player_value or {})
        _normalize_player_item_stacks(player_root.get("value"), use_modern_format=use_modern_item_format)
        if player_path:
            os.makedirs(os.path.dirname(player_path), exist_ok=True)
            if not _write_level_dat(player_path, player_root, player_compression or "gzip"):
                return False, "Failed to save selected player data."

        embedded_player = _compound_tag_value(_compound_child(original_data_value, "Player"))
        if isinstance(embedded_player, dict):
            _replace_compound_tag(data_value, "Player", embedded_player)
        else:
            _remove_compound_tag(data_value, "Player")
    elif isinstance(selected_player_value, dict):
        _replace_compound_tag(data_value, "Player", selected_player_value)

    if storage_paths.get("uses_modern_difficulty"):
        difficulty_value = _compound_tag_value(_compound_child(data_value, "difficulty_settings"))
        if difficulty_value is None:
            difficulty_value = _ensure_compound_value(data_value, "difficulty_settings")
        _set_compound_tag(
            difficulty_value,
            "difficulty",
            TAG_STRING,
            _difficulty_name_from_value(_tag_value(data_value, "Difficulty", _tag_value(difficulty_value, "difficulty", "normal"))),
        )
        _set_compound_tag(
            difficulty_value,
            "hardcore",
            TAG_BYTE,
            1 if _bool_value(_tag_value(data_value, "hardcore", _tag_value(difficulty_value, "hardcore", 0))) else 0,
        )
        _remove_compound_tag(data_value, "Difficulty")
        _remove_compound_tag(data_value, "hardcore")

    if storage_paths.get("uses_modern_spawn"):
        spawn_value = _compound_tag_value(_compound_child(data_value, "spawn"))
        if spawn_value is None:
            spawn_value = _ensure_compound_value(data_value, "spawn")
        _replace_list_of_ints_tag(
            spawn_value,
            "pos",
            [
                _int_value(_tag_value(data_value, "SpawnX", 0), 0) or 0,
                _int_value(_tag_value(data_value, "SpawnY", 0), 0) or 0,
                _int_value(_tag_value(data_value, "SpawnZ", 0), 0) or 0,
            ],
        )
        _remove_compound_tag(data_value, "SpawnX")
        _remove_compound_tag(data_value, "SpawnY")
        _remove_compound_tag(data_value, "SpawnZ")

    weather_path = str(storage_paths.get("weather_path") or "")
    if weather_path:
        weather_root, weather_compression = _load_aux_root(weather_path)
        if not weather_root:
            weather_root = _create_aux_root(world_data_version)
        weather_value = _ensure_compound_value(_ensure_root_value(weather_root), "data")
        _set_compound_tag(weather_value, "raining", TAG_BYTE, 1 if _bool_value(_tag_value(data_value, "raining", 0)) else 0)
        _set_compound_tag(weather_value, "thundering", TAG_BYTE, 1 if _bool_value(_tag_value(data_value, "thundering", 0)) else 0)
        _set_compound_tag(weather_value, "rain_time", TAG_INT, _int_value(_tag_value(data_value, "rainTime", 0), 0) or 0)
        _set_compound_tag(weather_value, "thunder_time", TAG_INT, _int_value(_tag_value(data_value, "thunderTime", 0), 0) or 0)
        _set_compound_tag(
            weather_value,
            "clear_weather_time",
            TAG_INT,
            _int_value(_tag_value(data_value, "clearWeatherTime", 0), 0) or 0,
        )
        os.makedirs(os.path.dirname(weather_path), exist_ok=True)
        if not _write_level_dat(weather_path, weather_root, weather_compression or "gzip"):
            return False, "Failed to save world weather data."
        for key in ("raining", "thundering", "rainTime", "thunderTime", "clearWeatherTime"):
            _remove_compound_tag(data_value, key)

    game_rules_path = str(storage_paths.get("game_rules_path") or "")
    if game_rules_path:
        game_rules_root, game_rules_compression = _load_aux_root(game_rules_path)
        if not game_rules_root:
            game_rules_root = _create_aux_root(world_data_version)
        game_rules_value = _ensure_compound_value(_ensure_root_value(game_rules_root), "data")
        game_rules_value.clear()
        selected_game_rules = _compound_tag_value(_compound_child(data_value, "GameRules"))
        if isinstance(selected_game_rules, dict):
            game_rules_value.update(_clone_nbt(selected_game_rules))
        os.makedirs(os.path.dirname(game_rules_path), exist_ok=True)
        if not _write_level_dat(game_rules_path, game_rules_root, game_rules_compression or "gzip"):
            return False, "Failed to save world gamerules data."
        _remove_compound_tag(data_value, "GameRules")

    world_clocks_path = str(storage_paths.get("world_clocks_path") or "")
    if world_clocks_path:
        world_clocks_root, world_clocks_compression = _load_aux_root(world_clocks_path)
        if not world_clocks_root:
            world_clocks_root = _create_aux_root(world_data_version)
        world_clock_data = _ensure_compound_value(_ensure_root_value(world_clocks_root), "data")
        overworld_clock = _ensure_compound_value(world_clock_data, OVERWORLD_CLOCK_ID)
        _set_compound_tag(
            overworld_clock,
            "total_ticks",
            TAG_LONG,
            _int_value(_tag_value(data_value, "DayTime", _tag_value(data_value, "Time", 0)), 0) or 0,
        )
        os.makedirs(os.path.dirname(world_clocks_path), exist_ok=True)
        if not _write_level_dat(world_clocks_path, world_clocks_root, world_clocks_compression or "gzip"):
            return False, "Failed to save world clock data."
        _remove_compound_tag(data_value, "DayTime")

    if not _write_level_dat(str(loaded.get("level_dat_path") or ""), level_root, str(loaded.get("compression") or "gzip")):
        return False, "Failed to save world NBT data."

    return True, selected_player_id


def get_world_nbt_editor(
    storage_target: str,
    world_id: str,
    *,
    custom_path: str = "",
    player_id: str = "",
) -> Dict[str, Any]:
    loaded = _load_world_nbt(storage_target, world_id, custom_path=custom_path)
    if not loaded.get("ok"):
        return {"ok": False, "error": loaded.get("error") or "Failed to load world NBT data."}

    editor_context = _modernize_editor_root(loaded, player_id=player_id)
    root_tag = editor_context["root_tag"]
    detail = get_world_detail(storage_target, world_id, custom_path=custom_path)
    if not detail.get("ok"):
        return detail

    return {
        "ok": True,
        "detail": detail,
        "simple": _simple_world_nbt_payload(root_tag),
        "advanced_json": json.dumps(_nbt_root_to_json_safe(root_tag), indent=2, ensure_ascii=True),
        "players": editor_context.get("player_entries") or [],
        "selected_player_id": editor_context.get("selected_player_id") or "",
    }


def update_world_simple_nbt(
    storage_target: str,
    world_id: str,
    *,
    custom_path: str = "",
    player_id: str = "",
    changes: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = changes if isinstance(changes, dict) else {}
    loaded = _load_world_nbt(storage_target, world_id, custom_path=custom_path)
    if not loaded.get("ok"):
        return {"ok": False, "error": loaded.get("error") or "Failed to load world NBT data."}

    editor_context = _modernize_editor_root(loaded, player_id=player_id)
    root_tag = editor_context["root_tag"]
    current_simple = _simple_world_nbt_payload(root_tag)

    try:
        game_mode = _parse_int_field(
            payload,
            "game_mode",
            "Game Mode",
            min_value=0,
            max_value=3,
            default=current_simple.get("game_mode", 0),
        )
        difficulty = _parse_int_field(
            payload,
            "difficulty",
            "Difficulty",
            min_value=0,
            max_value=3,
            default=current_simple.get("difficulty", 1),
        )
        world_time = _parse_int_field(payload, "time", "World Time", default=current_simple.get("time", 0))
        day_time = _parse_int_field(
            payload,
            "day_time",
            "Day Time",
            default=current_simple.get("day_time", world_time),
        )
        rain_time = _parse_int_field(payload, "rain_time", "Rain Time", default=current_simple.get("rain_time", 0))
        thunder_time = _parse_int_field(payload, "thunder_time", "Thunder Time", default=current_simple.get("thunder_time", 0))
        clear_weather_time = _parse_int_field(
            payload,
            "clear_weather_time",
            "Clear Weather Time",
            default=current_simple.get("clear_weather_time", 0),
        )
        spawn_x = _parse_int_field(payload, "spawn_x", "Spawn X", default=current_simple.get("spawn_x", 0))
        spawn_y = _parse_int_field(payload, "spawn_y", "Spawn Y", default=current_simple.get("spawn_y", 0))
        spawn_z = _parse_int_field(payload, "spawn_z", "Spawn Z", default=current_simple.get("spawn_z", 0))

        raining = _parse_bool_field(payload, "raining", bool(current_simple.get("raining")))
        thundering = _parse_bool_field(payload, "thundering", bool(current_simple.get("thundering")))
        if thundering:
            raining = True

        default_weather_time = 6000
        resolved_rain_time = _resolve_weather_duration(rain_time, current_simple.get("rain_time"), default=default_weather_time)
        resolved_thunder_time = _resolve_weather_duration(
            thunder_time,
            current_simple.get("thunder_time"),
            default=default_weather_time,
        )
        resolved_clear_weather_time = _resolve_weather_duration(
            clear_weather_time,
            current_simple.get("clear_weather_time"),
            default=default_weather_time,
        )

        if raining:
            rain_time = resolved_rain_time
            clear_weather_time = 0
        else:
            rain_time = resolved_rain_time
            clear_weather_time = resolved_clear_weather_time

        if thundering:
            thunder_time = resolved_thunder_time
        else:
            thunder_time = resolved_thunder_time

        health = _parse_float_field(payload, "health", "Health", min_value=0.0, default=current_simple.get("health"))
        food_level = _parse_int_field(
            payload,
            "food_level",
            "Food Level",
            min_value=0,
            default=current_simple.get("food_level"),
        )
        food_saturation = _parse_float_field(
            payload,
            "food_saturation",
            "Food Saturation",
            min_value=0.0,
            default=current_simple.get("food_saturation"),
        )
        xp_level = _parse_int_field(payload, "xp_level", "XP Level", min_value=0, default=current_simple.get("xp_level"))
        xp_total = _parse_int_field(payload, "xp_total", "XP Total", min_value=0, default=current_simple.get("xp_total"))
        selected_item_slot = _parse_int_field(
            payload,
            "selected_item_slot",
            "Selected Item Slot",
            min_value=0,
            max_value=8,
            default=current_simple.get("selected_item_slot"),
        )
        player_x = _parse_float_field(payload, "player_x", "Player X", default=current_simple.get("player_x"))
        player_y = _parse_float_field(payload, "player_y", "Player Y", default=current_simple.get("player_y"))
        player_z = _parse_float_field(payload, "player_z", "Player Z", default=current_simple.get("player_z"))

        inventory_items = _parse_inventory_items(
            payload.get("inventory_items"),
            item_label="Inventory item",
            min_slot=-128,
            max_slot=127,
        )
        ender_items = _parse_inventory_items(payload.get("ender_items"), item_label="Ender chest item", max_slot=26)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    data_value = _ensure_compound_value(_ensure_root_value(root_tag), "Data")

    _set_compound_tag(data_value, "GameType", TAG_INT, game_mode)
    _set_compound_tag(data_value, "Difficulty", TAG_BYTE, difficulty)
    _set_compound_tag(
        data_value,
        "allowCommands",
        TAG_BYTE,
        1 if _parse_bool_field(payload, "allow_commands", bool(current_simple.get("allow_commands"))) else 0,
    )
    _set_compound_tag(
        data_value,
        "hardcore",
        TAG_BYTE,
        1 if _parse_bool_field(payload, "hardcore", bool(current_simple.get("hardcore"))) else 0,
    )
    _set_compound_tag(data_value, "raining", TAG_BYTE, 1 if raining else 0)
    _set_compound_tag(data_value, "thundering", TAG_BYTE, 1 if thundering else 0)
    _set_compound_tag(data_value, "Time", TAG_LONG, world_time or 0)
    _set_compound_tag(data_value, "DayTime", TAG_LONG, day_time if day_time is not None else (world_time or 0))
    _set_compound_tag(data_value, "rainTime", TAG_INT, rain_time or 0)
    _set_compound_tag(data_value, "thunderTime", TAG_INT, thunder_time or 0)
    _set_compound_tag(data_value, "clearWeatherTime", TAG_INT, clear_weather_time or 0)
    _set_compound_tag(data_value, "SpawnX", TAG_INT, spawn_x or 0)
    _set_compound_tag(data_value, "SpawnY", TAG_INT, spawn_y or 0)
    _set_compound_tag(data_value, "SpawnZ", TAG_INT, spawn_z or 0)

    wants_player_updates = any(
        key in payload
        for key in {
            "health",
            "food_level",
            "food_saturation",
            "xp_level",
            "xp_total",
            "selected_item_slot",
            "player_x",
            "player_y",
            "player_z",
            "inventory_items",
            "ender_items",
        }
    )
    player_value = _compound_tag_value(_compound_child(data_value, "Player"))
    if wants_player_updates and player_value is None:
        player_value = _ensure_compound_value(data_value, "Player")

    if isinstance(player_value, dict):
        if health is not None:
            _set_compound_tag(player_value, "Health", TAG_FLOAT, health)
        if food_level is not None:
            _set_compound_tag(player_value, "foodLevel", TAG_INT, food_level)
        if food_saturation is not None:
            _set_compound_tag(player_value, "foodSaturationLevel", TAG_FLOAT, food_saturation)
        if xp_level is not None:
            _set_compound_tag(player_value, "XpLevel", TAG_INT, xp_level)
        if xp_total is not None:
            _set_compound_tag(player_value, "XpTotal", TAG_INT, xp_total)
        if selected_item_slot is not None:
            _set_compound_tag(player_value, "SelectedItemSlot", TAG_INT, selected_item_slot)
        if any(key in payload for key in {"player_x", "player_y", "player_z"}):
            resolved_player_x = player_x if player_x is not None else 0.0
            resolved_player_y = player_y if player_y is not None else 0.0
            resolved_player_z = player_z if player_z is not None else 0.0
            _set_player_position(player_value, resolved_player_x, resolved_player_y, resolved_player_z)
        if inventory_items is not None:
            _set_player_inventory(player_value, inventory_items)
        if ender_items is not None:
            _set_player_ender_items(player_value, ender_items)

    save_ok, selected_player_id = _write_editor_root(loaded, root_tag, player_id=player_id)
    if not save_ok:
        return {"ok": False, "error": selected_player_id or "Failed to save world NBT data."}

    detail = get_world_detail(storage_target, world_id, custom_path=custom_path)
    if not detail.get("ok"):
        return {"ok": False, "error": detail.get("error") or "World NBT saved, but details could not be reloaded."}

    detail.update({
        "message": "World NBT updated successfully.",
        "selected_player_id": selected_player_id or editor_context.get("selected_player_id") or "",
    })
    return detail


def update_world_advanced_nbt(
    storage_target: str,
    world_id: str,
    *,
    custom_path: str = "",
    player_id: str = "",
    nbt_json: str = "",
) -> Dict[str, Any]:
    loaded = _load_world_nbt(storage_target, world_id, custom_path=custom_path)
    if not loaded.get("ok"):
        return {"ok": False, "error": loaded.get("error") or "Failed to load world NBT data."}

    try:
        parsed = json.loads(str(nbt_json or ""))
    except Exception as exc:
        return {"ok": False, "error": f"Invalid JSON: {exc}"}

    try:
        root_tag = _nbt_root_from_json_safe(parsed)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    save_ok, selected_player_id = _write_editor_root(loaded, root_tag, player_id=player_id)
    if not save_ok:
        return {"ok": False, "error": selected_player_id or "Failed to save world NBT data."}

    detail = get_world_detail(storage_target, world_id, custom_path=custom_path)
    if not detail.get("ok"):
        return {"ok": False, "error": detail.get("error") or "World NBT saved, but details could not be reloaded."}

    detail.update({
        "message": "World NBT updated successfully.",
        "selected_player_id": selected_player_id or player_id or "",
    })
    return detail


__all__ = [
    "get_world_nbt_editor",
    "update_world_simple_nbt",
    "update_world_advanced_nbt",
]
