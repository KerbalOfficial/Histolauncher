from __future__ import annotations

import os
import re
import shutil
import subprocess
import urllib.parse
from typing import Any

from core.settings import normalize_custom_storage_directory
from core import world_manager


__all__ = [
    "SUPPORTED_SCREENSHOT_EXTENSIONS",
    "delete_screenshot",
    "list_screenshot_storage_options",
    "list_screenshots",
    "open_screenshot",
    "resolve_screenshot_file",
    "update_screenshot",
]


SUPPORTED_SCREENSHOT_EXTENSIONS = frozenset({
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
})

_FORBIDDEN_SCREENSHOT_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_SCREENSHOT_NAME_LENGTH = 240


def _normalize_screenshot_storage_target(value: Any) -> str:
    raw = str(value or "all").strip()
    if raw.lower().startswith("version:"):
        return f"version:{raw.split(':', 1)[1]}"
    normalized = raw.lower()
    if normalized in {"all", "default", "global", "custom"}:
        return normalized
    return "all"


def _is_supported_screenshot_file(path: str) -> bool:
    return os.path.splitext(str(path or ""))[1].lower() in SUPPORTED_SCREENSHOT_EXTENSIONS


def _simplify_screenshot_storage_label(label: Any) -> str:
    raw = str(label or "").strip()
    if raw.lower().startswith("default -> "):
        simplified = raw.split("->", 1)[1].strip()
        if simplified:
            return simplified
    return raw


def _normalize_requested_screenshot_name(requested_name: str, *, current_extension: str) -> str:
    candidate = str(requested_name or "").strip()
    if not candidate:
        raise ValueError("Screenshot name is required.")
    if candidate != os.path.basename(candidate):
        raise ValueError("Screenshot name cannot include folders.")

    stem, extension = os.path.splitext(candidate)
    normalized_extension = str(current_extension or "").lower()
    if extension:
        if normalized_extension and extension.lower() != normalized_extension:
            raise ValueError("Screenshot file extension cannot be changed.")
    elif normalized_extension:
        candidate = f"{candidate}{normalized_extension}"
        stem = os.path.splitext(candidate)[0]

    candidate = candidate.strip().strip(". ")
    stem = str(stem or "").strip().strip(". ")
    if not candidate or not stem:
        raise ValueError("Screenshot name is required.")
    if len(candidate) > _MAX_SCREENSHOT_NAME_LENGTH:
        raise ValueError(f"Screenshot name must be <= {_MAX_SCREENSHOT_NAME_LENGTH} characters.")
    if _FORBIDDEN_SCREENSHOT_NAME_CHARS.search(candidate):
        raise ValueError("Screenshot name contains invalid characters.")
    return candidate


def _build_screenshot_file_url(
    storage_target: str,
    relative_path: str,
    *,
    custom_path: str = "",
) -> str:
    query = {
        "storage_target": storage_target,
        "relative_path": str(relative_path or "").replace("\\", "/"),
    }
    if storage_target == "custom" and custom_path:
        query["custom_path"] = custom_path
    return "/api/screenshots/file?" + urllib.parse.urlencode(
        query,
        quote_via=urllib.parse.quote,
        safe="",
    )


def _resolve_screenshot_root(
    storage_target: str,
    *,
    custom_path: str = "",
) -> dict[str, Any] | None:
    normalized_target = _normalize_screenshot_storage_target(storage_target)
    if normalized_target == "all":
        return None

    normalized_custom_path = normalize_custom_storage_directory(custom_path)
    resolved = world_manager.resolve_storage_target(
        normalized_target,
        custom_path=normalized_custom_path,
        create_saves_dir=False,
    )
    if not resolved.get("ok"):
        return None

    game_dir = str(resolved.get("game_dir") or "").strip()
    if not game_dir:
        return None

    return {
        **resolved,
        "storage_target": normalized_target,
        "storage_label": _simplify_screenshot_storage_label(resolved.get("storage_label")),
        "custom_path": normalized_custom_path if normalized_target == "custom" else "",
        "screenshots_dir": os.path.join(game_dir, "screenshots"),
    }


def _iter_all_screenshot_roots(*, custom_path: str = ""):
    seen_paths: set[str] = set()
    normalized_custom_path = normalize_custom_storage_directory(custom_path)

    for option in world_manager.list_storage_options():
        target = _normalize_screenshot_storage_target((option or {}).get("value"))
        if target == "all":
            continue
        if target == "custom" and not normalized_custom_path:
            continue

        root = _resolve_screenshot_root(target, custom_path=normalized_custom_path)
        if not root:
            continue

        screenshots_dir = str(root.get("screenshots_dir") or "")
        real_dir = os.path.normcase(os.path.realpath(screenshots_dir))
        if not real_dir or real_dir in seen_paths:
            continue

        seen_paths.add(real_dir)
        yield root


