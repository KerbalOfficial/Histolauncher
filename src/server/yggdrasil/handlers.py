from __future__ import annotations

import json
import re
import time
import urllib.parse
import uuid
from urllib.parse import urlparse

from core.logger import colorize_log

from server.yggdrasil.identity import (
    _ensure_uuid,
    _get_username_and_uuid,
    _histolauncher_account_enabled,
    _normalize_uuid_hex,
    _uuid_hex_to_dashed,
)
from server.yggdrasil.state import STATE, SESSION_JOIN_TTL_SECONDS
from server.yggdrasil.textures.local import (
    _has_local_skin_file,
    _resolve_local_cape_url,
)
from server.yggdrasil.textures.metadata import _resolve_remote_texture_metadata
from server.yggdrasil.textures.property import _get_skin_property_with_timeout
from server.yggdrasil.textures.resolver import _resolve_skin_model
from server.yggdrasil.textures.urls import (
    _build_public_cape_url,
    _build_public_skin_url,
    _collect_texture_identifiers,
)


__all__ = [
    "handle_auth_post",
    "handle_session_get",
    "handle_services_profile_get",
    "handle_session_join_post",
    "handle_has_joined_get",
]


def handle_auth_post(path: str, body: str, port: int):
    try:
        data = json.loads(body) if body else {}
    except Exception:
        data = {}
    username, u_hex = _get_username_and_uuid()
    access_token = "offline-" + u_hex
    client_token = data.get("clientToken") or "offline-client"
    profile = {"id": u_hex, "name": username}
    resp = {
        "accessToken": access_token,
        "clientToken": client_token,
        "selectedProfile": profile,
        "availableProfiles": [profile],
    }
    return 200, resp


def handle_session_get(path: str, port: int, require_signature: bool = True):
    parsed = urlparse(path)
    path_only = parsed.path or ""
    match = re.search(r"/profile/([0-9a-fA-F-]{32,36})/?$", path_only)
    if not match:
        return 404, {"error": "Not Found"}

    raw_req_id = match.group(1)
    req_uuid = _normalize_uuid_hex(raw_req_id)
    username, u_hex = _get_username_and_uuid()

    if not req_uuid:
        return 404, {"error": "Not Found"}

    if req_uuid == "00000000000000000000000000000000":
        req_uuid = u_hex

    query = urllib.parse.parse_qs(parsed.query or "")
    query_name = (query.get("username") or [""])[0].strip()
    current_name = (username or "Player").strip() or "Player"

    if req_uuid == u_hex:
        profile_name = current_name
    else:
        cached_name = str(STATE.uuid_name_cache.get(req_uuid) or "").strip()
        profile_name = query_name or cached_name

    if profile_name:
        STATE.uuid_name_cache[req_uuid] = profile_name

    props = []
    skin_prop = _get_skin_property_with_timeout(
        port,
        target_uuid_hex=req_uuid,
        target_username=profile_name,
        timeout_seconds=1.0,
        require_signature=require_signature,
    )
    if skin_prop:
        props.append(skin_prop)

    signature_required = any(p.get("signature") for p in props)

    resp = {
        "id": req_uuid,
        "name": profile_name or current_name,
        "properties": props,
        "signatureRequired": signature_required,
        "profileActions": [],
    }
    print(colorize_log(
        f"[yggdrasil] session profile served: uuid={req_uuid}, "
        f"signature_required={signature_required}"
    ))
    return 200, resp


