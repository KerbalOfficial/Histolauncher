from __future__ import annotations

import atexit
import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote, urlparse

from core.settings import _apply_url_proxy, load_global_settings

from server.yggdrasil.identity import (
    _active_account_scope,
    _get_username_and_uuid,
    _normalize_uuid_hex,
    _profile_matches_active_player,
    _uuid_hex_to_dashed,
)
from server.yggdrasil.state import STATE, TEXTURE_PROP_CACHE_TTL_SECONDS
from server.yggdrasil.textures.local import (
    _has_local_skin_file,
    _is_valid_local_texture_file,
    _resolve_local_cape_url,
)
from server.yggdrasil.textures.metadata import (
    _get_cached_texture_metadata,
    _resolve_remote_texture_metadata,
)
from server.yggdrasil.textures.resolver import (
    _resolve_cached_skin_model,
)
from server.yggdrasil.textures.urls import (
    _build_public_skin_url,
    _build_texture_property_cape_url,
    _build_texture_property_skin_url,
    _collect_texture_identifiers,
    _minecraft_texture_id_from_url,
)


__all__ = [
    "_build_texture_property",
    "_get_skin_property",
    "_get_skin_property_fast_fallback",
    "_get_skin_property_with_timeout",
    "_schedule_skin_property_cache_refresh",
    "prewarm_authlib_texture_properties",
    "schedule_remote_texture_metadata_prefetch",
]


TEXTURE_METADATA_LOOKUP_TIMEOUT_SECONDS = 4.0
TEXTURE_PROPERTY_LOOKUP_TIMEOUT_SECONDS = 4.0
TEXTURE_SOURCE_PREFETCH_TIMEOUT_SECONDS = 8.0

_PREFETCH_INFLIGHT_LOCK = threading.Lock()
_PREFETCH_INFLIGHT: set[tuple[str, str, bool]] = set()
_PREWARM_INFLIGHT_LOCK = threading.Lock()
_PREWARM_INFLIGHT: set[tuple[int, str, str]] = set()
_PROPERTY_REFRESH_INFLIGHT_LOCK = threading.Lock()
_PROPERTY_REFRESH_INFLIGHT: set[tuple[int, str, str, bool]] = set()
_PROPERTY_REFRESH_EXECUTOR = ThreadPoolExecutor(
    max_workers=16, thread_name_prefix="authlib-profile-cache-refresh"
)
atexit.register(_PROPERTY_REFRESH_EXECUTOR.shutdown, wait=False, cancel_futures=True)


def _safe_texture_cache_id(identifier: str | None) -> str:
    value = str(identifier or "").strip()
    if not value or any(part in value for part in ("/", "\\", ":")):
        return ""
    return value


def _texture_cache_file_name(
    identifier: str | None,
    texture_type: str,
    *,
    microsoft_cache: bool = False,
) -> str:
    safe_identifier = _safe_texture_cache_id(identifier)
    if not safe_identifier:
        return ""
    suffix = "skin" if texture_type == "skin" else "cape"
    return f"{safe_identifier}+{suffix}.png"


def _texture_cache_file_path(
    identifier: str | None,
    texture_type: str,
    *,
    microsoft_cache: bool = False,
) -> str:
    safe_identifier = _safe_texture_cache_id(identifier)
    if not safe_identifier:
        return ""
    safe_type = "skin" if texture_type == "skin" else "cape"
    if microsoft_cache:
        try:
            from server.auth.microsoft import ensure_microsoft_texture_cache_path

            return ensure_microsoft_texture_cache_path(safe_identifier, safe_type)
        except Exception:
            return ""
    cache_name = _texture_cache_file_name(safe_identifier, safe_type)
    return os.path.join(os.path.expanduser("~/.histolauncher"), "skins", cache_name)


