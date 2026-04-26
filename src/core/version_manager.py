from __future__ import annotations

import configparser
import io
import os
import time
from typing import Any, Final

from core.constants import VERSION_SCAN_CACHE_TTL_S

__all__ = [
    "SUPPORTED_MODLOADER_TYPES",
    "ensure_loaders_dir",
    "get_clients_dir",
    "get_loaders_dir",
    "get_version_loaders",
    "scan_categories",
]


SUPPORTED_MODLOADER_TYPES: Final[tuple[str, ...]] = (
    "fabric",
    "babric",
    "forge",
    "modloader",
    "neoforge",
    "quilt",
)

_VALID_STORAGE_OVERRIDE_MODES: Final[frozenset[str]] = frozenset(
    {"default", "global", "version", "custom"}
)

_cache: dict[str, list[dict[str, Any]]] | None = None
_cache_ts: float = 0.0


def _settings():
    from core import settings  # noqa: PLC0415

    return settings


def get_clients_dir() -> str:
    return _settings().get_versions_profile_dir()


def _read_data_ini(path: str) -> dict[str, str]:
    if not os.path.exists(path):
        return {}

    try:
        with open(path, encoding="utf-8") as fp:
            raw = fp.read()
    except OSError:
        return {}

    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str  # keep original case
    try:
        parser.read_string("[__root__]\n" + raw, source=path)
    except configparser.Error:
        return _read_data_ini_legacy(io.StringIO(raw))
    return {k: v.strip() for k, v in parser["__root__"].items()}


def _read_data_ini_legacy(stream: io.StringIO) -> dict[str, str]:
    cfg: dict[str, str] = {}
    for raw_line in stream:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        cfg[key.strip()] = value.strip()
    return cfg


def _scan_loaders_in_version(version_path: str) -> dict[str, list[dict[str, Any]]]:
    loaders_dir = os.path.join(version_path, "loaders")
    result: dict[str, list[dict[str, Any]]] = {lt: [] for lt in SUPPORTED_MODLOADER_TYPES}

    if not os.path.isdir(loaders_dir):
        return result

    for loader_type in SUPPORTED_MODLOADER_TYPES:
        type_dir = os.path.join(loaders_dir, loader_type)
        if not os.path.isdir(type_dir):
            continue

        try:
            entries = os.listdir(type_dir)
        except OSError:
            continue

        for version_folder in entries:
            version_path_full = os.path.join(type_dir, version_folder)
            if not os.path.isdir(version_path_full):
                continue

            jars: list[str] = []
            for root, _, files in os.walk(version_path_full):
                for file_name in files:
                    if file_name.endswith(".jar"):
                        jars.append(
                            os.path.relpath(
                                os.path.join(root, file_name),
                                version_path_full,
                            )
                        )
            if jars:
                result[loader_type].append(
                    {
                        "type": loader_type,
                        "version": version_folder,
                        "folder": os.path.relpath(version_path_full, version_path),
                        "jars": jars,
                    }
                )

    return result


def _parse_launch_disabled(raw: str) -> tuple[bool, str]:
    if not raw:
        return False, ""
    parts = raw.split(",", 1)
    flag = parts[0].strip().lower() in ("1", "true", "yes")
    message = ""
    if len(parts) > 1:
        message = parts[1].strip()
        if (message.startswith('"') and message.endswith('"')) or (
            message.startswith("'") and message.endswith("'")
        ):
            message = message[1:-1]
    return flag, message


