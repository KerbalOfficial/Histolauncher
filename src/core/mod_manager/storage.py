from __future__ import annotations

import io
import json
import os
import shutil
import urllib.request
import zipfile
from typing import Any, Dict, List, Tuple

from core.settings import _apply_url_proxy, get_mods_profile_dir

from core.mod_manager._constants import (
    ADDON_STORAGE_DIRS,
    SUPPORTED_MOD_LOADERS,
    logger,
)
from core.mod_manager._validation import (
    _is_within_dir,
    _validate_addon_filename,
    _validate_mod_filename,
    _validate_mod_slug,
    addon_type_uses_loaders,
    normalize_addon_compatibility_types,
    normalize_addon_type,
    normalize_version_label,
)


def get_addons_profile_root() -> str:
    return get_mods_profile_dir()


def get_addon_storage_dir(addon_type: str) -> str:
    normalized_type = normalize_addon_type(addon_type)
    profile_root = get_addons_profile_root()
    storage_name = ADDON_STORAGE_DIRS.get(normalized_type, "mods")
    storage_dir = os.path.join(profile_root, storage_name)
    os.makedirs(storage_dir, exist_ok=True)
    return storage_dir


def get_mods_storage_dir() -> str:
    return get_addon_storage_dir("mods")


def get_addon_dir(addon_type: str, mod_slug: str, mod_loader: str = "") -> str:
    if not _validate_mod_slug(mod_slug):
        raise ValueError(f"Invalid mod slug: {mod_slug}")

    normalized_type = normalize_addon_type(addon_type)
    storage_dir = get_addon_storage_dir(normalized_type)
    if addon_type_uses_loaders(normalized_type):
        loader_key = str(mod_loader or "").strip().lower()
        if loader_key not in SUPPORTED_MOD_LOADERS:
            raise ValueError(f"Invalid mod loader: {mod_loader}")
        mod_dir = os.path.join(storage_dir, loader_key, mod_slug)
    else:
        mod_dir = os.path.join(storage_dir, mod_slug)
    os.makedirs(mod_dir, exist_ok=True)
    return mod_dir


def get_mod_dir(mod_loader: str, mod_slug: str) -> str:
    return get_addon_dir("mods", mod_slug, mod_loader=mod_loader)


def get_addon_version_dir(addon_type: str, mod_slug: str, version_label: str, mod_loader: str = "") -> str:
    mod_dir = get_addon_dir(addon_type, mod_slug, mod_loader=mod_loader)
    safe_label = normalize_version_label(version_label)
    ver_dir = os.path.join(mod_dir, safe_label)
    os.makedirs(ver_dir, exist_ok=True)
    return ver_dir


def get_mod_version_dir(mod_loader: str, mod_slug: str, version_label: str) -> str:
    return get_addon_version_dir("mods", mod_slug, version_label, mod_loader=mod_loader)


def _resolve_mod_archive_path(version_dir: str, preferred_file_name: str = "") -> str:
    safe_preferred = os.path.basename(str(preferred_file_name or "").strip())
    if safe_preferred and _validate_mod_filename(safe_preferred):
        preferred_path = os.path.join(version_dir, safe_preferred)
        if os.path.isfile(preferred_path):
            return preferred_path

    try:
        archive_names = sorted(
            (
                name for name in os.listdir(version_dir)
                if _validate_mod_filename(name)
            ),
            key=lambda x: x.lower(),
        )
    except Exception:
        return ""

    if not archive_names:
        return ""
    return os.path.join(version_dir, archive_names[0])


def _build_addon_icon_url(addon_type: str, mod_slug: str, loader_name: str = "") -> str:
    normalized_type = normalize_addon_type(addon_type)
    if normalized_type == "mods":
        return f"/mods-cache/{loader_name}/{mod_slug}/display.png"
    return f"/addons-cache/{normalized_type}/{mod_slug}/display.png"


