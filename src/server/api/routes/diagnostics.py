from __future__ import annotations

import datetime as dt
import json
import os
import platform
import shutil
import sys
from collections import Counter
from typing import Any, Callable

from core.java import detect_java_runtimes
from core.logger import colorize_log
from core.settings import (
    get_active_profile_id,
    get_active_scope_profile_id,
    get_base_dir,
    get_default_minecraft_dir,
    get_mods_profile_dir,
    get_versions_profile_dir,
    load_global_settings,
    validate_custom_storage_directory,
)
from core.version_manager import get_clients_dir, get_version_loaders, scan_categories
from server.api.version_check import read_local_version


__all__ = ["api_diagnostics_report"]


def _now_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _redact_path(value: Any) -> str:
    raw_path = str(value or "").strip()
    if not raw_path:
        return ""

    try:
        absolute_path = os.path.abspath(os.path.expanduser(raw_path))
    except Exception:
        return raw_path

    home_dir = os.path.abspath(os.path.expanduser("~"))
    try:
        common_path = os.path.commonpath([home_dir, absolute_path])
    except ValueError:
        common_path = ""

    if common_path == home_dir:
        try:
            relative_path = os.path.relpath(absolute_path, home_dir)
        except ValueError:
            return "~"
        return "~" if relative_path == "." else os.path.join("~", relative_path)

    return absolute_path


def _redact_settings(settings: dict[str, Any]) -> dict[str, Any]:
    java_path = str(settings.get("java_path") or "").strip()
    custom_storage = str(settings.get("custom_storage_directory") or "").strip()
    url_proxy = str(settings.get("url_proxy") or "").strip()
    username = str(settings.get("username") or "").strip()

    return {
        "account_type": settings.get("account_type", ""),
        "username_present": bool(username),
        "selected_version": settings.get("selected_version", ""),
        "min_ram": settings.get("min_ram", ""),
        "max_ram": settings.get("max_ram", ""),
        "game_resolution_width": settings.get("game_resolution_width", ""),
        "game_resolution_height": settings.get("game_resolution_height", ""),
        "game_fullscreen": settings.get("game_fullscreen", ""),
        "game_demo_mode": settings.get("game_demo_mode", ""),
        "storage_directory": settings.get("storage_directory", ""),
        "custom_storage_directory": _redact_path(custom_storage),
        "java_path": java_path if java_path in {"", "auto", "__java_path_default__"} else _redact_path(java_path),
        "url_proxy_configured": bool(url_proxy),
        "low_data_mode": settings.get("low_data_mode", ""),
        "show_third_party_versions": settings.get("show_third_party_versions", ""),
        "discord_rpc_enabled": settings.get("discord_rpc_enabled", ""),
        "desktop_notifications_enabled": settings.get("desktop_notifications_enabled", ""),
        "launcher_theme": settings.get("launcher_theme", ""),
        "launcher_ui_size": settings.get("launcher_ui_size", ""),
        "launcher_language": settings.get("launcher_language", ""),
        "layout_density": settings.get("layout_density", ""),
        "versions_view": settings.get("versions_view", ""),
        "addons_view": settings.get("addons_view", ""),
        "worlds_view": settings.get("worlds_view", ""),
    }


def _safe_section(name: str, builder: Callable[[], Any]) -> Any:
    try:
        return builder()
    except Exception as exc:
        print(colorize_log(f"[diagnostics] Failed to build {name}: {exc}"))
        return {"error": str(exc)}


def _disk_summary(path: str) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
    except Exception as exc:
        return {"error": str(exc)}
    return {
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
    }


def _platform_summary() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "python_executable": _redact_path(sys.executable),
    }


def _paths_summary(settings: dict[str, Any]) -> dict[str, Any]:
    custom_validation = validate_custom_storage_directory(settings.get("custom_storage_directory"))
    if isinstance(custom_validation, dict):
        custom_validation = dict(custom_validation)
        custom_validation["path"] = _redact_path(custom_validation.get("path"))

    return {
        "base_dir": _redact_path(get_base_dir()),
        "default_minecraft_dir": _redact_path(get_default_minecraft_dir()),
        "clients_dir": _redact_path(get_clients_dir()),
        "versions_profile_dir": _redact_path(get_versions_profile_dir()),
        "mods_profile_dir": _redact_path(get_mods_profile_dir()),
        "active_profile_id": get_active_profile_id(),
        "active_versions_profile_id": get_active_scope_profile_id("versions"),
        "active_addons_profile_id": get_active_scope_profile_id("addons"),
        "custom_storage_validation": custom_validation,
    }


