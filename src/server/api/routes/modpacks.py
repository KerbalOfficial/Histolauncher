from __future__ import annotations

import os
import shutil

from core.logger import safe_print
from launcher.i18n import t

from core.mod_manager._constants import CURSEFORGE_MODPACK_LOADERS
from server.api._constants import MAX_MODPACKS_IMPORT_PAYLOAD, VALID_MODPACK_LOADERS
from server.api.file_dialogs import (
    open_native_file_picker,
    save_native_file_picker,
    validate_selected_file,
)
from server.api._helpers import (
    _begin_operation,
    _clear_operation,
    _raise_if_operation_cancelled,
)
from server.api._state import STATE, CancelledOperationError
from server.api._validation import (
    _normalize_addon_type,
    _validate_modpack_loader_type,
    _validate_mod_slug,
    _validate_modpack_slug,
    _validate_version_label,
)


__all__ = [
    "api_modpacks_installed",
    "api_modpacks_export",
    "api_modpacks_export_versions",
    "api_modpacks_import_progress",
    "api_modpacks_import",
    "api_modpacks_import_select",
    "api_modpacks_toggle_mod",
    "api_modpacks_set_mod_overwrite",
    "api_modpacks_toggle",
    "api_modpacks_delete",
]


def api_modpacks_installed(data=None):
    try:
        from core import mod_manager

        packs = mod_manager.get_installed_modpacks()
        return {"ok": True, "modpacks": packs}
    except Exception as e:
        safe_print(f"[api] Failed to get installed modpacks: {e}")
        return {"ok": False, "error": str(e)}


def api_modpacks_export_versions(data=None):
    try:
        from core import mod_manager

        payload = data if isinstance(data, dict) else {}
        export_format = str(payload.get("export_format") or "histolauncher").strip().lower()
        mod_loader = str(payload.get("mod_loader") or "").strip().lower()
        minecraft_version = str(payload.get("minecraft_version") or "").strip()
        minecraft_versions = mod_manager.get_modpack_export_minecraft_versions(export_format, mod_loader)
        loader_versions = []
        if minecraft_version:
            loader_versions = mod_manager.get_modpack_export_loader_versions(
                mod_loader,
                minecraft_version,
                export_format=export_format,
            )
        return {
            "ok": True,
            "minecraft_versions": minecraft_versions,
            "loader_versions": loader_versions,
        }
    except Exception as e:
        safe_print(f"[api] Failed to get modpack export versions: {e}")
        return {"ok": False, "error": str(e), "minecraft_versions": [], "loader_versions": []}