def get_installed_addons(addon_type: str = "mods") -> List[Dict[str, Any]]:
    normalized_type = normalize_addon_type(addon_type)
    mods_storage = get_addon_storage_dir(normalized_type)
    installed = []

    if not os.path.isdir(mods_storage):
        return installed

    if addon_type_uses_loaders(normalized_type):
        loader_entries = []
        for loader_name in os.listdir(mods_storage):
            loader_path = os.path.join(mods_storage, loader_name)
            if os.path.isdir(loader_path):
                loader_entries.append((loader_name, loader_path))
    else:
        loader_entries = [("", mods_storage)]

    for loader_name, loader_path in loader_entries:
        for mod_slug in os.listdir(loader_path):
            mod_path = os.path.join(loader_path, mod_slug)
            if not os.path.isdir(mod_path):
                continue

            display_path = os.path.join(mod_path, "display.png")
            local_icon_url = ""
            if os.path.isfile(display_path):
                local_icon_url = _build_addon_icon_url(normalized_type, mod_slug, loader_name)

            meta_file = os.path.join(mod_path, "mod_meta.json")
            if not os.path.isfile(meta_file):
                continue

            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception as e:
                loader_prefix = f"{loader_name}/" if loader_name else ""
                logger.warning(f"Failed to read addon meta for {normalized_type}:{loader_prefix}{mod_slug}: {e}")
                continue

            versions = []
            for entry in os.listdir(mod_path):
                ver_path = os.path.join(mod_path, entry)
                if not os.path.isdir(ver_path):
                    continue
                ver_meta_file = os.path.join(ver_path, "version_meta.json")
                if not os.path.isfile(ver_meta_file):
                    continue
                try:
                    with open(ver_meta_file, "r", encoding="utf-8") as f:
                        ver_meta = json.load(f)
                    mod_files = [
                        fn for fn in os.listdir(ver_path)
                        if _validate_addon_filename(fn, normalized_type)
                    ]
                    compatibility_types = normalize_addon_compatibility_types(
                        normalized_type,
                        ver_meta.get("compatibility_types"),
                        fallback=ver_meta.get("mod_loader", loader_name),
                    )
                    versions.append({
                        "version_label": entry,
                        "version": ver_meta.get("version", entry),
                        "mod_loader": ver_meta.get("mod_loader", loader_name),
                        "compatibility_types": compatibility_types,
                        "file_name": ver_meta.get("file_name", ""),
                        "overwrite_classes": bool(ver_meta.get("overwrite_classes", False)),
                        "source_subfolder": str(ver_meta.get("source_subfolder", "") or ""),
                        "file_count": len(mod_files),
                        "jar_count": len(mod_files),
                    })
                except Exception as e:
                    loader_prefix = f"{loader_name}/" if loader_name else ""
                    logger.warning(
                        f"Failed to read addon version meta {normalized_type}:{loader_prefix}{mod_slug}/{entry}: {e}"
                    )

            compatibility_types = normalize_addon_compatibility_types(
                normalized_type,
                meta.get("compatibility_types"),
                fallback=meta.get("mod_loader", loader_name),
            )
            installed.append({
                "mod_slug": mod_slug,
                "mod_name": meta.get("name", mod_slug),
                "mod_id": meta.get("mod_id"),
                "mod_loader": meta.get("mod_loader", loader_name),
                "compatibility_types": compatibility_types,
                "description": meta.get("description", ""),
                "icon_url": local_icon_url or meta.get("icon_url", ""),
                "provider": meta.get("provider", "unknown"),
                "active_version": meta.get("active_version", ""),
                "disabled": meta.get("disabled", False),
                "is_imported": meta.get("is_imported", False),
                "addon_type": meta.get("addon_type", normalized_type),
                "versions": versions,
            })

    return installed


def get_installed_mods() -> List[Dict[str, Any]]:
    return get_installed_addons("mods")


def save_addon_metadata(addon_type: str, mod_slug: str, metadata: Dict[str, Any], mod_loader: str = ""):
    mod_dir = get_addon_dir(addon_type, mod_slug, mod_loader=mod_loader)
    meta_file = os.path.join(mod_dir, "mod_meta.json")

    try:
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
    except Exception as e:
        loader_prefix = f"{mod_loader}/" if mod_loader else ""
        logger.error(f"Failed to save addon metadata for {normalize_addon_type(addon_type)}:{loader_prefix}{mod_slug}: {e}")


def save_mod_metadata(mod_loader: str, mod_slug: str, metadata: Dict[str, Any]):
    save_addon_metadata("mods", mod_slug, metadata, mod_loader=mod_loader)


def save_addon_version_metadata(
    addon_type: str,
    mod_slug: str,
    version_label: str,
    metadata: Dict[str, Any],
    mod_loader: str = "",
):
    ver_dir = get_addon_version_dir(addon_type, mod_slug, version_label, mod_loader=mod_loader)
    meta_file = os.path.join(ver_dir, "version_meta.json")

    try:
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
    except Exception as e:
        loader_prefix = f"{mod_loader}/" if mod_loader else ""
        logger.error(
            f"Failed to save addon version metadata for "
            f"{normalize_addon_type(addon_type)}:{loader_prefix}{mod_slug}/{version_label}: {e}"
        )


