from __future__ import annotations

import configparser
import logging
import os
from typing import Any

from core.settings.defaults import (
    DEFAULTS,
    DEPRECATED_KEYS,
    all_default_keys,
    merged_defaults,
)
from core.settings.paths import (
    normalize_custom_storage_directory,
    normalize_storage_directory_mode,
)
from core.settings.profiles import get_settings_path

logger = logging.getLogger(__name__)

__all__ = [
    "load_global_settings",
    "load_version_data",
    "save_global_settings",
]


def _read_legacy_flat_ini(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                out[key.strip()] = value.strip()
    except OSError as e:
        logger.warning(f"Failed to parse legacy settings file: {e}")
    return out


def _normalise_loaded_dict(data: dict[str, Any]) -> dict[str, Any]:
    for deprecated in DEPRECATED_KEYS:
        data.pop(deprecated, None)

    merged: dict[str, Any] = merged_defaults()
    merged.update(data)
    merged["storage_directory"] = normalize_storage_directory_mode(merged.get("storage_directory"))
    merged["custom_storage_directory"] = normalize_custom_storage_directory(
        merged.get("custom_storage_directory")
    )
    return merged


def load_global_settings(profile_id: str | None = None) -> dict[str, Any]:
    path = get_settings_path(profile_id)
    data: dict[str, Any] = {}

    if os.path.exists(path):
        try:
            config = configparser.ConfigParser()
            config.read(path, encoding="utf-8")
            for section in config.sections():
                data.update(dict(config[section]))
        except (configparser.MissingSectionHeaderError, configparser.ParsingError):
            data = _read_legacy_flat_ini(path)
            if data:
                logger.info(f"Migrated legacy settings format from {path}")
        except (OSError, configparser.Error) as e:
            logger.warning(f"Failed to parse settings file, using defaults: {e}")
            data = {}

    return _normalise_loaded_dict(data)


def save_global_settings(
    settings_dict: dict[str, Any], profile_id: str | None = None
) -> None:
    path = get_settings_path(profile_id)
    current = load_global_settings(profile_id)
    current.update(settings_dict)
    current["storage_directory"] = normalize_storage_directory_mode(
        current.get("storage_directory")
    )
    current["custom_storage_directory"] = normalize_custom_storage_directory(
        current.get("custom_storage_directory")
    )

    config = configparser.ConfigParser()

    for section, defaults in DEFAULTS.items():
        config[section] = {key: str(current.get(key, defaults[key])) for key in defaults}

    extras = {k: v for k, v in current.items() if k not in all_default_keys()}
    if extras:
        if "launcher" not in config:
            config["launcher"] = {}
        for key, value in extras.items():
            config["launcher"][key] = str(value)

    os.makedirs(os.path.dirname(path), exist_ok=True)

    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            config.write(f)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def load_version_data(version_dir: str) -> dict[str, str] | None:
    data_path = os.path.join(version_dir, "data.ini")
    if not os.path.exists(data_path):
        return None

    data: dict[str, str] = {}
    try:
        with open(data_path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip()
    except OSError as e:
        logger.warning(f"Failed to read version data.ini at {data_path}: {e}")
        return None
    return data
