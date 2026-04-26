from __future__ import annotations

import os
from typing import Any, Dict

from core import modloaders as core_modloaders
from core.discord_rpc import set_install_presence, set_launcher_presence
from core.settings import (
    normalize_custom_storage_directory,
    normalize_storage_directory_mode,
    validate_custom_storage_directory,
)
from core.version_manager import get_clients_dir

from server.api._constants import (
    CANCELLED_OPERATION_ERROR_MESSAGE,
    VALID_VERSION_STORAGE_OVERRIDE_MODES,
)
from server.api._state import STATE, CancelledOperationError


__all__ = [
    "_loader_display_name",
    "_parse_install_key",
    "_update_rpc_install_presence",
    "_read_data_ini_file",
    "_write_data_ini_file",
    "_is_path_within",
    "_resolve_version_dir_secure",
    "_normalize_version_storage_override_mode",
    "_sanitize_settings_payload",
    "_prepare_settings_response",
    "_is_enabled_setting",
    "_normalize_operation_id",
    "_begin_operation",
    "_cancel_operation_request",
    "_clear_operation",
    "_raise_if_operation_cancelled",
    "_is_legacy_family_category",
    "_is_non_crash_exit",
    "_version_identity_key",
    "_format_bytes",
    "_extract_category",
]


def _loader_display_name(loader_type: str) -> str:
    return core_modloaders.LOADER_DISPLAY_NAMES.get(
        loader_type, str(loader_type or "").capitalize()
    )


def _parse_install_key(version_key: str) -> Dict[str, Any]:
    parts = (version_key or "").split("/")
    if len(parts) >= 3 and parts[2].startswith("modloader-"):
        tail = parts[2][len("modloader-"):]
        loader_type = ""
        loader_version = ""
        if "-" in tail:
            loader_type, loader_version = tail.split("-", 1)
        else:
            loader_type = tail
        return {
            "category": parts[0],
            "folder": parts[1],
            "is_modloader": True,
            "loader_type": loader_type,
            "loader_version": loader_version,
        }

    if len(parts) >= 2:
        return {
            "category": parts[0],
            "folder": parts[1],
            "is_modloader": False,
            "loader_type": None,
            "loader_version": None,
        }

    return {
        "category": None,
        "folder": None,
        "is_modloader": False,
        "loader_type": None,
        "loader_version": None,
    }


def _update_rpc_install_presence(version_key: str, status: Dict[str, Any]) -> None:
    info = _parse_install_key(version_key)
    if not info.get("category") or not info.get("folder"):
        return

    state = str((status or {}).get("status") or "").lower()
    start_time = STATE.rpc_install_started_at.get(version_key)
    version_identifier = f"{info['category']}/{info['folder']}"

    if state in ("downloading", "installing", "starting", "paused"):
        set_install_presence(
            version_identifier,
            progress_percent=(status or {}).get("overall_percent"),
            start_time=start_time,
            loader_type=info.get("loader_type"),
            loader_version=info.get("loader_version"),
        )
        return

    if state in ("installed", "failed", "error", "cancelled"):
        STATE.rpc_install_started_at.pop(version_key, None)
        set_launcher_presence()


def _read_data_ini_file(path: str) -> Dict[str, str]:
    if not os.path.isfile(path):
        return {}

    data: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    except Exception:
        return {}

    return data