def _java_summary(settings: dict[str, Any]) -> dict[str, Any]:
    runtimes = []
    for runtime in detect_java_runtimes(force_refresh=False):
        runtimes.append({
            "label": runtime.get("label", "Java"),
            "version": runtime.get("version", ""),
            "major": runtime.get("major", 0),
            "path": _redact_path(runtime.get("path")),
        })

    selected_java = str(settings.get("java_path") or "").strip()
    return {
        "selected_java_path": selected_java if selected_java in {"", "auto", "__java_path_default__"} else _redact_path(selected_java),
        "detected_count": len(runtimes),
        "detected_runtimes": runtimes,
    }


def _versions_summary() -> dict[str, Any]:
    categories = scan_categories(force_refresh=True)
    installed_versions = categories.get("* All", []) if isinstance(categories, dict) else []
    category_counts: Counter[str] = Counter()
    loader_counts: Counter[str] = Counter()
    version_storage_counts: Counter[str] = Counter()

    for version_entry in installed_versions:
        if not isinstance(version_entry, dict):
            continue

        category = str(version_entry.get("category") or "Unknown")
        folder = str(version_entry.get("folder") or "")
        category_counts[category] += 1
        version_storage_counts[str(version_entry.get("storage_override_mode") or "default")] += 1

        if not folder:
            continue
        try:
            loaders = get_version_loaders(category, folder)
        except Exception:
            continue
        if not isinstance(loaders, dict):
            continue
        for loader_name, loader_versions in loaders.items():
            if loader_versions:
                loader_counts[str(loader_name)] += len(loader_versions)

    return {
        "installed_count": len(installed_versions),
        "by_category": dict(sorted(category_counts.items())),
        "installed_loader_versions": dict(sorted(loader_counts.items())),
        "storage_modes": dict(sorted(version_storage_counts.items())),
    }


def _addons_summary() -> dict[str, Any]:
    from core import mod_manager

    summary: dict[str, Any] = {}
    for addon_type in ("mods", "resourcepacks", "shaderpacks"):
        entries = mod_manager.get_installed_addons(addon_type)
        provider_counts: Counter[str] = Counter()
        compatibility_counts: Counter[str] = Counter()
        disabled_count = 0

        for addon_entry in entries:
            if not isinstance(addon_entry, dict):
                continue
            provider_counts[str(addon_entry.get("provider") or "unknown")] += 1
            if addon_entry.get("disabled"):
                disabled_count += 1
            compatibility_values = addon_entry.get("compatibility_types") or addon_entry.get("mod_loader") or []
            if isinstance(compatibility_values, str):
                compatibility_values = [compatibility_values]
            for compatibility in compatibility_values:
                if compatibility:
                    compatibility_counts[str(compatibility)] += 1

        summary[addon_type] = {
            "installed_count": len(entries),
            "disabled_count": disabled_count,
            "providers": dict(sorted(provider_counts.items())),
            "compatibility": dict(sorted(compatibility_counts.items())),
        }

    modpacks = mod_manager.get_installed_modpacks()
    summary["modpacks"] = {
        "installed_count": len(modpacks),
        "disabled_count": sum(1 for modpack in modpacks if isinstance(modpack, dict) and modpack.get("disabled")),
    }
    return summary


def _iter_recent_log_candidates(log_root: str, *, limit: int = 80):
    if not os.path.isdir(log_root):
        return []

    candidates = []
    for current_root, directory_names, file_names in os.walk(log_root):
        relative_root = os.path.relpath(current_root, log_root)
        depth = 0 if relative_root == "." else len(relative_root.split(os.sep))
        if depth >= 4:
            directory_names[:] = []

        for file_name in file_names:
            if not file_name.lower().endswith((".log", ".txt")):
                continue
            file_path = os.path.join(current_root, file_name)
            try:
                stat_result = os.stat(file_path)
            except OSError:
                continue
            candidates.append((stat_result.st_mtime, stat_result.st_size, file_path))

        if len(candidates) >= limit * 3:
            break

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[:limit]