def _build_version_entry(
    *, base_dir: str, category: str, version: str, vpath: str
) -> dict[str, Any]:
    meta = _read_data_ini(os.path.join(vpath, "data.ini"))

    display_override = (meta.get("display_name") or "").strip()
    storage_mode = (meta.get("storage_override_mode") or "default").strip().lower()
    if storage_mode not in _VALID_STORAGE_OVERRIDE_MODES:
        storage_mode = "default"

    try:
        total_size_bytes = int(meta.get("total_size_bytes", "0"))
    except (TypeError, ValueError):
        total_size_bytes = 0

    launch_disabled, launch_disabled_message = _parse_launch_disabled(
        meta.get("launch_disabled", "").strip()
    )

    classpath = meta.get("classpath") or "client.jar"
    return {
        "folder": version,
        "display_name": display_override or version,
        "display_name_override": display_override,
        "image_url": (meta.get("image_url") or "").strip(),
        "main_class": meta.get("main_class") or "net.minecraft.client.Minecraft",
        "classpath": [p.strip() for p in classpath.split(",") if p.strip()],
        "native_subfolder": meta.get("native_subfolder") or "",
        "path": os.path.relpath(vpath, base_dir),
        "category": category,
        "storage_override_mode": storage_mode,
        "storage_override_path": (meta.get("storage_override_path") or "").strip(),
        "launch_disabled": launch_disabled,
        "launch_disabled_message": launch_disabled_message,
        "total_size_bytes": total_size_bytes,
        "full_assets": meta.get("full_assets", "true").lower() == "true",
        "loaders": _scan_loaders_in_version(vpath),
        "is_imported": meta.get("imported", "").lower() == "true",
    }


def _scan_once() -> dict[str, list[dict[str, Any]]]:
    clients_dir = get_clients_dir()
    results: dict[str, list[dict[str, Any]]] = {}
    if not os.path.isdir(clients_dir):
        return results

    base_dir = _settings().get_base_dir()

    for raw_category in sorted(os.listdir(clients_dir)):
        cat_path = os.path.join(clients_dir, raw_category)
        if not os.path.isdir(cat_path):
            continue

        category = raw_category.strip()
        versions = results.setdefault(category, [])

        for version in sorted(os.listdir(cat_path)):
            vpath = os.path.join(cat_path, version)
            if not os.path.isdir(vpath) or not os.path.exists(os.path.join(vpath, "data.ini")):
                continue
            versions.append(
                _build_version_entry(
                    base_dir=base_dir, category=category, version=version, vpath=vpath
                )
            )

    all_versions: list[dict[str, Any]] = []
    for vers in results.values():
        all_versions.extend(vers)
    all_versions.sort(key=lambda v: (v.get("category", ""), v.get("folder", "")))
    results["* All"] = all_versions
    return results


def scan_categories(force_refresh: bool = False) -> dict[str, list[dict[str, Any]]]:
    global _cache, _cache_ts

    now = time.time()
    if force_refresh or _cache is None or (now - _cache_ts) > VERSION_SCAN_CACHE_TTL_S:
        _cache = _scan_once()
        _cache_ts = now
    return _cache or {}


def get_version_loaders(category: str, folder: str) -> dict[str, list[dict[str, Any]]]:
    empty: dict[str, list[dict[str, Any]]] = {lt: [] for lt in SUPPORTED_MODLOADER_TYPES}
    for v in scan_categories().get(category, []):
        if v.get("folder") != folder:
            continue
        loaders = v.get("loaders")
        if not isinstance(loaders, dict):
            return empty
        for loader_type in SUPPORTED_MODLOADER_TYPES:
            loaders.setdefault(loader_type, [])
        return loaders
    return empty


def get_loaders_dir(category: str, folder: str) -> str:
    clients_dir = get_clients_dir()
    for cat in os.listdir(clients_dir):
        if cat.lower() == category.lower():
            candidate = os.path.join(clients_dir, cat, folder)
            if os.path.isdir(candidate):
                return os.path.join(candidate, "loaders")
    return os.path.join(clients_dir, category.lower(), folder, "loaders")


def ensure_loaders_dir(category: str, folder: str) -> str:
    loaders_dir = get_loaders_dir(category, folder)
    os.makedirs(loaders_dir, exist_ok=True)
    return loaders_dir
