from __future__ import annotations

import os
import re

from core.logger import colorize_log
from core.settings import (
    clear_account_token,
    get_active_profile_id,
    list_profiles,
    load_global_settings,
    normalize_custom_storage_directory,
    save_global_settings,
    validate_custom_storage_directory,
)
from core.version_manager import scan_categories
from launcher.i18n import t

from server.api._constants import (
    MAX_STORAGE_OVERRIDE_PATH_LENGTH,
    MAX_VERSION_DISPLAY_NAME_LENGTH,
    MAX_VERSION_IMAGE_UPLOAD_BYTES,
    MAX_VERSION_IMAGE_URL_LENGTH,
    VALID_VERSION_STORAGE_OVERRIDE_MODES,
)
from server.api._helpers import (
    _normalize_version_storage_override_mode,
    _prepare_settings_response,
    _is_enabled_setting,
    _read_data_ini_file,
    _resolve_version_dir_secure,
    _sanitize_settings_payload,
    _write_data_ini_file,
)
from server.api._validation import (
    _validate_category_string,
    _validate_version_string,
)


__all__ = [
    "api_settings",
    "api_version_edit",
    "api_storage_directory_validate",
    "api_storage_directory_select",
]


_RAM_OVERRIDE_RE = re.compile(r"^\d+[KMGT]?$", re.IGNORECASE)


def _normalize_version_ram_override(value, field: str):
    raw = str(value or "").strip().upper()
    if not raw:
        return "", ""
    if len(raw) > 16 or not _RAM_OVERRIDE_RE.match(raw):
        return "", f"{field} must be a number with optional K, M, G, or T suffix"
    return raw, ""


def _normalize_version_resolution_override(value, field: str):
    raw = str(value or "").strip()
    if not raw:
        return "", ""
    if not raw.isdigit():
        return "", f"{field} must be a positive number"
    number = int(raw)
    if number < 1 or number > 99999:
        return "", f"{field} must be between 1 and 99999"
    return str(number), ""


def _normalize_version_fullscreen_override(value):
    raw = str(value or "").strip().lower()
    if raw in {"", "default"}:
        return "", ""
    if raw in {"1", "true", "yes", "on", "fullscreen"}:
        return "1", ""
    if raw in {"0", "false", "no", "off", "windowed"}:
        return "0", ""
    return "", "launch_fullscreen must be default, 1, or 0"


def _normalize_version_boolean_override(value, field: str):
    raw = str(value or "").strip().lower()
    if raw in {"", "default"}:
        return "", ""
    if raw in {"1", "true", "yes", "on", "enabled"}:
        return "1", ""
    if raw in {"0", "false", "no", "off", "disabled"}:
        return "0", ""
    return "", f"{field} must be default, 1, or 0"


def _normalize_single_line_override(value, field: str, max_len: int):
    raw = str(value or "").strip()
    if len(raw) > max_len:
        return "", f"{field} must be <= {max_len} characters"
    if "\n" in raw or "\r" in raw:
        return "", f"{field} must be a single-line value"
    return raw, ""


def api_settings(data):
    if not isinstance(data, dict):
        data = {}
    target_profile_id = str(data.get("_profile_id") or "").strip()
    if target_profile_id:
        profile_ids = {str(profile.get("id") or "") for profile in list_profiles()}
        if target_profile_id not in profile_ids:
            return {"ok": False, "error": "Settings profile not found."}
    data = dict(data)
    data.pop("_profile_id", None)
    data = _sanitize_settings_payload(data)

    active_profile_id = get_active_profile_id()
    profile_arg = target_profile_id or None
    target_is_active = not target_profile_id or target_profile_id == active_profile_id
    current = load_global_settings(profile_arg)
    prev_type = (current.get("account_type") or "Local").strip()

    current.update(data)
    save_global_settings(current, profile_arg)
    current = _prepare_settings_response(load_global_settings(profile_arg))

    if target_is_active and "discord_rpc_enabled" in data:
        try:
            from core import discord_rpc

            if _is_enabled_setting(current.get("discord_rpc_enabled")):
                discord_rpc.start_discord_rpc()
                discord_rpc.set_launcher_presence()
            else:
                discord_rpc.stop_discord_rpc()
        except Exception:
            pass

    new_type = (current.get("account_type") or "Local").strip()
    if prev_type.lower() != new_type.lower() and new_type.lower() == "local":
        try:
            clear_account_token(profile_arg)
        except Exception:
            pass

    if target_is_active and current.get("account_type") == "Histolauncher":
        username = data.get("username") or current.get("username") or "(from session token)"
        uuid = data.get("uuid") or current.get("uuid") or "(from session token)"
        print(colorize_log(
            f"[api_settings] Histolauncher account configured: username={username}, uuid={uuid}"
        ))

    return {"ok": True, "message": "Settings saved.", "settings": current}