def _logs_summary() -> dict[str, Any]:
    roots = {
        "launcher_logs": os.path.join(get_base_dir(), "logs"),
        "clients": get_clients_dir(),
        "minecraft_logs": os.path.join(get_default_minecraft_dir(), "logs"),
        "minecraft_crash_reports": os.path.join(get_default_minecraft_dir(), "crash-reports"),
    }
    summary = {}
    for label, root_path in roots.items():
        candidates = _iter_recent_log_candidates(root_path, limit=10)
        summary[label] = {
            "root": _redact_path(root_path),
            "exists": os.path.isdir(root_path),
            "latest": [
                {
                    "path": _redact_path(file_path),
                    "size_bytes": file_size,
                    "modified_at": dt.datetime.fromtimestamp(modified_at, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                for modified_at, file_size, file_path in candidates
            ],
        }
    return summary


def _build_report() -> dict[str, Any]:
    settings = load_global_settings() or {}
    base_dir = get_base_dir()
    return {
        "generated_at": _now_stamp(),
        "launcher": {
            "name": "Histolauncher",
            "version": read_local_version(),
        },
        "platform": _safe_section("platform", _platform_summary),
        "paths": _safe_section("paths", lambda: _paths_summary(settings)),
        "settings": _safe_section("settings", lambda: _redact_settings(settings)),
        "java": _safe_section("java", lambda: _java_summary(settings)),
        "versions": _safe_section("versions", _versions_summary),
        "addons": _safe_section("addons", _addons_summary),
        "logs": _safe_section("logs", _logs_summary),
        "disk": _safe_section("disk", lambda: _disk_summary(base_dir)),
    }


def _format_report_text(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)


def _save_report_to_disk(report_text: str) -> tuple[bool, bool, str, str]:
    file_name = f"histolauncher-diagnostics-{_file_stamp()}.json"
    save_path = ""
    dialog_failed = False
    root = None

    try:
        from tkinter import Tk
        from tkinter.filedialog import asksaveasfilename

        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        save_path = asksaveasfilename(
            initialfile=file_name,
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Text", "*.txt"), ("All Files", "*.*")],
            initialdir=os.path.expanduser("~"),
            title="Save Histolauncher Diagnostics Report",
        )
    except Exception as exc:
        dialog_failed = True
        print(colorize_log(f"[diagnostics] Save dialog unavailable, using fallback path: {exc}"))
    finally:
        try:
            if root is not None:
                root.destroy()
        except Exception:
            pass

    if not save_path and not dialog_failed:
        return False, True, "", ""

    if not save_path:
        diagnostics_dir = os.path.join(get_base_dir(), "diagnostics")
        os.makedirs(diagnostics_dir, exist_ok=True)
        save_path = os.path.join(diagnostics_dir, file_name)

    with open(save_path, "w", encoding="utf-8") as report_file:
        report_file.write(report_text)
        report_file.write("\n")

    return True, False, save_path, _redact_path(save_path)


def api_diagnostics_report(data: Any = None):
    try:
        request = data if isinstance(data, dict) else {}
        save_to_disk = bool(request.get("save_to_disk"))
        include_text = bool(request.get("include_text", True)) or save_to_disk

        report = _build_report()
        report_text = _format_report_text(report)
        response: dict[str, Any] = {"ok": True, "report": report}
        if include_text:
            response["report_text"] = report_text

        if save_to_disk:
            saved, cancelled, saved_path, display_path = _save_report_to_disk(report_text)
            response.update({
                "saved": saved,
                "cancelled": cancelled,
                "saved_path": saved_path,
                "display_path": display_path,
            })

        return response
    except Exception as exc:
        print(colorize_log(f"[diagnostics] Failed to build diagnostics report: {exc}"))
        return {"ok": False, "error": str(exc)}