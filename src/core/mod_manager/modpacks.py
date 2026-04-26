from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import urllib.parse
import zipfile
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.settings import get_mods_profile_dir

from core.mod_manager._constants import (
    IMPORT_RETRY_ATTEMPTS,
    IMPORT_RETRY_DELAY,
    SUPPORTED_MOD_LOADERS,
    ExternalModpackImportError,
    _MAX_SAFE_COMPONENT_LENGTH,
    logger,
)
from core.mod_manager._http import (
    _curseforge_request,
    _download_external_mod_file,
    _raise_if_cancelled,
)
from core.mod_manager._validation import (
    _is_within_dir,
    _validate_addon_filename,
    _validate_mod_filename,
    _validate_mod_slug,
    _validate_modpack_slug,
    normalize_version_label,
)
from core.mod_manager.providers import _cf_resolve_download_url
from core.mod_manager.storage import get_addon_storage_dir, get_mods_storage_dir

# Re-export for backwards compatibility (tests import _MODPACK_NAME_FORBIDDEN):
_MODPACK_NAME_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MODPACK_EXTRA_ADDON_TYPES = ("resourcepacks", "shaderpacks")


def _read_json_file(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _resolve_addon_archive_path(version_dir: str, addon_type: str, preferred_file_name: str = "") -> str:
    preferred = os.path.basename(str(preferred_file_name or "").strip())
    if preferred and _validate_addon_filename(preferred, addon_type):
        preferred_path = os.path.join(version_dir, preferred)
        if os.path.isfile(preferred_path):
            return preferred_path
    try:
        for file_name in sorted(os.listdir(version_dir), key=lambda value: value.lower()):
            if _validate_addon_filename(file_name, addon_type):
                file_path = os.path.join(version_dir, file_name)
                if os.path.isfile(file_path):
                    return file_path
    except Exception:
        return ""
    return ""


def _file_hashes(path: str) -> Dict[str, str]:
    hashes = {"sha1": hashlib.sha1(), "sha512": hashlib.sha512()}
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            for digest in hashes.values():
                digest.update(chunk)
    return {name: digest.hexdigest() for name, digest in hashes.items()}


def _is_modrinth_download_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(str(url or "").strip())
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return host == "cdn.modrinth.com" or host.endswith(".cdn.modrinth.com")


def _unique_archive_path(written_paths: set, desired_path: str) -> str:
    normalized = str(desired_path or "").replace("\\", "/").lstrip("/")
    if not normalized:
        return ""
    if normalized not in written_paths:
        written_paths.add(normalized)
        return normalized

    directory, file_name = os.path.split(normalized)
    stem, ext = os.path.splitext(file_name)
    counter = 2
    while True:
        candidate_name = f"{stem}-{counter}{ext}"
        candidate = f"{directory}/{candidate_name}" if directory else candidate_name
        if candidate not in written_paths:
            written_paths.add(candidate)
            return candidate
        counter += 1


def _selected_entry_slug(entry: Dict[str, Any]) -> str:
    return str(
        entry.get("mod_slug")
        or entry.get("addon_slug")
        or entry.get("slug")
        or ""
    ).strip().lower()


def _collect_export_items(
    mod_loader: str,
    mods: List[Dict[str, Any]],
    resourcepacks: Optional[List[Dict[str, Any]]] = None,
    shaderpacks: Optional[List[Dict[str, Any]]] = None,
    cancel_check: Optional[Callable[[], None]] = None,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    loader_key = str(mod_loader or "").strip().lower()
    group_inputs = [
        ("mods", mods or [], get_mods_storage_dir(), loader_key),
        ("resourcepacks", resourcepacks or [], get_addon_storage_dir("resourcepacks"), ""),
        ("shaderpacks", shaderpacks or [], get_addon_storage_dir("shaderpacks"), ""),
    ]

    for addon_type, entries, storage_dir, loader_for_type in group_inputs:
        for entry in entries:
            _raise_if_cancelled(cancel_check)
            if not isinstance(entry, dict):
                continue
            slug = _selected_entry_slug(entry)
            version_label = str(entry.get("version_label") or "").strip()
            if not _validate_mod_slug(slug) or not version_label:
                continue

            addon_dir = os.path.join(storage_dir, loader_for_type, slug) if addon_type == "mods" else os.path.join(storage_dir, slug)
            version_dir = os.path.join(addon_dir, version_label)
            if not os.path.isdir(version_dir):
                continue

            version_meta = _read_json_file(os.path.join(version_dir, "version_meta.json"))
            mod_meta = _read_json_file(os.path.join(addon_dir, "mod_meta.json"))
            archive_path = _resolve_addon_archive_path(
                version_dir,
                addon_type,
                str(version_meta.get("file_name") or ""),
            )
            if not archive_path:
                continue

            file_name = os.path.basename(archive_path)
            display_name = str(
                entry.get("mod_name")
                or entry.get("addon_name")
                or mod_meta.get("name")
                or slug
            ).strip() or slug
            items.append({
                "addon_type": addon_type,
                "folder": addon_type if addon_type != "mods" else "mods",
                "slug": slug,
                "name": display_name,
                "version_label": version_label,
                "disabled": bool(entry.get("disabled", False)),
                "archive_path": archive_path,
                "file_name": file_name,
                "file_size": os.path.getsize(archive_path),
                "version_meta": version_meta,
                "mod_meta": mod_meta,
            })

    return items


def _detect_minecraft_version(items: List[Dict[str, Any]]) -> str:
    for item in items:
        for meta_key in ("version_meta", "mod_meta"):
            meta = item.get(meta_key)
            if not isinstance(meta, dict):
                continue
            candidates = meta.get("game_versions") or meta.get("minecraft_versions") or []
            if isinstance(candidates, str):
                candidates = [candidates]
            if isinstance(candidates, list):
                for value in candidates:
                    candidate = str(value or "").strip()
                    if candidate:
                        return candidate
    return ""


def _export_modrinth_modpack(
    name: str,
    version: str,
    description: str,
    mod_loader: str,
    items: List[Dict[str, Any]],
) -> bytes:
    buf = io.BytesIO()
    written_paths = set()
    files = []
    minecraft_version = _detect_minecraft_version(items)
    dependencies: Dict[str, str] = {}
    if minecraft_version:
        dependencies["minecraft"] = minecraft_version
    if mod_loader in {"fabric", "forge", "neoforge", "quilt"}:
        dependencies[mod_loader] = ""

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            provider = str((item.get("version_meta") or {}).get("provider") or (item.get("mod_meta") or {}).get("provider") or "").lower()
            download_url = str((item.get("version_meta") or {}).get("download_url") or "").strip()
            file_name = item.get("file_name") or os.path.basename(item.get("archive_path") or "")
            folder = item.get("folder") or "mods"

            if provider == "modrinth" and _is_modrinth_download_url(download_url):
                path = _unique_archive_path(written_paths, f"{folder}/{file_name}")
                files.append({
                    "path": path,
                    "hashes": _file_hashes(item["archive_path"]),
                    "env": {"client": "required", "server": "unsupported"},
                    "downloads": [download_url],
                    "fileSize": int(item.get("file_size") or 0),
                })
            else:
                override_path = _unique_archive_path(
                    written_paths,
                    f"overrides/{folder}/{file_name}",
                )
                zf.write(item["archive_path"], override_path)

        index = {
            "formatVersion": 1,
            "game": "minecraft",
            "versionId": str(version or "1.0.0"),
            "name": str(name or "Histolauncher Modpack"),
            "summary": str(description or ""),
            "files": files,
            "dependencies": dependencies,
        }
        zf.writestr("modrinth.index.json", json.dumps(index, indent=2))

    return buf.getvalue()


def _extract_curseforge_ids(item: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    mod_meta = item.get("mod_meta") if isinstance(item.get("mod_meta"), dict) else {}
    version_meta = item.get("version_meta") if isinstance(item.get("version_meta"), dict) else {}
    provider = str(version_meta.get("provider") or mod_meta.get("provider") or "").strip().lower()
    if provider != "curseforge":
        return None, None
    project_id = mod_meta.get("mod_id") or mod_meta.get("project_id") or version_meta.get("project_id")
    file_id = version_meta.get("file_id") or version_meta.get("fileID") or version_meta.get("fileId")
    try:
        project_id_int = int(project_id)
        file_id_int = int(file_id)
    except Exception:
        return None, None
    if project_id_int <= 0 or file_id_int <= 0:
        return None, None
    return project_id_int, file_id_int


def _export_curseforge_modpack(
    name: str,
    version: str,
    description: str,
    author: str,
    mod_loader: str,
    items: List[Dict[str, Any]],
) -> bytes:
    buf = io.BytesIO()
    written_paths = set()
    manifest_files = []
    minecraft_version = _detect_minecraft_version(items)

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            project_id, file_id = _extract_curseforge_ids(item)
            if item.get("addon_type") == "mods" and project_id and file_id:
                manifest_files.append({
                    "projectID": project_id,
                    "fileID": file_id,
                    "required": not bool(item.get("disabled", False)),
                })
                continue

            file_name = item.get("file_name") or os.path.basename(item.get("archive_path") or "")
            folder = item.get("folder") or "mods"
            override_path = _unique_archive_path(
                written_paths,
                f"overrides/{folder}/{file_name}",
            )
            zf.write(item["archive_path"], override_path)

        manifest = {
            "minecraft": {
                "version": minecraft_version,
                "modLoaders": ([{"id": str(mod_loader or "").lower(), "primary": True}] if mod_loader else []),
            },
            "manifestType": "minecraftModpack",
            "manifestVersion": 1,
            "name": str(name or "Histolauncher Modpack"),
            "version": str(version or "1.0.0"),
            "author": str(author or "")[:64],
            "files": manifest_files,
            "overrides": "overrides",
        }
        if description:
            manifest["description"] = str(description)[:8192]
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    return buf.getvalue()


def get_modpacks_storage_dir() -> str:
    profile_root = get_mods_profile_dir()
    d = os.path.join(profile_root, "modpacks")
    os.makedirs(d, exist_ok=True)
    return d


def _modpack_slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or "modpack"


def _is_modpack_mod_enabled(mod_entry: Dict[str, Any]) -> bool:
    return not bool(mod_entry.get("disabled", False))


def _get_modpack_mod_icon_path(pack_dir: str, mod_loader: str, mod_slug: str) -> str:
    icon_new = os.path.join(pack_dir, "mods", mod_slug, "display.png")
    if os.path.isfile(icon_new):
        return icon_new

    icon_legacy = os.path.join(pack_dir, "mod_icons", mod_slug, "display.png")
    if os.path.isfile(icon_legacy):
        return icon_legacy

    icon_legacy_loader = os.path.join(pack_dir, "mods", mod_loader, mod_slug, "display.png")
    if os.path.isfile(icon_legacy_loader):
        return icon_legacy_loader

    return ""


def get_installed_modpacks() -> List[Dict[str, Any]]:
    base = get_modpacks_storage_dir()
    result = []
    if not os.path.isdir(base):
        return result
    for slug in os.listdir(base):
        pack_dir = os.path.join(base, slug)
        if not os.path.isdir(pack_dir):
            continue
        data_file = os.path.join(pack_dir, "data.json")
        if not os.path.isfile(data_file):
            continue
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            stored_icon_url = str(data.get("source_icon_url") or data.get("icon_url") or "").strip()
            icon_url = stored_icon_url
            if os.path.isfile(os.path.join(pack_dir, "display.png")):
                icon_url = f"/modpacks-cache/{slug}/display.png"
            data["slug"] = slug
            data["icon_url"] = icon_url
            if stored_icon_url:
                data["source_icon_url"] = stored_icon_url
            raw_imported = data.get("is_imported", data.get("install_source") != "installed")
            if isinstance(raw_imported, str):
                data["is_imported"] = raw_imported.strip().lower() not in {"0", "false", "no", "installed"}
            else:
                data["is_imported"] = bool(raw_imported)
            data["install_source"] = str(
                data.get("install_source") or ("imported" if data["is_imported"] else "installed")
            )
            mod_loader = (data.get("mod_loader") or "").lower()
            for mod_entry in data.get("mods", []):
                ms = mod_entry.get("mod_slug", "")
                mod_entry["disabled"] = bool(mod_entry.get("disabled", False))
                # Surface overwrite_classes / source_subfolder for the UI by
                # falling back to the per-version meta packed inside the
                # modpack (older modpacks won't have these on the data.json
                # entry, but their bundled version_meta.json may still
                # describe class-overwrite behaviour).
                ver_label = str(mod_entry.get("version_label") or "").strip()
                packed_overwrite = False
                packed_subfolder = ""
                if ms and ver_label:
                    packed_meta_path = os.path.join(
                        pack_dir, "mods", ms, ver_label, "version_meta.json"
                    )
                    if os.path.isfile(packed_meta_path):
                        try:
                            with open(packed_meta_path, "r", encoding="utf-8") as vmf:
                                vm = json.load(vmf) or {}
                            packed_overwrite = bool(vm.get("overwrite_classes", False))
                            packed_subfolder = str(vm.get("source_subfolder", "") or "")
                        except Exception:
                            pass
                if "overwrite_classes" not in mod_entry:
                    mod_entry["overwrite_classes"] = packed_overwrite
                else:
                    mod_entry["overwrite_classes"] = bool(mod_entry.get("overwrite_classes"))
                if "source_subfolder" not in mod_entry:
                    mod_entry["source_subfolder"] = packed_subfolder
                else:
                    mod_entry["source_subfolder"] = str(mod_entry.get("source_subfolder") or "")
                icon_path = _get_modpack_mod_icon_path(pack_dir, mod_loader, ms) if ms else ""
                if icon_path:
                    rel = os.path.relpath(icon_path, pack_dir).replace("\\", "/")
                    mod_entry["icon_url"] = f"/modpacks-cache/{slug}/{rel}"
                else:
                    mod_entry["icon_url"] = ""

            for addon_type in _MODPACK_EXTRA_ADDON_TYPES:
                raw_entries = data.get(addon_type)
                entries = raw_entries if isinstance(raw_entries, list) else []
                if not entries:
                    addon_root = os.path.join(pack_dir, addon_type)
                    if os.path.isdir(addon_root):
                        recovered = []
                        for addon_slug in sorted(os.listdir(addon_root), key=lambda value: value.lower()):
                            addon_dir = os.path.join(addon_root, addon_slug)
                            if not os.path.isdir(addon_dir) or not _validate_mod_slug(addon_slug):
                                continue
                            meta = _read_json_file(os.path.join(addon_dir, "mod_meta.json"))
                            version_label = str(meta.get("active_version") or "").strip()
                            if not version_label:
                                try:
                                    version_label = next(
                                        entry_name for entry_name in sorted(os.listdir(addon_dir), key=lambda value: value.lower())
                                        if os.path.isdir(os.path.join(addon_dir, entry_name))
                                    )
                                except StopIteration:
                                    version_label = ""
                            recovered.append({
                                "mod_slug": addon_slug,
                                "mod_name": str(meta.get("name") or addon_slug),
                                "version_label": version_label,
                                "disabled": bool(meta.get("disabled", False)),
                                "addon_type": addon_type,
                            })
                        entries = recovered

                normalized_entries = []
                for addon_entry in entries:
                    if not isinstance(addon_entry, dict):
                        continue
                    addon_slug = _selected_entry_slug(addon_entry)
                    if not addon_slug:
                        continue
                    normalized_entry = dict(addon_entry)
                    normalized_entry["mod_slug"] = addon_slug
                    normalized_entry["addon_type"] = addon_type
                    normalized_entry["disabled"] = bool(addon_entry.get("disabled", False))
                    normalized_entry["mod_name"] = str(
                        addon_entry.get("mod_name")
                        or addon_entry.get("addon_name")
                        or addon_slug
                    )
                    icon_path = os.path.join(pack_dir, addon_type, addon_slug, "display.png")
                    if os.path.isfile(icon_path):
                        rel = os.path.relpath(icon_path, pack_dir).replace("\\", "/")
                        normalized_entry["icon_url"] = f"/modpacks-cache/{slug}/{rel}"
                    else:
                        normalized_entry["icon_url"] = ""
                    normalized_entries.append(normalized_entry)
                data[addon_type] = normalized_entries
                data[f"{addon_type[:-1]}_count"] = len(normalized_entries)
            result.append(data)
        except Exception as e:
            logger.warning(f"Failed to read modpack {slug}: {e}")
    return result


def export_modpack(name: str, version: str, description: str,
                   mod_loader: str, mods: List[Dict[str, Any]],
                   image_data: bytes = None,
                   cancel_check: Optional[Callable[[], None]] = None,
                   resourcepacks: Optional[List[Dict[str, Any]]] = None,
                   shaderpacks: Optional[List[Dict[str, Any]]] = None,
                   author: str = "",
                   export_format: str = "histolauncher") -> bytes:
    author_value = str(author or "").strip()[:64]
    normalized_format = str(export_format or "histolauncher").strip().lower()
    if normalized_format in {"modrinth", "mrpack"}:
        items = _collect_export_items(
            mod_loader,
            mods,
            resourcepacks=resourcepacks,
            shaderpacks=shaderpacks,
            cancel_check=cancel_check,
        )
        return _export_modrinth_modpack(name, version, description, mod_loader, items)
    if normalized_format in {"curseforge", "curse", "zip"}:
        items = _collect_export_items(
            mod_loader,
            mods,
            resourcepacks=resourcepacks,
            shaderpacks=shaderpacks,
            cancel_check=cancel_check,
        )
        return _export_curseforge_modpack(name, version, description, author_value, mod_loader, items)

    buf = io.BytesIO()
    mods_storage = get_mods_storage_dir()
    mod_entries = []
    resourcepack_entries = []
    shaderpack_entries = []

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        written_paths = set()

        def _write_if_exists(src_path: str, arc_path: str) -> bool:
            if not os.path.isfile(src_path):
                return False
            normalized_arc = str(arc_path or "").replace("\\", "/").lstrip("/")
            if not normalized_arc or normalized_arc in written_paths:
                return False
            zf.write(src_path, normalized_arc)
            written_paths.add(normalized_arc)
            return True

        if image_data:
            zf.writestr("display.png", image_data)
            written_paths.add("display.png")

        for m in mods:
            _raise_if_cancelled(cancel_check)
            slug = m.get("mod_slug", "")
            ver_label = m.get("version_label", "")
            if not slug or not ver_label:
                continue

            mod_dir = os.path.join(mods_storage, mod_loader.lower(), slug)
            ver_dir = os.path.join(mod_dir, ver_label)
            if not os.path.isdir(ver_dir):
                continue

            disabled_in_pack = bool(m.get("disabled", False))

            # Optional per-mod overwrite-classpath settings supplied from the
            # export wizard. When provided we patch the version_meta.json that
            # ships inside the modpack so the launcher can honour them at
            # launch time without affecting the standalone mod entry.
            overwrite_override_present = (
                "overwrite_classes" in m or "source_subfolder" in m
            )
            overwrite_classes = bool(m.get("overwrite_classes", False))
            source_subfolder = str(m.get("source_subfolder", "") or "")

            patched_version_meta = None
            if overwrite_override_present:
                version_meta_src = os.path.join(ver_dir, "version_meta.json")
                base_meta = {}
                if os.path.isfile(version_meta_src):
                    try:
                        with open(version_meta_src, "r", encoding="utf-8") as vmf:
                            base_meta = json.load(vmf) or {}
                    except Exception:
                        base_meta = {}
                base_meta["overwrite_classes"] = overwrite_classes
                base_meta["source_subfolder"] = source_subfolder
                patched_version_meta = base_meta

            for fn in sorted(os.listdir(ver_dir)):
                _raise_if_cancelled(cancel_check)
                src = os.path.join(ver_dir, fn)
                if not os.path.isfile(src):
                    continue
                arc_path = f"mods/{slug}/{ver_label}/{fn}"
                if patched_version_meta is not None and fn == "version_meta.json":
                    normalized_arc = arc_path.replace("\\", "/").lstrip("/")
                    if normalized_arc and normalized_arc not in written_paths:
                        zf.writestr(
                            normalized_arc,
                            json.dumps(patched_version_meta, indent=2),
                        )
                        written_paths.add(normalized_arc)
                    continue
                _write_if_exists(src, arc_path)

            # If the source mod had no version_meta.json on disk but the
            # exporter still wants overwrite settings, write a minimal one so
            # the launcher can find it on import.
            if patched_version_meta is not None:
                normalized_meta_arc = f"mods/{slug}/{ver_label}/version_meta.json"
                if normalized_meta_arc not in written_paths:
                    zf.writestr(
                        normalized_meta_arc,
                        json.dumps(patched_version_meta, indent=2),
                    )
                    written_paths.add(normalized_meta_arc)

            meta_src = os.path.join(mod_dir, "mod_meta.json")
            _write_if_exists(meta_src, f"mods/{slug}/mod_meta.json")

            mod_icon_src = os.path.join(mod_dir, "display.png")
            _write_if_exists(mod_icon_src, f"mods/{slug}/display.png")

            meta_file = os.path.join(mod_dir, "mod_meta.json")
            mod_name = slug
            if os.path.isfile(meta_file):
                try:
                    _raise_if_cancelled(cancel_check)
                    with open(meta_file, "r", encoding="utf-8") as f:
                        mm = json.load(f)
                    mod_name = mm.get("name", slug)
                except Exception:
                    pass

            entry = {
                "mod_slug": slug,
                "mod_name": mod_name,
                "version_label": ver_label,
                "disabled": disabled_in_pack,
            }
            if overwrite_override_present:
                entry["overwrite_classes"] = overwrite_classes
                entry["source_subfolder"] = source_subfolder
            mod_entries.append(entry)

        def _export_extra_addons(addon_type: str, selected_addons: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
            addon_entries = []
            storage_dir = get_addon_storage_dir(addon_type)
            for addon in selected_addons or []:
                _raise_if_cancelled(cancel_check)
                if not isinstance(addon, dict):
                    continue
                slug = _selected_entry_slug(addon)
                ver_label = str(addon.get("version_label") or "").strip()
                if not slug or not ver_label or not _validate_mod_slug(slug):
                    continue

                addon_dir = os.path.join(storage_dir, slug)
                ver_dir = os.path.join(addon_dir, ver_label)
                if not os.path.isdir(ver_dir):
                    continue

                disabled_in_pack = bool(addon.get("disabled", False))
                for fn in sorted(os.listdir(ver_dir)):
                    _raise_if_cancelled(cancel_check)
                    src = os.path.join(ver_dir, fn)
                    if not os.path.isfile(src):
                        continue
                    if fn != "version_meta.json" and not _validate_addon_filename(fn, addon_type):
                        continue
                    _write_if_exists(src, f"{addon_type}/{slug}/{ver_label}/{fn}")

                meta_src = os.path.join(addon_dir, "mod_meta.json")
                _write_if_exists(meta_src, f"{addon_type}/{slug}/mod_meta.json")

                addon_icon_src = os.path.join(addon_dir, "display.png")
                _write_if_exists(addon_icon_src, f"{addon_type}/{slug}/display.png")

                meta = _read_json_file(meta_src)
                addon_entries.append({
                    "mod_slug": slug,
                    "mod_name": str(addon.get("mod_name") or meta.get("name") or slug),
                    "version_label": ver_label,
                    "disabled": disabled_in_pack,
                    "addon_type": addon_type,
                })
            return addon_entries

        resourcepack_entries = _export_extra_addons("resourcepacks", resourcepacks)
        shaderpack_entries = _export_extra_addons("shaderpacks", shaderpacks)

        data_json = {
            "name": name,
            "version": version,
            "author": author_value,
            "description": description,
            "mod_loader": mod_loader.lower(),
            "mod_count": len(mod_entries),
            "mods": mod_entries,
            "resourcepack_count": len(resourcepack_entries),
            "resourcepacks": resourcepack_entries,
            "shaderpack_count": len(shaderpack_entries),
            "shaderpacks": shaderpack_entries,
        }
        zf.writestr("data.json", json.dumps(data_json, indent=2))

    return buf.getvalue()


def _sanitize_modpack_name(name: str, fallback: str = "Imported Modpack") -> str:
    value = str(name or "").strip()
    if not value:
        value = fallback
    value = _MODPACK_NAME_FORBIDDEN.sub("-", value)
    value = re.sub(r"\s+", " ", value).strip(" .-_")
    if not value:
        value = fallback
    return value[:64]


def _slugify_mod_name(value: str, fallback: str = "imported-mod") -> str:
    base = os.path.splitext(os.path.basename(str(value or "").strip()))[0].lower()
    slug = re.sub(r"[^a-z0-9._-]+", "-", base).strip("-._")
    if not slug:
        slug = fallback
    if not slug[0].isalnum():
        slug = f"m-{slug}"
    slug = slug[:_MAX_SAFE_COMPONENT_LENGTH]
    if not _validate_mod_slug(slug):
        slug = fallback
    return slug


def _ensure_unique_mod_slug(base_slug: str, used: set) -> str:
    slug = base_slug
    counter = 1
    while slug in used or not _validate_mod_slug(slug):
        counter += 1
        suffix = f"-{counter}"
        trimmed = base_slug[:max(1, _MAX_SAFE_COMPONENT_LENGTH - len(suffix))]
        slug = f"{trimmed}{suffix}"
    used.add(slug)
    return slug


def _guess_loader_from_text(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "babric" in text:
        return "babric"
    if "modloader" in text:
        return "modloader"
    if "neoforge" in text:
        return "neoforge"
    if "quilt" in text:
        return "quilt"
    if "forge" in text:
        return "forge"
    if "fabric" in text:
        return "fabric"
    return ""


def _derive_loader_from_manifest(manifest: Dict[str, Any]) -> str:
    if not isinstance(manifest, dict):
        return ""
    minecraft = manifest.get("minecraft")
    if not isinstance(minecraft, dict):
        return ""
    loaders = minecraft.get("modLoaders")
    if not isinstance(loaders, list):
        return ""
    for entry in loaders:
        if isinstance(entry, dict):
            candidate = _guess_loader_from_text(entry.get("id"))
        else:
            candidate = _guess_loader_from_text(entry)
        if candidate:
            return candidate
    return ""


def _extract_curseforge_manifest_refs(manifest: Dict[str, Any]) -> List[Tuple[int, int]]:
    if not isinstance(manifest, dict):
        return []

    files = manifest.get("files")
    if not isinstance(files, list):
        return []

    refs = []
    seen = set()

    for entry in files:
        if not isinstance(entry, dict):
            continue

        required_value = entry.get("required", True)
        if isinstance(required_value, str):
            if required_value.strip().lower() in ("0", "false", "no", "off"):
                continue
        elif required_value is False:
            continue

        project_id = entry.get("projectID", entry.get("projectId", entry.get("project_id")))
        file_id = entry.get("fileID", entry.get("fileId", entry.get("file_id")))

        try:
            project_id_int = int(project_id)
            file_id_int = int(file_id)
        except Exception:
            continue

        if project_id_int <= 0 or file_id_int <= 0:
            continue

        key = (project_id_int, file_id_int)
        if key in seen:
            continue
        seen.add(key)
        refs.append(key)

    return refs


def _resolve_curseforge_manifest_mods(
    file_refs: List[Tuple[int, int]],
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], None]] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    resolved = []
    warnings = []

    seen_file_ids = set()
    seen_file_names = set()
    total_files = len(file_refs)
    completed_files = 0

    if progress_callback:
        progress_callback(completed_files, total_files)

    for project_id, file_id in file_refs:
        _raise_if_cancelled(cancel_check)
        if file_id in seen_file_ids:
            completed_files += 1
            if progress_callback:
                progress_callback(completed_files, total_files)
            continue

        response = _curseforge_request(
            f"/mods/{project_id}/files/{file_id}",
            max_attempts=IMPORT_RETRY_ATTEMPTS,
            retry_delay=IMPORT_RETRY_DELAY,
        )
        file_data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(file_data, dict):
            err = "metadata lookup failed"
            if isinstance(response, dict):
                err = str(response.get("error") or err)
                if response.get("requires_api_key"):
                    err = f"{err} (requires API key)"
            raise ExternalModpackImportError(
                f"Failed to import CurseForge mod {project_id}/{file_id}: {err}"
            )

        archive_name = str(file_data.get("fileName") or "").strip()
        if not _validate_mod_filename(archive_name):
            warnings.append(f"CurseForge {project_id}/{file_id}: unsupported file '{archive_name or 'unknown'}'")
            completed_files += 1
            if progress_callback:
                progress_callback(completed_files, total_files)
            continue

        lower_name = archive_name.lower()
        if lower_name in seen_file_names:
            completed_files += 1
            if progress_callback:
                progress_callback(completed_files, total_files)
            continue

        download_url = _cf_resolve_download_url(file_data)
        if not download_url:
            raise ExternalModpackImportError(
                f"Failed to import required mod {archive_name}: missing download URL"
            )

        file_bytes, download_err = _download_external_mod_file(
            [download_url],
            max_attempts=IMPORT_RETRY_ATTEMPTS,
            retry_delay=IMPORT_RETRY_DELAY,
            cancel_check=cancel_check,
        )
        if file_bytes is None:
            raise ExternalModpackImportError(
                f"Failed to import required mod {archive_name}: {download_err}"
            )

        base_name = os.path.splitext(archive_name)[0]
        version_hint = str(file_data.get("displayName") or base_name or f"cf-{file_id}").strip()

        resolved.append({
            "mod_name": base_name,
            "version_label": version_hint,
            "file_name": archive_name,
            "file_bytes": file_bytes,
            "project_id": project_id,
            "file_id": file_id,
        })
        seen_file_ids.add(file_id)
        seen_file_names.add(lower_name)

        completed_files += 1
        if progress_callback:
            progress_callback(completed_files, total_files)

    return resolved, warnings


def _verify_external_file_hash(file_bytes: bytes, hashes: Any) -> bool:
    if not isinstance(hashes, dict):
        return True
    for algo in ("sha512", "sha256", "sha1"):
        expected = str(hashes.get(algo) or "").strip().lower()
        if not expected:
            continue
        try:
            digest = hashlib.new(algo)
            digest.update(file_bytes)
            return digest.hexdigest().lower() == expected
        except Exception:
            return False
    return True


def _collect_bundled_mod_archives(zf: zipfile.ZipFile) -> List[Tuple[str, str, bytes]]:
    bundled = []
    for zi in zf.infolist():
        if zi.is_dir():
            continue
        normalized = zi.filename.replace("\\", "/").lstrip("/")
        if not normalized:
            continue
        lower_path = normalized.lower()
        file_name = os.path.basename(normalized)
        if not _validate_mod_filename(file_name):
            continue
        looks_like_mod_path = (
            lower_path.startswith("mods/")
            or "/mods/" in lower_path
            or "/" not in normalized
        )
        if not looks_like_mod_path:
            continue
        try:
            bundled.append((normalized, file_name, zf.read(zi)))
        except Exception:
            continue
    return bundled


def _collect_bundled_addon_archives(zf: zipfile.ZipFile, addon_type: str) -> List[Tuple[str, str, bytes]]:
    normalized_type = "shaderpacks" if str(addon_type or "").lower() == "shaderpacks" else "resourcepacks"
    bundled = []
    path_tokens = {
        "resourcepacks": ("resourcepacks", "texturepacks"),
        "shaderpacks": ("shaderpacks",),
    }[normalized_type]

    for zi in zf.infolist():
        if zi.is_dir():
            continue
        normalized = zi.filename.replace("\\", "/").lstrip("/")
        if not normalized:
            continue
        lower_parts = [part.lower() for part in normalized.split("/") if part]
        if not any(token in lower_parts for token in path_tokens):
            continue
        file_name = os.path.basename(normalized)
        if not _validate_addon_filename(file_name, normalized_type):
            continue
        try:
            bundled.append((normalized, file_name, zf.read(zi)))
        except Exception:
            continue
    return bundled


def _build_hlmp_from_mod_entries(
    pack_name: str,
    pack_version: str,
    description: str,
    mod_loader: str,
    mod_entries: List[Dict[str, Any]],
    author: str = "",
    resourcepack_entries: Optional[List[Dict[str, Any]]] = None,
    shaderpack_entries: Optional[List[Dict[str, Any]]] = None,
) -> Optional[bytes]:
    out = io.BytesIO()
    data_mods = []
    data_resourcepacks = []
    data_shaderpacks = []

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as out_zip:
        for entry in mod_entries:
            mod_slug = str(entry.get("mod_slug") or "").strip().lower()
            file_name = str(entry.get("file_name") or "").strip()
            version_label = normalize_version_label(entry.get("version_label") or "imported")
            file_bytes = entry.get("file_bytes")

            if not _validate_mod_slug(mod_slug):
                continue
            if not _validate_mod_filename(file_name):
                continue
            if not isinstance(file_bytes, (bytes, bytearray)) or not file_bytes:
                continue

            out_zip.writestr(f"mods/{mod_slug}/{version_label}/{file_name}", bytes(file_bytes))
            data_mods.append({
                "mod_slug": mod_slug,
                "mod_name": str(entry.get("mod_name") or mod_slug),
                "version_label": version_label,
                "disabled": bool(entry.get("disabled", False)),
            })

        def _write_extra_entries(addon_type: str, entries: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
            data_entries = []
            for entry in entries or []:
                addon_slug = _selected_entry_slug(entry)
                file_name = str(entry.get("file_name") or "").strip()
                version_label = normalize_version_label(entry.get("version_label") or "imported")
                file_bytes = entry.get("file_bytes")

                if not _validate_mod_slug(addon_slug):
                    continue
                if not _validate_addon_filename(file_name, addon_type):
                    continue
                if not isinstance(file_bytes, (bytes, bytearray)) or not file_bytes:
                    continue

                out_zip.writestr(f"{addon_type}/{addon_slug}/{version_label}/{file_name}", bytes(file_bytes))
                data_entries.append({
                    "mod_slug": addon_slug,
                    "mod_name": str(entry.get("mod_name") or entry.get("addon_name") or addon_slug),
                    "version_label": version_label,
                    "disabled": bool(entry.get("disabled", False)),
                    "addon_type": addon_type,
                })
            return data_entries

        data_resourcepacks = _write_extra_entries("resourcepacks", resourcepack_entries)
        data_shaderpacks = _write_extra_entries("shaderpacks", shaderpack_entries)

        if not data_mods:
            return None

        out_zip.writestr(
            "data.json",
            json.dumps(
                {
                    "name": _sanitize_modpack_name(pack_name),
                    "version": str(pack_version or "imported")[:32],
                    "author": str(author or "").strip()[:64],
                    "description": str(description or "")[:8192],
                    "mod_loader": mod_loader,
                    "mod_count": len(data_mods),
                    "mods": data_mods,
                    "resourcepack_count": len(data_resourcepacks),
                    "resourcepacks": data_resourcepacks,
                    "shaderpack_count": len(data_shaderpacks),
                    "shaderpacks": data_shaderpacks,
                },
                indent=2,
            ),
        )

    return out.getvalue()


def _convert_mrpack_to_hlmp(
    zf: zipfile.ZipFile,
    file_name: str = "",
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], None]] = None,
) -> Dict[str, Any]:
    index_name = None
    for name in zf.namelist():
        if name.lower() == "modrinth.index.json":
            index_name = name
            break

    if not index_name:
        return {"ok": False, "error": "Invalid .mrpack: missing modrinth.index.json"}

    try:
        index_data = json.loads(zf.read(index_name))
    except Exception:
        return {"ok": False, "error": "Invalid .mrpack: corrupt modrinth.index.json"}

    dependencies = index_data.get("dependencies") if isinstance(index_data, dict) else {}
    mod_loader = ""
    if isinstance(dependencies, dict):
        dep_keys = list(dependencies.keys())
        dep_values = [str(v) for v in dependencies.values()]
        for key in dep_keys + dep_values:
            guessed = _guess_loader_from_text(key)
            if guessed:
                mod_loader = guessed
                break
    if not mod_loader:
        mod_loader = _guess_loader_from_text(file_name)
    if mod_loader not in SUPPORTED_MOD_LOADERS:
        mod_loader = "fabric"

    fallback_name = os.path.splitext(os.path.basename(str(file_name or "imported-modpack.mrpack")))[0]
    pack_name = _sanitize_modpack_name(index_data.get("name"), fallback=fallback_name or "Imported Modpack")
    pack_version = normalize_version_label(index_data.get("versionId") or "imported")
    author = str(index_data.get("author") or "").strip()
    description = f"Imported from Modrinth modpack {pack_name}"

    files = index_data.get("files") if isinstance(index_data, dict) else []
    warnings = []
    used_slugs = set()
    used_resourcepack_slugs = set()
    used_shaderpack_slugs = set()
    seen_file_names = set()
    entries = []
    resourcepack_entries = []
    shaderpack_entries = []

    if isinstance(files, list):
        total_files = len(files)
        downloaded_files = 0
        if progress_callback:
            progress_callback(downloaded_files, total_files)

        for file_entry in files:
            _raise_if_cancelled(cancel_check)
            if not isinstance(file_entry, dict):
                downloaded_files += 1
                if progress_callback: progress_callback(downloaded_files, total_files)
                continue

            env = file_entry.get("env")
            if isinstance(env, dict):
                if str(env.get("client") or "").lower() == "unsupported" and str(env.get("server") or "").lower() == "unsupported":
                    downloaded_files += 1
                    if progress_callback: progress_callback(downloaded_files, total_files)
                    continue

            rel_path = str(file_entry.get("path") or "").replace("\\", "/").lstrip("/")
            lower_rel_path = rel_path.lower()
            if lower_rel_path.startswith("mods/"):
                entry_addon_type = "mods"
            elif lower_rel_path.startswith("resourcepacks/") or lower_rel_path.startswith("texturepacks/"):
                entry_addon_type = "resourcepacks"
            elif lower_rel_path.startswith("shaderpacks/"):
                entry_addon_type = "shaderpacks"
            else:
                downloaded_files += 1
                if progress_callback: progress_callback(downloaded_files, total_files)
                continue

            archive_name = os.path.basename(rel_path)
            if entry_addon_type == "mods":
                valid_archive = _validate_mod_filename(archive_name)
            else:
                valid_archive = _validate_addon_filename(archive_name, entry_addon_type)
            if not valid_archive:
                warnings.append(f"Skipped unsupported file in mrpack: {archive_name}")
                downloaded_files += 1
                if progress_callback: progress_callback(downloaded_files, total_files)
                continue

            urls = []
            downloads = file_entry.get("downloads")
            if isinstance(downloads, list):
                urls.extend([str(u).strip() for u in downloads if str(u).strip()])
            if file_entry.get("url"):
                urls.append(str(file_entry.get("url")).strip())

            file_bytes, err = _download_external_mod_file(
                urls,
                max_attempts=IMPORT_RETRY_ATTEMPTS,
                retry_delay=IMPORT_RETRY_DELAY,
                cancel_check=cancel_check,
            )
            if file_bytes is None:
                return {
                    "ok": False,
                    "error": f"Failed to import required mod {archive_name}: {err}",
                }

            if not _verify_external_file_hash(file_bytes, file_entry.get("hashes")):
                return {
                    "ok": False,
                    "error": f"Failed to import required mod {archive_name}: hash verification failed",
                }

            if archive_name.lower() in seen_file_names:
                downloaded_files += 1
                if progress_callback: progress_callback(downloaded_files, total_files)
                continue
            seen_file_names.add(archive_name.lower())

            if entry_addon_type == "mods":
                slug_set = used_slugs
            elif entry_addon_type == "resourcepacks":
                slug_set = used_resourcepack_slugs
            else:
                slug_set = used_shaderpack_slugs
            slug = _ensure_unique_mod_slug(_slugify_mod_name(archive_name), slug_set)
            converted_entry = {
                "mod_slug": slug,
                "mod_name": os.path.splitext(archive_name)[0],
                "version_label": os.path.splitext(archive_name)[0],
                "file_name": archive_name,
                "file_bytes": file_bytes,
            }
            if entry_addon_type == "mods":
                entries.append(converted_entry)
            elif entry_addon_type == "resourcepacks":
                resourcepack_entries.append(converted_entry)
            else:
                shaderpack_entries.append(converted_entry)

            downloaded_files += 1
            if progress_callback:
                progress_callback(downloaded_files, total_files)

    for normalized_path, archive_name, file_bytes in _collect_bundled_mod_archives(zf):
        lower = normalized_path.lower()
        if not (
            lower.startswith("mods/")
            or lower.startswith("overrides/mods/")
            or lower.startswith("client-overrides/mods/")
        ):
            continue
        if archive_name.lower() in seen_file_names:
            continue
        seen_file_names.add(archive_name.lower())

        slug = _ensure_unique_mod_slug(_slugify_mod_name(archive_name), used_slugs)
        entries.append({
            "mod_slug": slug,
            "mod_name": os.path.splitext(archive_name)[0],
            "version_label": os.path.splitext(archive_name)[0],
            "file_name": archive_name,
            "file_bytes": file_bytes,
        })

    for addon_type, target_entries, slug_set in (
        ("resourcepacks", resourcepack_entries, used_resourcepack_slugs),
        ("shaderpacks", shaderpack_entries, used_shaderpack_slugs),
    ):
        for _normalized_path, archive_name, file_bytes in _collect_bundled_addon_archives(zf, addon_type):
            if archive_name.lower() in seen_file_names:
                continue
            seen_file_names.add(archive_name.lower())
            slug = _ensure_unique_mod_slug(_slugify_mod_name(archive_name), slug_set)
            target_entries.append({
                "mod_slug": slug,
                "mod_name": os.path.splitext(archive_name)[0],
                "version_label": os.path.splitext(archive_name)[0],
                "file_name": archive_name,
                "file_bytes": file_bytes,
            })

    if not entries:
        details = ""
        if warnings:
            details = f" Details: {warnings[0]}"
        return {"ok": False, "error": f"No importable mod files found in .mrpack.{details}"}

    hlmp_bytes = _build_hlmp_from_mod_entries(
        pack_name,
        pack_version,
        description,
        mod_loader,
        entries,
        author=author,
        resourcepack_entries=resourcepack_entries,
        shaderpack_entries=shaderpack_entries,
    )
    if not hlmp_bytes:
        return {"ok": False, "error": "Failed to convert .mrpack into importable modpack format"}

    result = {"ok": True, "hlmp_bytes": hlmp_bytes, "source_format": "mrpack"}
    if warnings:
        result["warnings"] = warnings
    return result


def _convert_generic_zip_to_hlmp(
    zf: zipfile.ZipFile,
    file_name: str = "",
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], None]] = None,
) -> Dict[str, Any]:
    manifest_name = None
    for name in zf.namelist():
        if name.lower() == "manifest.json":
            manifest_name = name
            break

    manifest_data = {}
    if manifest_name:
        try:
            parsed = json.loads(zf.read(manifest_name))
            if isinstance(parsed, dict):
                manifest_data = parsed
        except Exception:
            manifest_data = {}

    fallback_name = os.path.splitext(os.path.basename(str(file_name or "imported-modpack.zip")))[0]
    pack_name = _sanitize_modpack_name(manifest_data.get("name"), fallback=fallback_name or "Imported Modpack")
    pack_version = normalize_version_label(manifest_data.get("version") or "imported")
    author = str(manifest_data.get("author") or "").strip()
    manifest_type = str(manifest_data.get("manifestType") or "").strip().lower()
    cf_file_refs = _extract_curseforge_manifest_refs(manifest_data)
    is_curseforge_manifest = bool(cf_file_refs) or manifest_type == "minecraftmodpack"
    description = (
        f"Imported from CurseForge modpack {pack_name}"
        if is_curseforge_manifest
        else "Imported from external zip modpack"
    )

    mod_loader = _derive_loader_from_manifest(manifest_data)
    if not mod_loader:
        mod_loader = _guess_loader_from_text(file_name)
    if not mod_loader:
        for hint in (pack_name, manifest_data.get("name", ""), manifest_data.get("author", "")):
            guessed = _guess_loader_from_text(hint)
            if guessed:
                mod_loader = guessed
                break
    if mod_loader not in SUPPORTED_MOD_LOADERS:
        mod_loader = "fabric"

    bundled = _collect_bundled_mod_archives(zf)
    manifest_entries = []
    warnings = []

    if cf_file_refs:
        try:
            manifest_entries, manifest_warnings = _resolve_curseforge_manifest_mods(
                cf_file_refs,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )
            warnings.extend(manifest_warnings)
        except ExternalModpackImportError as exc:
            return {"ok": False, "error": str(exc)}

    if not bundled and not manifest_entries:
        file_refs = manifest_data.get("files") if isinstance(manifest_data, dict) else []
        if isinstance(file_refs, list) and file_refs:
            if cf_file_refs:
                details = f" Details: {warnings[0]}" if warnings else ""
                return {
                    "ok": False,
                    "error": f"This CurseForge modpack references external mods, but none could be downloaded.{details}",
                }
            return {
                "ok": False,
                "error": "This modpack zip contains only manifest references and no bundled mod archives. Try importing a .mrpack file or a zip that includes mod .jar files.",
            }
        return {"ok": False, "error": "No importable .jar/.zip mod files found in archive"}

    used_slugs = set()
    used_resourcepack_slugs = set()
    used_shaderpack_slugs = set()
    entries = []
    resourcepack_entries = []
    shaderpack_entries = []
    seen_file_names = set()

    for normalized_path, archive_name, file_bytes in bundled:
        lower_path = normalized_path.lower()
        if not (
            lower_path.startswith("mods/")
            or lower_path.startswith("overrides/mods/")
            or lower_path.startswith("client-overrides/mods/")
            or "/mods/" in lower_path
            or "/" not in normalized_path
        ):
            continue

        if archive_name.lower() in seen_file_names:
            continue
        seen_file_names.add(archive_name.lower())

        slug = _ensure_unique_mod_slug(_slugify_mod_name(archive_name), used_slugs)
        entries.append({
            "mod_slug": slug,
            "mod_name": os.path.splitext(archive_name)[0],
            "version_label": os.path.splitext(archive_name)[0],
            "file_name": archive_name,
            "file_bytes": file_bytes,
        })

    for addon_type, target_entries, slug_set in (
        ("resourcepacks", resourcepack_entries, used_resourcepack_slugs),
        ("shaderpacks", shaderpack_entries, used_shaderpack_slugs),
    ):
        for _normalized_path, archive_name, file_bytes in _collect_bundled_addon_archives(zf, addon_type):
            if archive_name.lower() in seen_file_names:
                continue
            seen_file_names.add(archive_name.lower())
            slug = _ensure_unique_mod_slug(_slugify_mod_name(archive_name), slug_set)
            target_entries.append({
                "mod_slug": slug,
                "mod_name": os.path.splitext(archive_name)[0],
                "version_label": os.path.splitext(archive_name)[0],
                "file_name": archive_name,
                "file_bytes": file_bytes,
            })

    for entry in manifest_entries:
        archive_name = str(entry.get("file_name") or "").strip()
        if not _validate_mod_filename(archive_name):
            continue

        lower_name = archive_name.lower()
        if lower_name in seen_file_names:
            continue
        seen_file_names.add(lower_name)

        slug = _ensure_unique_mod_slug(_slugify_mod_name(archive_name), used_slugs)
        entries.append({
            "mod_slug": slug,
            "mod_name": str(entry.get("mod_name") or os.path.splitext(archive_name)[0]),
            "version_label": str(entry.get("version_label") or os.path.splitext(archive_name)[0]),
            "file_name": archive_name,
            "file_bytes": entry.get("file_bytes"),
        })

    if not entries:
        details = f" Details: {warnings[0]}" if warnings else ""
        return {"ok": False, "error": f"No importable mod files found in zip.{details}"}

    hlmp_bytes = _build_hlmp_from_mod_entries(
        pack_name,
        pack_version,
        description,
        mod_loader,
        entries,
        author=author,
        resourcepack_entries=resourcepack_entries,
        shaderpack_entries=shaderpack_entries,
    )
    if not hlmp_bytes:
        return {"ok": False, "error": "Failed to convert zip into importable modpack format"}

    result = {
        "ok": True,
        "hlmp_bytes": hlmp_bytes,
        "source_format": "curseforge" if is_curseforge_manifest else "zip",
    }
    if warnings:
        result["warnings"] = warnings
    return result


