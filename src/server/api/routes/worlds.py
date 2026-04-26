from __future__ import annotations

import re
from typing import Any

from core.logger import colorize_log
from core.notifications import send_desktop_notification
from core.settings import normalize_custom_storage_directory


__all__ = [
    "_normalize_world_storage_target",
    "api_worlds_storage_options",
    "api_worlds_version_options",
    "api_worlds_installed",
    "api_worlds_detail",
    "api_worlds_nbt",
    "api_worlds_nbt_simple_update",
    "api_worlds_nbt_advanced_update",
    "api_worlds_update",
    "api_worlds_icon_update",
    "api_worlds_delete",
    "api_worlds_open",
    "api_worlds_search",
    "api_worlds_versions",
    "api_worlds_install",
    "api_worlds_export",
    "api_worlds_import_scan",
    "api_worlds_import",
]


def _normalize_world_storage_target(value: Any) -> str:
    raw = str(value or "default").strip()
    if raw.lower().startswith("version:"):
        return f"version:{raw.split(':', 1)[1]}"
    normalized = raw.lower()
    if normalized in {"default", "global", "custom"}:
        return normalized
    return "default"


def _normalize_world_install_progress_key(value: Any, fallback: str) -> str:
    raw = str(value or fallback or "").strip()
    key = re.sub(r"[^A-Za-z0-9._~:/-]+", "-", raw).strip("-._/")
    fallback_key = re.sub(r"[^A-Za-z0-9._~:/-]+", "-", str(fallback or "worlds/install")).strip("-._/")
    return (key or fallback_key or "worlds/install")[:180]


def _progress_percent(done: Any, total: Any) -> float:
    try:
        total_value = float(total or 0)
        done_value = float(done or 0)
    except (TypeError, ValueError):
        return 0.0
    if total_value <= 0:
        return 0.0
    return max(0.0, min(100.0, (done_value / total_value) * 100.0))


def _finish_world_install_progress(tracker: Any, status: str, message: str) -> None:
    if not tracker:
        return
    try:
        tracker.finish(status=status, message=message, keep_seconds=2.5)
    except Exception:
        pass


def _send_world_install_notification(world_name: str) -> None:
    try:
        name = str(world_name or "World").strip() or "World"
        send_desktop_notification(
            title=f"[{name}] World Installation complete!",
            message=f'World {name} has installed successfully!',
        )
    except Exception as exc:
        print(colorize_log(f"[api] Could not send world notification: {exc}"))


def api_worlds_storage_options(data=None):
    try:
        from core import world_manager

        return {"ok": True, "options": world_manager.list_storage_options()}
    except Exception as e:
        print(colorize_log(f"[api] Failed to load world storage options: {e}"))
        return {"ok": False, "error": str(e), "options": []}


def api_worlds_version_options(data=None):
    try:
        from core import world_manager

        return {"ok": True, "versions": world_manager.list_version_options()}
    except Exception as e:
        print(colorize_log(f"[api] Failed to load world version options: {e}"))
        return {"ok": False, "error": str(e), "versions": []}


def api_worlds_installed(data=None):
    try:
        from core import world_manager

        payload = data if isinstance(data, dict) else {}
        storage_target = _normalize_world_storage_target(payload.get("storage_target"))
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))
        result = world_manager.list_worlds(storage_target, custom_path=custom_path)
        return {
            "ok": bool(result.get("ok")),
            "worlds": result.get("worlds", []),
            "storage_label": result.get("storage_label", storage_target.title()),
            "storage_path": result.get("storage_path", ""),
            "error": result.get("error", ""),
        }
    except Exception as e:
        print(colorize_log(f"[api] Failed to get installed worlds: {e}"))
        return {"ok": False, "error": str(e), "worlds": []}


