from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import unquote, urlparse

from core.settings import _apply_url_proxy

from server.yggdrasil.identity import (
    _active_account_scope,
    _get_username_and_uuid,
    _normalize_uuid_hex,
    _uuid_hex_to_dashed,
)
from server.yggdrasil.signing import _sign_texture_property, get_public_key_pem
from server.yggdrasil.state import STATE, TEXTURE_PROP_CACHE_TTL_SECONDS
from server.yggdrasil.textures.local import (
    _has_local_skin_file,
    _is_valid_local_texture_file,
    _resolve_local_cape_url,
)
from server.yggdrasil.textures.metadata import _resolve_remote_texture_metadata
from server.yggdrasil.textures.resolver import (
    _resolve_cached_skin_model,
)
from server.yggdrasil.textures.urls import (
    _build_histolauncher_texture_url,
    _build_public_skin_url,
    _build_texture_property_cape_url,
    _build_texture_property_skin_url,
    _collect_texture_identifiers,
    _minecraft_texture_id_from_url,
)


__all__ = [
    "_build_texture_property",
    "_get_skin_property",
    "_get_skin_property_with_timeout",
]


TEXTURE_METADATA_LOOKUP_TIMEOUT_SECONDS = 6.0
TEXTURE_PROPERTY_LOOKUP_TIMEOUT_SECONDS = 18.0
TEXTURE_SOURCE_PREFETCH_TIMEOUT_SECONDS = 8.0
TEXTURE_HISTOLAUNCHER_FALLBACK_TIMEOUT_SECONDS = 2.0


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
) -> None:
    worker_threads: list[threading.Thread] = []
    for texture_type, remote_url, uuid_hex, username, microsoft_cache in sources:
        if not remote_url:
            continue
        worker_thread = threading.Thread(
            target=_prefetch_texture_source,
            args=(texture_type, remote_url, uuid_hex, username, timeout_seconds, microsoft_cache),
        )
        worker_thread.daemon = True
        worker_thread.start()
        worker_threads.append(worker_thread)

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


def _prefetch_histolauncher_skin_source(uuid_hex: str, username: str = "") -> str | None:
    for identifier in _collect_texture_identifiers(uuid_hex, username):
        source_url = _build_histolauncher_texture_url("skin", identifier)
        if not source_url:
            continue
        if _prefetch_texture_source(
            "skin",
            source_url,
            uuid_hex,
            username,
            timeout_seconds=TEXTURE_HISTOLAUNCHER_FALLBACK_TIMEOUT_SECONDS,
        ):
            return source_url
    return None


def _resolve_microsoft_texture_metadata(identifier: str = "", username: str = "") -> dict | None:
    try:
        from server.auth.microsoft import resolve_microsoft_texture_metadata

        return resolve_microsoft_texture_metadata(identifier, username)
    except Exception:
        return None


def _microsoft_account_enabled() -> bool:
    try:
        from server.auth.microsoft import microsoft_account_enabled

        return microsoft_account_enabled()
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
        "signatureRequired": bool(require_signature),
        "textures": textures or {},
    }
    if profile_name:
        tex["profileName"] = profile_name
    if require_signature:
        public_key = get_public_key_pem()
        if public_key:
            tex["histolauncherSignaturePublickey"] = public_key

    def _encode_texture_payload(payload: dict) -> str:
        json_bytes = json.dumps(payload).encode("utf-8")
        return base64.b64encode(json_bytes).decode("utf-8")

    encoded = _encode_texture_payload(tex)
    signature = None
    if require_signature:
        sig = _sign_texture_property(encoded)
        if sig:
            signature = sig
        else:
            tex["signatureRequired"] = False
            encoded = _encode_texture_payload(tex)

    prop = {"name": "textures", "value": encoded}
    if signature:
        prop["signature"] = signature
    return prop