def _source_cache_identifiers(
    remote_url: str | None, uuid_hex: str, username: str = ""
) -> list[str]:
    identifiers: list[str] = []
    minecraft_texture_id = _minecraft_texture_id_from_url(remote_url)
    if minecraft_texture_id:
        identifiers.append(minecraft_texture_id)

    try:
        parsed = urlparse(str(remote_url or "").strip())
        basename = unquote(os.path.basename(parsed.path or "")).strip()
        if basename:
            identifiers.append(basename)
    except Exception:
        pass

    identifiers.extend(_collect_texture_identifiers(uuid_hex, username))

    seen: set[str] = set()
    out: list[str] = []
    for identifier in identifiers:
        safe_identifier = _safe_texture_cache_id(identifier)
        if not safe_identifier or safe_identifier in seen:
            continue
        seen.add(safe_identifier)
        out.append(safe_identifier)
    return out


def _prefetch_texture_source(
    texture_type: str,
    remote_url: str | None,
    uuid_hex: str,
    username: str = "",
    timeout_seconds: float = TEXTURE_SOURCE_PREFETCH_TIMEOUT_SECONDS,
    microsoft_cache: bool = False,
) -> bool:
    safe_type = str(texture_type or "").strip().lower()
    raw_url = str(remote_url or "").strip()
    if safe_type not in {"skin", "cape"} or not raw_url:
        return False
    if raw_url.startswith("http://127.0.0.1:") or raw_url.startswith("http://localhost:"):
        return True

    identifiers = _source_cache_identifiers(raw_url, uuid_hex, username)
    if not identifiers:
        return False

    primary_path = _texture_cache_file_path(
        identifiers[0],
        safe_type,
        microsoft_cache=microsoft_cache,
    )
    if _is_valid_local_texture_file(primary_path, safe_type):
        return True

    probe_urls: list[str] = []
    proxied_url = _apply_url_proxy(raw_url)
    if proxied_url:
        probe_urls.append(proxied_url)
    if raw_url not in probe_urls:
        probe_urls.append(raw_url)

    payload: bytes | None = None
    for probe_url in probe_urls:
        try:
            req = urllib.request.Request(
                probe_url,
                headers={"User-Agent": "Histolauncher/1.0"},
            )
            with urllib.request.urlopen(req, timeout=float(timeout_seconds)) as resp:
                ctype = str(resp.headers.get("Content-Type") or "").lower()
                if "image/" not in ctype:
                    continue
                payload = resp.read()
            break
        except urllib.error.HTTPError:
            continue
        except Exception:
            continue

    if not payload:
        return False

    saved_primary = False
    for identifier in identifiers:
        target_path = _texture_cache_file_path(
            identifier,
            safe_type,
            microsoft_cache=microsoft_cache,
        )
        if not target_path:
            continue
        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, "wb") as texture_file:
                texture_file.write(payload)
            if identifier == identifiers[0]:
                saved_primary = _is_valid_local_texture_file(target_path, safe_type)
        except Exception:
            continue
    return saved_primary


def _prefetch_texture_sources(
    sources: list[tuple[str, str | None, str, str, bool]],
    timeout_seconds: float = TEXTURE_SOURCE_PREFETCH_TIMEOUT_SECONDS,
    *,
    wait_for_completion: bool = True,
) -> None:
    worker_threads: list[threading.Thread] = []
    for texture_type, remote_url, uuid_hex, username, microsoft_cache in sources:
        if not remote_url:
            continue
        prefetch_key = (
            str(texture_type or "").strip().lower(),
            str(remote_url or "").strip(),
            bool(microsoft_cache),
        )
        with _PREFETCH_INFLIGHT_LOCK:
            if prefetch_key in _PREFETCH_INFLIGHT:
                continue
            _PREFETCH_INFLIGHT.add(prefetch_key)

        def _run_prefetch(
            key: tuple[str, str, bool],
            kind: str,
            source_url: str | None,
            profile_uuid: str,
            profile_name: str,
            use_microsoft_cache: bool,
        ) -> None:
            try:
                _prefetch_texture_source(
                    kind,
                    source_url,
                    profile_uuid,
                    profile_name,
                    timeout_seconds,
                    use_microsoft_cache,
                )
            finally:
                with _PREFETCH_INFLIGHT_LOCK:
                    _PREFETCH_INFLIGHT.discard(key)

        worker_thread = threading.Thread(
            target=_run_prefetch,
            args=(
                prefetch_key,
                texture_type,
                remote_url,
                uuid_hex,
                username,
                microsoft_cache,
            ),
            name="texture-prefetch",
            daemon=True,
        )
        worker_thread.start()
        worker_threads.append(worker_thread)

    if not wait_for_completion:
        return

    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    for worker_thread in worker_threads:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        worker_thread.join(remaining)