def api_version_edit(data):
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid request"}

    category = str(data.get("category") or "").strip()
    folder = str(data.get("folder") or "").strip()

    if not category or not folder:
        return {"ok": False, "error": "missing category or folder"}
    if not _validate_category_string(category):
        return {"ok": False, "error": "invalid category format"}
    if not _validate_version_string(folder):
        return {"ok": False, "error": "invalid folder format"}

    resolved = _resolve_version_dir_secure(category, folder)
    if not resolved.get("ok"):
        return {"ok": False, "error": resolved.get("error") or "invalid version path"}

    version_dir = resolved.get("path") or ""
    data_ini_path = os.path.join(version_dir, "data.ini")
    if not os.path.isfile(data_ini_path):
        return {"ok": False, "error": "Version metadata file not found (data.ini)."}

    existing_data = _read_data_ini_file(data_ini_path)
    custom_display_path = os.path.join(version_dir, "custom_display.png")
    reset_all = str(data.get("reset_all") or "").strip().lower() in {"1", "true", "yes", "on"}

    display_name = ""
    image_url = ""
    image_upload_bytes = None
    storage_override_mode = "default"
    storage_override_path = ""
    launch_min_ram = ""
    launch_max_ram = ""
    launch_extra_jvm_args = ""
    launch_java_path = ""
    launch_resolution_width = ""
    launch_resolution_height = ""
    launch_fullscreen = ""
    launch_demo = ""

    if not reset_all:
        display_name = str(data.get("display_name") or "").strip()
        if len(display_name) > MAX_VERSION_DISPLAY_NAME_LENGTH:
            return {
                "ok": False,
                "error": f"display_name must be <= {MAX_VERSION_DISPLAY_NAME_LENGTH} characters",
            }

        image_url = str(data.get("image_url") or "").strip()
        if len(image_url) > MAX_VERSION_IMAGE_URL_LENGTH:
            return {
                "ok": False,
                "error": f"image_url must be <= {MAX_VERSION_IMAGE_URL_LENGTH} characters",
            }
        if "\n" in image_url or "\r" in image_url:
            return {"ok": False, "error": "image_url must be a single-line value"}

        image_upload_data = data.get("image_data")
        if image_upload_data:
            try:
                import base64

                image_upload_bytes = base64.b64decode(str(image_upload_data), validate=True)
            except Exception:
                return {"ok": False, "error": "image_data must be valid base64 image data"}

            if not image_upload_bytes:
                return {"ok": False, "error": "image_data is empty"}
            if len(image_upload_bytes) > MAX_VERSION_IMAGE_UPLOAD_BYTES:
                return {
                    "ok": False,
                    "error": f"image_data exceeds max size ({MAX_VERSION_IMAGE_UPLOAD_BYTES} bytes)",
                }

        raw_mode = data.get("storage_override_mode")
        if (
            raw_mode is not None
            and str(raw_mode).strip().lower() not in VALID_VERSION_STORAGE_OVERRIDE_MODES
        ):
            return {
                "ok": False,
                "error": "storage_override_mode must be one of: default, global, version, custom",
            }
        storage_override_mode = _normalize_version_storage_override_mode(
            raw_mode if raw_mode is not None else existing_data.get("storage_override_mode")
        )

        storage_override_path = str(data.get("storage_override_path") or "").strip()
        if len(storage_override_path) > MAX_STORAGE_OVERRIDE_PATH_LENGTH:
            return {
                "ok": False,
                "error": (
                    f"storage_override_path must be <= "
                    f"{MAX_STORAGE_OVERRIDE_PATH_LENGTH} characters"
                ),
            }

        if storage_override_mode == "custom":
            validation = validate_custom_storage_directory(storage_override_path)
            if not validation.get("ok"):
                return {
                    "ok": False,
                    "error": validation.get("error") or "Custom storage directory is invalid.",
                }
            storage_override_path = validation.get("path") or storage_override_path
        else:
            storage_override_path = ""

        launch_min_ram, error = _normalize_version_ram_override(
            data.get("launch_min_ram"), "launch_min_ram"
        )
        if error:
            return {"ok": False, "error": error}

        launch_max_ram, error = _normalize_version_ram_override(
            data.get("launch_max_ram"), "launch_max_ram"
        )
        if error:
            return {"ok": False, "error": error}

        launch_resolution_width, error = _normalize_version_resolution_override(
            data.get("launch_resolution_width"), "launch_resolution_width"
        )
        if error:
            return {"ok": False, "error": error}

        launch_resolution_height, error = _normalize_version_resolution_override(
            data.get("launch_resolution_height"), "launch_resolution_height"
        )
        if error:
            return {"ok": False, "error": error}

        launch_fullscreen, error = _normalize_version_fullscreen_override(
            data.get("launch_fullscreen")
        )
        if error:
            return {"ok": False, "error": error}

        launch_demo, error = _normalize_version_boolean_override(
            data.get("launch_demo"), "launch_demo"
        )
        if error:
            return {"ok": False, "error": error}

        launch_extra_jvm_args, error = _normalize_single_line_override(
            data.get("launch_extra_jvm_args"), "launch_extra_jvm_args", 2048
        )
        if error:
            return {"ok": False, "error": error}

        launch_java_path, error = _normalize_single_line_override(
            data.get("launch_java_path"), "launch_java_path", 500
        )
        if error:
            return {"ok": False, "error": error}

    if display_name:
        existing_data["display_name"] = display_name
    else:
        existing_data.pop("display_name", None)

    if reset_all:
        existing_data.pop("image_url", None)
        try:
            if os.path.isfile(custom_display_path):
                os.remove(custom_display_path)
        except Exception as e:
            return {"ok": False, "error": f"Failed to remove custom display image: {e}"}
    elif image_upload_bytes is not None:
        try:
            with open(custom_display_path, "wb") as f:
                f.write(image_upload_bytes)
        except Exception as e:
            return {"ok": False, "error": f"Failed to save uploaded image: {e}"}
        existing_data.pop("image_url", None)
    elif image_url:
        existing_data["image_url"] = image_url
        try:
            if os.path.isfile(custom_display_path):
                os.remove(custom_display_path)
        except Exception as e:
            return {"ok": False, "error": f"Failed to remove custom display image: {e}"}
    else:
        existing_data.pop("image_url", None)

    if reset_all:
        existing_data.pop("storage_override_mode", None)
        existing_data.pop("storage_override_path", None)
    else:
        existing_data["storage_override_mode"] = storage_override_mode
        if storage_override_mode == "custom":
            existing_data["storage_override_path"] = storage_override_path
        else:
            existing_data.pop("storage_override_path", None)

    launch_override_values = {
        "launch_min_ram": launch_min_ram,
        "launch_max_ram": launch_max_ram,
        "launch_extra_jvm_args": launch_extra_jvm_args,
        "launch_java_path": launch_java_path,
        "launch_resolution_width": launch_resolution_width,
        "launch_resolution_height": launch_resolution_height,
        "launch_fullscreen": launch_fullscreen,
        "launch_demo": launch_demo,
    }
    for launch_key, launch_value in launch_override_values.items():
        if reset_all or not launch_value:
            existing_data.pop(launch_key, None)
        else:
            existing_data[launch_key] = launch_value

    if not str(existing_data.get("category") or "").strip():
        existing_data["category"] = category

    try:
        _write_data_ini_file(data_ini_path, existing_data)
    except Exception as e:
        return {"ok": False, "error": f"Failed to save version metadata: {e}"}

    categories = scan_categories(force_refresh=True)
    updated_version = None
    for item in categories.get("* All", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("folder") or "") != folder:
            continue
        if str(item.get("category") or "").lower() != category.lower():
            continue
        updated_version = item
        break

    if updated_version is None:
        updated_version = {
            "category": category,
            "folder": folder,
            "display_name": display_name or folder,
            "display_name_override": display_name,
            "image_url": str(existing_data.get("image_url") or ""),
            "storage_override_mode": storage_override_mode,
            "storage_override_path": storage_override_path,
            **launch_override_values,
        }

    return {
        "ok": True,
        "message": "Version settings saved.",
        "version": updated_version,
    }


