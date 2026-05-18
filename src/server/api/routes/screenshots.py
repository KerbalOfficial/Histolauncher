from __future__ import annotations

from typing import Any

from core.logger import colorize_log
from core.settings import normalize_custom_storage_directory


__all__ = [
    "api_screenshots_delete",
    "api_screenshots_installed",
    "api_screenshots_open",
    "api_screenshots_storage_options",
    "api_screenshots_update",
]


def _normalize_screenshot_storage_target(value: Any) -> str:
    raw = str(value or "all").strip()
    if raw.lower().startswith("version:"):
        return f"version:{raw.split(':', 1)[1]}"
    normalized = raw.lower()
    if normalized in {"all", "default", "global", "custom"}:
        return normalized
    return "all"


def api_screenshots_storage_options(data=None):
    try:
        from core import screenshots

        payload = data if isinstance(data, dict) else {}
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))
        return {
            "ok": True,
            "options": screenshots.list_screenshot_storage_options(custom_path=custom_path),
        }
    except Exception as exc:
        print(colorize_log(f"[api] Failed to load screenshot storage options: {exc}"))
        return {"ok": False, "error": str(exc), "options": []}


def api_screenshots_installed(data=None):
    try:
        from core import screenshots

        payload = data if isinstance(data, dict) else {}
        storage_target = _normalize_screenshot_storage_target(payload.get("storage_target"))
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))
        result = screenshots.list_screenshots(storage_target, custom_path=custom_path)
        return {
            "ok": bool(result.get("ok")),
            "screenshots": result.get("screenshots", []),
            "storage_label": result.get("storage_label", storage_target.title()),
            "storage_path": result.get("storage_path", ""),
            "error": result.get("error", ""),
        }
    except Exception as exc:
        print(colorize_log(f"[api] Failed to load screenshots: {exc}"))
        return {"ok": False, "error": str(exc), "screenshots": []}


def api_screenshots_update(data=None):
    try:
        from core import screenshots

        payload = data if isinstance(data, dict) else {}
        storage_target = _normalize_screenshot_storage_target(payload.get("storage_target"))
        relative_path = str(payload.get("relative_path") or "").strip()
        new_name = str(payload.get("new_name") or "").strip()
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))
        if not relative_path:
            return {"ok": False, "error": "relative_path is required"}
        if not new_name:
            return {"ok": False, "error": "new_name is required"}
        return screenshots.update_screenshot(
            storage_target,
            relative_path,
            custom_path=custom_path,
            new_name=new_name,
        )
    except Exception as exc:
        print(colorize_log(f"[api] Failed to update screenshot: {exc}"))
        return {"ok": False, "error": str(exc)}


def api_screenshots_delete(data=None):
    try:
        from core import screenshots

        payload = data if isinstance(data, dict) else {}
        storage_target = _normalize_screenshot_storage_target(payload.get("storage_target"))
        relative_path = str(payload.get("relative_path") or "").strip()
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))
        if not relative_path:
            return {"ok": False, "error": "relative_path is required"}
        return screenshots.delete_screenshot(
            storage_target,
            relative_path,
            custom_path=custom_path,
        )
    except Exception as exc:
        print(colorize_log(f"[api] Failed to delete screenshot: {exc}"))
        return {"ok": False, "error": str(exc)}


def api_screenshots_open(data=None):
    try:
        from core import screenshots

        payload = data if isinstance(data, dict) else {}
        storage_target = _normalize_screenshot_storage_target(payload.get("storage_target"))
        relative_path = str(payload.get("relative_path") or "").strip()
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))
        if not relative_path:
            return {"ok": False, "error": "relative_path is required"}
        return screenshots.open_screenshot(
            storage_target,
            relative_path,
            custom_path=custom_path,
        )
    except Exception as exc:
        print(colorize_log(f"[api] Failed to open screenshot: {exc}"))
        return {"ok": False, "error": str(exc)}