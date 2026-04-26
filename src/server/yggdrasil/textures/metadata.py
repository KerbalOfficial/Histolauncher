from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request

from core.settings import _apply_url_proxy

from server.yggdrasil.identity import _histolauncher_account_enabled
from server.yggdrasil.state import (
    STATE,
    TEXTURE_METADATA_CACHE_TTL_SECONDS,
    TEXTURES_API_HOSTNAME,
)
from server.yggdrasil.textures.local import _persist_cached_skin_model
from server.yggdrasil.textures.urls import (
    _collect_texture_identifiers,
    _normalize_remote_texture_metadata,
)


__all__ = [
    "_fetch_remote_texture_metadata",
    "_get_cached_texture_metadata",
    "_store_cached_texture_metadata",
    "_resolve_remote_texture_metadata",
    "_resolve_remote_texture_url",
    "_fetch_remote_skin_model",
]


def _fetch_remote_texture_metadata(
    identifier: str, timeout_seconds: float = 1.2
) -> dict | None:
    if not _histolauncher_account_enabled():
        return None

    ident = str(identifier or "").strip()
    if not ident:
        return None

    remote_url = (
        f"https://{TEXTURES_API_HOSTNAME}/model/"
        f"{urllib.parse.quote(ident, safe='')}"
    )
    probe_url = _apply_url_proxy(remote_url)
    try:
        req = urllib.request.Request(probe_url, headers={"User-Agent": "Histolauncher/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        return _normalize_remote_texture_metadata(payload)
    except Exception:
        return None


def _get_cached_texture_metadata(
    cache_key: str, now: float | None = None, allow_stale: bool = False
) -> tuple[bool, dict | None]:
    now = time.time() if now is None else now
    with STATE.texture_metadata_lock:
        cached = STATE.texture_metadata_cache.get(cache_key)

    if not cached:
        return False, None

    cached_at = float(cached.get("at", 0) or 0)
    if allow_stale or (now - cached_at <= TEXTURE_METADATA_CACHE_TTL_SECONDS):
        return True, cached.get("meta")

    return False, cached.get("meta")


def _store_cached_texture_metadata(
    cache_key: str, metadata: dict | None, now: float | None = None
) -> None:
    stamped = time.time() if now is None else now
    with STATE.texture_metadata_lock:
        STATE.texture_metadata_cache[cache_key] = {"meta": metadata, "at": stamped}


def _resolve_remote_texture_metadata(
    uuid_hex: str,
    username: str = "",
    *,
    wait_for_inflight: bool = True,
    allow_stale: bool = False,
    timeout_seconds: float = 1.2,
) -> dict | None:
    if not _histolauncher_account_enabled():
        return None

    cache_key = f"{uuid_hex}|{(username or '').strip().lower()}"
    now = time.time()
    has_cached, cached_meta = _get_cached_texture_metadata(
        cache_key, now=now, allow_stale=allow_stale
    )
    if has_cached:
        return cached_meta

    with STATE.texture_metadata_lock:
        inflight = STATE.texture_metadata_inflight.get(cache_key)
        if inflight is None:
            inflight = threading.Event()
            STATE.texture_metadata_inflight[cache_key] = inflight
            is_owner = True
        else:
            is_owner = False

    if not is_owner:
        if allow_stale:
            return cached_meta
        if wait_for_inflight:
            inflight.wait(timeout=max(0.1, float(timeout_seconds) + 0.2))
            has_cached_after_wait, cached_after_wait = _get_cached_texture_metadata(
                cache_key,
                now=time.time(),
                allow_stale=allow_stale,
            )
            if has_cached_after_wait:
                return cached_after_wait
        return None

    metadata: dict | None = None
    try:
        for identifier in _collect_texture_identifiers(uuid_hex, username):
            metadata = _fetch_remote_texture_metadata(
                identifier, timeout_seconds=timeout_seconds
            )
            if metadata is None:
                continue

            if uuid_hex:
                _persist_cached_skin_model(
                    uuid_hex, metadata.get("model") or "classic", username
                )
            break
    finally:
        _store_cached_texture_metadata(cache_key, metadata, now=time.time())
        with STATE.texture_metadata_lock:
            done = STATE.texture_metadata_inflight.pop(cache_key, None)
        if done:
            done.set()

    return metadata


def _resolve_remote_texture_url(
    texture_type: str, uuid_hex: str = "", username: str = ""
) -> str | None:
    safe_type = str(texture_type or "").strip().lower()
    if safe_type not in {"skin", "cape"}:
        return None

    metadata = _resolve_remote_texture_metadata(uuid_hex, username)
    if not metadata:
        return None

    value = metadata.get(safe_type)
    return str(value).strip() if value else None


def _fetch_remote_skin_model(
    identifier: str, timeout_seconds: float = 1.2
) -> str | None:
    metadata = _fetch_remote_texture_metadata(identifier, timeout_seconds=timeout_seconds)
    return (metadata or {}).get("model")