def list_screenshot_storage_options(*, custom_path: str = "") -> list[dict[str, str]]:
    return [
        {"value": "all", "label": "All"},
        *[
            {
                **option,
                "label": _simplify_screenshot_storage_label((option or {}).get("label")),
            }
            for option in world_manager.list_storage_options()
        ],
    ]


def _screenshot_entry_from_file(
    file_path: str,
    *,
    storage_target: str,
    storage_label: str,
    custom_path: str = "",
    screenshots_dir: str,
) -> dict[str, Any]:
    file_name = os.path.basename(file_path)
    stem, extension = os.path.splitext(file_name)
    try:
        modified_at = int(os.path.getmtime(file_path) * 1000)
    except Exception:
        modified_at = 0
    try:
        created_at = int(os.path.getctime(file_path) * 1000)
    except Exception:
        created_at = 0
    try:
        size_bytes = int(os.path.getsize(file_path))
    except Exception:
        size_bytes = 0

    try:
        relative_path = os.path.relpath(file_path, screenshots_dir)
    except Exception:
        relative_path = file_name
    relative_path = str(relative_path or file_name).replace("\\", "/")
    relative_dir = os.path.dirname(relative_path).replace("\\", "/")

    summary_parts = []
    if storage_label:
        summary_parts.append(storage_label)
    if relative_dir and relative_dir != ".":
        summary_parts.append(relative_dir)
    summary = " | ".join(summary_parts)

    return {
        "screenshot_id": f"{storage_target}::{relative_path}",
        "title": stem or file_name,
        "display_name": stem or file_name,
        "file_name": file_name,
        "extension": extension.lower(),
        "relative_path": relative_path,
        "relative_dir": "" if relative_dir in {"", "."} else relative_dir,
        "description": summary,
        "summary": summary,
        "image_url": _build_screenshot_file_url(
            storage_target,
            relative_path,
            custom_path=custom_path,
        ),
        "storage_target": storage_target,
        "storage_label": storage_label,
        "modified_at": modified_at,
        "created_at": created_at,
        "size_bytes": size_bytes,
    }


def list_screenshots(storage_target: str = "all", *, custom_path: str = "") -> dict[str, Any]:
    normalized_target = _normalize_screenshot_storage_target(storage_target)
    normalized_custom_path = normalize_custom_storage_directory(custom_path)

    if normalized_target == "all":
        roots = list(_iter_all_screenshot_roots(custom_path=normalized_custom_path))
        storage_label = "All"
        storage_path = ""
    else:
        root = _resolve_screenshot_root(normalized_target, custom_path=normalized_custom_path)
        if not root:
            return {
                "ok": False,
                "storage_label": normalized_target.title(),
                "storage_path": "",
                "screenshots": [],
                "error": "Failed to resolve screenshots storage directory.",
            }
        roots = [root]
        storage_label = str(root.get("storage_label") or normalized_target.title())
        storage_path = str(root.get("screenshots_dir") or "")

    screenshots: list[dict[str, Any]] = []
    for root in roots:
        screenshots_dir = str(root.get("screenshots_dir") or "")
        if not os.path.isdir(screenshots_dir):
            continue

        try:
            for current_root, _, file_names in os.walk(screenshots_dir):
                for file_name in sorted(file_names, key=lambda value: value.lower()):
                    file_path = os.path.join(current_root, file_name)
                    if not _is_supported_screenshot_file(file_path):
                        continue
                    screenshots.append(_screenshot_entry_from_file(
                        file_path,
                        storage_target=str(root.get("storage_target") or normalized_target),
                        storage_label=str(root.get("storage_label") or ""),
                        custom_path=str(root.get("custom_path") or ""),
                        screenshots_dir=screenshots_dir,
                    ))
        except Exception as exc:
            return {
                "ok": False,
                "storage_label": storage_label,
                "storage_path": storage_path,
                "screenshots": [],
                "error": str(exc),
            }

    screenshots.sort(
        key=lambda item: (
            int(item.get("modified_at") or 0),
            str(item.get("file_name") or "").lower(),
        ),
        reverse=True,
    )

    return {
        "ok": True,
        "storage_label": storage_label,
        "storage_path": storage_path,
        "screenshots": screenshots,
        "error": "",
    }


