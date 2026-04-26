from __future__ import annotations

import os
import re
from typing import Any

from server.api._constants import (
    MAX_ARCHIVE_SUBFOLDER_LENGTH,
    MAX_CATEGORY_LENGTH,
    MAX_FILENAME_LENGTH,
    MAX_MOD_SLUG_LENGTH,
    MAX_MODPACK_SLUG_LENGTH,
    MAX_VERSION_ID_LENGTH,
    MAX_VERSION_LABEL_LENGTH,
    VALID_ADDON_TYPES,
    VALID_LOADER_TYPES,
    VALID_MOD_LOADERS,
)


__all__ = [
    "_validate_version_string",
    "_validate_category_string",
    "_validate_loader_type",
    "_validate_mod_loader_type",
    "_normalize_addon_type",
    "_validate_addon_type",
    "_looks_like_path_traversal",
    "_validate_mod_slug",
    "_validate_modpack_slug",
    "_validate_version_label",
    "_validate_mod_filename",
    "_validate_addon_filename",
    "_normalize_mod_archive_subfolder",
    "_slugify_import_name",
]


def _validate_version_string(version_id: str, max_length: int = MAX_VERSION_ID_LENGTH) -> bool:
    if not isinstance(version_id, str):
        return False
    version_id = version_id.strip()
    if not version_id or len(version_id) > max_length:
        return False
    if _looks_like_path_traversal(version_id):
        return False
    return bool(re.match(r"^[a-zA-Z0-9._-]+$", version_id))


def _validate_category_string(category: str, max_length: int = MAX_CATEGORY_LENGTH) -> bool:
    if not isinstance(category, str):
        return False
    category = category.strip()
    if not category or len(category) > max_length:
        return False
    return bool(re.match(r"^[a-zA-Z0-9 _-]+$", category))


def _validate_loader_type(loader_type: str) -> bool:
    return loader_type in VALID_LOADER_TYPES


def _validate_mod_loader_type(loader_type: str) -> bool:
    return loader_type in VALID_MOD_LOADERS


def _normalize_addon_type(addon_type: Any) -> str:
    raw = str(addon_type or "mods").strip().lower()
    aliases = {
        "mod": "mods",
        "mods": "mods",
        "resourcepack": "resourcepacks",
        "resourcepacks": "resourcepacks",
        "resource-pack": "resourcepacks",
        "resource-packs": "resourcepacks",
        "shader": "shaderpacks",
        "shaders": "shaderpacks",
        "shaderpack": "shaderpacks",
        "shaderpacks": "shaderpacks",
        "shader-pack": "shaderpacks",
        "shader-packs": "shaderpacks",
        "modpack": "modpacks",
        "modpacks": "modpacks",
        "mod-pack": "modpacks",
        "mod-packs": "modpacks",
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in VALID_ADDON_TYPES else "mods"


def _validate_addon_type(addon_type: Any) -> bool:
    return _normalize_addon_type(addon_type) in VALID_ADDON_TYPES


def _looks_like_path_traversal(value: str) -> bool:
    if not isinstance(value, str):
        return True
    if "\x00" in value:
        return True
    normalized = value.replace("\\", "/")
    if "/" in normalized:
        return True
    if ".." in normalized:
        return True
    if os.path.isabs(value):
        return True
    if len(value) >= 2 and value[1] == ":":
        return True
    return False


def _validate_mod_slug(mod_slug: str, max_length: int = MAX_MOD_SLUG_LENGTH) -> bool:
    if not isinstance(mod_slug, str):
        return False
    mod_slug = mod_slug.strip().lower()
    if not mod_slug or len(mod_slug) > max_length:
        return False
    if _looks_like_path_traversal(mod_slug):
        return False
    return bool(re.match(r"^[a-z0-9][a-z0-9._-]*$", mod_slug))


def _validate_modpack_slug(slug: str, max_length: int = MAX_MODPACK_SLUG_LENGTH) -> bool:
    if not isinstance(slug, str):
        return False
    slug = slug.strip().lower()
    if not slug or len(slug) > max_length:
        return False
    if _looks_like_path_traversal(slug):
        return False
    return bool(re.match(r"^[a-z0-9][a-z0-9-]*$", slug))


def _validate_version_label(version_label: str, max_length: int = MAX_VERSION_LABEL_LENGTH) -> bool:
    if not isinstance(version_label, str):
        return False
    version_label = version_label.strip()
    if not version_label or len(version_label) > max_length:
        return False
    return not _looks_like_path_traversal(version_label)


def _validate_mod_filename(file_name: str, max_length: int = MAX_FILENAME_LENGTH) -> bool:
    if not isinstance(file_name, str):
        return False
    file_name = file_name.strip()
    if not file_name or len(file_name) > max_length:
        return False
    if _looks_like_path_traversal(file_name):
        return False
    if os.path.basename(file_name) != file_name:
        return False
    if any(c in file_name for c in '<>:"|?*'):
        return False
    return os.path.splitext(file_name)[1].lower() in {".jar", ".zip"}


def _validate_addon_filename(
    file_name: str, addon_type: Any, max_length: int = MAX_FILENAME_LENGTH
) -> bool:
    if not isinstance(file_name, str):
        return False
    file_name = file_name.strip()
    if not file_name or len(file_name) > max_length:
        return False
    if _looks_like_path_traversal(file_name):
        return False
    if os.path.basename(file_name) != file_name:
        return False
    if any(c in file_name for c in '<>:"|?*'):
        return False

    normalized_type = _normalize_addon_type(addon_type)
    if normalized_type == "mods":
        allowed_exts = {".jar", ".zip"}
    elif normalized_type == "modpacks":
        allowed_exts = {".hlmp", ".mrpack", ".zip"}
    else:
        allowed_exts = {".zip"}
    return os.path.splitext(file_name)[1].lower() in allowed_exts


def _normalize_mod_archive_subfolder(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if raw in ("", "/", ".", "./"):
        return ""
    if len(raw) > MAX_ARCHIVE_SUBFOLDER_LENGTH:
        raise ValueError("source_subfolder is too long")
    if raw.startswith("/"):
        raise ValueError("source_subfolder must be relative")

    parts = []
    for seg_raw in raw.split("/"):
        seg = seg_raw.strip()
        if not seg:
            continue
        if seg in (".", ".."):
            raise ValueError("source_subfolder contains path traversal")
        if any(ord(ch) < 32 for ch in seg) or ":" in seg:
            raise ValueError("source_subfolder contains invalid characters")
        parts.append(seg)

    normalized = "/".join(parts).strip("/")
    if normalized in ("", "."):
        return ""
    if normalized.startswith("../") or normalized == "..":
        raise ValueError("source_subfolder contains path traversal")
    return normalized


def _slugify_import_name(value: str) -> str:
    base = os.path.splitext(os.path.basename(str(value or "").strip()))[0].lower()
    slug = re.sub(r"[^a-z0-9]+", "-", base).strip("-") or "imported-mod"
    if not _validate_mod_slug(slug):
        slug = "imported-mod"
    return slug