def _get_skin_property(
    port: int,
    target_uuid_hex: str = "",
    target_username: str = "",
    require_signature: bool = True,
) -> dict | None:
    username, current_u_hex = _get_username_and_uuid()
    microsoft_enabled = _microsoft_account_enabled()
    u_hex = _normalize_uuid_hex(target_uuid_hex) or current_u_hex
    is_current_profile = (
        _normalize_uuid_hex(u_hex) and _normalize_uuid_hex(u_hex) == _normalize_uuid_hex(current_u_hex)
    )
    allow_local_override = not (microsoft_enabled and is_current_profile)
    profile_name = _resolve_profile_name_for_target(
        u_hex, target_username, username, current_u_hex
    )
    if u_hex and profile_name:
        STATE.uuid_name_cache[u_hex] = profile_name
    u_with_dashes = _uuid_hex_to_dashed(u_hex)
    cape_url = _resolve_local_cape_url(u_hex, profile_name, port) if allow_local_override else None

    skin_model = _resolve_cached_skin_model(u_hex, profile_name) or "classic"
    url: str | None = None
    skin_exists = False
    skin_source_is_microsoft = False
    cape_source_is_microsoft = False

    if allow_local_override and _has_local_skin_file(u_hex, profile_name):
        skin_exists = True
        url = _build_public_skin_url(u_with_dashes, port)
    else:
        remote_metadata = _resolve_remote_texture_metadata(
            u_hex,
            profile_name,
            timeout_seconds=TEXTURE_METADATA_LOOKUP_TIMEOUT_SECONDS,
        )
        url = (remote_metadata or {}).get("skin") or None
        skin_model = (remote_metadata or {}).get("model") or skin_model
        if url:
            skin_exists = True

        if url and microsoft_enabled and is_current_profile:
            skin_source_is_microsoft = True

        microsoft_metadata = _resolve_microsoft_texture_metadata(u_hex, profile_name)
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

        if not url and allow_local_override:
            histolauncher_skin_url = _prefetch_histolauncher_skin_source(
                u_hex, profile_name
            )
            if histolauncher_skin_url:
                url = histolauncher_skin_url
                skin_exists = True

        if not cape_url:
            cape_url = (remote_metadata or {}).get("cape") or None
            if not cape_url:
                cape_url = (microsoft_metadata or {}).get("cape") or None
                if cape_url:
                    cape_source_is_microsoft = True

        if cape_url and microsoft_enabled and is_current_profile:
            cape_source_is_microsoft = True

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

    if port and port > 0:
        sources: list[tuple[str, str | None, str, str, bool]] = []
        if url and texture_skin_url:
            sources.append(("skin", url, u_hex, profile_name, skin_source_is_microsoft))
        if cape_url and texture_cape_url:
            sources.append(("cape", cape_url, u_hex, profile_name, cape_source_is_microsoft))
        _prefetch_texture_sources(sources)

    cache_scope = _active_account_scope()
    cache_key = (
        f"{cache_scope}|{u_hex}|{profile_name}|{texture_skin_url or ''}|{texture_cape_url or ''}|"
        f"{'signed' if require_signature else 'unsigned'}"
    )
    cached = STATE.texture_prop_cache.get(cache_key)
    now = time.time()
    if cached and (now - cached.get("at", 0) <= TEXTURE_PROP_CACHE_TTL_SECONDS):
        return cached.get("prop")

    prop = _build_texture_property(textures, u_hex, profile_name, require_signature)
    STATE.texture_prop_cache[cache_key] = {"prop": prop, "at": now}
    return prop


