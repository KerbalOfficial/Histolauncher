from __future__ import annotations

import os
import shutil
import sys
import time
import urllib.parse

from core.downloader.installers import vanilla as _vanilla
from core.downloader import progress as _progress
from core.discord_rpc import set_install_presence, set_launcher_presence
from core.settings import get_base_dir, load_global_settings
from core.version_manager import get_clients_dir, scan_categories

from server.api._helpers import (
    _is_enabled_setting,
    _is_path_within,
    _normalize_operation_id,
    _cancel_operation_request,
    _update_rpc_install_presence,
)
from server.api._state import STATE
from server.api._validation import (
    _validate_category_string,
    _validate_version_string,
)


__all__ = [
    "api_install",
    "api_status",
    "api_cancel",
    "api_pause",
    "api_resume",
    "api_operations_cancel",
    "api_installed",
    "api_open_data_folder",
    "api_delete_version",
]


def api_install(data):
    if not isinstance(data, dict):
        return {"error": "invalid request"}

    version_id = data.get("version") or data.get("folder")
    category = data.get("category")
    full_assets = bool(data.get("full_assets", False))
    force_redownload = bool(data.get("force_redownload") or data.get("redownload"))

    if not version_id or not category:
        return {"error": "missing version or category"}

    if not _validate_version_string(version_id):
        return {"error": "invalid version format"}

    if not _validate_category_string(category):
        return {"error": "invalid category format"}

    storage_type = category.lower()
    settings_dict = load_global_settings() or {}
    show_third_party = _is_enabled_setting(settings_dict.get("show_third_party_versions", "0"))

    _vanilla.install_version(
        version_id,
        storage_category=storage_type,
        full_assets=full_assets,
        background=True,
        include_third_party=show_third_party,
        force_redownload=force_redownload,
    )

    version_key = f"{storage_type}/{version_id}"
    STATE.rpc_install_started_at[version_key] = time.time()
    set_install_presence(
        f"{category}/{version_id}",
        start_time=STATE.rpc_install_started_at[version_key],
    )
    return {"started": True, "version": version_key}


def api_status(version_key):
    try:
        decoded = urllib.parse.unquote(version_key)
        try:
            from core.downloader.progress import read_progress_dict

            progress_status = read_progress_dict(decoded)
            if isinstance(progress_status, dict) and progress_status.get("status"):
                status = dict(progress_status)
                if str(status.get("status") or "").lower() == "running":
                    status["status"] = "installing"
                _update_rpc_install_presence(decoded, status)
                return status
        except Exception:
            pass

        if "/" not in decoded:
            return {"status": "unknown"}
        category, version_id = decoded.split("/", 1)
        status = _vanilla.get_install_status(version_id, category)
        if not status:
            if decoded in STATE.rpc_install_started_at:
                STATE.rpc_install_started_at.pop(decoded, None)
                set_launcher_presence()
            return {"status": "unknown"}

        _update_rpc_install_presence(decoded, status)
        return status
    except Exception as e:
        return {"error": str(e)}


def api_cancel(version_key):
    try:
        decoded = urllib.parse.unquote(version_key)
        if "/" not in decoded:
            return {"ok": False, "error": "invalid key"}

        if "/modloader-" in decoded:
            try:
                from core.downloader.jobs import REGISTRY
                from core.downloader._legacy._state import STATE as LEGACY_STATE

                parts = decoded.split("/")
                if len(parts) >= 3 and parts[2].startswith("modloader-"):
                    loader_tail = parts[2][len("modloader-"):]
                    job_key = f"{parts[0]}/{parts[1]}/loader-{loader_tail}"
                    REGISTRY.cancel(job_key)
                    LEGACY_STATE.cancel_flags[decoded] = True
                    return {"ok": True}
            except Exception:
                pass

        category, version_id = decoded.split("/", 1)

        _vanilla.cancel_install(version_id, category, wait_seconds=3.0)
        STATE.rpc_install_started_at.pop(decoded, None)
        set_launcher_presence()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_pause(version_key):
    try:
        decoded = urllib.parse.unquote(version_key)
        if "/" not in decoded:
            return {"ok": False, "error": "invalid key"}

        if "/modloader-" in decoded:
            try:
                from core.downloader.jobs import REGISTRY
                from core.downloader._legacy._state import STATE as LEGACY_STATE

                parts = decoded.split("/")
                if len(parts) >= 3 and parts[2].startswith("modloader-"):
                    loader_tail = parts[2][len("modloader-"):]
                    paused = REGISTRY.pause(f"{parts[0]}/{parts[1]}/loader-{loader_tail}")
                    if not paused:
                        LEGACY_STATE.pause_flags[decoded] = True
                    return {"ok": True}
            except Exception:
                pass

        category, version_id = decoded.split("/", 1)
        _vanilla.pause_install(version_id, category)
        prog = _vanilla.get_install_status(version_id, category) or {"status": "paused"}
        _update_rpc_install_presence(decoded, prog)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_resume(version_key):
    try:
        decoded = urllib.parse.unquote(version_key)
        if "/" not in decoded:
            return {"ok": False, "error": "invalid key"}

        if "/modloader-" in decoded:
            try:
                from core.downloader.jobs import REGISTRY
                from core.downloader._legacy._state import STATE as LEGACY_STATE

                parts = decoded.split("/")
                if len(parts) >= 3 and parts[2].startswith("modloader-"):
                    loader_tail = parts[2][len("modloader-"):]
                    REGISTRY.resume(f"{parts[0]}/{parts[1]}/loader-{loader_tail}")
                    LEGACY_STATE.pause_flags.pop(decoded, None)
                    return {"ok": True}
            except Exception:
                pass

        category, version_id = decoded.split("/", 1)
        _vanilla.resume_install(version_id, category)
        prog = _vanilla.get_install_status(version_id, category) or {"status": "downloading"}
        _update_rpc_install_presence(decoded, prog)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_operations_cancel(data):
    if not isinstance(data, dict):
        return {"ok": False, "error": "Invalid request"}

    operation_id = _normalize_operation_id(data.get("operation_id"))
    if not operation_id:
        return {"ok": False, "error": "operation_id is required"}

    _cancel_operation_request(operation_id)
    return {"ok": True}


def api_installed():
    try:
        categories = scan_categories()
        return categories.get("* All", [])
    except Exception:
        return {}


def api_open_data_folder():
    try:
        base = get_base_dir()

        if os.name == "nt":
            os.startfile(base)
        else:
            if sys.platform == "darwin":
                import subprocess

                subprocess.Popen(["open", base])
            else:
                import subprocess

                subprocess.Popen(["xdg-open", base])

        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_delete_version(data):
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid request"}

    category = (data.get("category") or "").strip()
    folder = (data.get("folder") or "").strip()

    if not category or not folder:
        return {"ok": False, "error": "missing category or folder"}

    if not _validate_category_string(category):
        return {"ok": False, "error": "invalid category format"}

    if not _validate_version_string(folder):
        return {"ok": False, "error": "invalid folder format"}

    clients_dir = get_clients_dir()
    version_dir = os.path.join(clients_dir, category.lower(), folder)

    if not _is_path_within(clients_dir, version_dir):
        return {"ok": False, "error": "invalid version path"}

    if not os.path.isdir(version_dir):
        return {"ok": False, "error": "version directory does not exist"}

    try:
        shutil.rmtree(version_dir)
        version_key = f"{category.lower()}/{folder}"
        _progress.delete_progress(version_key)
        scan_categories(force_refresh=True)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
