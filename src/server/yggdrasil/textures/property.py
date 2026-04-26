from __future__ import annotations

import base64
import json
import threading
import time

from server.yggdrasil.identity import (
    _get_username_and_uuid,
    _normalize_uuid_hex,
    _uuid_hex_to_dashed,
)
from server.yggdrasil.signing import _sign_texture_property
from server.yggdrasil.state import STATE, TEXTURE_PROP_CACHE_TTL_SECONDS
from server.yggdrasil.textures.local import (
    _has_local_skin_file,
    _resolve_local_cape_url,
)
from server.yggdrasil.textures.metadata import _resolve_remote_texture_metadata
from server.yggdrasil.textures.resolver import (
    _resolve_cached_skin_model,
    _resolve_cape_url,
    _resolve_skin_model,
)
from server.yggdrasil.textures.urls import (
    _build_public_cape_url,
    _build_public_skin_url,
    _collect_texture_identifiers,
    _remote_texture_exists,
)


__all__ = [
    "_build_texture_property",
    "_get_skin_property",
    "_get_skin_property_with_timeout",
]


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
    u_hex = _normalize_uuid_hex(target_uuid_hex) or current_u_hex
    profile_name = (target_username or username or "").strip()
    u_with_dashes = _uuid_hex_to_dashed(u_hex)
    cape_url = _resolve_cape_url(u_hex, profile_name, port, probe_remote=True)

    skin_model = _resolve_skin_model(u_hex, profile_name)
    url: str | None = None
    skin_exists = False

    if _has_local_skin_file(u_hex, profile_name):
        skin_exists = True
        url = _build_public_skin_url(u_with_dashes, port)
    else:
        remote_metadata = _resolve_remote_texture_metadata(u_hex, profile_name)
        url = (remote_metadata or {}).get("skin") or None
        skin_model = (remote_metadata or {}).get("model") or skin_model
        if url:
            skin_exists = True

        if not url:
            skin_exists = _remote_texture_exists(
                "skin", u_with_dashes or u_hex or profile_name
            )
            if skin_exists:
                url = _build_public_skin_url(u_with_dashes, port)

        # Use remote cape only if no local cape exists.
        if not cape_url:
            cape_url = (remote_metadata or {}).get("cape") or None

    if url and port and port > 0:
        url = _build_public_skin_url(u_with_dashes, port)

    textures: dict = {}
    if skin_exists and url:
        skin_data = {"url": url}
        if skin_model == "slim":
            skin_data["metadata"] = {"model": "slim"}
        textures["SKIN"] = skin_data

    if cape_url:
        if port and port > 0:
            identifiers = _collect_texture_identifiers(u_hex, profile_name)
            ident = identifiers[0] if identifiers else (profile_name or "")
            textures["CAPE"] = {"url": _build_public_cape_url(ident, port)}
        else:
            textures["CAPE"] = {"url": cape_url}

    cache_key = (
        f"{u_hex}|{profile_name}|{url}|{cape_url or ''}|"
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
    timeout_seconds: float = 1.0,
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
        profile_name = (target_username or "").strip()
        remote_metadata = _resolve_remote_texture_metadata(
            u_hex,
            profile_name,
            wait_for_inflight=False,
            allow_stale=True,
        )

        dashed = _uuid_hex_to_dashed(u_hex) if u_hex else ""
        has_local_skin = _has_local_skin_file(u_hex or "", profile_name)
        skin_url: str | None = None
        if has_local_skin:
            skin_url = _build_public_skin_url(dashed, port)
        elif (remote_metadata or {}).get("skin"):
            skin_url = (remote_metadata or {}).get("skin")
            if port and port > 0:
                skin_url = _build_public_skin_url(dashed, port)

        cape_url = _resolve_local_cape_url(u_hex or "", profile_name, port) or (
            remote_metadata or {}
        ).get("cape")
        if cape_url and port and port > 0:
            identifiers = _collect_texture_identifiers(u_hex or "", profile_name)
            ident = identifiers[0] if identifiers else (profile_name or "")
            cape_url = _build_public_cape_url(ident, port)

        skin_model = (
            (remote_metadata or {}).get("model")
            or _resolve_cached_skin_model(u_hex or "", profile_name, allow_stale=True)
            or "classic"
        )
        textures: dict = {}
        if skin_url:
            skin_data = {"url": skin_url}
            if skin_model == "slim":
                skin_data["metadata"] = {"model": "slim"}
            textures["SKIN"] = skin_data
        if cape_url:
            textures["CAPE"] = {"url": cape_url}

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
