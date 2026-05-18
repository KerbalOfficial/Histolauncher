from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from core.settings import _apply_url_proxy

from server.yggdrasil.identity import (
    _active_account_scope,
    _ensure_uuid,
    _normalize_uuid_hex,
    _profile_matches_active_player,
)
from server.yggdrasil.state import (
    STATE,
    TEXTURE_METADATA_CACHE_TTL_SECONDS,
    HISTOLAUNCHER_TEXTURE_METADATA_TTL_SECONDS,
    TEXTURES_API_HOSTNAME,
)
from server.yggdrasil.textures.local import _persist_cached_skin_model
from server.yggdrasil.textures.urls import (
    _collect_texture_identifiers,
    _normalize_remote_texture_metadata,
)


OFFICIAL_PROFILE_BY_NAME_URL = "https://api.mojang.com/users/profiles/minecraft/{name}"
OFFICIAL_SESSION_PROFILE_URL = (
    "https://sessionserver.mojang.com/session/minecraft/profile/{uuid}?unsigned=false"
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
    ident = str(identifier or "").strip()
    if not ident:
        return None

    remote_url = (
        f"https://{TEXTURES_API_HOSTNAME}/model/"
        f"{urllib.parse.quote(ident, safe='')}"
    )
    payload = _request_json(remote_url, timeout_seconds=timeout_seconds)
    return _normalize_remote_texture_metadata(payload)


def _candidate_urls(raw_url: str) -> list[str]:
    urls: list[str] = []
    proxied = _apply_url_proxy(raw_url)
    if proxied:
        urls.append(proxied)
    if raw_url not in urls:
        urls.append(raw_url)
    return urls


def _request_json(raw_url: str, timeout_seconds: float = 1.2) -> dict | None:
    _MAX_RESPONSE_BYTES = 1 * 1024 * 1024
    for probe_url in _candidate_urls(str(raw_url or "").strip()):
        try:
            req = urllib.request.Request(
                probe_url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Histolauncher/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                raw = resp.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                continue
            payload = raw.decode("utf-8", errors="replace")
            if not payload.strip():
                return None
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            return data if isinstance(data, dict) else None
        except urllib.error.HTTPError:
            continue
        except Exception:
            continue
    return None


def _decode_official_texture_property(profile_payload: dict | None) -> dict | None:
    if not isinstance(profile_payload, dict):
        return None

    properties = profile_payload.get("properties")
    if not isinstance(properties, list):
        return None

    encoded = ""
    for prop in properties:
        if not isinstance(prop, dict):
            continue
        if str(prop.get("name") or "").strip().lower() == "textures":
            encoded = str(prop.get("value") or "").strip()
            break

    if not encoded:
        return None

    try:
        padded = encoded + ("=" * (-len(encoded) % 4))
        decoded = base64.b64decode(padded).decode("utf-8", errors="replace")
        payload = json.loads(decoded)
    except Exception:
        return None

    textures = payload.get("textures") if isinstance(payload, dict) else {}
    if not isinstance(textures, dict):
        return None

    skin_obj = textures.get("SKIN") if isinstance(textures.get("SKIN"), dict) else {}
    cape_obj = textures.get("CAPE") if isinstance(textures.get("CAPE"), dict) else {}
    skin_url = skin_obj.get("url") if isinstance(skin_obj, dict) else None
    cape_url = cape_obj.get("url") if isinstance(cape_obj, dict) else None
    metadata = skin_obj.get("metadata") if isinstance(skin_obj.get("metadata"), dict) else {}

    return _normalize_remote_texture_metadata(
        {
            "skin": skin_url,
            "cape": cape_url,
            "model": metadata.get("model") if isinstance(metadata, dict) else None,
        }
    )


def _fetch_official_texture_metadata(
    uuid_hex: str = "", username: str = "", timeout_seconds: float = 1.2
) -> dict | None:
    clean_uuid = _normalize_uuid_hex(uuid_hex)
    clean_username = str(username or "").strip()
    offline_uuid = ""
    if clean_username:
        offline_uuid = _normalize_uuid_hex(_ensure_uuid(clean_username))

    def _lookup_profile_uuid_by_name() -> str:
        if not clean_username:
            return ""
        profile_lookup_url = OFFICIAL_PROFILE_BY_NAME_URL.format(
            name=urllib.parse.quote(clean_username, safe="")
        )
        profile_lookup = _request_json(
            profile_lookup_url, timeout_seconds=timeout_seconds
        )
        return _normalize_uuid_hex((profile_lookup or {}).get("id"))

    if not clean_uuid or clean_uuid == offline_uuid:
        clean_uuid = _lookup_profile_uuid_by_name()

    if not clean_uuid:
        return None

    session_url = OFFICIAL_SESSION_PROFILE_URL.format(uuid=clean_uuid)
    metadata = _decode_official_texture_property(
        _request_json(session_url, timeout_seconds=timeout_seconds)
    )
    if metadata or not clean_username:
        return metadata

    username_uuid = _lookup_profile_uuid_by_name()
    if not username_uuid or username_uuid == clean_uuid:
        return None

    session_url = OFFICIAL_SESSION_PROFILE_URL.format(uuid=username_uuid)
    return _decode_official_texture_property(
        _request_json(session_url, timeout_seconds=timeout_seconds)
    )


def _texture_metadata_has_texture(metadata: dict | None) -> bool:
    if not isinstance(metadata, dict):
        return False
    return bool(metadata.get("skin") or metadata.get("cape"))


def _texture_metadata_is_authoritative(metadata: dict | None) -> bool:
    return bool(isinstance(metadata, dict) and metadata.get("skin"))


def _merge_texture_metadata(primary: dict | None, fallback: dict | None) -> dict | None:
    if _texture_metadata_is_authoritative(primary):
        return primary
    if _texture_metadata_is_authoritative(fallback):
        return fallback
    if _texture_metadata_has_texture(primary):
        return primary
    if _texture_metadata_has_texture(fallback):
        return fallback
    return primary or fallback


def _metadata_is_from_histolauncher(metadata: dict | None) -> bool:
    if not isinstance(metadata, dict):
        return False
    skin_url = str(metadata.get("skin") or "").lower()
    cape_url = str(metadata.get("cape") or "").lower()
    hostname = TEXTURES_API_HOSTNAME.lower()
    return hostname in skin_url or hostname in cape_url


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
    force_refresh: bool = False,
) -> dict | None:
    cache_scope = _active_account_scope()
    cache_key = f"{cache_scope}|{uuid_hex}|{(username or '').strip().lower()}"
    now = time.time()
    cached_meta: dict | None = None
    if not force_refresh:
        has_cached, cached_meta = _get_cached_texture_metadata(
            cache_key, now=now, allow_stale=allow_stale
        )
        if has_cached:
            return cached_meta
    else:
        _, cached_meta = _get_cached_texture_metadata(
            cache_key, now=now, allow_stale=True
        )

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

    is_active_player = _profile_matches_active_player(uuid_hex, username)
    prefer_histolauncher_metadata = (
        cache_scope in {"local", "histolauncher"} and is_active_player
    )

    def _is_offline_uuid(u: str) -> bool:
        clean = _normalize_uuid_hex(u)
        return bool(clean) and clean[12] == "3"

    skip_official = _is_offline_uuid(uuid_hex)

    def _query_histolauncher() -> dict | None:
        first_texture_response: dict | None = None
        for identifier in _collect_texture_identifiers(uuid_hex, username):
            response = _fetch_remote_texture_metadata(
                identifier, timeout_seconds=timeout_seconds
            )
            if first_texture_response is None and _texture_metadata_has_texture(response):
                first_texture_response = response
            if _texture_metadata_is_authoritative(response):
                return response
        return first_texture_response

    def _query_official() -> dict | None:
        if not (uuid_hex or username):
            return None
        return _fetch_official_texture_metadata(
            uuid_hex=uuid_hex,
            username=username,
            timeout_seconds=timeout_seconds,
        )

    try:
        if prefer_histolauncher_metadata or skip_official:
            metadata = _query_histolauncher()
            if not _texture_metadata_is_authoritative(metadata) and not skip_official:
                official = _query_official()
                metadata = _merge_texture_metadata(metadata, official)
        else:
            metadata = _query_official()
            if not _texture_metadata_is_authoritative(metadata):
                histolauncher = _query_histolauncher()
                metadata = _merge_texture_metadata(metadata, histolauncher)

        if uuid_hex and isinstance(metadata, dict):
            _persist_cached_skin_model(
                uuid_hex, metadata.get("model") or "classic", username
            )

    finally:
        cache_at = time.time()
        if not _texture_metadata_has_texture(metadata):
            negative_ttl = 8.0
            cache_at = cache_at - max(
                0.0, float(TEXTURE_METADATA_CACHE_TTL_SECONDS) - negative_ttl
            )
        elif _metadata_is_from_histolauncher(metadata):
            hl_ttl = float(HISTOLAUNCHER_TEXTURE_METADATA_TTL_SECONDS)
            cache_at = cache_at - max(
                0.0, float(TEXTURE_METADATA_CACHE_TTL_SECONDS) - hl_ttl
            )
        _store_cached_texture_metadata(cache_key, metadata, now=cache_at)
        with STATE.texture_metadata_lock:
            done = STATE.texture_metadata_inflight.pop(cache_key, None)
        if done:
            done.set()

    return metadata


def _resolve_remote_texture_url(
    texture_type: str,
    uuid_hex: str = "",
    username: str = "",
    *,
    timeout_seconds: float = 1.2,
    force_refresh_missing: bool = False,
) -> str | None:
    safe_type = str(texture_type or "").strip().lower()
    if safe_type not in {"skin", "cape"}:
        return None

    metadata = _resolve_remote_texture_metadata(
        uuid_hex, username, timeout_seconds=timeout_seconds
    )
    if not metadata and force_refresh_missing:
        metadata = _resolve_remote_texture_metadata(
            uuid_hex,
            username,
            timeout_seconds=timeout_seconds,
            force_refresh=True,
        )
    if not metadata:
        return None

    value = metadata.get(safe_type)
    if not value and force_refresh_missing:
        metadata = _resolve_remote_texture_metadata(
            uuid_hex,
            username,
            timeout_seconds=timeout_seconds,
            force_refresh=True,
        )
        value = (metadata or {}).get(safe_type)
    return str(value).strip() if value else None


def _fetch_remote_skin_model(
    identifier: str, timeout_seconds: float = 1.2
) -> str | None:
    metadata = _fetch_remote_texture_metadata(identifier, timeout_seconds=timeout_seconds)
    return (metadata or {}).get("model")
