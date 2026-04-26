from __future__ import annotations

import html
import json
import os
import re as _re
import tempfile

from core.logger import colorize_log
from core.notifications import send_desktop_notification
from core.version_manager import get_version_loaders, scan_categories

from server.api._archive import (
    _extract_import_archive_metadata,
    _extract_pack_mcmeta_description,
)
from server.api._constants import (
    MAX_VERSION_LABEL_LENGTH,
    VALID_LOADER_TYPES,
    VALID_MOD_LOADERS,
)
from server.api._helpers import _loader_display_name
from server.api._validation import (
    _normalize_addon_type,
    _normalize_mod_archive_subfolder,
    _slugify_import_name,
    _validate_addon_filename,
    _validate_mod_loader_type,
    _validate_mod_slug,
    _validate_version_label,
)


__all__ = [
    "api_mods_installed",
    "api_mods_search",
    "api_mods_version_options",
    "api_mods_versions",
    "api_mods_install",
    "api_mods_import",
    "api_mods_delete",
    "api_mods_toggle",
    "api_mods_move",
    "api_mods_set_active_version",
    "api_mods_archive_subfolders",
    "api_mods_update_version_settings",
    "api_mods_detail",
]


def _normalize_install_progress_key(value, fallback: str) -> str:
    raw = str(value or fallback or "").strip()
    key = _re.sub(r"[^A-Za-z0-9._~:/-]+", "-", raw).strip("-._/")
    fallback_key = _re.sub(r"[^A-Za-z0-9._~:/-]+", "-", str(fallback or "addons/install")).strip("-._/")
    return (key or fallback_key or "addons/install")[:180]


def create_progress_suffix(raw_version, file_name: str) -> str:
    source = str(raw_version or os.path.splitext(str(file_name or ""))[0] or "install")
    suffix = _re.sub(r"[^A-Za-z0-9._~-]+", "-", source).strip("-._")
    return (suffix or "install")[:64]


def _progress_percent(done, total) -> float:
    try:
        total_value = float(total or 0)
        done_value = float(done or 0)
    except (TypeError, ValueError):
        return 0.0
    if total_value <= 0:
        return 0.0
    return max(0.0, min(100.0, (done_value / total_value) * 100.0))


def _finish_install_progress(tracker, status: str, message: str) -> None:
    if not tracker:
        return
    try:
        tracker.finish(status=status, message=message, keep_seconds=2.5)
    except Exception:
        pass


def _addon_type_display_name(addon_type: str) -> str:
    return {
        "mods": "Mod",
        "modpacks": "Modpack",
        "resourcepacks": "Resource Pack",
        "shaderpacks": "Shader Pack",
    }.get(str(addon_type or "").strip().lower(), "Addon")


def _send_addon_install_notification(
    addon_type: str,
    addon_name: str,
    *,
    version: str = "",
    mod_loader: str = "",
) -> None:
    try:
        label = _addon_type_display_name(addon_type)
        name = str(addon_name or label).strip() or label
        version_text = str(version or "").strip()
        version_suffix = "" if not version_text or version_text.lower() == "unknown" else f" v{version_text}"
        loader_text = ""
        if addon_type == "mods" and mod_loader:
            loader_text = f" for {_loader_display_name(mod_loader)}"

        send_desktop_notification(
            title=f"[{name}] {label} Installation complete!",
            message=f"{label} {name}{version_suffix}{loader_text} has installed successfully!",
        )
    except Exception as exc:
        print(colorize_log(f"[api] Could not send addon notification: {exc}"))