def api_worlds_detail(data=None):
    try:
        from core import world_manager

        payload = data if isinstance(data, dict) else {}
        project_id = str(payload.get("project_id") or "").strip()
        provider = str(payload.get("provider") or "curseforge").strip().lower()

        if project_id:
            if provider != "curseforge":
                return {"ok": False, "error": f"Unknown provider: {provider}"}
            detail = world_manager.get_world_detail_curseforge(project_id)
            if detail:
                return {"ok": True, **detail}
            return {"ok": False, "error": "Failed to fetch world details"}

        storage_target = _normalize_world_storage_target(payload.get("storage_target"))
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))
        world_id = str(payload.get("world_id") or "").strip()
        if not world_id:
            return {"ok": False, "error": "world_id is required"}
        return world_manager.get_world_detail(storage_target, world_id, custom_path=custom_path)
    except Exception as e:
        print(colorize_log(f"[api] Failed to get world detail: {e}"))
        return {"ok": False, "error": str(e)}


def api_worlds_nbt(data=None):
    try:
        from core import world_manager

        payload = data if isinstance(data, dict) else {}
        world_id = str(payload.get("world_id") or "").strip()
        player_id = str(payload.get("player_id") or "").strip()
        if not world_id:
            return {"ok": False, "error": "world_id is required"}

        storage_target = _normalize_world_storage_target(payload.get("storage_target"))
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))
        return world_manager.get_world_nbt_editor(
            storage_target,
            world_id,
            custom_path=custom_path,
            player_id=player_id,
        )
    except Exception as e:
        print(colorize_log(f"[api] Failed to get world NBT data: {e}"))
        return {"ok": False, "error": str(e)}


def api_worlds_nbt_simple_update(data=None):
    try:
        from core import world_manager

        payload = data if isinstance(data, dict) else {}
        world_id = str(payload.get("world_id") or "").strip()
        player_id = str(payload.get("player_id") or "").strip()
        if not world_id:
            return {"ok": False, "error": "world_id is required"}

        storage_target = _normalize_world_storage_target(payload.get("storage_target"))
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))
        changes = payload.get("changes")
        return world_manager.update_world_simple_nbt(
            storage_target,
            world_id,
            custom_path=custom_path,
            player_id=player_id,
            changes=changes if isinstance(changes, dict) else {},
        )
    except Exception as e:
        print(colorize_log(f"[api] Failed to save simple world NBT data: {e}"))
        return {"ok": False, "error": str(e)}


def api_worlds_nbt_advanced_update(data=None):
    try:
        from core import world_manager

        payload = data if isinstance(data, dict) else {}
        world_id = str(payload.get("world_id") or "").strip()
        player_id = str(payload.get("player_id") or "").strip()
        if not world_id:
            return {"ok": False, "error": "world_id is required"}

        storage_target = _normalize_world_storage_target(payload.get("storage_target"))
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))
        nbt_json = str(payload.get("nbt_json") or "")
        return world_manager.update_world_advanced_nbt(
            storage_target,
            world_id,
            custom_path=custom_path,
            player_id=player_id,
            nbt_json=nbt_json,
        )
    except Exception as e:
        print(colorize_log(f"[api] Failed to save advanced world NBT data: {e}"))
        return {"ok": False, "error": str(e)}


def api_worlds_update(data=None):
    try:
        from core import world_manager

        payload = data if isinstance(data, dict) else {}
        world_id = str(payload.get("world_id") or "").strip()
        if not world_id:
            return {"ok": False, "error": "world_id is required"}

        storage_target = _normalize_world_storage_target(payload.get("storage_target"))
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))
        new_world_id = str(payload.get("new_world_id") or "").strip()
        new_title = str(payload.get("new_title") or "").strip()
        return world_manager.update_world(
            storage_target,
            world_id,
            custom_path=custom_path,
            new_world_id=new_world_id,
            new_title=new_title,
        )
    except Exception as e:
        print(colorize_log(f"[api] Failed to update world: {e}"))
        return {"ok": False, "error": str(e)}


def api_worlds_icon_update(data=None):
    try:
        import base64

        from core import world_manager

        payload = data if isinstance(data, dict) else {}
        world_id = str(payload.get("world_id") or "").strip()
        if not world_id:
            return {"ok": False, "error": "world_id is required"}

        image_b64 = str(payload.get("image_data") or "").strip()
        if image_b64.startswith("data:") and "," in image_b64:
            image_b64 = image_b64.split(",", 1)[1]
        if not image_b64:
            return {"ok": False, "error": "image_data is required"}
        try:
            image_data = base64.b64decode(image_b64, validate=True)
        except Exception:
            return {"ok": False, "error": "Invalid PNG image data"}

        storage_target = _normalize_world_storage_target(payload.get("storage_target"))
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))
        return world_manager.replace_world_icon(
            storage_target,
            world_id,
            custom_path=custom_path,
            image_data=image_data,
        )
    except Exception as e:
        print(colorize_log(f"[api] Failed to update world icon: {e}"))
        return {"ok": False, "error": str(e)}