def _write_data_ini_file(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for k, v in (data or {}).items():
            f.write(f"{k}={v}\n")


def _is_path_within(root: str, target: str) -> bool:
    try:
        real_root = os.path.normcase(os.path.realpath(root))
        real_target = os.path.normcase(os.path.realpath(target))
        return os.path.commonpath([real_root, real_target]) == real_root
    except (OSError, ValueError):
        return False


def _resolve_version_dir_secure(category: str, folder: str) -> Dict[str, str]:
    clients_dir = get_clients_dir()
    matched_category = ""
    try:
        for cat_name in os.listdir(clients_dir):
            if str(cat_name).lower() == str(category).lower():
                matched_category = str(cat_name)
                break
    except Exception:
        matched_category = ""

    if not matched_category:
        matched_category = str(category).lower()

    version_dir = os.path.join(clients_dir, matched_category, folder)

    if not _is_path_within(clients_dir, version_dir):
        return {"ok": False, "error": "invalid version path", "path": ""}

    if not os.path.isdir(version_dir):
        return {"ok": False, "error": "version directory does not exist", "path": ""}

    return {"ok": True, "error": "", "path": version_dir}


def _normalize_version_storage_override_mode(value: Any) -> str:
    mode = str(value or "default").strip().lower()
    if mode in VALID_VERSION_STORAGE_OVERRIDE_MODES:
        return mode
    return "default"


def _sanitize_settings_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(data or {})
    sanitized.pop("custom_storage_directory_valid", None)
    sanitized.pop("custom_storage_directory_error", None)

    if "storage_directory" in sanitized:
        sanitized["storage_directory"] = normalize_storage_directory_mode(
            sanitized.get("storage_directory")
        )
    if "custom_storage_directory" in sanitized:
        sanitized["custom_storage_directory"] = normalize_custom_storage_directory(
            sanitized.get("custom_storage_directory")
        )
    return sanitized


def _prepare_settings_response(settings: Dict[str, Any]) -> Dict[str, Any]:
    prepared = dict(settings or {})
    prepared["storage_directory"] = normalize_storage_directory_mode(
        prepared.get("storage_directory")
    )
    prepared["custom_storage_directory"] = normalize_custom_storage_directory(
        prepared.get("custom_storage_directory")
    )

    storage_mode = prepared.get("storage_directory") or "global"
    validation = validate_custom_storage_directory(
        prepared.get("custom_storage_directory")
    )
    prepared["custom_storage_directory_valid"] = (
        storage_mode != "custom" or bool(validation.get("ok"))
    )
    prepared["custom_storage_directory_error"] = (
        ""
        if prepared["custom_storage_directory_valid"]
        else str(validation.get("error") or "Custom storage directory is invalid.")
    )
    return prepared


def _is_enabled_setting(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_operation_id(value: Any) -> str:
    return str(value or "").strip()[:128]


def _begin_operation(operation_id: Any) -> str:
    normalized = _normalize_operation_id(operation_id)
    if not normalized:
        return ""
    with STATE.operation_cancel_lock:
        STATE.operation_cancel_flags[normalized] = bool(
            STATE.operation_cancel_flags.get(normalized, False)
        )
    return normalized


def _cancel_operation_request(operation_id: Any) -> bool:
    normalized = _normalize_operation_id(operation_id)
    if not normalized:
        return False
    with STATE.operation_cancel_lock:
        STATE.operation_cancel_flags[normalized] = True
    return True


def _clear_operation(operation_id: Any) -> None:
    normalized = _normalize_operation_id(operation_id)
    if not normalized:
        return
    with STATE.operation_cancel_lock:
        STATE.operation_cancel_flags.pop(normalized, None)


def _raise_if_operation_cancelled(operation_id: Any) -> None:
    normalized = _normalize_operation_id(operation_id)
    if not normalized:
        return
    with STATE.operation_cancel_lock:
        cancelled = bool(STATE.operation_cancel_flags.get(normalized, False))
    if cancelled:
        raise CancelledOperationError(CANCELLED_OPERATION_ERROR_MESSAGE)


def _is_legacy_family_category(category: str) -> bool:
    c = str(category or "").strip().lower()
    if not c:
        return False

    legacy_tags = {"alpha", "beta", "classic", "indev", "infdev", "pre-classic", "preclassic"}
    return c in legacy_tags or (
        c.startswith("oa-") and any(tag in c for tag in legacy_tags)
    )


def _is_non_crash_exit(version_id: str, exit_code: int) -> bool:
    if exit_code == 0:
        return True

    category = (
        version_id.split("/", 1)[0].lower() if "/" in version_id else version_id.lower()
    )

    if _is_legacy_family_category(category) and exit_code == 1:
        return True

    if exit_code in (-1073741510, 130):
        return True

    return False


def _version_identity_key(category: Any, folder: Any) -> str:
    cat = str(category or "").strip().lower()
    fol = str(folder or "").strip().lower()
    return f"{cat}/{fol}"


def _format_bytes(bytes_size: int) -> str:
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} KB"
    elif bytes_size < 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_size / (1024 * 1024 * 1024):.2f} GB"


def _extract_category(path: str) -> str:
    parts = path.split("/api/versions", 1)[1].lstrip("/").split("/")
    return parts[0] if parts and parts[0] else None
