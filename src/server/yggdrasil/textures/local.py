from __future__ import annotations

import json
import os
import time

from server.yggdrasil.identity import _uuid_hex_to_dashed
from server.yggdrasil.textures.urls import (
    _build_public_cape_url,
    _collect_texture_identifiers,
    _normalize_skin_model,
)


__all__ = [
    "_collect_local_texture_paths",
    "_remove_local_texture_files",
    "_remove_local_skin_model_metadata",
    "_persist_cached_skin_model",
    "_has_local_skin_file",
    "_resolve_local_cape_url",
]


def _collect_local_texture_paths(
    uuid_hex: str, username: str = "", texture_type: str = ""
) -> list[str]:
    safe_type = str(texture_type or "").strip().lower()
    if safe_type not in {"skin", "cape"}:
        return []

    base_dir = os.path.expanduser("~/.histolauncher")
    skins_dir = os.path.join(base_dir, "skins")
    dashed = _uuid_hex_to_dashed(uuid_hex) if uuid_hex else ""

    candidates: list[str] = []
    if dashed:
        candidates.append(os.path.join(skins_dir, f"{dashed}+{safe_type}.png"))
    if uuid_hex:
        candidates.append(os.path.join(skins_dir, f"{uuid_hex}+{safe_type}.png"))

    for identifier in _collect_texture_identifiers(uuid_hex, username):
        if identifier:
            candidates.append(os.path.join(skins_dir, f"{identifier}+{safe_type}.png"))

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
    if dashed:
        candidates.append(os.path.join(skins_dir, f"{dashed}.json"))
    if uuid_hex:
        candidates.append(os.path.join(skins_dir, f"{uuid_hex}.json"))

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
    if dashed:
        targets.append(os.path.join(skins_dir, f"{dashed}.json"))
    if uuid_hex:
        targets.append(os.path.join(skins_dir, f"{uuid_hex}.json"))

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
    if dashed:
        candidates.append(os.path.join(skins_dir, f"{dashed}+skin.png"))
    if uuid_hex:
        candidates.append(os.path.join(skins_dir, f"{uuid_hex}+skin.png"))

    clean_username = (username or "").strip()
    if clean_username:
        candidates.append(os.path.join(skins_dir, f"{clean_username}+skin.png"))

    return any(candidate and os.path.isfile(candidate) for candidate in candidates)


def _resolve_local_cape_url(
    uuid_hex: str, username: str = "", port: int = 0
) -> str | None:
    identifiers = _collect_texture_identifiers(uuid_hex, username)
    base_dir = os.path.expanduser("~/.histolauncher")
    skins_dir = os.path.join(base_dir, "skins")
    dashed = _uuid_hex_to_dashed(uuid_hex) if uuid_hex else ""

    for identifier in identifiers:
        local_candidates: list[str] = []
        if dashed:
            local_candidates.append(os.path.join(skins_dir, f"{dashed}+cape.png"))
        if uuid_hex:
            local_candidates.append(os.path.join(skins_dir, f"{uuid_hex}+cape.png"))
        if identifier:
            local_candidates.append(os.path.join(skins_dir, f"{identifier}+cape.png"))

        for candidate in local_candidates:
            if candidate and os.path.isfile(candidate):
                return _build_public_cape_url(identifier, port)

    return None