def _get_skin_property_with_timeout(
    port: int,
    target_uuid_hex: str = "",
    target_username: str = "",
    timeout_seconds: float = TEXTURE_PROPERTY_LOOKUP_TIMEOUT_SECONDS,
    require_signature: bool = True,
) -> dict | None:
    container: dict = {}

    def _worker() -> None:
        try:
            container["prop"] = _get_skin_property(
                port, target_uuid_hex, target_username, require_signature=require_signature
            )
        except Exception:
            container["prop"] = None

    t = threading.Thread(target=_worker)
    t.daemon = True
    t.start()
    t.join(timeout_seconds)

    if "prop" in container:
        return container.get("prop")

    try:
        u_hex = _normalize_uuid_hex(target_uuid_hex) or _normalize_uuid_hex(
            _get_username_and_uuid()[1]
        )
        current_username, current_uuid_hex = _get_username_and_uuid()
        microsoft_enabled = _microsoft_account_enabled()
        is_current_profile = (
            _normalize_uuid_hex(u_hex) and _normalize_uuid_hex(u_hex) == _normalize_uuid_hex(current_uuid_hex)
        )
        allow_local_override = not (microsoft_enabled and is_current_profile)
        profile_name = _resolve_profile_name_for_target(
            u_hex or "", target_username, current_username, current_uuid_hex
        )
        if u_hex and profile_name:
            STATE.uuid_name_cache[u_hex] = profile_name
        remote_metadata = _resolve_remote_texture_metadata(
            u_hex,
            profile_name,
            wait_for_inflight=False,
            allow_stale=True,
        )

        dashed = _uuid_hex_to_dashed(u_hex) if u_hex else ""
        has_local_skin = allow_local_override and _has_local_skin_file(u_hex or "", profile_name)
        skin_url: str | None = None
        skin_source_is_microsoft = False
        cape_source_is_microsoft = False
        if has_local_skin:
            skin_url = _build_public_skin_url(dashed, port)
        elif (remote_metadata or {}).get("skin"):
            skin_url = (remote_metadata or {}).get("skin")

        if skin_url and microsoft_enabled and is_current_profile:
            skin_source_is_microsoft = True

        microsoft_metadata = _resolve_microsoft_texture_metadata(u_hex or "", profile_name)
        microsoft_local_skin_id = str((microsoft_metadata or {}).get("local_skin_id") or "").strip()
        microsoft_default_skin_id = str((microsoft_metadata or {}).get("default_skin_id") or "").strip()
        if microsoft_local_skin_id and port and port > 0:
            skin_url = _build_public_skin_url(microsoft_local_skin_id, port)
            skin_source_is_microsoft = True
        elif microsoft_default_skin_id and port and port > 0:
            skin_url = _build_public_skin_url(microsoft_default_skin_id, port)
            skin_source_is_microsoft = True
        elif not skin_url:
            if (microsoft_metadata or {}).get("skin"):
                skin_url = (microsoft_metadata or {}).get("skin")
                skin_source_is_microsoft = True

        cape_url = _resolve_local_cape_url(u_hex or "", profile_name, port) if allow_local_override else None
        if not cape_url:
            cape_url = (remote_metadata or {}).get("cape") or None
        if not cape_url:
            cape_url = (microsoft_metadata or {}).get("cape") or None
            if cape_url:
                cape_source_is_microsoft = True

        if cape_url and microsoft_enabled and is_current_profile:
            cape_source_is_microsoft = True
        skin_model = (
            ((microsoft_metadata or {}).get("model") if microsoft_local_skin_id else "")
            or ((microsoft_metadata or {}).get("model") if microsoft_default_skin_id else "")
            or (remote_metadata or {}).get("model")
            or (microsoft_metadata or {}).get("model")
            or _resolve_cached_skin_model(u_hex or "", profile_name, allow_stale=True)
            or "classic"
        )
        textures: dict = {}
        texture_skin_url = _build_texture_property_skin_url(
            skin_url, u_hex or "", profile_name, port
        )
        if texture_skin_url:
            skin_data = {"url": texture_skin_url}
            if skin_model == "slim":
                skin_data["metadata"] = {"model": "slim"}
            textures["SKIN"] = skin_data
        texture_cape_url = _build_texture_property_cape_url(cape_url, u_hex or "", profile_name, port)
        if texture_cape_url:
            textures["CAPE"] = {"url": texture_cape_url}

        if port and port > 0:
            sources: list[tuple[str, str | None, str, str, bool]] = []
            if skin_url and texture_skin_url:
                sources.append(("skin", skin_url, u_hex or "", profile_name, skin_source_is_microsoft))
            if cape_url and texture_cape_url:
                sources.append(("cape", cape_url, u_hex or "", profile_name, cape_source_is_microsoft))
            _prefetch_texture_sources(sources)

        prop = _build_texture_property(
            textures,
            u_hex or "",
            profile_name,
            require_signature=require_signature,
            fast_timestamp=True,
        )
        return prop
    except Exception:
        return None