def api_worlds_delete(data=None):
    try:
        from core import world_manager

        payload = data if isinstance(data, dict) else {}
        world_id = str(payload.get("world_id") or "").strip()
        if not world_id:
            return {"ok": False, "error": "world_id is required"}

        storage_target = _normalize_world_storage_target(payload.get("storage_target"))
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))
        return world_manager.delete_world(storage_target, world_id, custom_path=custom_path)
    except Exception as e:
        print(colorize_log(f"[api] Failed to delete world: {e}"))
        return {"ok": False, "error": str(e)}


def api_worlds_open(data=None):
    try:
        from core import world_manager

        payload = data if isinstance(data, dict) else {}
        world_id = str(payload.get("world_id") or "").strip()
        if not world_id:
            return {"ok": False, "error": "world_id is required"}

        storage_target = _normalize_world_storage_target(payload.get("storage_target"))
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))
        return world_manager.open_world_folder(storage_target, world_id, custom_path=custom_path)
    except Exception as e:
        print(colorize_log(f"[api] Failed to open world folder: {e}"))
        return {"ok": False, "error": str(e)}


def api_worlds_search(data=None):
    try:
        from core import world_manager

        payload = data if isinstance(data, dict) else {}
        provider = str(payload.get("provider") or "curseforge").strip().lower()
        if provider != "curseforge":
            return {"ok": False, "error": f"Unknown provider: {provider}"}

        result = world_manager.search_worlds_curseforge(
            search_query=payload.get("search_query", ""),
            game_version=payload.get("game_version", ""),
            category=payload.get("category", ""),
            sort_by=payload.get("sort_by", "relevance"),
            page_size=payload.get("page_size", 20),
            index=payload.get("page_index", 0),
            api_key=payload.get("api_key"),
        )
        return {
            "ok": True,
            "worlds": result.get("worlds", []),
            "total_count": result.get("total", 0),
            "categories": result.get("categories", []),
            "error": result.get("error"),
            "requires_api_key": bool(result.get("requires_api_key")),
        }
    except Exception as e:
        print(colorize_log(f"[api] Failed to search worlds: {e}"))
        return {"ok": False, "error": str(e), "worlds": []}


def api_worlds_versions(data=None):
    try:
        from core import world_manager

        payload = data if isinstance(data, dict) else {}
        provider = str(payload.get("provider") or "curseforge").strip().lower()
        project_id = str(payload.get("project_id") or "").strip()
        if not project_id:
            return {"ok": False, "error": "project_id is required"}
        if provider != "curseforge":
            return {"ok": False, "error": f"Unknown provider: {provider}"}

        versions = world_manager.get_world_files_curseforge(
            project_id,
            game_version=payload.get("game_version", ""),
            api_key=payload.get("api_key"),
        )
        return {"ok": True, "versions": versions}
    except Exception as e:
        print(colorize_log(f"[api] Failed to fetch world versions: {e}"))
        return {"ok": False, "error": str(e), "versions": []}


