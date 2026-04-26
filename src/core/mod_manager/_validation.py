from __future__ import annotations

import os
import re
import urllib.parse
from typing import Any, List

from core.settings import _apply_url_proxy

from core.mod_manager._constants import (
    ADDON_IMPORT_EXTENSIONS,
    SUPPORTED_ADDON_TYPES,
    SUPPORTED_MOD_LOADERS,
    SUPPORTED_SHADER_TYPES,
    _MAX_SAFE_COMPONENT_LENGTH,
    _SUPPORTED_MOD_ARCHIVE_EXTENSIONS,
)


def _is_within_dir(base_dir: str, target_path: str) -> bool:
    base_real = os.path.realpath(base_dir)
    target_real = os.path.realpath(target_path)
    return target_real == base_real or target_real.startswith(base_real + os.sep)


def _validate_mod_slug(mod_slug: str) -> bool:
    if not isinstance(mod_slug, str):
        return False
    s = mod_slug.strip().lower()
    if not s or len(s) > _MAX_SAFE_COMPONENT_LENGTH:
        return False
    if "/" in s or "\\" in s or ".." in s:
        return False
    return bool(re.match(r"^[a-z0-9][a-z0-9._-]*$", s))


def _validate_modpack_slug(slug: str) -> bool:
    if not isinstance(slug, str):
        return False
    s = slug.strip().lower()
    if not s or len(s) > _MAX_SAFE_COMPONENT_LENGTH:
        return False
    if "/" in s or "\\" in s or ".." in s:
        return False
    return bool(re.match(r"^[a-z0-9][a-z0-9-]*$", s))


def normalize_version_label(version_label: str) -> str:
    raw = str(version_label or "").strip()
    raw = raw.replace("/", "_").replace("\\", "_").replace("|", "_").replace("..", "_")
    safe_label = re.sub(r"[^a-zA-Z0-9._ +()-]+", "_", raw).strip(" .")
    if not safe_label:
        safe_label = "unknown"
    return safe_label[:_MAX_SAFE_COMPONENT_LENGTH]


def _validate_mod_filename(file_name: str) -> bool:
    if not isinstance(file_name, str):
        return False
    f = file_name.strip()
    if not f or len(f) > 255:
        return False
    if os.path.basename(f) != f:
        return False
    if "/" in f or "\\" in f or ".." in f:
        return False
    if any(c in f for c in '<>:"|?*'):
        return False
    return os.path.splitext(f)[1].lower() in _SUPPORTED_MOD_ARCHIVE_EXTENSIONS


def normalize_addon_type(addon_type: str) -> str:
    raw = str(addon_type or "mods").strip().lower()
    aliases = {
        "mod": "mods",
        "mods": "mods",
        "resourcepack": "resourcepacks",
        "resourcepacks": "resourcepacks",
        "resource-pack": "resourcepacks",
        "modpack": "modpacks",
        "mod_pack": "modpacks",
        "resource-packs": "resourcepacks",
        "shader": "shaderpacks",
        "shaders": "shaderpacks",
        "shaderpack": "shaderpacks",
        "shaderpacks": "shaderpacks",
        "shader-pack": "shaderpacks",
        "shader-packs": "shaderpacks",
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in SUPPORTED_ADDON_TYPES else "mods"


def addon_type_uses_loaders(addon_type: str) -> bool:
    return normalize_addon_type(addon_type) == "mods"


def _normalize_addon_compatibility_token(value: Any) -> str:
    compact = re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())
    aliases = {
        "fabric": "fabric",
        "babric": "babric",
        "forge": "forge",
        "modloader": "modloader",
        "neoforge": "neoforge",
        "quilt": "quilt",
        "optifine": "optifine",
        "iris": "iris",
    }
    if compact in aliases:
        return aliases[compact]
    if "optifine" in compact:
        return "optifine"
    if "iris" in compact:
        return "iris"
    return ""