def api_mods_installed(data=None):
    try:
        from core import mod_manager

        addon_type = (
            _normalize_addon_type((data or {}).get("addon_type"))
            if isinstance(data, dict)
            else "mods"
        )
        mods = mod_manager.get_installed_addons(addon_type)

        return {
            "ok": True,
            "mods": mods,
            "addons": mods,
            "addon_type": addon_type,
        }
    except Exception as e:
        print(colorize_log(f"[api] Failed to get installed mods: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_search(data):
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        addon_type = _normalize_addon_type(data.get("addon_type"))
        provider = (data.get("provider") or "modrinth").lower()
        search_query = data.get("search_query", "")
        game_version = data.get("game_version")
        mod_loader = data.get("mod_loader")
        category = str(data.get("category") or "").strip()
        sort_by = str(data.get("sort_by") or "relevance").strip().lower()
        try:
            page_size = max(1, min(int(data.get("page_size", 20) or 20), 100))
        except Exception:
            page_size = 20
        try:
            page_index = max(0, int(data.get("page_index", 0) or 0))
        except Exception:
            page_index = 0
        api_key = data.get("api_key")

        if provider == "curseforge":
            result = mod_manager.search_projects_curseforge(
                addon_type=addon_type,
                search_query=search_query,
                game_version=game_version,
                mod_loader_type=mod_loader,
                category=category,
                sort_by=sort_by,
                page_size=page_size,
                index=page_index,
                api_key=api_key,
            )
        elif provider == "modrinth":
            result = mod_manager.search_projects_modrinth(
                addon_type=addon_type,
                search_query=search_query,
                game_version=game_version,
                mod_loader=mod_loader,
                category=category,
                sort_by=sort_by,
                limit=page_size,
                offset=page_index * page_size,
            )
        else:
            return {"ok": False, "error": f"Unknown provider: {provider}"}

        return {
            "ok": True,
            "total_count": result.get("total", 0),
            "addon_type": addon_type,
            **result,
        }
    except Exception as e:
        print(colorize_log(f"[api] Failed to search mods: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_version_options(data=None):
    try:
        addon_type = (
            _normalize_addon_type((data or {}).get("addon_type"))
            if isinstance(data, dict)
            else "mods"
        )
        categories = scan_categories(force_refresh=True)
        installed_versions = (
            categories.get("* All", []) if isinstance(categories, dict) else []
        )

        options = []
        seen_versions = set()
        for item in installed_versions:
            category = (item or {}).get("category")
            folder = (item or {}).get("folder")
            if not category or not folder:
                continue

            if addon_type == "mods":
                installed_loaders = get_version_loaders(category, folder)
                has_supported_loader = any(
                    installed_loaders.get(loader_type) for loader_type in VALID_LOADER_TYPES
                )
                if not has_supported_loader:
                    continue

            version_value = folder
            if version_value in seen_versions:
                continue
            seen_versions.add(version_value)

            options.append({
                "category": category,
                "folder": folder,
                "display": (item or {}).get("display_name") or folder,
                "version": version_value,
            })

        options.sort(key=lambda x: x.get("version", ""), reverse=True)

        return {
            "ok": True,
            "versions": options,
            "addon_type": addon_type,
        }
    except Exception as e:
        print(colorize_log(f"[api] Failed to get mod version options: {e}"))
        return {"ok": False, "error": str(e), "versions": []}


def api_mods_versions(data):
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        addon_type = _normalize_addon_type(data.get("addon_type"))
        provider = (data.get("provider") or "modrinth").lower()
        mod_id = data.get("mod_id")
        game_version = data.get("game_version")
        mod_loader = data.get("mod_loader")
        api_key = data.get("api_key")

        if not mod_id:
            return {"ok": False, "error": "mod_id is required"}

        if provider == "curseforge":
            versions = mod_manager.get_mod_files_curseforge(
                mod_id=mod_id,
                game_version=game_version,
                mod_loader_type=mod_loader,
                api_key=api_key,
                addon_type=addon_type,
            )
        elif provider == "modrinth":
            versions = mod_manager.get_mod_versions_modrinth(
                mod_id=mod_id,
                game_version=game_version,
                mod_loader=mod_loader,
            )
            if versions is None:
                return {"ok": False, "error": "Failed to fetch mod versions"}
        else:
            return {"ok": False, "error": f"Unknown provider: {provider}"}

        return {
            "ok": True,
            "versions": versions,
            "addon_type": addon_type,
        }
    except Exception as e:
        print(colorize_log(f"[api] Failed to get mod versions: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_install(data):
    tracker = None
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        addon_type = _normalize_addon_type(data.get("addon_type"))
        provider = (data.get("provider") or "modrinth").lower()
        mod_id = data.get("mod_id")
        mod_slug = (data.get("mod_slug") or "").strip().lower()
        mod_name = data.get("mod_name", mod_slug)
        mod_loader = str(data.get("mod_loader") or "").strip().lower()
        compatibility_types = mod_manager.normalize_addon_compatibility_types(
            addon_type,
            data.get("compatibility_types"),
            fallback=mod_loader,
        )
        if addon_type != "mods" and not mod_loader and compatibility_types:
            mod_loader = compatibility_types[0]
        download_url = data.get("download_url")
        file_name = (data.get("file_name") or "").strip()
        file_id = str(data.get("file_id") or "").strip()
        game_versions = data.get("game_versions") if isinstance(data.get("game_versions"), list) else []
        version_loaders = data.get("loaders") if isinstance(data.get("loaders"), list) else []
        description = data.get("description", "")
        icon_url = data.get("icon_url", "")
        raw_version = str(data.get("version", "unknown") or "unknown").strip()

        if not mod_slug or not download_url or not file_name:
            return {"ok": False, "error": "Missing required fields"}
        if addon_type == "mods" and not mod_loader:
            return {"ok": False, "error": "mod_loader is required for mods"}

        if addon_type == "mods" and not _validate_mod_loader_type(mod_loader.lower()):
            valid = ", ".join(VALID_MOD_LOADERS)
            return {"ok": False, "error": f"Invalid mod_loader (must be one of: {valid})"}

        if not _validate_mod_slug(mod_slug):
            return {"ok": False, "error": "Invalid mod_slug format"}

        if not _validate_addon_filename(file_name, addon_type):
            return {"ok": False, "error": "Invalid file_name format"}

        progress_key = _normalize_install_progress_key(
            data.get("install_key"),
            f"addons/{addon_type}/{mod_slug}/{create_progress_suffix(raw_version, file_name)}",
        )

        if addon_type == "modpacks":
            from core.downloader.http import CLIENT
            from core.downloader.progress import ProgressTracker, StageWeight
            from core.mod_manager._validation import _normalize_download_url

            normalized_url = _normalize_download_url(download_url)
            if not normalized_url:
                return {"ok": False, "error": "Invalid download URL"}

            tracker = ProgressTracker(
                progress_key,
                kind="loader",
                stages=(
                    StageWeight("download", 35),
                    StageWeight("install", 60),
                    StageWeight("finalize", 5),
                ),
            )
            tracker.update("download", 0, f"Downloading {mod_name}")
            ext = os.path.splitext(file_name)[1].lower()
            temp_path = ""
            try:
                fd, temp_path = tempfile.mkstemp(suffix=ext or ".zip")
                os.close(fd)
                os.remove(temp_path)

                def download_progress(done, total):
                    pct = _progress_percent(done, total)
                    tracker.update("download", pct, f"Downloading {mod_name}")

                CLIENT.download(normalized_url, temp_path, progress_cb=download_progress, force=True)
                tracker.update("download", 100, f"Downloaded {mod_name}")
                with open(temp_path, "rb") as f:
                    archive_data = f.read()
            finally:
                if temp_path:
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

            source_format = "mrpack" if ext == ".mrpack" else "zip"

            def import_progress(done, total):
                tracker.update("install", _progress_percent(done, total), f"Installing {mod_name}")

            tracker.update("install", 0, f"Installing {mod_name}")
            result = mod_manager.import_modpack(
                archive_data,
                file_name=file_name,
                source_format=source_format,
                progress_callback=import_progress,
                is_imported=False,
                source_metadata={
                    "name": mod_name,
                    "description": description,
                    "icon_url": icon_url,
                    "provider": provider,
                    "mod_id": mod_id,
                    "mod_slug": mod_slug,
                    "download_url": download_url,
                    "version": raw_version,
                },
            )
            if result.get("ok"):
                tracker.update("finalize", 100, f"Installed {mod_name}")
                _finish_install_progress(tracker, "installed", f"Installed {mod_name}")
                _send_addon_install_notification(
                    addon_type,
                    mod_name,
                    version=raw_version,
                )
                result.update({
                    "message": f"Successfully installed {mod_name}",
                    "addon_type": addon_type,
                    "provider": provider,
                    "mod_id": mod_id,
                    "install_key": progress_key,
                })
            else:
                _finish_install_progress(tracker, "failed", result.get("error") or f"Failed to install {mod_name}")
            return result

        if len(raw_version) > MAX_VERSION_LABEL_LENGTH * 4:
            return {"ok": False, "error": "Invalid version label"}
        version_label = mod_manager.normalize_version_label(raw_version)
        if not _validate_version_label(version_label):
            return {"ok": False, "error": "Invalid version label"}

        from core.downloader.progress import ProgressTracker, StageWeight

        tracker = ProgressTracker(
            progress_key,
            kind="loader",
            stages=(
                StageWeight("download", 85),
                StageWeight("finalize", 15),
            ),
        )
        tracker.update("download", 0, f"Downloading {mod_name}")

        def download_progress(done, total):
            tracker.update("download", _progress_percent(done, total), f"Downloading {mod_name}")

        success = mod_manager.download_addon_file(
            download_url=download_url,
            addon_type=addon_type,
            mod_slug=mod_slug,
            version_label=version_label,
            file_name=file_name,
            mod_loader=mod_loader,
            progress_cb=download_progress,
        )

        if not success:
            _finish_install_progress(tracker, "failed", "Failed to download addon file")
            return {"ok": False, "error": "Failed to download mod file"}

        tracker.update("finalize", 15, f"Saving {mod_name}")

        mod_manager.save_addon_version_metadata(
            addon_type,
            mod_slug,
            version_label,
            {
                "version": raw_version,
                "mod_loader": mod_loader,
                "compatibility_types": compatibility_types,
                "file_name": file_name,
                "file_id": file_id,
                "download_url": download_url,
                "provider": provider,
                "game_versions": game_versions,
                "loaders": version_loaders,
                "overwrite_classes": False,
                "source_subfolder": "",
                "addon_type": addon_type,
            },
            mod_loader=mod_loader,
        )

        mod_dir = mod_manager.get_addon_dir(addon_type, mod_slug, mod_loader=mod_loader)
        meta_file = os.path.join(mod_dir, "mod_meta.json")
        if os.path.isfile(meta_file):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = {}
        else:
            existing = {}

        existing.update({
            "mod_id": mod_id,
            "name": mod_name,
            "description": description,
            "icon_url": icon_url,
            "provider": provider,
            "mod_loader": mod_loader,
            "compatibility_types": compatibility_types,
            "addon_type": addon_type,
            "disabled": existing.get("disabled", False),
        })
        if not existing.get("active_version"):
            existing["active_version"] = version_label
        mod_manager.save_addon_metadata(addon_type, mod_slug, existing, mod_loader=mod_loader)

        if icon_url:
            mod_manager.download_addon_icon(
                icon_url, addon_type, mod_slug, mod_loader=mod_loader
            )

        tracker.update("finalize", 100, f"Installed {mod_name}")
        _finish_install_progress(tracker, "installed", f"Installed {mod_name}")
        _send_addon_install_notification(
            addon_type,
            mod_name,
            version=raw_version,
            mod_loader=mod_loader,
        )

        print(colorize_log(
            f"[api] Installed {addon_type} version: {mod_name} v{raw_version} "
            f"({mod_loader or addon_type})"
        ))

        return {
            "ok": True,
            "message": f"Successfully installed {mod_name} v{raw_version}",
            "addon_type": addon_type,
            "install_key": progress_key,
        }
    except Exception as e:
        _finish_install_progress(tracker, "failed", str(e))
        print(colorize_log(f"[api] Failed to install mod: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_import(data):
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        addon_type = _normalize_addon_type(data.get("addon_type"))
        mod_loader = (data.get("mod_loader") or "").strip().lower()
        compatibility_types = mod_manager.normalize_addon_compatibility_types(
            addon_type,
            data.get("compatibility_types"),
            fallback=mod_loader,
        )
        if addon_type != "mods" and not mod_loader and compatibility_types:
            mod_loader = compatibility_types[0]
        file_name = str(data.get("file_name") or data.get("jar_name") or "").strip()
        file_data = data.get("file_data")
        if file_data is None:
            file_data = data.get("jar_data")

        if addon_type == "mods" and (not mod_loader or not _validate_mod_loader_type(mod_loader)):
            valid = ", ".join(VALID_MOD_LOADERS)
            return {"ok": False, "error": f"mod_loader must be one of: {valid}"}
        if not _validate_addon_filename(file_name, addon_type):
            if addon_type == "mods":
                expected_exts = ".jar or .zip"
            elif addon_type == "modpacks":
                expected_exts = ".hlmp, .mrpack, or .zip"
            else:
                expected_exts = ".zip"
            return {"ok": False, "error": f"A valid {expected_exts} filename is required"}
        if not isinstance(file_data, (bytes, bytearray)):
            return {"ok": False, "error": "Invalid addon file data"}
        if not file_data or len(file_data) == 0:
            return {"ok": False, "error": "Addon file data is empty"}

        if addon_type == "modpacks":
            ext = os.path.splitext(file_name)[1].lower()
            source_format = "mrpack" if ext == ".mrpack" else "zip"
            result = mod_manager.import_modpack(
                bytes(file_data),
                file_name=file_name,
                source_format=source_format,
            )
            if result.get("ok"):
                result["message"] = result.get("message") or "Successfully imported modpack"
                result["addon_type"] = addon_type
            return result

        if addon_type == "mods":
            inferred = _extract_import_archive_metadata(file_name, file_data)
        else:
            inferred = {
                "mod_slug": _slugify_import_name(file_name),
                "mod_name": os.path.splitext(file_name)[0] or "Imported Addon",
                "version_label": "imported",
                "detected_loader": "",
            }

        default_base_name = "Imported Mod" if addon_type == "mods" else "Imported Addon"
        base_name = str(
            inferred.get("mod_name") or os.path.splitext(file_name)[0] or default_base_name
        ).strip()
        mod_slug = str(inferred.get("mod_slug") or "").strip().lower()
        if not _validate_mod_slug(mod_slug):
            mod_slug = (
                _re.sub(r"[^a-z0-9]+", "-", base_name.lower()).strip("-") or "imported-mod"
            )

        inferred_version = str(inferred.get("version_label") or "imported").strip() or "imported"
        version_label = mod_manager.normalize_version_label(inferred_version)
        if not _validate_version_label(version_label):
            version_label = "imported"

        detected_loader = str(inferred.get("detected_loader") or "").strip().lower()

        ver_dir = mod_manager.get_addon_version_dir(
            addon_type, mod_slug, version_label, mod_loader=mod_loader
        )
        file_path = os.path.join(ver_dir, file_name)
        with open(file_path, "wb") as f:
            f.write(file_data)

        mod_manager.save_addon_version_metadata(
            addon_type,
            mod_slug,
            version_label,
            {
                "version": inferred_version,
                "mod_loader": mod_loader,
                "compatibility_types": compatibility_types,
                "file_name": file_name,
                "provider": "imported",
                "overwrite_classes": False,
                "source_subfolder": "",
                "addon_type": addon_type,
            },
            mod_loader=mod_loader,
        )

        mod_dir = mod_manager.get_addon_dir(addon_type, mod_slug, mod_loader=mod_loader)
        meta_file = os.path.join(mod_dir, "mod_meta.json")
        if os.path.isfile(meta_file):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = {}
        else:
            existing = {}

        import_description = f"Imported from local archive: {file_name}"
        if addon_type == "resourcepacks":
            extracted_description = _extract_pack_mcmeta_description(file_data)
            if extracted_description:
                import_description = extracted_description

        existing.update({
            "name": base_name,
            "description": import_description,
            "provider": "imported",
            "mod_loader": mod_loader,
            "compatibility_types": compatibility_types,
            "addon_type": addon_type,
            "is_imported": True,
            "disabled": existing.get("disabled", False),
        })
        if not existing.get("active_version"):
            existing["active_version"] = version_label
        mod_manager.save_addon_metadata(addon_type, mod_slug, existing, mod_loader=mod_loader)

        if addon_type in ("resourcepacks", "shaderpacks"):
            mod_manager.save_addon_import_icon(
                addon_type, mod_slug, file_data, mod_loader=mod_loader
            )

        print(colorize_log(
            f"[api] Imported custom {addon_type}: {file_name} ({mod_loader or addon_type})"
        ))

        response = {
            "ok": True,
            "message": f"Successfully imported {base_name}",
            "mod_slug": mod_slug,
            "version_label": version_label,
            "addon_type": addon_type,
        }
        if addon_type == "mods" and detected_loader and detected_loader != mod_loader:
            response["warning"] = (
                f"Archive metadata suggests loader '{detected_loader}', "
                f"but the mod was imported into '{mod_loader}'."
            )
        return response
    except Exception as e:
        print(colorize_log(f"[api] Failed to import mod: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_delete(data):
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        addon_type = _normalize_addon_type(data.get("addon_type"))
        mod_slug = (data.get("mod_slug") or "").strip().lower()
        mod_loader = (data.get("mod_loader") or "").strip().lower()
        version_label = data.get("version_label")

        if not mod_slug:
            return {"ok": False, "error": "Missing mod_slug"}
        if addon_type == "mods" and not mod_loader:
            return {"ok": False, "error": "Missing mod_loader"}

        if addon_type == "mods" and not _validate_mod_loader_type(mod_loader):
            return {"ok": False, "error": "Invalid mod_loader"}

        if not _validate_mod_slug(mod_slug):
            return {"ok": False, "error": "Invalid mod_slug format"}

        if version_label is not None and not _validate_version_label(str(version_label)):
            return {"ok": False, "error": "Invalid version_label"}

        success = mod_manager.delete_addon(
            addon_type, mod_slug, version_label, mod_loader=mod_loader
        )

        if success:
            what = f"{mod_slug}/{version_label}" if version_label else mod_slug
            return {"ok": True, "message": f"Deleted {what}", "addon_type": addon_type}
        return {"ok": False, "error": "Failed to delete mod"}
    except Exception as e:
        print(colorize_log(f"[api] Failed to delete mod: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_toggle(data):
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        addon_type = _normalize_addon_type(data.get("addon_type"))
        mod_slug = (data.get("mod_slug") or "").strip().lower()
        mod_loader = (data.get("mod_loader") or "").strip().lower()
        disabled = bool(data.get("disabled", False))

        if not mod_slug:
            return {"ok": False, "error": "Missing mod_slug"}
        if addon_type == "mods" and not mod_loader:
            return {"ok": False, "error": "Missing mod_loader"}

        if addon_type == "mods" and not _validate_mod_loader_type(mod_loader):
            return {"ok": False, "error": "Invalid mod_loader"}

        if not _validate_mod_slug(mod_slug):
            return {"ok": False, "error": "Invalid mod_slug format"}

        success = mod_manager.toggle_addon_disabled(
            addon_type, mod_slug, disabled, mod_loader=mod_loader
        )
        if success:
            return {"ok": True, "disabled": disabled, "addon_type": addon_type}
        return {"ok": False, "error": "Failed to toggle mod"}
    except Exception as e:
        print(colorize_log(f"[api] Failed to toggle mod: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_move(data):
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        addon_type = _normalize_addon_type(data.get("addon_type"))
        if addon_type != "mods":
            return {"ok": False, "error": "Only mods can be moved between loaders"}

        mod_slug = (data.get("mod_slug") or "").strip().lower()
        mod_loader = (data.get("mod_loader") or "").strip().lower()
        target_loader = (data.get("target_loader") or "").strip().lower()

        if not mod_slug or not mod_loader or not target_loader:
            return {"ok": False, "error": "Missing mod_slug, mod_loader or target_loader"}

        if not _validate_mod_loader_type(mod_loader):
            return {"ok": False, "error": "Invalid mod_loader"}

        if not _validate_mod_loader_type(target_loader):
            return {"ok": False, "error": "Invalid target_loader"}

        if mod_loader == target_loader:
            return {"ok": False, "error": "Source and target loader are the same"}

        if not _validate_mod_slug(mod_slug):
            return {"ok": False, "error": "Invalid mod_slug format"}

        mod_display_name = mod_slug
        try:
            source_dir = os.path.join(
                mod_manager.get_mods_storage_dir(), mod_loader, mod_slug
            )
            meta_file = os.path.join(source_dir, "mod_meta.json")
            if os.path.isfile(meta_file):
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                mod_display_name = (
                    str(meta.get("name") or meta.get("mod_name") or mod_slug).strip() or mod_slug
                )
        except Exception:
            pass

        ok, message = mod_manager.move_mod_to_loader(mod_loader, mod_slug, target_loader)
        if not ok:
            return {"ok": False, "error": message or "Failed to move mod"}

        return {
            "ok": True,
            "message": (
                f"Moved <i>{html.escape(mod_display_name)}</i> from "
                f"<b>{html.escape(_loader_display_name(mod_loader))}</b> "
                f"to <b>{html.escape(_loader_display_name(target_loader))}</b>"
            ),
            "mod_slug": mod_slug,
            "mod_name": mod_display_name,
            "mod_loader": target_loader,
        }
    except Exception as e:
        print(colorize_log(f"[api] Failed to move mod: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_set_active_version(data):
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        addon_type = _normalize_addon_type(data.get("addon_type"))
        mod_slug = (data.get("mod_slug") or "").strip().lower()
        mod_loader = (data.get("mod_loader") or "").strip().lower()
        version_label = data.get("version_label")

        if not mod_slug or not version_label:
            return {"ok": False, "error": "Missing mod_slug or version_label"}
        if addon_type == "mods" and not mod_loader:
            return {"ok": False, "error": "Missing mod_loader"}

        if addon_type == "mods" and not _validate_mod_loader_type(mod_loader):
            return {"ok": False, "error": "Invalid mod_loader"}

        if not _validate_mod_slug(mod_slug):
            return {"ok": False, "error": "Invalid mod_slug format"}

        if not _validate_version_label(str(version_label)):
            return {"ok": False, "error": "Invalid version_label"}

        success = mod_manager.set_addon_active_version(
            addon_type, mod_slug, version_label, mod_loader=mod_loader
        )
        if success:
            return {"ok": True, "active_version": version_label, "addon_type": addon_type}
        return {"ok": False, "error": "Failed to set active version"}
    except Exception as e:
        print(colorize_log(f"[api] Failed to set active version: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_archive_subfolders(data):
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        mod_slug = (data.get("mod_slug") or "").strip().lower()
        mod_loader = (data.get("mod_loader") or "").strip().lower()
        version_label = str(data.get("version_label") or "").strip()

        if not mod_slug or not mod_loader or not version_label:
            return {"ok": False, "error": "Missing mod_slug, mod_loader or version_label"}

        if not _validate_mod_loader_type(mod_loader):
            return {"ok": False, "error": "Invalid mod_loader"}
        if not _validate_mod_slug(mod_slug):
            return {"ok": False, "error": "Invalid mod_slug format"}
        if not _validate_version_label(version_label):
            return {"ok": False, "error": "Invalid version_label"}

        version_dir = mod_manager.get_mod_version_dir(mod_loader, mod_slug, version_label)
        version_meta_path = os.path.join(version_dir, "version_meta.json")
        preferred_file_name = ""
        if os.path.isfile(version_meta_path):
            try:
                with open(version_meta_path, "r", encoding="utf-8") as f:
                    version_meta = json.load(f)
                preferred_file_name = str(version_meta.get("file_name") or "").strip()
            except Exception:
                preferred_file_name = ""

        source_folders = mod_manager.list_mod_archive_source_folders(
            mod_loader,
            mod_slug,
            version_label,
            preferred_file_name=preferred_file_name,
        )

        options = [{"value": "", "label": "/ (default)"}]
        seen_values = {""}
        for item in source_folders:
            try:
                normalized = _normalize_mod_archive_subfolder(item)
            except ValueError:
                continue
            if not normalized or normalized in seen_values:
                continue
            seen_values.add(normalized)
            options.append({"value": normalized, "label": normalized})

        return {"ok": True, "subfolders": options}
    except Exception as e:
        print(colorize_log(f"[api] Failed to list archive subfolders: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_update_version_settings(data):
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        mod_slug = (data.get("mod_slug") or "").strip().lower()
        mod_loader = (data.get("mod_loader") or "").strip().lower()
        version_label = str(data.get("version_label") or "").strip()

        if not mod_slug or not mod_loader or not version_label:
            return {"ok": False, "error": "Missing mod_slug, mod_loader or version_label"}

        if not _validate_mod_loader_type(mod_loader):
            return {"ok": False, "error": "Invalid mod_loader"}
        if not _validate_mod_slug(mod_slug):
            return {"ok": False, "error": "Invalid mod_slug format"}
        if not _validate_version_label(version_label):
            return {"ok": False, "error": "Invalid version_label"}

        version_dir = mod_manager.get_mod_version_dir(mod_loader, mod_slug, version_label)
        version_meta_path = os.path.join(version_dir, "version_meta.json")
        if not os.path.isfile(version_meta_path):
            return {"ok": False, "error": "Version metadata not found"}

        try:
            with open(version_meta_path, "r", encoding="utf-8") as f:
                version_meta = json.load(f)
        except Exception:
            version_meta = {}

        overwrite_classes = bool(version_meta.get("overwrite_classes", False))
        if "overwrite_classes" in data:
            overwrite_classes = bool(data.get("overwrite_classes"))

        if "source_subfolder" in data:
            try:
                source_subfolder = _normalize_mod_archive_subfolder(data.get("source_subfolder"))
            except ValueError as e:
                return {"ok": False, "error": str(e)}
        else:
            try:
                source_subfolder = _normalize_mod_archive_subfolder(
                    version_meta.get("source_subfolder", "")
                )
            except ValueError:
                source_subfolder = ""

        if not overwrite_classes:
            source_subfolder = ""
        else:
            preferred_file_name = str(version_meta.get("file_name") or "").strip()
            available_subfolders = set(
                mod_manager.list_mod_archive_source_folders(
                    mod_loader,
                    mod_slug,
                    version_label,
                    preferred_file_name=preferred_file_name,
                )
            )
            if source_subfolder not in available_subfolders:
                return {
                    "ok": False,
                    "error": "Selected source_subfolder was not found in archive",
                }

        version_meta["overwrite_classes"] = overwrite_classes
        version_meta["source_subfolder"] = source_subfolder
        mod_manager.save_version_metadata(mod_loader, mod_slug, version_label, version_meta)

        return {
            "ok": True,
            "overwrite_classes": overwrite_classes,
            "source_subfolder": source_subfolder,
        }
    except Exception as e:
        print(colorize_log(f"[api] Failed to update version settings: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_detail(data):
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        addon_type = _normalize_addon_type(data.get("addon_type"))
        provider = (data.get("provider") or "modrinth").lower()
        mod_id = data.get("mod_id")

        if not mod_id:
            return {"ok": False, "error": "mod_id is required"}

        if provider == "modrinth":
            detail = mod_manager.get_project_detail_modrinth(mod_id, addon_type=addon_type)
        elif provider == "curseforge":
            detail = mod_manager.get_project_detail_curseforge(mod_id)
        else:
            return {"ok": False, "error": f"Unknown provider: {provider}"}

        if detail:
            return {"ok": True, "addon_type": addon_type, **detail}
        return {"ok": False, "error": "Failed to fetch mod details"}
    except Exception as e:
        print(colorize_log(f"[api] Failed to get mod detail: {e}"))
        return {"ok": False, "error": str(e)}