def api_storage_directory_validate(data):
    if not isinstance(data, dict):
        data = {}

    validation = validate_custom_storage_directory(data.get("path"))
    return {
        "ok": bool(validation.get("ok")),
        "path": validation.get("path") or "",
        "error": validation.get("error") or "",
    }


def api_storage_directory_select(data):
    if not isinstance(data, dict):
        data = {}

    current_settings = load_global_settings() or {}
    save_to_settings = (
        str(data.get("save_to_settings") or "").strip().lower()
        not in {"0", "false", "no", "off"}
    )
    current_path = normalize_custom_storage_directory(
        data.get("current_path") or current_settings.get("custom_storage_directory")
    )
    root = None

    try:
        from tkinter import Tk
        from tkinter.filedialog import askdirectory

        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        initialdir = current_path if os.path.isdir(current_path) else os.path.expanduser("~")
        selected_path = askdirectory(
            initialdir=initialdir,
            title=t("native.fileDialogs.customStorageTitle"),
            mustexist=True,
        )
    except Exception as e:
        print(colorize_log(f"[api] Failed to open custom storage directory picker: {e}"))
        return {"ok": False, "error": f"Failed to open folder picker: {e}"}
    finally:
        try:
            if root is not None:
                root.destroy()
        except Exception:
            pass

    if not selected_path:
        return {"ok": False, "cancelled": True, "path": current_path}

    normalized_path = normalize_custom_storage_directory(selected_path)
    validation = validate_custom_storage_directory(normalized_path)
    if not validation.get("ok"):
        return {
            "ok": False,
            "path": validation.get("path") or normalized_path,
            "error": validation.get("error") or "Selected folder is invalid.",
        }

    if not save_to_settings:
        return {"ok": True, "path": validation.get("path") or normalized_path}

    save_global_settings({"custom_storage_directory": normalized_path})
    settings_dict = _prepare_settings_response(load_global_settings())
    return {
        "ok": True,
        "path": settings_dict.get("custom_storage_directory", ""),
        "settings": settings_dict,
    }
