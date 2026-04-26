from __future__ import annotations

import os

from core.logger import colorize_log
from core.settings import (
    get_default_minecraft_dir,
    get_versions_profile_dir,
    normalize_storage_directory_mode,
    validate_custom_storage_directory,
)

__all__ = [
    "_ensure_neoforge_early_window_disabled",
    "_extract_mc_version_string",
    "_load_data_ini",
    "_read_version_data_ini",
    "_resolve_game_dir",
    "_resolve_game_dir_with_error",
    "_resolve_version_dir",
]


def _extract_mc_version_string(version_identifier):
    if "/" in version_identifier:
        _, base = version_identifier.split("/", 1)
    else:
        base = version_identifier
    return base.split("-", 1)[0]


def _resolve_version_dir(version_identifier):
    clients_dir = get_versions_profile_dir()
    if "/" in version_identifier:
        parts = version_identifier.replace("\\", "/").split("/", 1)
        category, folder = parts[0], parts[1]

        for cat in os.listdir(clients_dir):
            if cat.lower() == category.lower():
                candidate = os.path.join(clients_dir, cat, folder)
                if os.path.isdir(candidate):
                    return candidate
        return os.path.join(clients_dir, category, folder)

    for cat in os.listdir(clients_dir):
        candidate = os.path.join(clients_dir, cat, version_identifier)
        if os.path.isdir(candidate):
            return candidate
    return None


def _read_version_data_ini(version_dir: str) -> dict:
    data: dict = {}
    if not version_dir:
        return data

    data_ini_path = os.path.join(version_dir, "data.ini")
    if not os.path.isfile(data_ini_path):
        return data

    try:
        with open(data_ini_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip()
    except Exception:
        return {}

    return data


def _resolve_game_dir_with_error(global_settings, version_dir):
    version_meta = _read_version_data_ini(version_dir)
    override_mode = str(version_meta.get("storage_override_mode") or "default").strip().lower()
    if override_mode not in ("default", "global", "version", "custom"):
        override_mode = "default"

    if override_mode == "custom":
        validation = validate_custom_storage_directory(
            version_meta.get("storage_override_path")
        )
        if validation.get("ok"):
            return (validation.get("path") or "", "")
        return (
            "",
            validation.get("error") or "Version custom storage directory is invalid.",
        )
    if override_mode == "global":
        return (get_default_minecraft_dir(), "")
    if override_mode == "version":
        return (os.path.join(version_dir, "data"), "")

    storage_mode = normalize_storage_directory_mode(
        (global_settings or {}).get("storage_directory", "global")
    )
    if storage_mode == "version":
        return (os.path.join(version_dir, "data"), "")
    if storage_mode == "custom":
        validation = validate_custom_storage_directory(
            (global_settings or {}).get("custom_storage_directory")
        )
        if validation.get("ok"):
            return (validation.get("path") or "", "")
        return ("", validation.get("error") or "Custom storage directory is invalid.")

    return (get_default_minecraft_dir(), "")


def _resolve_game_dir(global_settings, version_dir):
    game_dir, _error = _resolve_game_dir_with_error(global_settings, version_dir)
    return game_dir


def _load_data_ini(version_dir):
    data_ini = os.path.join(version_dir, "data.ini")
    if not os.path.exists(data_ini):
        return {}
    meta: dict = {}
    with open(data_ini, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                meta[k.strip()] = v.strip()
    return meta


def _ensure_neoforge_early_window_disabled(game_dir: str) -> None:
    if not game_dir:
        return

    config_dir = os.path.join(game_dir, "config")
    config_path = os.path.join(config_dir, "fml.toml")
    target_key = "earlyWindowControl"
    target_line = f"{target_key} = false"
    comment_line = (
        "# Shows an early loading screen for mod loading which improves the user "
        "experience with early feedback about mod loading."
    )

    try:
        os.makedirs(config_dir, exist_ok=True)
    except Exception:
        return

    lines: list[str] = []
    changed = False
    found = False

    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except Exception as e:
            print(colorize_log(f"[launcher] Warning: Could not read NeoForge config file: {e}"))
            return

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith(target_key):
                continue
            found = True
            if stripped != target_line:
                lines[idx] = target_line
                changed = True
            break

        if not found:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(comment_line)
            lines.append(target_line)
            changed = True
    else:
        lines = [comment_line, target_line]
        changed = True

    if not changed:
        return

    tmp_path = config_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8", errors="replace", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp_path, config_path)
        print(colorize_log("[launcher] Applied NeoForge workaround: earlyWindowControl=false"))
    except Exception as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        print(colorize_log(f"[launcher] Warning: Could not update NeoForge config file: {e}"))