def api_modpacks_export(data):
    operation_id = ""
    try:
        import base64
        import re as _re
        import tempfile

        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        name = (data.get("name") or "").strip()
        version = (data.get("version") or "").strip()
        author = (data.get("author") or "").strip()
        description = (data.get("description") or "").strip()
        mod_loader = (data.get("mod_loader") or "").strip().lower()
        mods_list = data.get("mods") or []
        resourcepacks_list = data.get("resourcepacks") or []
        shaderpacks_list = data.get("shaderpacks") or []
        datapacks_list = data.get("datapacks") or []
        minecraft_version = (data.get("minecraft_version") or "").strip()
        loader_version = (data.get("loader_version") or "").strip()
        raw_export_format = str(data.get("export_format") or "histolauncher").strip().lower()
        save_to_disk = bool(data.get("save_to_disk", False))
        operation_id = _begin_operation(data.get("operation_id"))

        export_formats = {
            "histolauncher": {
                "format": "histolauncher",
                "extension": ".hlmp",
                "description": "Histolauncher Modpack",
                "filetypes": [("Histolauncher Modpack", "*.hlmp")],
            },
            "hlmp": {
                "format": "histolauncher",
                "extension": ".hlmp",
                "description": "Histolauncher Modpack",
                "filetypes": [("Histolauncher Modpack", "*.hlmp")],
            },
            "modrinth": {
                "format": "modrinth",
                "extension": ".mrpack",
                "description": "Modrinth Modpack",
                "filetypes": [("Modrinth Modpack", "*.mrpack")],
            },
            "mrpack": {
                "format": "modrinth",
                "extension": ".mrpack",
                "description": "Modrinth Modpack",
                "filetypes": [("Modrinth Modpack", "*.mrpack")],
            },
            "curseforge": {
                "format": "curseforge",
                "extension": ".zip",
                "description": "CurseForge Modpack",
                "filetypes": [("CurseForge Modpack", "*.zip")],
            },
            "curse": {
                "format": "curseforge",
                "extension": ".zip",
                "description": "CurseForge Modpack",
                "filetypes": [("CurseForge Modpack", "*.zip")],
            },
        }
        format_spec = export_formats.get(raw_export_format)
        if not format_spec:
            return {"ok": False, "error": "export_format must be histolauncher, modrinth, or curseforge"}

        if not name or len(name) > 64:
            return {"ok": False, "error": "Name must be 1-64 characters"}
        if _re.search(r'[<>:"/\\|?*\x00-\x1f]', name):
            return {"ok": False, "error": "Name contains forbidden characters"}
        if not version or len(version) > 16:
            return {"ok": False, "error": "Version must be 1-16 characters"}
        if len(author) > 64:
            return {"ok": False, "error": "Author must be 64 characters or fewer"}
        if _re.search(r'[<>:"/\\|?*\x00-\x1f]', author):
            return {"ok": False, "error": "Author contains forbidden characters"}
        if len(description) > 8192:
            return {"ok": False, "error": "Description too long (max 8192)"}
        if not _validate_modpack_loader_type(mod_loader):
            valid = ", ".join(VALID_MODPACK_LOADERS)
            return {"ok": False, "error": f"mod_loader must be one of: {valid}"}
        if format_spec["format"] == "curseforge" and mod_loader not in CURSEFORGE_MODPACK_LOADERS:
            valid = ", ".join(sorted(CURSEFORGE_MODPACK_LOADERS))
            return {"ok": False, "error": f"CurseForge modpacks support these loaders only: {valid}"}
        if len(minecraft_version) > 32:
            return {"ok": False, "error": "minecraft_version must be 32 characters or fewer"}
        if len(loader_version) > 64:
            return {"ok": False, "error": "loader_version must be 64 characters or fewer"}

        normalized_mods = []
        for entry in mods_list:
            if not isinstance(entry, dict):
                continue
            mod_slug = (entry.get("mod_slug") or "").strip().lower()
            version_label = (entry.get("version_label") or "").strip()
            if not _validate_mod_slug(mod_slug):
                continue
            if not _validate_version_label(version_label):
                continue
            normalized_entry = {
                "mod_slug": mod_slug,
                "version_label": version_label,
                "mod_name": (entry.get("mod_name") or mod_slug).strip(),
                "disabled": bool(entry.get("disabled", False)),
            }
            if "overwrite_classes" in entry:
                normalized_entry["overwrite_classes"] = bool(entry.get("overwrite_classes", False))
            if "source_subfolder" in entry:
                source_value = str(entry.get("source_subfolder") or "")
                if len(source_value) > 512:
                    return {"ok": False, "error": "source_subfolder too long"}
                normalized_entry["source_subfolder"] = source_value
            normalized_mods.append(normalized_entry)

        def _normalize_extra_addons(raw_entries, addon_label):
            normalized = []
            if not isinstance(raw_entries, list):
                return normalized
            for entry in raw_entries:
                if not isinstance(entry, dict):
                    continue
                mod_slug = (
                    entry.get("mod_slug")
                    or entry.get("addon_slug")
                    or ""
                )
                mod_slug = str(mod_slug).strip().lower()
                version_label = (entry.get("version_label") or "").strip()
                if not _validate_mod_slug(mod_slug):
                    continue
                if not _validate_version_label(version_label):
                    continue
                normalized.append({
                    "mod_slug": mod_slug,
                    "version_label": version_label,
                    "mod_name": (entry.get("mod_name") or entry.get("addon_name") or mod_slug).strip(),
                    "disabled": bool(entry.get("disabled", False)),
                    "addon_type": addon_label,
                })
            return normalized

        normalized_resourcepacks = _normalize_extra_addons(resourcepacks_list, "resourcepacks")
        normalized_shaderpacks = _normalize_extra_addons(shaderpacks_list, "shaderpacks")
        normalized_datapacks = _normalize_extra_addons(datapacks_list, "datapacks")

        image_data = None
        image_b64 = data.get("image_data")
        if image_b64:
            image_data = base64.b64decode(image_b64)

        archive_bytes = mod_manager.export_modpack(
            name=name,
            version=version,
            description=description,
            mod_loader=mod_loader,
            mods=normalized_mods,
            image_data=image_data,
            cancel_check=lambda: _raise_if_operation_cancelled(operation_id),
            resourcepacks=normalized_resourcepacks,
            shaderpacks=normalized_shaderpacks,
            datapacks=normalized_datapacks,
            author=author,
            export_format=format_spec["format"],
            minecraft_version=minecraft_version,
            loader_version=loader_version,
        )

        file_name = f"{name}{format_spec['extension']}"

        if save_to_disk:
            temp_fd = None
            temp_path = None
            try:
                temp_fd, temp_path = tempfile.mkstemp(
                    prefix="histolauncher_modpack_", suffix=format_spec["extension"]
                )
                with os.fdopen(temp_fd, "wb") as tmpf:
                    tmpf.write(archive_bytes)
                temp_fd = None

                save_path = ""
                dialog_failed = False

                try:
                    _raise_if_operation_cancelled(operation_id)
                    save_path = save_native_file_picker(
                        initialfile=file_name,
                        defaultextension=format_spec["extension"],
                        filetypes=[*format_spec["filetypes"], (t("native.fileDialogs.allFiles"), "*.*")],
                        initialdir=os.path.expanduser("~"),
                        title=t("native.fileDialogs.saveModpackExportTitle", {"name": name}),
                    )
                except Exception as dialog_err:
                    dialog_failed = True
                    safe_print(
                        f"[api] Modpack save dialog unavailable, "
                        f"using fallback path: {dialog_err}"
                    )

                if save_path and str(save_path).strip():
                    _raise_if_operation_cancelled(operation_id)
                    final_path = save_path
                elif not dialog_failed:
                    return {
                        "ok": False,
                        "cancelled": True,
                        "error": "Export cancelled by user",
                    }
                else:
                    downloads_dir = os.path.expanduser("~/Downloads")
                    if not os.path.isdir(downloads_dir):
                        downloads_dir = os.path.expanduser("~")

                    base_name, ext = os.path.splitext(file_name)
                    final_path = os.path.join(downloads_dir, file_name)
                    counter = 1
                    while os.path.exists(final_path):
                        final_path = os.path.join(
                            downloads_dir, f"{base_name}_{counter}{ext}"
                        )
                        counter += 1

                _raise_if_operation_cancelled(operation_id)
                shutil.copy2(temp_path, final_path)
                return {
                    "ok": True,
                    "filename": os.path.basename(final_path),
                    "filepath": final_path,
                    "size_bytes": os.path.getsize(final_path),
                    "message": f"Exported to {os.path.dirname(final_path)}",
                }
            finally:
                try:
                    if temp_fd is not None:
                        os.close(temp_fd)
                except Exception:
                    pass
                try:
                    if temp_path and os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception:
                    pass

        return {
            "ok": True,
            "modpack_data": base64.b64encode(archive_bytes).decode("ascii"),
            "hlmp_data": base64.b64encode(archive_bytes).decode("ascii"),
            "filename": file_name,
            "extension": format_spec["extension"],
            "export_format": format_spec["format"],
            "type_description": format_spec["description"],
            "size_bytes": len(archive_bytes),
        }
    except CancelledOperationError:
        return {
            "ok": False,
            "cancelled": True,
            "error": "Export cancelled by user",
        }
    except Exception as e:
        safe_print(f"[api] Failed to export modpack: {e}")
        return {"ok": False, "error": f"Failed to export modpack: {str(e)}"}
    finally:
        _clear_operation(operation_id)


