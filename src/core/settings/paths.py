from __future__ import annotations

import os
import platform
from typing import Any

from core.settings.defaults import VALID_STORAGE_DIRECTORY_MODES

__all__ = [
    "get_base_dir",
    "get_default_minecraft_dir",
    "get_profiles_root_dir",
    "get_profiles_settings_dir",
    "get_profiles_meta_path",
    "normalize_custom_storage_directory",
    "normalize_storage_directory_mode",
    "validate_custom_storage_directory",
]


def get_base_dir() -> str:
    user = os.path.expanduser("~")
    base = os.path.join(user, ".histolauncher")
    os.makedirs(base, exist_ok=True)
    return base


def get_default_minecraft_dir() -> str:
    system = platform.system().lower()
    if "windows" in system:
        appdata = os.environ.get("APPDATA")
        if appdata:
            return os.path.join(appdata, ".minecraft")
    return os.path.expanduser(os.path.join("~", ".minecraft"))


def get_profiles_root_dir() -> str:
    return os.path.join(get_base_dir(), "profiles")


def get_profiles_settings_dir() -> str:
    path = os.path.join(get_profiles_root_dir(), "settings")
    os.makedirs(path, exist_ok=True)
    return path


def get_profiles_meta_path() -> str:
    return os.path.join(get_profiles_settings_dir(), "profiles.json")


def normalize_storage_directory_mode(value: Any) -> str:
    mode = str(value or "global").strip().lower()
    if mode in VALID_STORAGE_DIRECTORY_MODES:
        return mode
    return "global"


def normalize_custom_storage_directory(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return os.path.abspath(os.path.expanduser(raw))


def validate_custom_storage_directory(value: Any) -> dict[str, Any]:
    normalized = normalize_custom_storage_directory(value)
    if not normalized:
        return {
            "ok": False,
            "path": "",
            "error": "Custom storage directory is not set. Select a folder before launching.",
        }
    if not os.path.exists(normalized):
        return {
            "ok": False,
            "path": normalized,
            "error": (
                "Custom storage directory does not exist anymore. "
                "Select another folder or restore it."
            ),
        }
    if not os.path.isdir(normalized):
        return {
            "ok": False,
            "path": normalized,
            "error": "Custom storage directory is not a folder. Select a valid folder before launching.",
        }
    return {"ok": True, "path": normalized, "error": ""}