def save_version_metadata(mod_loader: str, mod_slug: str, version_label: str, metadata: Dict[str, Any]):
    save_addon_version_metadata("mods", mod_slug, version_label, metadata, mod_loader=mod_loader)


def set_addon_active_version(addon_type: str, mod_slug: str, version_label: str, mod_loader: str = "") -> bool:
    mod_dir = get_addon_dir(addon_type, mod_slug, mod_loader=mod_loader)
    meta_file = os.path.join(mod_dir, "mod_meta.json")
    if not os.path.isfile(meta_file):
        return False
    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["active_version"] = version_label
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        logger.info(
            f"Set active version for {normalize_addon_type(addon_type)}:{mod_loader or '-'}:{mod_slug} to {version_label}"
        )
        return True
    except Exception as e:
        logger.error(f"Failed to set active addon version for {mod_slug}: {e}")
        return False


def set_active_version(mod_loader: str, mod_slug: str, version_label: str) -> bool:
    return set_addon_active_version("mods", mod_slug, version_label, mod_loader=mod_loader)


def toggle_addon_disabled(addon_type: str, mod_slug: str, disabled: bool, mod_loader: str = "") -> bool:
    mod_dir = get_addon_dir(addon_type, mod_slug, mod_loader=mod_loader)
    meta_file = os.path.join(mod_dir, "mod_meta.json")
    if not os.path.isfile(meta_file):
        return False
    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["disabled"] = disabled
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        logger.info(
            f"{'Disabled' if disabled else 'Enabled'} "
            f"{normalize_addon_type(addon_type)}:{mod_loader or '-'}:{mod_slug}"
        )
        return True
    except Exception as e:
        logger.error(f"Failed to toggle addon {mod_slug}: {e}")
        return False


def toggle_mod_disabled(mod_loader: str, mod_slug: str, disabled: bool) -> bool:
    return toggle_addon_disabled("mods", mod_slug, disabled, mod_loader=mod_loader)


def download_addon_icon(icon_url: str, addon_type: str, mod_slug: str, mod_loader: str = "") -> bool:
    if not icon_url:
        return False
    mod_dir = get_addon_dir(addon_type, mod_slug, mod_loader=mod_loader)
    display_path = os.path.join(mod_dir, "display.png")
    if os.path.isfile(display_path):
        return True
    try:
        url = _apply_url_proxy(icon_url)
        req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher/1.0"})
        with urllib.request.urlopen(req, timeout=10.0) as response:
            with open(display_path, "wb") as f:
                shutil.copyfileobj(response, f)
        return True
    except Exception as e:
        logger.warning(f"Failed to download addon icon for {mod_slug}: {e}")
        return False


def download_mod_icon(icon_url: str, mod_loader: str, mod_slug: str) -> bool:
    return download_addon_icon(icon_url, "mods", mod_slug, mod_loader=mod_loader)


def _get_default_addon_icon_path(addon_type: str) -> str:
    normalized_type = normalize_addon_type(addon_type)
    ui_images_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "ui",
        "assets",
        "images",
    )

    if normalized_type in ("resourcepacks", "shaderpacks"):
        preferred = os.path.join(ui_images_dir, "placeholder_pack.png")
        if os.path.isfile(preferred):
            return preferred

    fallback = os.path.join(ui_images_dir, "placeholder.png")
    if os.path.isfile(fallback):
        return fallback
    return ""


