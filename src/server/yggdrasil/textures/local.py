from __future__ import annotations

import json
import os
import re
import time

from server.yggdrasil.identity import _uuid_hex_to_dashed
from server.yggdrasil.textures.urls import (
    _build_public_cape_url,
    _collect_texture_identifiers,
    _normalize_skin_model,
)


__all__ = [
    "_collect_local_texture_paths",
    "_is_valid_local_texture_file",
    "_remove_local_texture_files",
    "_remove_local_skin_model_metadata",
    "_persist_cached_skin_model",
    "_has_local_skin_file",
    "_resolve_local_cape_url",
]


_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")


def _is_safe_identifier(identifier: str) -> bool:
    if not identifier:
        return False
    if any(bad in identifier for bad in ("/", "\\", "\x00")):
        return False
    if identifier in (".", "..") or ".." in identifier:
        return False
    return bool(_SAFE_IDENTIFIER_RE.match(identifier))


def _safe_skin_path(skins_dir: str, identifier: str, suffix: str) -> str | None:
    if not _is_safe_identifier(identifier):
        return None
    safe_suffix = str(suffix or "").strip()
    if any(bad in safe_suffix for bad in ("/", "\\", "\x00", "..")):
        return None
    candidate = os.path.join(skins_dir, f"{identifier}{safe_suffix}")
    try:
        skins_real = os.path.realpath(skins_dir)
        candidate_real = os.path.realpath(candidate)
    except Exception:
        return None
    try:
        if os.path.commonpath([skins_real, candidate_real]) != skins_real:
            return None
    except ValueError:
        return None
    return candidate


def _read_png_dimensions(path: str) -> tuple[int, int] | None:
    try:
        with open(path, "rb") as f:
            header = f.read(24)
        if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        width = int.from_bytes(header[16:20], "big")
        height = int.from_bytes(header[20:24], "big")
        return width, height
    except Exception:
        return None


def _is_valid_local_texture_file(path: str, texture_type: str) -> bool:
    if not path or not os.path.isfile(path):
        return False

    safe_type = str(texture_type or "").strip().lower()
    dimensions = _read_png_dimensions(path)
    if not dimensions:
        return False

    width, height = dimensions
    if safe_type == "skin":
        if width < 64 or height < 32 or (width % 64) != 0:
            return False
        is_legacy = width == (height * 2) and (height % 32) == 0
        is_modern = width == height and (height % 64) == 0
        return is_legacy or is_modern
    if safe_type == "cape":
        if width < 64 or height < 32:
            return False
        return width == (height * 2) and (width % 64) == 0
    return False


def _collect_local_texture_paths(
    uuid_hex: str, username: str = "", texture_type: str = ""
) -> list[str]:
    safe_type = str(texture_type or "").strip().lower()
    if safe_type not in {"skin", "cape"}:
        return []

    base_dir = os.path.expanduser("~/.histolauncher")
    skins_dir = os.path.join(base_dir, "skins")
    dashed = _uuid_hex_to_dashed(uuid_hex) if uuid_hex else ""

    suffix = f"+{safe_type}.png"
    candidates: list[str] = []
    for ident in (dashed, uuid_hex, *_collect_texture_identifiers(uuid_hex, username)):
        path = _safe_skin_path(skins_dir, ident, suffix)
        if path:
            candidates.append(path)

    seen: set[str] = set()
    out: list[str] = []
    for candidate in candidates:
        normalized = os.path.normcase(os.path.normpath(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(candidate)
    return out


def _remove_local_texture_files(
    uuid_hex: str, username: str = "", texture_type: str = ""
) -> list[str]:
    removed: list[str] = []
    for candidate in _collect_local_texture_paths(uuid_hex, username, texture_type):
        try:
            if os.path.isfile(candidate):
                os.remove(candidate)
                removed.append(candidate)
        except Exception:
            continue
    return removed


def _remove_local_skin_model_metadata(uuid_hex: str) -> list[str]:
    removed: list[str] = []
    base_dir = os.path.expanduser("~/.histolauncher")
    skins_dir = os.path.join(base_dir, "skins")
    dashed = _uuid_hex_to_dashed(uuid_hex) if uuid_hex else ""

    candidates: list[str] = []
    for ident in (dashed, uuid_hex):
        path = _safe_skin_path(skins_dir, ident, ".json")
        if path:
            candidates.append(path)

    for candidate in candidates:
        try:
            if os.path.isfile(candidate):
                os.remove(candidate)
                removed.append(candidate)
        except Exception:
            continue
    return removed


def _persist_cached_skin_model(uuid_hex: str, model: str, username: str = "") -> None:
    normalized = _normalize_skin_model(model)
    if normalized is None:
        return

    base_dir = os.path.expanduser("~/.histolauncher")
    skins_dir = os.path.join(base_dir, "skins")
    os.makedirs(skins_dir, exist_ok=True)

    dashed = _uuid_hex_to_dashed(uuid_hex) if uuid_hex else ""
    targets: list[str] = []
    for ident in (dashed, uuid_hex):
        path = _safe_skin_path(skins_dir, ident, ".json")
        if path:
            targets.append(path)

    payload = {
        "model": normalized,
        "skin_model": normalized,
        "username": str(username or "").strip(),
        "updated_at": int(time.time()),
    }

    for path in targets:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except Exception:
            continue


def _has_local_skin_file(uuid_hex: str, username: str = "") -> bool:
    base_dir = os.path.expanduser("~/.histolauncher")
    skins_dir = os.path.join(base_dir, "skins")
    dashed = _uuid_hex_to_dashed(uuid_hex) if uuid_hex else ""

    candidates: list[str] = []
    for ident in (dashed, uuid_hex, (username or "").strip()):
        path = _safe_skin_path(skins_dir, ident, "+skin.png")
        if path:
            candidates.append(path)

    return any(
        candidate and _is_valid_local_texture_file(candidate, "skin")
        for candidate in candidates
    )


def _resolve_local_cape_url(
    uuid_hex: str, username: str = "", port: int = 0
) -> str | None:
    identifiers = _collect_texture_identifiers(uuid_hex, username)
    base_dir = os.path.expanduser("~/.histolauncher")
    skins_dir = os.path.join(base_dir, "skins")
    dashed = _uuid_hex_to_dashed(uuid_hex) if uuid_hex else ""

    for identifier in identifiers:
        local_candidates: list[str] = []
        for ident in (dashed, uuid_hex, identifier):
            path = _safe_skin_path(skins_dir, ident, "+cape.png")
            if path:
                local_candidates.append(path)

        for candidate in local_candidates:
            if candidate and _is_valid_local_texture_file(candidate, "cape"):
                return _build_public_cape_url(identifier, port)

    return None