def _resolve_profile_name_for_target(
    uuid_hex: str,
    target_username: str,
    current_username: str,
    current_uuid_hex: str,
) -> str:
    clean_target_name = str(target_username or "").strip()
    if clean_target_name:
        return clean_target_name

    clean_uuid = _normalize_uuid_hex(uuid_hex)
    clean_current_uuid = _normalize_uuid_hex(current_uuid_hex)
    if clean_uuid and clean_uuid != clean_current_uuid:
        return str(STATE.uuid_name_cache.get(clean_uuid) or "").strip()

    return str(current_username or "").strip()


def _get_cached_remote_texture_metadata_entry(
    uuid_hex: str,
    username: str = "",
) -> tuple[bool, dict | None]:
    cache_key = f"{_active_account_scope()}|{uuid_hex}|{(username or '').strip().lower()}"
    try:
        return _get_cached_texture_metadata(cache_key, allow_stale=True)
    except Exception:
        return False, None


def _resolve_microsoft_texture_metadata(identifier: str = "", username: str = "") -> dict | None:
    try:
        from server.auth.microsoft import resolve_microsoft_texture_metadata

        return resolve_microsoft_texture_metadata(identifier, username)
    except Exception:
        return None


def _microsoft_account_enabled() -> bool:
    try:
        settings = load_global_settings() or {}
        return str(settings.get("account_type") or "Local").strip().lower() == "microsoft"
    except Exception:
        return False