def _convert_external_modpack_to_hlmp(
    zf: zipfile.ZipFile,
    file_name: str = "",
    source_format: str = "",
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], None]] = None,
) -> Dict[str, Any]:
    forced = str(source_format or "").strip().lower()
    names = {name.lower() for name in zf.namelist()}

    if forced == "mrpack" or "modrinth.index.json" in names:
        return _convert_mrpack_to_hlmp(
            zf,
            file_name=file_name,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

    return _convert_generic_zip_to_hlmp(
        zf,
        file_name=file_name,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )


def import_modpack(
    hlmp_bytes: bytes,
    file_name: str = "",
    source_format: str = "",
    allow_external: bool = True,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], None]] = None,
    is_imported: bool = True,
    source_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(hlmp_bytes), "r")
    except Exception:
        return {"ok": False, "error": "Invalid modpack archive (not a valid zip)"}

    if "data.json" not in zf.namelist():
        if allow_external:
            def conversion_progress(done: int, total: int) -> None:
                if not progress_callback:
                    return
                if total <= 0:
                    progress_callback(0, 100)
                    return
                pct = int(max(0, min(80, (done / total) * 80)))
                progress_callback(pct, 100)

            converted = _convert_external_modpack_to_hlmp(
                zf,
                file_name=file_name,
                source_format=source_format,
                progress_callback=conversion_progress,
                cancel_check=cancel_check,
            )
            zf.close()

            if converted.get("ok") and converted.get("hlmp_bytes"):
                if progress_callback:
                    progress_callback(80, 100)

                def import_progress(done: int, total: int) -> None:
                    if not progress_callback:
                        return
                    if total <= 0:
                        progress_callback(100, 100)
                        return
                    pct = 80 + int(max(0, min(20, (done / total) * 20)))
                    progress_callback(pct, 100)

                result = import_modpack(
                    converted.get("hlmp_bytes"),
                    file_name=file_name,
                    source_format="hlmp",
                    allow_external=False,
                    progress_callback=import_progress,
                    cancel_check=cancel_check,
                    is_imported=is_imported,
                    source_metadata=source_metadata,
                )
                if result.get("ok"):
                    if converted.get("source_format"):
                        result["source_format"] = converted.get("source_format")
                    if converted.get("warnings"):
                        result["import_warnings"] = converted.get("warnings")
                return result

            return converted if isinstance(converted, dict) else {"ok": False, "error": "Unsupported modpack format"}

        zf.close()
        return {"ok": False, "error": "Invalid modpack: missing data.json"}

    try:
        data = json.loads(zf.read("data.json"))
    except Exception:
        zf.close()
        return {"ok": False, "error": "Invalid modpack: corrupt data.json"}

    pack_name = (data.get("name") or "").strip()
    if not pack_name or len(pack_name) > 64 or _MODPACK_NAME_FORBIDDEN.search(pack_name):
        zf.close()
        return {"ok": False, "error": "Invalid modpack name"}

    pack_author = str(data.get("author") or "").strip()
    if len(pack_author) > 64 or _MODPACK_NAME_FORBIDDEN.search(pack_author):
        zf.close()
        return {"ok": False, "error": "Invalid modpack author"}
    data["author"] = pack_author

    mod_loader = (data.get("mod_loader") or "").lower()
    if mod_loader not in SUPPORTED_MOD_LOADERS:
        zf.close()
        return {"ok": False, "error": "Invalid mod_loader in modpack"}

    normalized_mods = []
    for pm in data.get("mods", []):
        if not isinstance(pm, dict):
            continue
        mod_slug = str(pm.get("mod_slug") or "").strip().lower()
        if not mod_slug:
            continue
        entry = {
            "mod_slug": mod_slug,
            "mod_name": pm.get("mod_name", mod_slug),
            "version_label": str(pm.get("version_label") or "").strip(),
            "disabled": bool(pm.get("disabled", False)),
        }
        if "overwrite_classes" in pm:
            entry["overwrite_classes"] = bool(pm.get("overwrite_classes", False))
        if "source_subfolder" in pm:
            entry["source_subfolder"] = str(pm.get("source_subfolder") or "")
        normalized_mods.append(entry)

    data["mods"] = normalized_mods
    pack_mods = normalized_mods
    pack_extra_addons: Dict[str, List[Dict[str, Any]]] = {}
    for addon_type in _MODPACK_EXTRA_ADDON_TYPES:
        normalized_addons = []
        raw_addons = data.get(addon_type)
        if isinstance(raw_addons, list):
            for addon_entry in raw_addons:
                if not isinstance(addon_entry, dict):
                    continue
                addon_slug = _selected_entry_slug(addon_entry)
                if not _validate_mod_slug(addon_slug):
                    continue
                version_label = str(addon_entry.get("version_label") or "").strip()
                if not version_label:
                    continue
                normalized_addons.append({
                    "mod_slug": addon_slug,
                    "mod_name": str(addon_entry.get("mod_name") or addon_entry.get("addon_name") or addon_slug),
                    "version_label": version_label,
                    "disabled": bool(addon_entry.get("disabled", False)),
                    "addon_type": addon_type,
                })
        data[addon_type] = normalized_addons
        data[f"{addon_type[:-1]}_count"] = len(normalized_addons)
        pack_extra_addons[addon_type] = normalized_addons
    slug = _modpack_slug(pack_name)

    existing_packs = get_installed_modpacks()
    incoming_slugs = {m.get("mod_slug") for m in pack_mods if m.get("mod_slug")}

    for ep in existing_packs:
        if ep.get("slug") == slug:
            continue
        ep_slugs = {m.get("mod_slug") for m in ep.get("mods", []) if m.get("mod_slug")}
        overlap = incoming_slugs & ep_slugs
        if overlap:
            names = ", ".join(sorted(overlap)[:5])
            zf.close()
            return {
                "ok": False,
                "error": f"Conflict with modpack \"{ep.get('name', ep.get('slug'))}\": overlapping mods ({names})",
            }

    base = get_modpacks_storage_dir()
    pack_dir = os.path.join(base, slug)
    pack_dir_real = os.path.realpath(pack_dir)
    archive_entries = [
        zi for zi in zf.infolist()
        if (
            not zi.is_dir()
            and (
                zi.filename.startswith("mods/")
                or zi.filename.startswith("mod_icons/")
                or zi.filename.startswith("resourcepacks/")
                or zi.filename.startswith("shaderpacks/")
            )
        )
    ]
    total_extract = len(archive_entries) + (1 if "display.png" in zf.namelist() else 0)
    extracted = 0

    if os.path.isdir(pack_dir):
        shutil.rmtree(pack_dir)
    os.makedirs(pack_dir, exist_ok=True)

    if progress_callback:
        progress_callback(0, total_extract or 1)

    try:
        for zi in archive_entries:
            _raise_if_cancelled(cancel_check)
            normalized = zi.filename.replace("\\", "/")
            parts = normalized.split("/")
            if any(part in ("", ".", "..") for part in parts):
                raise ExternalModpackImportError(f"Invalid path in modpack archive: {zi.filename}")

            target = os.path.join(pack_dir, normalized.replace("/", os.sep))
            target_real = os.path.realpath(target)
            if not _is_within_dir(pack_dir_real, target_real):
                raise ExternalModpackImportError(f"Unsafe archive entry: {zi.filename}")

            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(zi) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)

            extracted += 1
            if progress_callback:
                progress_callback(extracted, total_extract or 1)

        if "display.png" in zf.namelist():
            _raise_if_cancelled(cancel_check)
            display_target = os.path.join(pack_dir, "display.png")
            with zf.open("display.png") as src, open(display_target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted += 1
            if progress_callback:
                progress_callback(extracted, total_extract or 1)

        legacy_loader_root = os.path.join(pack_dir, "mods", mod_loader)
        if os.path.isdir(legacy_loader_root):
            for slug_name in os.listdir(legacy_loader_root):
                _raise_if_cancelled(cancel_check)
                legacy_slug_dir = os.path.join(legacy_loader_root, slug_name)
                if not os.path.isdir(legacy_slug_dir):
                    continue

                canonical_slug_dir = os.path.join(pack_dir, "mods", slug_name)
                os.makedirs(canonical_slug_dir, exist_ok=True)

                for entry in os.listdir(legacy_slug_dir):
                    _raise_if_cancelled(cancel_check)
                    src = os.path.join(legacy_slug_dir, entry)
                    dst = os.path.join(canonical_slug_dir, entry)
                    if os.path.exists(dst):
                        continue
                    shutil.move(src, dst)

                try:
                    if not os.listdir(legacy_slug_dir):
                        os.rmdir(legacy_slug_dir)
                except Exception:
                    pass

            try:
                if not os.listdir(legacy_loader_root):
                    os.rmdir(legacy_loader_root)
            except Exception:
                pass

        legacy_icons_root = os.path.join(pack_dir, "mod_icons")
        if os.path.isdir(legacy_icons_root):
            for slug_name in os.listdir(legacy_icons_root):
                _raise_if_cancelled(cancel_check)
                icon_src = os.path.join(legacy_icons_root, slug_name, "display.png")
                if not os.path.isfile(icon_src):
                    continue
                icon_dst = os.path.join(pack_dir, "mods", slug_name, "display.png")
                os.makedirs(os.path.dirname(icon_dst), exist_ok=True)
                if not os.path.isfile(icon_dst):
                    shutil.copy2(icon_src, icon_dst)

        data["disabled"] = False
        data["slug"] = slug
        data["mods"] = pack_mods
        data["resourcepacks"] = pack_extra_addons.get("resourcepacks", [])
        data["shaderpacks"] = pack_extra_addons.get("shaderpacks", [])
        data["is_imported"] = bool(is_imported)
        data["install_source"] = "imported" if is_imported else "installed"

        metadata = source_metadata if isinstance(source_metadata, dict) else {}
        if metadata:
            source_icon_url = str(metadata.get("icon_url") or "").strip()
            if source_icon_url:
                data["source_icon_url"] = source_icon_url
                data["icon_url"] = source_icon_url

            provider = str(metadata.get("provider") or "").strip()
            if provider:
                data["provider"] = provider

            source_slug = str(metadata.get("mod_slug") or metadata.get("slug") or "").strip().lower()
            if source_slug:
                data["source_slug"] = source_slug

            source_project_id = str(metadata.get("mod_id") or metadata.get("project_id") or "").strip()
            if source_project_id:
                data["source_project_id"] = source_project_id

            download_url = str(metadata.get("download_url") or "").strip()
            if download_url:
                data["source_download_url"] = download_url

            if not is_imported:
                source_name = str(metadata.get("name") or metadata.get("mod_name") or "").strip()
                if source_name:
                    data["name"] = _sanitize_modpack_name(source_name, fallback=data.get("name") or pack_name)

                source_description = str(metadata.get("description") or "").strip()
                if source_description:
                    data["description"] = source_description[:8192]
                elif str(data.get("description") or "").lower().startswith("imported from"):
                    provider_label = str(data.get("provider") or "launcher").strip().title()
                    data["description"] = f"Installed from {provider_label}"

                source_version = str(metadata.get("version") or "").strip()
                if source_version:
                    data["version"] = normalize_version_label(source_version)
        with open(os.path.join(pack_dir, "data.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        mods_storage = get_mods_storage_dir()
        disabled_standalone = []
        for pm in pack_mods:
            _raise_if_cancelled(cancel_check)
            if not _is_modpack_mod_enabled(pm):
                continue
            ms = pm.get("mod_slug", "")
            if not ms:
                continue
            mod_dir = os.path.join(mods_storage, mod_loader, ms)
            meta_file = os.path.join(mod_dir, "mod_meta.json")
            if os.path.isfile(meta_file):
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        mm = json.load(f)
                    if not mm.get("disabled"):
                        mm["disabled"] = True
                        mm["blocked_by_modpack"] = slug
                        with open(meta_file, "w", encoding="utf-8") as f:
                            json.dump(mm, f, indent=2)
                        disabled_standalone.append(ms)
                except Exception:
                    pass

        return {
            "ok": True,
            "name": pack_name,
            "slug": slug,
            "disabled_standalone": disabled_standalone,
        }
    except ExternalModpackImportError as exc:
        shutil.rmtree(pack_dir, ignore_errors=True)
        return {"ok": False, "error": str(exc)}
    except Exception:
        shutil.rmtree(pack_dir, ignore_errors=True)
        raise
    finally:
        zf.close()


def toggle_addon_in_modpack(
    pack_slug: str,
    addon_type: str,
    addon_slug: str,
    disabled: bool,
) -> bool:
    normalized_type = str(addon_type or "mods").strip().lower()
    if normalized_type not in ("mods", *_MODPACK_EXTRA_ADDON_TYPES):
        return False
    if not _validate_modpack_slug(pack_slug) or not _validate_mod_slug(addon_slug):
        return False
    base = get_modpacks_storage_dir()
    data_file = os.path.join(base, pack_slug, "data.json")
    if not os.path.isfile(data_file):
        return False
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        found = False
        entries = data.get(normalized_type, [])
        if not isinstance(entries, list):
            return False
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_slug = str(
                entry.get("mod_slug") or entry.get("addon_slug") or ""
            ).strip().lower()
            if entry_slug == addon_slug:
                entry["disabled"] = disabled
                found = True
        if not found:
            return False
        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(
            f"Toggled {normalized_type} addon {addon_slug} in modpack {pack_slug}: "
            f"disabled={disabled}"
        )
        return True
    except Exception as e:
        logger.error(
            f"Failed to toggle {normalized_type} addon in modpack "
            f"{pack_slug}/{addon_slug}: {e}"
        )
        return False


def toggle_mod_in_modpack(pack_slug: str, mod_slug: str, disabled: bool) -> bool:
    return toggle_addon_in_modpack(pack_slug, "mods", mod_slug, disabled)


def set_modpack_mod_overwrite(
    pack_slug: str,
    mod_slug: str,
    overwrite_classes: bool,
    source_subfolder: str = "",
) -> bool:
    if not _validate_modpack_slug(pack_slug) or not _validate_mod_slug(mod_slug):
        return False
    base = get_modpacks_storage_dir()
    pack_dir = os.path.join(base, pack_slug)
    data_file = os.path.join(pack_dir, "data.json")
    if not os.path.isfile(data_file):
        return False

    overwrite_flag = bool(overwrite_classes)
    subfolder_value = str(source_subfolder or "")

    try:
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        target_entry = None
        for m in data.get("mods", []):
            if m.get("mod_slug") == mod_slug:
                m["overwrite_classes"] = overwrite_flag
                m["source_subfolder"] = subfolder_value
                target_entry = m
                break

        if target_entry is None:
            return False

        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        ver_label = str(target_entry.get("version_label") or "").strip()
        if ver_label:
            packed_meta_path = os.path.join(
                pack_dir, "mods", mod_slug, ver_label, "version_meta.json"
            )
            packed_meta = {}
            if os.path.isfile(packed_meta_path):
                try:
                    with open(packed_meta_path, "r", encoding="utf-8") as vmf:
                        packed_meta = json.load(vmf) or {}
                except Exception:
                    packed_meta = {}
            packed_meta["overwrite_classes"] = overwrite_flag
            packed_meta["source_subfolder"] = subfolder_value
            os.makedirs(os.path.dirname(packed_meta_path), exist_ok=True)
            with open(packed_meta_path, "w", encoding="utf-8") as vmf:
                json.dump(packed_meta, vmf, indent=2)

        logger.info(
            f"Updated overwrite settings for {mod_slug} in modpack {pack_slug}: "
            f"overwrite_classes={overwrite_flag}, source_subfolder={subfolder_value!r}"
        )
        return True
    except Exception as e:
        logger.error(
            f"Failed to update overwrite settings for {pack_slug}/{mod_slug}: {e}"
        )
        return False


def toggle_modpack(slug: str, disabled: bool) -> bool:
    if not _validate_modpack_slug(slug):
        return False
    base = get_modpacks_storage_dir()
    data_file = os.path.join(base, slug, "data.json")
    if not os.path.isfile(data_file):
        return False
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["disabled"] = disabled
        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        if disabled:
            _unblock_standalone_mods(slug)

        if not disabled:
            mods_storage = get_mods_storage_dir()
            mod_loader = data.get("mod_loader", "")
            for pm in data.get("mods", []):
                if not _is_modpack_mod_enabled(pm):
                    continue
                ms = pm.get("mod_slug", "")
                if not ms:
                    continue
                mod_dir = os.path.join(mods_storage, mod_loader, ms)
                meta_file = os.path.join(mod_dir, "mod_meta.json")
                if os.path.isfile(meta_file):
                    try:
                        with open(meta_file, "r", encoding="utf-8") as f:
                            mm = json.load(f)
                        mm["disabled"] = True
                        mm["blocked_by_modpack"] = slug
                        with open(meta_file, "w", encoding="utf-8") as f:
                            json.dump(mm, f, indent=2)
                    except Exception:
                        pass

        return True
    except Exception as e:
        logger.error(f"Failed to toggle modpack {slug}: {e}")
        return False


def delete_modpack(slug: str) -> bool:
    if not _validate_modpack_slug(slug):
        return False
    base = get_modpacks_storage_dir()
    pack_dir = os.path.join(base, slug)
    if not os.path.isdir(pack_dir):
        return False
    try:
        _unblock_standalone_mods(slug)
        shutil.rmtree(pack_dir)
        logger.info(f"Deleted modpack {slug}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete modpack {slug}: {e}")
        return False


def _unblock_standalone_mods(modpack_slug: str):
    mods_storage = get_mods_storage_dir()
    if not os.path.isdir(mods_storage):
        return
    for loader_name in os.listdir(mods_storage):
        loader_path = os.path.join(mods_storage, loader_name)
        if not os.path.isdir(loader_path):
            continue
        for mod_slug in os.listdir(loader_path):
            mod_path = os.path.join(loader_path, mod_slug)
            meta_file = os.path.join(mod_path, "mod_meta.json")
            if not os.path.isfile(meta_file):
                continue
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    mm = json.load(f)
                if mm.get("blocked_by_modpack") == modpack_slug:
                    mm["disabled"] = False
                    mm.pop("blocked_by_modpack", None)
                    with open(meta_file, "w", encoding="utf-8") as f:
                        json.dump(mm, f, indent=2)
            except Exception:
                pass
