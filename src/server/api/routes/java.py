from __future__ import annotations

from typing import Any

from core.java import (
    detect_java_runtimes,
    download_java_installer,
    get_java_install_environment,
    get_java_install_options,
    install_downloaded_java_package,
    open_java_installer_file,
)
from core.settings import load_global_settings


__all__ = [
    "_build_java_runtime_response",
    "api_java_download",
    "api_java_install_options",
    "api_java_runtimes",
    "api_java_runtimes_refresh",
]


def _build_java_runtime_response(force_refresh: bool = False):
    settings = load_global_settings() or {}
    selected_java_path = (settings.get("java_path") or "").strip()

    runtimes = detect_java_runtimes(force_refresh=force_refresh)
    options = []
    for rt in runtimes:
        path = str(rt.get("path") or "")
        label = str(rt.get("label") or "Java")
        version = str(rt.get("version") or "unknown")
        major = int(rt.get("major") or 0)
        options.append(
            {
                "path": path,
                "label": label,
                "version": version,
                "major": major,
                "display": f"{label} ({version}) - {path}",
            }
        )

    return {
        "ok": True,
        "selected_java_path": selected_java_path,
        "runtimes": options,
    }


def api_java_runtimes():
    try:
        return _build_java_runtime_response(force_refresh=False)
    except Exception as e:
        return {"ok": False, "error": str(e), "runtimes": []}


def api_java_runtimes_refresh():
    try:
        return _build_java_runtime_response(force_refresh=True)
    except Exception as e:
        return {"ok": False, "error": str(e), "runtimes": []}


def api_java_install_options():
    try:
        env = get_java_install_environment()
        if not env.get("supported"):
            return {
                "ok": False,
                "error": env.get("error") or "This system is not supported",
                "environment": env,
                "options": [],
            }
        return {
            "ok": True,
            "environment": env,
            "options": get_java_install_options(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "options": []}


def api_java_download(data: Any):
    if not isinstance(data, dict):
        return {"ok": False, "error": "Invalid request"}

    try:
        version = int(data.get("version") or data.get("java_version") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Invalid Java version"}

    try:
        download_info = download_java_installer(version)
        if download_info.get("os") == "linux" and download_info.get("kind") == "package":
            install_info = install_downloaded_java_package(download_info)
            return {
                "ok": True,
                "opened": False,
                "open_error": "",
                **download_info,
                **install_info,
            }
        opened, open_error = open_java_installer_file(download_info.get("path", ""))
        return {
            "ok": True,
            "opened": opened,
            "open_error": open_error,
            **download_info,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