def _build_texture_property(
    textures: dict,
    profile_id: str,
    profile_name: str,
    require_signature: bool = True,
    fast_timestamp: bool = False,
) -> dict:
    now = time.time()
    if fast_timestamp:
        timestamp = int(now * 1000)
    else:
        timestamp = (
            int(now // TEXTURE_PROP_CACHE_TTL_SECONDS)
            * TEXTURE_PROP_CACHE_TTL_SECONDS
            * 1000
        )

    tex = {
        "timestamp": timestamp,
        "profileId": profile_id or "",
        "textures": textures or {},
    }
    if profile_name:
        tex["profileName"] = profile_name

    json_bytes = json.dumps(tex).encode("utf-8")
    encoded = base64.b64encode(json_bytes).decode("utf-8")

    prop = {"name": "textures", "value": encoded}
    if require_signature:
        prop["signature"] = "AA=="
    return prop


def _texture_property_cache_key(
    profile_id: str,
    profile_name: str,
    port: int,
    require_signature: bool,
) -> str:
    cache_scope = _active_account_scope()
    return (
        f"{cache_scope}|{profile_id}|{(profile_name or '').strip().lower()}|"
        f"port={int(port or 0)}|{'signed' if require_signature else 'unsigned'}"
    )


def _store_texture_property_cache(
    profile_id: str,
    profile_name: str,
    port: int,
    require_signature: bool,
    prop: dict | None,
    *,
    fast_fallback: bool = False,
) -> None:
    if not prop:
        return
    cache_key = _texture_property_cache_key(
        profile_id,
        profile_name,
        port,
        require_signature,
    )
    STATE.texture_prop_cache[cache_key] = {
        "prop": prop,
        "at": time.time(),
        "fast_fallback": bool(fast_fallback),
    }


def _get_cached_texture_property(
    profile_id: str,
    profile_name: str,
    port: int,
    require_signature: bool,
    *,
    allow_fast_fallback: bool = True,
) -> dict | None:
    cache_key = _texture_property_cache_key(
        profile_id,
        profile_name,
        port,
        require_signature,
    )
    cached = STATE.texture_prop_cache.get(cache_key)
    if cached and cached.get("prop"):
        if cached.get("fast_fallback") and not allow_fast_fallback:
            return None
        cached_at = float(cached.get("at") or 0)
        if time.time() - cached_at > TEXTURE_PROP_CACHE_TTL_SECONDS:
            return None
        return cached.get("prop")
    return None


def _build_texture_property_variant(
    prop: dict | None,
    profile_id: str,
    profile_name: str,
    require_signature: bool,
) -> dict | None:
    if not prop:
        return None
    try:
        payload = json.loads(base64.b64decode(str(prop.get("value") or "")).decode("utf-8"))
        textures = payload.get("textures") if isinstance(payload, dict) else None
        if not isinstance(textures, dict):
            return None
        return _build_texture_property(
            textures,
            str((payload or {}).get("profileId") or profile_id or ""),
            str((payload or {}).get("profileName") or profile_name or ""),
            require_signature=require_signature,
        )
    except Exception:
        return None


def _texture_property_urls(prop: dict | None) -> list[str]:
    if not prop:
        return []
    try:
        payload = json.loads(base64.b64decode(str(prop.get("value") or "")).decode("utf-8"))
        textures = payload.get("textures") if isinstance(payload, dict) else None
        if not isinstance(textures, dict):
            return []
        urls: list[str] = []
        for texture_data in textures.values():
            if not isinstance(texture_data, dict):
                continue
            url = str(texture_data.get("url") or "").strip()
            if url and url not in urls:
                urls.append(url)
        return urls
    except Exception:
        return []


def _is_local_texture_proxy_url(url: str) -> bool:
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return False
    host = str(parsed.hostname or "").strip().lower()
    return host in {"127.0.0.1", "localhost", "::1"} and str(parsed.path or "").startswith("/texture/")


def _prewarm_texture_property_urls(
    prop: dict | None,
    *,
    timeout_seconds: float = TEXTURE_SOURCE_PREFETCH_TIMEOUT_SECONDS,
) -> dict:
    urls = [url for url in _texture_property_urls(prop) if _is_local_texture_proxy_url(url)]
    result = {"attempted": 0, "ready": 0, "urls": len(urls)}
    for url in urls:
        result["attempted"] += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher/1.0"})
            with urllib.request.urlopen(req, timeout=float(timeout_seconds)) as resp:
                ctype = str(resp.headers.get("Content-Type") or "").lower()
                payload = resp.read()
            if payload and "image" in ctype:
                result["ready"] += 1
        except Exception:
            continue
    return result


def _resolve_authlib_port(port: int = 0) -> int:
    try:
        value = int(port or 0)
        if value > 0:
            return value
    except Exception:
        pass

    for raw in (
        os.environ.get("HISTOLAUNCHER_PORT"),
        (load_global_settings() or {}).get("ygg_port"),
    ):
        try:
            value = int(str(raw or "").strip())
            if value > 0:
                return value
        except Exception:
            continue
    return 0


def prewarm_authlib_texture_properties(
    port: int = 0,
    target_uuid_hex: str = "",
    target_username: str = "",
    *,
    wait_seconds: float = 0.0,
) -> dict:
    resolved_port = _resolve_authlib_port(port)
    if resolved_port <= 0:
        return {"ok": False, "ready": False, "error": "authlib port is not available"}

    target_u_hex = _normalize_uuid_hex(target_uuid_hex)
    target_name = str(target_username or "").strip()
    if target_u_hex and target_name:
        current_username, current_uuid_hex = target_name, target_u_hex
    else:
        current_username, current_uuid_hex = _get_username_and_uuid()
    u_hex = target_u_hex or _normalize_uuid_hex(current_uuid_hex)
    profile_name = _resolve_profile_name_for_target(
        u_hex or "",
        target_username,
        current_username,
        current_uuid_hex,
    )
    if not u_hex:
        return {"ok": False, "ready": False, "error": "profile uuid is not available"}

    if u_hex and profile_name:
        STATE.uuid_name_cache[u_hex] = profile_name

    prewarm_key = (resolved_port, u_hex, profile_name.lower())
    with _PREWARM_INFLIGHT_LOCK:
        if prewarm_key in _PREWARM_INFLIGHT:
            return {"ok": True, "ready": False, "already_running": True}
        _PREWARM_INFLIGHT.add(prewarm_key)

    result = {"ok": True, "ready": False, "already_running": False}

    def _worker() -> None:
        try:
            signed_prop = _get_skin_property_with_timeout(
                resolved_port,
                target_uuid_hex=u_hex,
                target_username=profile_name,
                timeout_seconds=TEXTURE_PROPERTY_LOOKUP_TIMEOUT_SECONDS,
                require_signature=True,
                prefetch_sources=True,
            )
            _store_texture_property_cache(
                u_hex,
                profile_name,
                resolved_port,
                True,
                signed_prop,
            )

            unsigned_prop = _build_texture_property_variant(
                signed_prop,
                u_hex,
                profile_name,
                False,
            )
            if not unsigned_prop:
                unsigned_prop = _get_skin_property_with_timeout(
                    resolved_port,
                    target_uuid_hex=u_hex,
                    target_username=profile_name,
                    timeout_seconds=TEXTURE_PROPERTY_LOOKUP_TIMEOUT_SECONDS,
                    require_signature=False,
                    prefetch_sources=True,
                )
            _store_texture_property_cache(
                u_hex,
                profile_name,
                resolved_port,
                False,
                unsigned_prop,
            )
            result["profile_ready"] = True
            result["textures"] = _prewarm_texture_property_urls(signed_prop)
            result["ready"] = True
        except Exception as e:
            result["ok"] = False
            result["error"] = str(e)
        finally:
            with _PREWARM_INFLIGHT_LOCK:
                _PREWARM_INFLIGHT.discard(prewarm_key)

    thread = threading.Thread(
        target=_worker,
        name="authlib-texture-prewarm",
        daemon=True,
    )
    thread.start()

    if wait_seconds and wait_seconds > 0:
        thread.join(max(0.0, float(wait_seconds)))
        result["ready"] = bool(result.get("ready")) or not thread.is_alive()
    return result


def _get_skin_property(
    port: int,
    target_uuid_hex: str = "",
    target_username: str = "",
    require_signature: bool = True,
    *,
    prefetch_sources: bool = True,
) -> dict | None:
    target_u_hex = _normalize_uuid_hex(target_uuid_hex)
    target_name = str(target_username or "").strip()
    if target_u_hex and target_name:
        username, current_u_hex = target_name, target_u_hex
    else:
        username, current_u_hex = _get_username_and_uuid()
    microsoft_enabled = _microsoft_account_enabled()
    u_hex = target_u_hex or current_u_hex
    profile_name = _resolve_profile_name_for_target(
        u_hex, target_username, username, current_u_hex
    )
    is_current_profile = _profile_matches_active_player(u_hex, profile_name)
    active_username = ""
    active_uuid_hex = ""
    if is_current_profile:
        try:
            active_username, active_uuid_hex = _get_username_and_uuid()
        except Exception:
            active_username = profile_name
            active_uuid_hex = ""
    if u_hex and profile_name:
        STATE.uuid_name_cache[u_hex] = profile_name

    cached = _get_cached_texture_property(
        u_hex,
        profile_name,
        port,
        require_signature,
        allow_fast_fallback=False,
    )
    if cached:
        return cached

    cape_url = None

    skin_model = _resolve_cached_skin_model(u_hex, profile_name) or "classic"
    url: str | None = None
    skin_exists = False
    skin_source_is_microsoft = False
    cape_source_is_microsoft = False

    remote_metadata = _resolve_remote_texture_metadata(
        u_hex,
        profile_name,
        timeout_seconds=TEXTURE_METADATA_LOOKUP_TIMEOUT_SECONDS,
    )
    url = (remote_metadata or {}).get("skin") or None
    cape_url = (remote_metadata or {}).get("cape") or None
    skin_model = (remote_metadata or {}).get("model") or skin_model
    if url:
        skin_exists = True

    if url and microsoft_enabled and is_current_profile:
        skin_source_is_microsoft = True
    if cape_url and microsoft_enabled and is_current_profile:
        cape_source_is_microsoft = True

    microsoft_metadata = None
    if microsoft_enabled and is_current_profile:
        microsoft_metadata = _resolve_microsoft_texture_metadata(
            active_uuid_hex or u_hex,
            active_username or profile_name,
        )
    microsoft_local_skin_id = str((microsoft_metadata or {}).get("local_skin_id") or "").strip()
    microsoft_default_skin_id = str((microsoft_metadata or {}).get("default_skin_id") or "").strip()
    if microsoft_local_skin_id and port and port > 0:
        url = _build_public_skin_url(microsoft_local_skin_id, port)
        skin_model = (microsoft_metadata or {}).get("model") or skin_model
        skin_exists = True
        skin_source_is_microsoft = True
    elif microsoft_default_skin_id and port and port > 0:
        url = _build_public_skin_url(microsoft_default_skin_id, port)
        skin_model = (microsoft_metadata or {}).get("model") or skin_model
        skin_exists = True
        skin_source_is_microsoft = True
    elif not url:
        url = (microsoft_metadata or {}).get("skin") or None
        skin_model = (microsoft_metadata or {}).get("model") or skin_model
        if url:
            skin_exists = True
            skin_source_is_microsoft = True

    if not cape_url:
        cape_url = (microsoft_metadata or {}).get("cape") or None
        if cape_url:
            cape_source_is_microsoft = True

    if not microsoft_enabled and port and port > 0:
        if not url and _has_local_skin_file(u_hex, profile_name):
            url = _build_public_skin_url(_uuid_hex_to_dashed(u_hex), port)
            skin_exists = True
        if not cape_url:
            cape_url = _resolve_local_cape_url(u_hex, profile_name, port)

    textures: dict = {}
    texture_skin_url = _build_texture_property_skin_url(url, u_hex, profile_name, port)
    if skin_exists and texture_skin_url:
        skin_data = {"url": texture_skin_url}
        if skin_model == "slim":
            skin_data["metadata"] = {"model": "slim"}
        textures["SKIN"] = skin_data

    texture_cape_url = _build_texture_property_cape_url(cape_url, u_hex, profile_name, port)
    if texture_cape_url:
        textures["CAPE"] = {"url": texture_cape_url}

    if prefetch_sources and port and port > 0:
        sources: list[tuple[str, str | None, str, str, bool]] = []
        if url and texture_skin_url:
            sources.append(("skin", url, u_hex, profile_name, skin_source_is_microsoft))
        if cape_url and texture_cape_url:
            sources.append(("cape", cape_url, u_hex, profile_name, cape_source_is_microsoft))
        _prefetch_texture_sources(sources, wait_for_completion=False)

    prop = _build_texture_property(textures, u_hex, profile_name, require_signature)
    _store_texture_property_cache(u_hex, profile_name, port, require_signature, prop)
    return prop


def _get_skin_property_fast_fallback(
    port: int,
    target_uuid_hex: str = "",
    target_username: str = "",
    require_signature: bool = True,
) -> dict | None:
    u_hex = _normalize_uuid_hex(target_uuid_hex)
    if not u_hex or not port or port <= 0:
        return None

    profile_name = str(target_username or STATE.uuid_name_cache.get(u_hex) or "").strip()
    if profile_name:
        STATE.uuid_name_cache[u_hex] = profile_name

    cached = _get_cached_texture_property(
        u_hex,
        profile_name,
        port,
        require_signature,
    )
    if cached:
        return cached

    microsoft_enabled = _microsoft_account_enabled()
    is_active_player = _profile_matches_active_player(u_hex, profile_name)
    active_username = ""
    active_uuid_hex = ""
    if is_active_player:
        try:
            active_username, active_uuid_hex = _get_username_and_uuid()
        except Exception:
            active_username = profile_name
            active_uuid_hex = ""

    microsoft_metadata: dict | None = None
    microsoft_skin_url = ""
    microsoft_cape_url = ""
    microsoft_model = ""
    if microsoft_enabled and is_active_player:
        microsoft_metadata = _resolve_microsoft_texture_metadata(
            active_uuid_hex or u_hex,
            active_username or profile_name,
        )
        if microsoft_metadata:
            local_skin_id = str(microsoft_metadata.get("local_skin_id") or "").strip()
            default_skin_id = str(microsoft_metadata.get("default_skin_id") or "").strip()
            if local_skin_id:
                microsoft_skin_url = _build_public_skin_url(local_skin_id, port)
            elif default_skin_id:
                microsoft_skin_url = _build_public_skin_url(default_skin_id, port)
            elif microsoft_metadata.get("skin"):
                microsoft_skin_url = str(microsoft_metadata.get("skin") or "").strip()
            microsoft_cape_url = str(microsoft_metadata.get("cape") or "").strip()
            microsoft_model = str(microsoft_metadata.get("model") or "").strip()

    has_cached_metadata, cached_metadata_raw = _get_cached_remote_texture_metadata_entry(
        u_hex,
        profile_name,
    )
    cached_metadata = cached_metadata_raw or {}
    cached_skin_url = str((cached_metadata or {}).get("skin") or "").strip()
    cached_cape_url = str((cached_metadata or {}).get("cape") or "").strip()
    skin_model = (
        microsoft_model
        or (cached_metadata or {}).get("model")
        or _resolve_cached_skin_model(u_hex, profile_name, allow_stale=True)
        or "classic"
    )
    textures: dict = {}
    resolved_skin_url = None
    if microsoft_skin_url:
        if microsoft_skin_url.startswith("http://127.0.0.1:"):
            resolved_skin_url = microsoft_skin_url
        else:
            resolved_skin_url = _build_texture_property_skin_url(
                microsoft_skin_url,
                u_hex,
                profile_name,
                port,
            )
    elif cached_skin_url:
        resolved_skin_url = _build_texture_property_skin_url(
            cached_skin_url,
            u_hex,
            profile_name,
            port,
        )
    else:
        resolved_skin_url = _build_public_skin_url(_uuid_hex_to_dashed(u_hex), port)

    if resolved_skin_url:
        skin_data = {"url": resolved_skin_url}
        if skin_model == "slim":
            skin_data["metadata"] = {"model": "slim"}
        textures["SKIN"] = skin_data
    effective_cape_url = microsoft_cape_url or cached_cape_url
    if not effective_cape_url and not microsoft_enabled:
        effective_cape_url = _resolve_local_cape_url(u_hex, profile_name, port) or ""
    texture_cape_url = _build_texture_property_cape_url(
        effective_cape_url,
        u_hex,
        profile_name,
        port,
    )
    if texture_cape_url:
        textures["CAPE"] = {"url": texture_cape_url}

    prop = _build_texture_property(
        textures,
        u_hex,
        profile_name,
        require_signature=require_signature,
        fast_timestamp=True,
    )
    _store_texture_property_cache(
        u_hex,
        profile_name,
        port,
        require_signature,
        prop,
        fast_fallback=True,
    )
    return prop


def _get_skin_property_with_timeout(
    port: int,
    target_uuid_hex: str = "",
    target_username: str = "",
    timeout_seconds: float = TEXTURE_PROPERTY_LOOKUP_TIMEOUT_SECONDS,
    require_signature: bool = True,
    *,
    prefetch_sources: bool = True,
) -> dict | None:
    try:
        target_u_hex = _normalize_uuid_hex(target_uuid_hex)
        target_name = str(target_username or "").strip()
        if target_u_hex and target_name:
            current_username, current_uuid_hex = target_name, target_u_hex
        else:
            current_username, current_uuid_hex = _get_username_and_uuid()
        u_hex = target_u_hex or _normalize_uuid_hex(current_uuid_hex)
        profile_name = _resolve_profile_name_for_target(
            u_hex or "",
            target_username,
            current_username,
            current_uuid_hex,
        )
        cached = _get_cached_texture_property(
            u_hex,
            profile_name,
            port,
            require_signature,
            allow_fast_fallback=False,
        )
        if cached:
            return cached
    except Exception:
        pass

    container: dict = {}

    def _worker() -> None:
        try:
            container["prop"] = _get_skin_property(
                port,
                target_uuid_hex,
                target_username,
                require_signature=require_signature,
                prefetch_sources=prefetch_sources,
            )
        except Exception:
            container["prop"] = None

    t = threading.Thread(target=_worker)
    t.daemon = True
    t.start()
    t.join(timeout_seconds)

    if "prop" in container:
        return container.get("prop")

    return _get_skin_property_fast_fallback(
        port,
        target_uuid_hex=target_uuid_hex,
        target_username=target_username,
        require_signature=require_signature,
    )


def _schedule_skin_property_cache_refresh(
    port: int,
    target_uuid_hex: str = "",
    target_username: str = "",
    *,
    require_signature: bool = True,
) -> None:
    try:
        resolved_port = int(port or 0)
    except Exception:
        resolved_port = 0
    if resolved_port <= 0:
        return

    u_hex = _normalize_uuid_hex(target_uuid_hex)
    if not u_hex:
        return

    profile_name = str(target_username or STATE.uuid_name_cache.get(u_hex) or "").strip()
    refresh_key = (resolved_port, u_hex, profile_name.lower(), bool(require_signature))
    with _PROPERTY_REFRESH_INFLIGHT_LOCK:
        if refresh_key in _PROPERTY_REFRESH_INFLIGHT:
            return
        _PROPERTY_REFRESH_INFLIGHT.add(refresh_key)

    def _worker() -> None:
        try:
            _get_skin_property(
                resolved_port,
                target_uuid_hex=u_hex,
                target_username=profile_name,
                require_signature=require_signature,
                prefetch_sources=False,
            )
        except Exception:
            pass
        finally:
            with _PROPERTY_REFRESH_INFLIGHT_LOCK:
                _PROPERTY_REFRESH_INFLIGHT.discard(refresh_key)

    try:
        _PROPERTY_REFRESH_EXECUTOR.submit(_worker)
    except Exception:
        thread = threading.Thread(
            target=_worker,
            name="authlib-profile-cache-refresh-fallback",
            daemon=True,
        )
        thread.start()


_REMOTE_METADATA_PREFETCH_INFLIGHT_LOCK = threading.Lock()
_REMOTE_METADATA_PREFETCH_INFLIGHT: set[tuple[str, str]] = set()


def schedule_remote_texture_metadata_prefetch(
    uuid_hex: str,
    username: str = "",
) -> None:
    norm_uuid = _normalize_uuid_hex(uuid_hex)
    clean_name = str(username or "").strip()
    if not norm_uuid and not clean_name:
        return

    inflight_key = (norm_uuid, clean_name.lower())
    with _REMOTE_METADATA_PREFETCH_INFLIGHT_LOCK:
        if inflight_key in _REMOTE_METADATA_PREFETCH_INFLIGHT:
            return
        _REMOTE_METADATA_PREFETCH_INFLIGHT.add(inflight_key)

    def _worker() -> None:
        try:
            _resolve_remote_texture_metadata(
                norm_uuid,
                clean_name,
                wait_for_inflight=False,
                timeout_seconds=4.0,
            )
        except Exception:
            pass
        finally:
            with _REMOTE_METADATA_PREFETCH_INFLIGHT_LOCK:
                _REMOTE_METADATA_PREFETCH_INFLIGHT.discard(inflight_key)

    try:
        _PROPERTY_REFRESH_EXECUTOR.submit(_worker)
    except Exception:
        thread = threading.Thread(
            target=_worker,
            name="authlib-metadata-prefetch-fallback",
            daemon=True,
        )
        thread.start()
