from __future__ import annotations

import os
import shutil
import threading
import time
from typing import Any

from core.downloader.installers.loaders import dispatch as core_downloader
from core import modloaders as core_modloaders
from core.discord_rpc import set_install_presence
from core.logger import colorize_log
from core.notifications import send_desktop_notification
from core.version_manager import get_clients_dir, get_version_loaders, scan_categories

from server.api._constants import (
    FORGE_INSTALL_BLOCKED_VERSIONS,
    MAX_LOADER_VERSION_LENGTH,
    VALID_LOADER_TYPES,
)
from server.api._helpers import (
    _format_bytes,
    _loader_display_name,
    _resolve_version_dir_secure,
)
from server.api._state import STATE
from server.api._validation import (
    _validate_category_string,
    _validate_loader_type,
    _validate_version_string,
)


__all__ = [
    "_get_available_loader_catalog",
    "api_loaders",
    "api_loaders_installed",
    "api_install_loader",
    "api_delete_loader",
]


def _get_available_loader_catalog(folder: str):
    fabric_loaders = core_modloaders.get_fabric_loaders_for_version(folder, stable_only=False)
    babric_loaders = core_modloaders.get_babric_loaders_for_version(folder, stable_only=False)
    forge_versions = core_modloaders.get_forge_versions_for_mc(folder)
    modloader_versions = core_modloaders.get_modloader_versions_for_mc(folder)
    quilt_loaders = core_modloaders.get_quilt_loaders_for_version(folder, stable_only=False)
    neoforge_versions = core_modloaders.get_neoforge_versions_for_mc(folder)

    if folder in FORGE_INSTALL_BLOCKED_VERSIONS:
        forge_versions = []

    available = {
        "fabric": [
            {"version": loader.get("version"), "stable": loader.get("stable", False)}
            for loader in fabric_loaders
            if loader.get("version")
        ],
        "babric": [
            {"version": loader.get("version"), "stable": loader.get("stable", False)}
            for loader in babric_loaders
            if loader.get("version")
        ],
        "forge": [
            {"version": fv.get("forge_version")}
            for fv in forge_versions
            if fv.get("forge_version")
        ],
        "modloader": [
            {"version": ml.get("modloader_version"), "stable": True}
            for ml in modloader_versions
            if ml.get("modloader_version")
        ],
        "quilt": [
            {"version": loader.get("version"), "stable": loader.get("stable", False)}
            for loader in quilt_loaders
            if loader.get("version")
        ],
        "neoforge": [
            {"version": nf.get("neoforge_version"), "stable": nf.get("stable", False)}
            for nf in neoforge_versions
            if nf.get("neoforge_version")
        ],
    }
    total_available = {loader_type: len(entries) for loader_type, entries in available.items()}
    return available, total_available


def api_loaders(version_key: str):
    if not version_key or "/" not in version_key:
        return {"ok": False, "error": "invalid version key"}

    parts = version_key.split("/", 1)
    category_input, folder = parts[0], parts[1]

    categories_data = scan_categories(force_refresh=True)

    category = None
    for cat_name in categories_data.keys():
        if cat_name.lower() == category_input.lower():
            category = cat_name
            break

    if not category:
        return {"ok": False, "error": f"category not found: {category_input}"}

    installed = get_version_loaders(category, folder)

    loaders_base = os.path.join(get_clients_dir(), category, folder, "loaders")

    for loader_type in installed:
        for loader in installed[loader_type]:
            loader_path = os.path.join(loaders_base, loader_type, loader["version"])
            total_size = 0
            if os.path.isdir(loader_path):
                for root, dirs, files in os.walk(loader_path):
                    for fname in files:
                        try:
                            total_size += os.path.getsize(os.path.join(root, fname))
                        except Exception:
                            pass
            loader["size"] = total_size
            loader["size_display"] = _format_bytes(total_size)

    available, total_available = _get_available_loader_catalog(folder)

    return {
        "ok": True,
        "version_key": version_key,
        "installed": installed,
        "available": available,
        "total_available": total_available,
    }


def api_loaders_installed(version_key: str):
    if not version_key or "/" not in version_key:
        return {"ok": False, "error": "invalid version key"}

    parts = version_key.split("/", 1)
    category_input, folder = parts[0], parts[1]

    resolved = _resolve_version_dir_secure(category_input, folder)
    if not resolved.get("ok"):
        return {
            "ok": False,
            "error": resolved.get("error") or "version directory does not exist",
            "installed": {},
        }

    version_dir = resolved.get("path") or ""
    loaders_dir = os.path.join(version_dir, "loaders")

    installed = {loader_type: [] for loader_type in VALID_LOADER_TYPES}
    if os.path.isdir(loaders_dir):
        for loader_type in VALID_LOADER_TYPES:
            type_dir = os.path.join(loaders_dir, loader_type)
            if not os.path.isdir(type_dir):
                continue

            try:
                versions = sorted(os.listdir(type_dir))
            except Exception:
                continue

            for ver in versions:
                ver_dir = os.path.join(type_dir, ver)
                if not os.path.isdir(ver_dir):
                    continue
                installed[loader_type].append({"type": loader_type, "version": ver})

    return {
        "ok": True,
        "version_key": version_key,
        "installed": installed,
    }