def handle_services_profile_get(port: int):
    username, u_hex = _get_username_and_uuid()
    u_with_dashes = _uuid_hex_to_dashed(u_hex)
    remote_metadata = _resolve_remote_texture_metadata(u_hex, username)
    skin_model = (remote_metadata or {}).get("model") or _resolve_skin_model(u_hex, username)
    cape_url = (remote_metadata or {}).get("cape") or _resolve_local_cape_url(
        u_hex, username, port
    )

    skin_url: str | None = None
    if _has_local_skin_file(u_hex, username):
        skin_url = _build_public_skin_url(u_with_dashes, port)
    else:
        skin_url = (remote_metadata or {}).get("skin")
        if not skin_url and _histolauncher_account_enabled():
            skin_url = _build_public_skin_url(u_with_dashes, port)
        if skin_url and port and port > 0:
            skin_url = _build_public_skin_url(u_with_dashes, port)

    if cape_url and port and port > 0:
        identifiers = _collect_texture_identifiers(u_hex, username)
        ident = identifiers[0] if identifiers else (username or "")
        cape_url = _build_public_cape_url(ident, port)

    variant = "SLIM" if skin_model == "slim" else "CLASSIC"

    capes = []
    if cape_url:
        capes.append(
            {
                "id": str(uuid.uuid4()),
                "state": "ACTIVE",
                "url": cape_url,
            }
        )

    signature_required = bool(skin_url and cape_url)

    resp = {
        "id": u_hex,
        "name": username,
        "skins": (
            [
                {
                    "id": str(uuid.uuid4()),
                    "state": "ACTIVE",
                    "url": skin_url,
                    "variant": variant,
                }
            ]
            if skin_url
            else []
        ),
        "capes": capes,
        "signatureRequired": signature_required,
    }
    print(colorize_log(
        f"[yggdrasil] services profile served: uuid={u_hex}, variant={variant}"
    ))
    return 200, resp


def handle_session_join_post(path: str, body: str):
    try:
        data = json.loads(body) if body else {}
    except Exception:
        data = {}

    server_id = str(data.get("serverId") or "").strip()
    selected_profile = str(data.get("selectedProfile") or "").strip()

    if not server_id:
        return 400, {
            "error": "IllegalArgumentException",
            "errorMessage": "Missing serverId",
        }

    username, current_uuid_hex = _get_username_and_uuid()
    current_uuid_hex = _normalize_uuid_hex(current_uuid_hex) or _normalize_uuid_hex(
        selected_profile
    )
    if not current_uuid_hex:
        return 403, {
            "error": "ForbiddenOperationException",
            "errorMessage": "Invalid profile",
        }

    now = time.time()
    stale = [
        k
        for k, v in STATE.session_join_cache.items()
        if now - float(v.get("at", 0)) > SESSION_JOIN_TTL_SECONDS
    ]
    for k in stale:
        STATE.session_join_cache.pop(k, None)

    STATE.session_join_cache[server_id] = {
        "uuid": current_uuid_hex,
        "name": (username or "Player").strip() or "Player",
        "at": now,
    }
    STATE.uuid_name_cache[current_uuid_hex] = (username or "Player").strip() or "Player"
    print(colorize_log(
        f"[yggdrasil] session join accepted: serverId={server_id}, uuid={current_uuid_hex}"
    ))
    return 204, None


def handle_has_joined_get(path: str, port: int, require_signature: bool = True):
    parsed = urlparse(path)
    query = urllib.parse.parse_qs(parsed.query or "")
    server_id = str((query.get("serverId") or [""])[0]).strip()
    username_q = str((query.get("username") or [""])[0]).strip()

    if not server_id or not username_q:
        return 400, {
            "error": "IllegalArgumentException",
            "errorMessage": "Missing username/serverId",
        }

    username, current_uuid_hex = _get_username_and_uuid()
    current_name = (username or "Player").strip() or "Player"
    current_uuid_hex = _normalize_uuid_hex(current_uuid_hex)

    joined = STATE.session_join_cache.get(server_id) or {}
    joined_uuid = _normalize_uuid_hex(joined.get("uuid"))
    joined_name = str(joined.get("name") or "").strip()

    if joined_uuid and joined_name.lower() == username_q.lower():
        out_uuid = joined_uuid
        out_name = joined_name
    elif current_uuid_hex and current_name.lower() == username_q.lower():
        out_uuid = current_uuid_hex
        out_name = current_name
    else:
        out_uuid = _normalize_uuid_hex(_ensure_uuid(username_q))
        out_name = username_q
        if not out_uuid:
            return 204, None

    STATE.uuid_name_cache[out_uuid] = out_name

    props = []
    skin_prop = _get_skin_property_with_timeout(
        port,
        target_uuid_hex=out_uuid,
        target_username=out_name,
        timeout_seconds=1.0,
        require_signature=require_signature,
    )
    if skin_prop:
        props.append(skin_prop)

    signature_required = any(p.get("signature") for p in props)
    resp = {
        "id": out_uuid,
        "name": out_name,
        "properties": props,
        "signatureRequired": signature_required,
        "profileActions": [],
    }
    print(colorize_log(
        f"[yggdrasil] hasJoined served: serverId={server_id}, "
        f"username={out_name}, uuid={out_uuid}"
    ))
    return 200, resp