def api_worlds_install(data=None):
    tracker = None
    try:
        from core import world_manager
        from core.downloader.progress import ProgressTracker, StageWeight

        payload = data if isinstance(data, dict) else {}
        provider = str(payload.get("provider") or "curseforge").strip().lower()
        if provider != "curseforge":
            return {"ok": False, "error": f"Unknown provider: {provider}"}

        storage_target = _normalize_world_storage_target(payload.get("storage_target"))
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))
        download_url = str(payload.get("download_url") or "").strip()
        file_name = str(payload.get("file_name") or "").strip()
        if not download_url or not file_name:
            return {"ok": False, "error": "download_url and file_name are required"}

        world_name = str(payload.get("world_name") or "").strip()
        world_slug = str(payload.get("world_slug") or "").strip()
        progress_key = _normalize_world_install_progress_key(
            payload.get("install_key"),
            f"worlds/{world_slug or world_name or file_name}",
        )
        tracker = ProgressTracker(
            progress_key,
            kind="loader",
            stages=(
                StageWeight("download", 60),
                StageWeight("extract", 35),
                StageWeight("finalize", 5),
            ),
        )
        tracker.update("download", 0, f"Downloading {world_name or world_slug or file_name}")

        def install_progress(stage, done, total):
            label = world_name or world_slug or file_name
            stage_name = str(stage or "download")
            if stage_name == "extract":
                message = f"Extracting {label}"
            elif stage_name == "finalize":
                message = f"Finalizing {label}"
            else:
                message = f"Downloading {label}"
            tracker.update(stage_name, _progress_percent(done, total), message)

        result = world_manager.install_world_archive(
            download_url,
            file_name,
            world_name=world_name,
            world_slug=world_slug,
            storage_target=storage_target,
            custom_path=custom_path,
            progress_callback=install_progress,
        )
        result["install_key"] = progress_key
        if result.get("ok"):
            tracker.update("finalize", 100, result.get("message") or "World installed")
            _finish_world_install_progress(tracker, "installed", result.get("message") or "World installed")
            _send_world_install_notification(
                result.get("title") or world_name or world_slug or file_name
            )
        else:
            _finish_world_install_progress(tracker, "failed", result.get("error") or "Failed to install world")
        return result
    except Exception as e:
        _finish_world_install_progress(tracker, "failed", str(e))
        print(colorize_log(f"[api] Failed to install world: {e}"))
        return {"ok": False, "error": str(e)}


def api_worlds_export(data=None):
    try:
        from core import world_manager
        import base64

        payload = data if isinstance(data, dict) else {}
        storage_target = _normalize_world_storage_target(payload.get("storage_target"))
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))
        world_id = str(payload.get("world_id") or "").strip()
        if not world_id:
            return {"ok": False, "error": "world_id is required"}

        result = world_manager.export_world_zip(
            storage_target,
            world_id,
            custom_path=custom_path,
        )
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error") or "Failed to export world."}

        zip_bytes = result.pop("zip_bytes", b"")
        result["zip_b64"] = base64.b64encode(zip_bytes).decode("ascii")
        return result
    except Exception as e:
        print(colorize_log(f"[api] Failed to export world: {e}"))
        return {"ok": False, "error": str(e)}


def api_worlds_import_scan(data=None):
    try:
        from core import world_manager

        payload = data if isinstance(data, dict) else {}
        zip_bytes = payload.get("zip_bytes")
        if not isinstance(zip_bytes, (bytes, bytearray)) or not zip_bytes:
            return {"ok": False, "error": "Missing world zip payload."}

        return world_manager.scan_world_zip_bytes(bytes(zip_bytes))
    except Exception as e:
        print(colorize_log(f"[api] Failed to scan world zip: {e}"))
        return {"ok": False, "error": str(e)}


def api_worlds_import(data=None):
    try:
        from core import world_manager

        payload = data if isinstance(data, dict) else {}
        zip_bytes = payload.get("zip_bytes")
        if not isinstance(zip_bytes, (bytes, bytearray)) or not zip_bytes:
            return {"ok": False, "error": "Missing world zip payload."}

        storage_target = _normalize_world_storage_target(payload.get("storage_target"))
        custom_path = normalize_custom_storage_directory(payload.get("custom_path"))

        raw_selected = payload.get("selected_roots")
        selected_roots = None
        if isinstance(raw_selected, list):
            selected_roots = [str(item or "").strip().strip("/") for item in raw_selected if item is not None]
            selected_roots = [item for item in selected_roots if item != ""] or selected_roots

        return world_manager.import_world_zip_bytes(
            bytes(zip_bytes),
            storage_target,
            custom_path=custom_path,
            selected_roots=selected_roots,
        )
    except Exception as e:
        print(colorize_log(f"[api] Failed to import world zip: {e}"))
        return {"ok": False, "error": str(e)}