def save_addon_import_icon(addon_type: str, mod_slug: str, file_data: bytes, mod_loader: str = "") -> bool:
    normalized_type = normalize_addon_type(addon_type)
    mod_dir = get_addon_dir(normalized_type, mod_slug, mod_loader=mod_loader)
    display_path = os.path.join(mod_dir, "display.png")

    try:
        if normalized_type == "resourcepacks" and isinstance(file_data, (bytes, bytearray)) and file_data:
            with zipfile.ZipFile(io.BytesIO(file_data), "r") as zf:
                for name in zf.namelist():
                    normalized_name = str(name or "").replace("\\", "/").strip("/")
                    if not normalized_name or normalized_name.endswith("/"):
                        continue
                    if os.path.basename(normalized_name).lower() != "pack.png":
                        continue
                    with zf.open(name, "r") as src, open(display_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    return True
    except Exception as e:
        logger.warning(f"Failed to extract imported {normalized_type} icon for {mod_slug}: {e}")

    fallback_icon = _get_default_addon_icon_path(normalized_type)
    if fallback_icon and os.path.isfile(fallback_icon):
        try:
            shutil.copyfile(fallback_icon, display_path)
            return True
        except Exception as e:
            logger.warning(f"Failed to copy fallback addon icon for {mod_slug}: {e}")
    return False


def delete_addon(addon_type: str, mod_slug: str, version_label: str = None, mod_loader: str = "") -> bool:
    if not _validate_mod_slug(mod_slug):
        return False

    mod_dir = get_addon_dir(addon_type, mod_slug, mod_loader=mod_loader)

    try:
        if version_label:
            safe_version_label = normalize_version_label(version_label)
            ver_dir = os.path.join(mod_dir, safe_version_label)
            if not _is_within_dir(mod_dir, ver_dir):
                return False
            if os.path.isdir(ver_dir):
                shutil.rmtree(ver_dir)
                logger.info(
                    f"Deleted version {safe_version_label} of "
                    f"{normalize_addon_type(addon_type)}:{mod_loader or '-'}:{mod_slug}"
                )

                meta_file = os.path.join(mod_dir, "mod_meta.json")
                if os.path.isfile(meta_file):
                    with open(meta_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    if meta.get("active_version") == safe_version_label:
                        remaining = [d for d in os.listdir(mod_dir)
                                     if os.path.isdir(os.path.join(mod_dir, d))
                                     and os.path.isfile(os.path.join(mod_dir, d, "version_meta.json"))]
                        meta["active_version"] = remaining[0] if remaining else ""
                        with open(meta_file, "w", encoding="utf-8") as f:
                            json.dump(meta, f, indent=2)

                remaining = [d for d in os.listdir(mod_dir)
                             if os.path.isdir(os.path.join(mod_dir, d))
                             and os.path.isfile(os.path.join(mod_dir, d, "version_meta.json"))]
                if not remaining:
                    shutil.rmtree(mod_dir)
                    logger.info(f"No versions left - deleted entire addon {mod_slug}")
                return True
            return False
        else:
            if os.path.isdir(mod_dir):
                shutil.rmtree(mod_dir)
                logger.info(f"Deleted addon {mod_slug}")
                return True
    except Exception as e:
        logger.error(f"Failed to delete addon {mod_slug}: {e}")

    return False


def delete_mod(mod_loader: str, mod_slug: str, version_label: str = None) -> bool:
    return delete_addon("mods", mod_slug, version_label, mod_loader=mod_loader)


def move_mod_to_loader(mod_loader: str, mod_slug: str, target_loader: str) -> Tuple[bool, str]:
    source_loader = str(mod_loader or "").strip().lower()
    destination_loader = str(target_loader or "").strip().lower()

    if source_loader not in SUPPORTED_MOD_LOADERS:
        return False, "Invalid source mod loader"
    if destination_loader not in SUPPORTED_MOD_LOADERS:
        return False, "Invalid target mod loader"
    if source_loader == destination_loader:
        return False, "Source and target mod loader are the same"
    if not _validate_mod_slug(mod_slug):
        return False, "Invalid mod_slug format"

    mods_storage = get_mods_storage_dir()
    source_dir = os.path.join(mods_storage, source_loader, mod_slug)
    dest_loader_dir = os.path.join(mods_storage, destination_loader)
    dest_dir = os.path.join(dest_loader_dir, mod_slug)

    if not os.path.isdir(source_dir):
        return False, f"Mod not found: {source_loader}/{mod_slug}"
    if os.path.exists(dest_dir):
        return False, f"Target already has a mod with this slug: {destination_loader}/{mod_slug}"

    try:
        os.makedirs(dest_loader_dir, exist_ok=True)
        shutil.move(source_dir, dest_dir)

        meta_file = os.path.join(dest_dir, "mod_meta.json")
        if os.path.isfile(meta_file):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                meta = {}
            meta["mod_loader"] = destination_loader
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)

        for entry in os.listdir(dest_dir):
            version_dir = os.path.join(dest_dir, entry)
            if not os.path.isdir(version_dir):
                continue
            version_meta_file = os.path.join(version_dir, "version_meta.json")
            if not os.path.isfile(version_meta_file):
                continue
            try:
                with open(version_meta_file, "r", encoding="utf-8") as f:
                    version_meta = json.load(f)
            except Exception:
                version_meta = {}
            version_meta["mod_loader"] = destination_loader
            with open(version_meta_file, "w", encoding="utf-8") as f:
                json.dump(version_meta, f, indent=2)

        logger.info(f"Moved mod {mod_slug} from {source_loader} to {destination_loader}")
        return True, f"Moved {mod_slug} from {source_loader} to {destination_loader}"
    except Exception as e:
        logger.error(f"Failed to move mod {mod_slug} from {source_loader} to {destination_loader}: {e}")
        return False, str(e)