def api_install_loader(data: Any):
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid request"}

    category = (data.get("category") or "").strip()
    folder = (data.get("folder") or "").strip()
    loader_type = (data.get("loader_type") or "").lower().strip()
    loader_version = (data.get("loader_version") or "").strip()

    if not all([category, folder, loader_type, loader_version]):
        return {"ok": False, "error": "missing required fields"}

    if not _validate_category_string(category):
        return {"ok": False, "error": "invalid category format"}

    if not _validate_version_string(folder):
        return {"ok": False, "error": "invalid folder format"}

    if not _validate_loader_type(loader_type):
        return {"ok": False, "error": "invalid loader type"}

    if not _validate_version_string(loader_version, MAX_LOADER_VERSION_LENGTH):
        return {"ok": False, "error": "invalid loader version format"}

    if loader_type == "forge" and folder in FORGE_INSTALL_BLOCKED_VERSIONS:
        return {
            "ok": False,
            "error": (
                f"Forge installation is disabled for Minecraft {folder}. "
                "These legacy Forge builds are ModLoader addons and are not supported "
                "by automatic Forge installation."
            ),
        }

    available_catalog, _ = _get_available_loader_catalog(folder)
    available_versions = {
        str(entry.get("version")).strip()
        for entry in available_catalog.get(loader_type, [])
        if str(entry.get("version") or "").strip()
    }
    if loader_version not in available_versions:
        return {
            "ok": False,
            "error": (
                f"{_loader_display_name(loader_type)} {loader_version} is not available "
                f"for Minecraft {folder}."
            ),
        }

    install_key = f"{category.lower()}/{folder}/modloader-{loader_type}-{loader_version}"

    with STATE.loader_install_lock:
        if install_key in STATE.active_loader_install_keys:
            return {
                "ok": True,
                "install_key": install_key,
                "loader_type": loader_type,
                "loader_version": loader_version,
                "message": f"{_loader_display_name(loader_type)} {loader_version} is already installing...",
                "already_running": True,
            }
        STATE.active_loader_install_keys.add(install_key)

    STATE.rpc_install_started_at[install_key] = time.time()
    set_install_presence(
        f"{category}/{folder}",
        start_time=STATE.rpc_install_started_at[install_key],
        loader_type=loader_type,
        loader_version=loader_version,
    )

    def install_loader_background():
        try:
            result = core_downloader.download_loader(
                loader_type=loader_type,
                mc_version=folder,
                loader_version=loader_version,
                category=category,
                folder=folder,
            )

            if result.get("ok"):
                scan_categories(force_refresh=True)

                try:
                    loader_name = _loader_display_name(loader_type)
                    send_desktop_notification(
                        title=f"[{loader_name} {loader_version}] Mod Loader Installation complete!",
                        message=(
                            f"{loader_name} {loader_version} for {category} {folder} "
                            "has installed successfully!"
                        ),
                    )
                except Exception as e:
                    print(colorize_log(f"[api] Could not send notification: {e}"))

                print(colorize_log(
                    f"[api] {_loader_display_name(loader_type)} {loader_version} "
                    f"installed successfully for {install_key}"
                ))
            else:
                error_msg = result.get("error", "Unknown error")
                print(colorize_log(f"[api] Failed to install {loader_type} loader: {error_msg}"))
        except Exception as e:
            print(colorize_log(f"[api] Exception during loader installation: {e}"))
        finally:
            with STATE.loader_install_lock:
                STATE.active_loader_install_keys.discard(install_key)

    thread = threading.Thread(target=install_loader_background, daemon=True)
    thread.start()

    return {
        "ok": True,
        "install_key": install_key,
        "loader_type": loader_type,
        "loader_version": loader_version,
        "message": f"Installing {_loader_display_name(loader_type)} {loader_version}...",
    }


def api_delete_loader(data: Any):
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid request"}

    category = (data.get("category") or "").strip()
    folder = (data.get("folder") or "").strip()
    loader_type = (data.get("loader_type") or "").lower().strip()
    loader_version = (data.get("loader_version") or "").strip()

    if not all([category, folder, loader_type, loader_version]):
        return {"ok": False, "error": "missing required fields"}

    if not _validate_category_string(category):
        return {"ok": False, "error": "invalid category format"}

    if not _validate_version_string(folder):
        return {"ok": False, "error": "invalid folder format"}

    if not _validate_loader_type(loader_type):
        return {"ok": False, "error": "invalid loader type"}

    if not _validate_version_string(loader_version, MAX_LOADER_VERSION_LENGTH):
        return {"ok": False, "error": "invalid loader version format"}

    try:
        loader_path = os.path.join(
            get_clients_dir(), category, folder, "loaders", loader_type, loader_version
        )

        if not os.path.isdir(loader_path):
            return {"ok": False, "error": f"Loader directory not found: {loader_path}"}

        shutil.rmtree(loader_path)
        print(colorize_log(
            f"[api] Deleted {loader_type} loader {loader_version} for {category}/{folder}"
        ))

        scan_categories(force_refresh=True)

        return {
            "ok": True,
            "loader_type": loader_type,
            "loader_version": loader_version,
            "message": f"{_loader_display_name(loader_type)} {loader_version} deleted successfully",
        }

    except Exception as e:
        import traceback

        traceback.print_exc()
        return {"ok": False, "error": f"Failed to delete loader: {str(e)}"}