def api_modpacks_import_progress(import_id):
    if not import_id:
        return {"ok": False, "error": "No ID"}
    if import_id in STATE.import_progress:
        val = STATE.import_progress[import_id]
        if val["total"] > 0:
            pct = int((val["done"] / val["total"]) * 100)
        else:
            pct = 100
        return {"ok": True, "percent": pct}
    return {"ok": False, "error": "Not found"}


def api_modpacks_import_select(data):
    operation_id = ""
    progress_id = ""
    try:
        payload = data if isinstance(data, dict) else {}
        operation_id = str(payload.get("operation_id") or payload.get("import_id") or "").strip()
        progress_id = str(payload.get("import_id") or operation_id or "").strip()

        selected_path = open_native_file_picker(
            title=t(
                "native.fileDialogs.openModpackImportTitle",
                default="Import Modpack",
            ),
            filetypes=[
                ("Modpack archives", "*.hlmp *.mrpack *.zip"),
                (t("native.fileDialogs.allFiles"), "*.*"),
            ],
        )
        selected = validate_selected_file(
            selected_path,
            allowed_extensions={".hlmp", ".mrpack", ".zip"},
            max_size=MAX_MODPACKS_IMPORT_PAYLOAD,
            label="modpack archive",
        )
        if not selected.get("ok"):
            return selected

        _raise_if_operation_cancelled(operation_id)

        file_name = str(selected.get("file_name") or "")
        extension = os.path.splitext(file_name)[1].lower()
        source_format = "mrpack" if extension == ".mrpack" else ("hlmp" if extension == ".hlmp" else "zip")
        return api_modpacks_import({
            "archive_path": selected.get("path") or "",
            "file_name": file_name,
            "source_format": source_format,
            "import_id": progress_id,
            "operation_id": operation_id or progress_id,
        })
    except CancelledOperationError:
        return {
            "ok": False,
            "cancelled": True,
            "error": "Import cancelled by user",
        }
    except Exception as e:
        safe_print(f"[api] Failed to select modpack import file: {e}")
        return {"ok": False, "error": str(e)}


