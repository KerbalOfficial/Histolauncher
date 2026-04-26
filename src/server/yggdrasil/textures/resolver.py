from __future__ import annotations

import json
import os
import time

from core.logger import colorize_log

from server.yggdrasil.identity import (
    _normalize_uuid_hex,
    _uuid_hex_to_dashed,
)
from server.yggdrasil.state import (
    CAPE_CACHE_TTL_SECONDS,
    MODEL_CACHE_TTL_SECONDS,
    STATE,
)
from server.yggdrasil.textures.local import _resolve_local_cape_url
from server.yggdrasil.textures.metadata import (
    _resolve_remote_texture_metadata,
    _resolve_remote_texture_url,
)
from server.yggdrasil.textures.urls import (
    _build_public_cape_url,
    _collect_texture_identifiers,
    _normalize_skin_model,
)


__all__ = [
    "_resolve_cached_skin_model",
    "_resolve_skin_model",
    "_resolve_cape_url",
    "invalidate_texture_cache",
]


def _resolve_cached_skin_model(
    uuid_hex: str, username: str = "", allow_stale: bool = False
) -> str | None:
    cache_key = f"{uuid_hex}|{(username or '').strip().lower()}"
    now = time.time()
    cached = STATE.model_cache.get(cache_key)
    if cached and (allow_stale or (now - cached.get("at", 0) <= MODEL_CACHE_TTL_SECONDS)):
        model = _normalize_skin_model(cached.get("model"))
        if model in ("slim", "classic"):
            return model

    base_dir = os.path.expanduser("~/.histolauncher")
    skins_dir = os.path.join(base_dir, "skins")
    dashed = _uuid_hex_to_dashed(uuid_hex)

    candidates = [
        os.path.join(skins_dir, f"{dashed}.json"),
        os.path.join(skins_dir, f"{uuid_hex}.json"),
    ]

    for meta_path in candidates:
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            model = _normalize_skin_model(meta.get("model") or meta.get("skin_model"))
            if model in ("slim", "classic"):
                STATE.model_cache[cache_key] = {"model": model, "at": now}
                return model
        except Exception:
            continue

    return None


def _resolve_skin_model(uuid_hex: str, username: str = "") -> str:
    cache_key = f"{uuid_hex}|{(username or '').strip().lower()}"
    now = time.time()

    clean_username = (username or "").strip()
    remote_metadata = _resolve_remote_texture_metadata(uuid_hex, clean_username)
    if remote_metadata and remote_metadata.get("model") in ("slim", "classic"):
        remote_model = remote_metadata.get("model")
        STATE.model_cache[cache_key] = {"model": remote_model, "at": now}
        # Re-importing locally avoids a hard import cycle with the local module.
        from server.yggdrasil.textures.local import _persist_cached_skin_model

        _persist_cached_skin_model(uuid_hex, remote_model, clean_username)
        return remote_model

    local_model = _resolve_cached_skin_model(uuid_hex, clean_username)
    if local_model in ("slim", "classic"):
        return local_model

    STATE.model_cache[cache_key] = {"model": "classic", "at": now}
    return "classic"


def _resolve_cape_url(
    uuid_hex: str,
    username: str = "",
    port: int = 0,
    probe_remote: bool = True,
) -> str | None:
    cache_key = f"{uuid_hex}|{(username or '').strip().lower()}"
    cached = STATE.cape_cache.get(cache_key)
    now = time.time()
    if cached and (now - cached.get("at", 0) <= CAPE_CACHE_TTL_SECONDS):
        return cached.get("url")

    # Prefer local cached cape first to avoid unnecessary remote requests.
    local_url = _resolve_local_cape_url(uuid_hex, username, port)
    if local_url:
        STATE.cape_cache[cache_key] = {"url": local_url, "at": now}
        return local_url

    if probe_remote:
        remote_url = _resolve_remote_texture_url("cape", uuid_hex, username)
        if remote_url:
            print(colorize_log(
                f"[yggdrasil] Cape resolved via texture metadata: {remote_url}"
            ))
            if port and port > 0:
                identifiers = _collect_texture_identifiers(uuid_hex, username)
                ident = identifiers[0] if identifiers else (username or "")
                local_url = _build_public_cape_url(ident, port)
                STATE.cape_cache[cache_key] = {"url": local_url, "at": now}
                return local_url
            STATE.cape_cache[cache_key] = {"url": remote_url, "at": now}
            return remote_url

    STATE.cape_cache[cache_key] = {"url": None, "at": now}
    return None


def invalidate_texture_cache(uuid_hex: str = "", username: str = "") -> None:
    norm_uuid = _normalize_uuid_hex(uuid_hex)
    clean_username = str(username or "").strip().lower()

    def _matches_key(key: str) -> bool:
        key_norm = str(key or "").strip().lower()
        if norm_uuid and key_norm.startswith(f"{norm_uuid}|"):
            return True
        if clean_username and (
            key_norm.endswith(f"|{clean_username}") or f"|{clean_username}|" in key_norm
        ):
            return True
        return False

    for cache_dict in (STATE.model_cache, STATE.cape_cache, STATE.texture_prop_cache):
        for key in list(cache_dict.keys()):
            if _matches_key(key):
                cache_dict.pop(key, None)

    with STATE.texture_metadata_lock:
        for key in list(STATE.texture_metadata_cache.keys()):
            if _matches_key(key):
                STATE.texture_metadata_cache.pop(key, None)