def normalize_addon_compatibility_types(
    addon_type: str,
    values: Any,
    fallback: Any = None,
) -> List[str]:
    normalized_type = normalize_addon_type(addon_type)
    if normalized_type in ("mods", "modpacks"):
        allowed = set(SUPPORTED_MOD_LOADERS)
    elif normalized_type == "shaderpacks":
        allowed = set(SUPPORTED_SHADER_TYPES)
    else:
        allowed = set()

    raw_values: List[Any] = []
    if isinstance(values, (list, tuple, set)):
        raw_values.extend(list(values))
    elif values not in (None, ""):
        raw_values.append(values)

    if isinstance(fallback, (list, tuple, set)):
        raw_values.extend(list(fallback))
    elif fallback not in (None, ""):
        raw_values.append(fallback)

    seen = set()
    normalized_values: List[str] = []
    for value in raw_values:
        normalized = _normalize_addon_compatibility_token(value)
        if not normalized or normalized not in allowed or normalized in seen:
            continue
        seen.add(normalized)
        normalized_values.append(normalized)
    return normalized_values


def _validate_addon_filename(file_name: str, addon_type: str = "mods") -> bool:
    if not isinstance(file_name, str):
        return False
    f = file_name.strip()
    if not f or len(f) > 255:
        return False
    if os.path.basename(f) != f:
        return False
    if "/" in f or "\\" in f or ".." in f:
        return False
    if any(c in f for c in '<>:"|?*'):
        return False

    normalized_type = normalize_addon_type(addon_type)
    allowed_exts = ADDON_IMPORT_EXTENSIONS.get(normalized_type, _SUPPORTED_MOD_ARCHIVE_EXTENSIONS)
    return os.path.splitext(f)[1].lower() in allowed_exts


def _normalize_archive_source_subfolder(source_subfolder: str) -> str:
    raw = str(source_subfolder or "").strip().replace("\\", "/")
    if raw in ("", "/", ".", "./"):
        return ""
    if raw.startswith("/"):
        raise ValueError("source_subfolder must be a relative archive path")

    parts = []
    for segment in raw.split("/"):
        seg = segment.strip()
        if not seg:
            continue
        if seg in (".", ".."):
            raise ValueError("source_subfolder contains path traversal")
        if len(seg) > _MAX_SAFE_COMPONENT_LENGTH:
            raise ValueError("source_subfolder segment is too long")
        if any(ord(ch) < 32 for ch in seg) or ":" in seg:
            raise ValueError("source_subfolder contains invalid characters")
        parts.append(seg)

    normalized = "/".join(parts).strip("/")
    if normalized in ("", "."):
        return ""
    if normalized.startswith("../") or normalized == "..":
        raise ValueError("source_subfolder contains path traversal")
    return normalized


def _is_safe_zip_entry_path(entry_name: str) -> bool:
    normalized = str(entry_name or "").replace("\\", "/").lstrip("/")
    if not normalized:
        return False
    parts = [p for p in normalized.split("/") if p]
    if not parts:
        return False
    for part in parts:
        if part in (".", ".."):
            return False
        if "\x00" in part:
            return False
    return True


def _normalize_download_url(download_url: str) -> str:
    raw = str(download_url or "").strip()
    if not raw:
        return ""
    try:
        parts = urllib.parse.urlsplit(raw)
        if not parts.scheme or not parts.netloc:
            return raw
        encoded_path = urllib.parse.quote(
            urllib.parse.unquote(parts.path),
            safe="/@%+~!$&'()*,;=:-._"
        )
        encoded_query = urllib.parse.quote(
            urllib.parse.unquote(parts.query),
            safe="=&%+/:,.-_~!$'()[]*"
        )
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, encoded_path, encoded_query, parts.fragment))
    except Exception:
        return raw


def _iter_request_urls(url: str) -> list[str]:
    proxied = _apply_url_proxy(url)
    out = []
    if proxied:
        out.append(proxied)
    if url not in out:
        out.append(url)
    return out