def api_modpacks_import(data):
    operation_id = ""
    progress_id = ""
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        archive_data = data.get("hlmp_data")
        if archive_data is None:
            archive_data = data.get("modpack_data")
        archive_path = str(data.get("archive_path") or "").strip()

        if archive_path:
            if not os.path.isfile(archive_path):
                return {"ok": False, "error": "Selected modpack archive was not found"}
        elif not isinstance(archive_data, (bytes, bytearray)) or len(archive_data) == 0:
            return {"ok": False, "error": "No modpack archive data"}

        file_name = str(data.get("file_name") or "").strip()
        if not file_name and archive_path:
            file_name = os.path.basename(archive_path)
        source_format = str(data.get("source_format") or "").strip().lower()
        if not source_format and file_name:
            extension = os.path.splitext(file_name)[1].lower()
            source_format = "mrpack" if extension == ".mrpack" else ("hlmp" if extension == ".hlmp" else "zip")
        progress_id = str(data.get("import_id") or data.get("operation_id") or "").strip()
        operation_id = _begin_operation(data.get("operation_id") or progress_id)

        def progress_callback(done: int, total: int):
            _raise_if_operation_cancelled(operation_id)
            if progress_id:
                STATE.import_progress[progress_id] = {"done": done, "total": total}

        if progress_id:
            STATE.import_progress[progress_id] = {"done": 0, "total": 1}

        archive_input = archive_path if archive_path else bytes(archive_data)
        result = mod_manager.import_modpack(
            archive_input,
            file_name=file_name,
            source_format=source_format,
            progress_callback=progress_callback,
            cancel_check=lambda: _raise_if_operation_cancelled(operation_id),
        )

        return result
    except CancelledOperationError:
        return {
            "ok": False,
            "cancelled": True,
            "error": "Import cancelled by user",
        }
    except Exception as e:
        safe_print(f"[api] Failed to import modpack: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        if progress_id and progress_id in STATE.import_progress:
            del STATE.import_progress[progress_id]
        _clear_operation(operation_id)


def api_modpacks_toggle_mod(data):
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        pack_slug = (data.get("pack_slug") or "").strip().lower()
        addon_type = _normalize_addon_type(data.get("addon_type"))
        addon_slug = (data.get("mod_slug") or data.get("addon_slug") or "").strip().lower()
        disabled = bool(data.get("disabled", False))

        if addon_type not in ("mods", "resourcepacks", "shaderpacks"):
            return {"ok": False, "error": "Invalid addon_type"}

        if not pack_slug or not addon_slug:
            return {"ok": False, "error": "Missing pack_slug or addon slug"}

        if not _validate_modpack_slug(pack_slug):
            return {"ok": False, "error": "Invalid pack_slug"}

        if not _validate_mod_slug(addon_slug):
            return {"ok": False, "error": "Invalid addon slug"}

        success = mod_manager.toggle_addon_in_modpack(pack_slug, addon_type, addon_slug, disabled)
        if success:
            return {"ok": True, "disabled": disabled, "addon_type": addon_type}
        return {"ok": False, "error": "Addon not found in modpack"}
    except Exception as e:
        safe_print(f"[api] Failed to toggle mod in modpack: {e}")
        return {"ok": False, "error": str(e)}


def api_modpacks_set_mod_overwrite(data):
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        pack_slug = (data.get("pack_slug") or "").strip().lower()
        mod_slug = (data.get("mod_slug") or "").strip().lower()
        overwrite_classes = bool(data.get("overwrite_classes", False))
        source_subfolder = str(data.get("source_subfolder") or "")

        if not pack_slug or not mod_slug:
            return {"ok": False, "error": "Missing pack_slug or mod_slug"}

        if not _validate_modpack_slug(pack_slug):
            return {"ok": False, "error": "Invalid pack_slug"}

        if not _validate_mod_slug(mod_slug):
            return {"ok": False, "error": "Invalid mod_slug"}

        if len(source_subfolder) > 512:
            return {"ok": False, "error": "source_subfolder too long"}

        success = mod_manager.set_modpack_mod_overwrite(
            pack_slug, mod_slug, overwrite_classes, source_subfolder
        )
        if success:
            return {
                "ok": True,
                "overwrite_classes": overwrite_classes,
                "source_subfolder": source_subfolder,
            }
        return {"ok": False, "error": "Mod not found in modpack"}
    except Exception as e:
        safe_print(f"[api] Failed to set modpack mod overwrite: {e}")
        return {"ok": False, "error": str(e)}


def api_modpacks_toggle(data):
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        slug = (data.get("slug") or "").strip().lower()
        disabled = bool(data.get("disabled", False))

        if not slug:
            return {"ok": False, "error": "Missing modpack slug"}

        if not _validate_modpack_slug(slug):
            return {"ok": False, "error": "Invalid modpack slug"}

        success = mod_manager.toggle_modpack(slug, disabled)
        if success:
            return {"ok": True, "disabled": disabled}
        return {"ok": False, "error": "Failed to toggle modpack"}
    except Exception as e:
        safe_print(f"[api] Failed to toggle modpack: {e}")
        return {"ok": False, "error": str(e)}


def api_modpacks_delete(data):
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        slug = (data.get("slug") or "").strip().lower()
        if not slug:
            return {"ok": False, "error": "Missing modpack slug"}

        if not _validate_modpack_slug(slug):
            return {"ok": False, "error": "Invalid modpack slug"}

        success = mod_manager.delete_modpack(slug)
        if success:
            return {"ok": True, "message": f"Deleted modpack {slug}"}
        return {"ok": False, "error": "Failed to delete modpack"}
    except Exception as e:
        safe_print(f"[api] Failed to delete modpack: {e}")
        return {"ok": False, "error": str(e)}