def resolve_screenshot_file(
    storage_target: str,
    relative_path: str,
    *,
    custom_path: str = "",
) -> dict[str, Any]:
    root = _resolve_screenshot_root(storage_target, custom_path=custom_path)
    if not root:
        return {"ok": False, "error": "Failed to resolve screenshots directory."}

    raw_relative_path = str(relative_path or "").strip().replace("\\", "/")
    raw_relative_path = raw_relative_path.lstrip("/")
    if not raw_relative_path or "\x00" in raw_relative_path:
        return {"ok": False, "error": "Invalid screenshot path."}

    normalized_relative_path = os.path.normpath(raw_relative_path.replace("/", os.sep))
    if normalized_relative_path in {"", "."} or os.path.isabs(normalized_relative_path):
        return {"ok": False, "error": "Invalid screenshot path."}

    screenshots_dir = str(root.get("screenshots_dir") or "")
    candidate_path = os.path.join(screenshots_dir, normalized_relative_path)

    try:
        real_root = os.path.normcase(os.path.realpath(screenshots_dir))
        real_path = os.path.normcase(os.path.realpath(candidate_path))
        if os.path.commonpath([real_root, real_path]) != real_root:
            return {"ok": False, "error": "Invalid screenshot path."}
    except Exception:
        return {"ok": False, "error": "Invalid screenshot path."}

    if not os.path.isfile(candidate_path) or not _is_supported_screenshot_file(candidate_path):
        return {"ok": False, "error": "Screenshot was not found."}

    return {
        "ok": True,
        "file_path": candidate_path,
        "file_name": os.path.basename(candidate_path),
        "screenshots_dir": screenshots_dir,
        "storage_label": str(root.get("storage_label") or ""),
        "storage_target": str(root.get("storage_target") or storage_target),
        "relative_path": normalized_relative_path.replace("\\", "/"),
    }


def update_screenshot(
    storage_target: str,
    relative_path: str,
    *,
    custom_path: str = "",
    new_name: str = "",
) -> dict[str, Any]:
    resolved = resolve_screenshot_file(storage_target, relative_path, custom_path=custom_path)
    if not resolved.get("ok"):
        return {"ok": False, "error": resolved.get("error") or "Failed to resolve screenshot."}

    source_path = str(resolved.get("file_path") or "")
    screenshots_dir = str(resolved.get("screenshots_dir") or "")
    file_name = str(resolved.get("file_name") or "")
    requested_name = str(new_name or "").strip()
    if not requested_name:
        return {"ok": False, "error": "new_name is required"}

    try:
        target_name = _normalize_requested_screenshot_name(
            requested_name,
            current_extension=os.path.splitext(file_name)[1],
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    target_path = os.path.join(os.path.dirname(source_path), target_name)
    try:
        real_root = os.path.normcase(os.path.realpath(screenshots_dir))
        real_target = os.path.normcase(os.path.realpath(target_path))
        if os.path.commonpath([real_root, real_target]) != real_root:
            return {"ok": False, "error": "Invalid screenshot path."}
    except Exception:
        return {"ok": False, "error": "Invalid screenshot path."}

    if os.path.normcase(source_path) == os.path.normcase(target_path):
        return {
            "ok": True,
            "screenshot": _screenshot_entry_from_file(
                source_path,
                storage_target=str(resolved.get("storage_target") or storage_target),
                storage_label=str(resolved.get("storage_label") or ""),
                custom_path=normalize_custom_storage_directory(custom_path),
                screenshots_dir=screenshots_dir,
            ),
        }

    if os.path.exists(target_path):
        return {"ok": False, "error": "A screenshot with that name already exists."}

    try:
        os.replace(source_path, target_path)
    except Exception as exc:
        return {"ok": False, "error": f"Failed to rename screenshot: {exc}"}

    return {
        "ok": True,
        "screenshot": _screenshot_entry_from_file(
            target_path,
            storage_target=str(resolved.get("storage_target") or storage_target),
            storage_label=str(resolved.get("storage_label") or ""),
            custom_path=normalize_custom_storage_directory(custom_path),
            screenshots_dir=screenshots_dir,
        ),
    }


def delete_screenshot(
    storage_target: str,
    relative_path: str,
    *,
    custom_path: str = "",
) -> dict[str, Any]:
    resolved = resolve_screenshot_file(storage_target, relative_path, custom_path=custom_path)
    if not resolved.get("ok"):
        return {"ok": False, "error": resolved.get("error") or "Failed to resolve screenshot."}

    try:
        os.remove(str(resolved.get("file_path") or ""))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def open_screenshot(
    storage_target: str,
    relative_path: str,
    *,
    custom_path: str = "",
) -> dict[str, Any]:
    resolved = resolve_screenshot_file(storage_target, relative_path, custom_path=custom_path)
    if not resolved.get("ok"):
        return {"ok": False, "error": resolved.get("error") or "Failed to resolve screenshot."}

    file_path = str(resolved.get("file_path") or "")
    try:
        if os.name == "nt":
            os.startfile(file_path)
        elif shutil.which("open"):
            subprocess.Popen(["open", file_path])
        else:
            subprocess.Popen(["xdg-open", file_path])
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}