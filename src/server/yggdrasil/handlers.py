from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlparse

from core.logger import colorize_log
from core.settings import _apply_url_proxy

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
    _build_public_skin_url,
    _build_texture_property_cape_url,
    _cape_requires_minecraft_texture_host,
    _is_minecraft_texture_url,
)


__all__ = [
    "handle_auth_post",
    "handle_session_get",
    "handle_player_certificates",
    "handle_services_profile_get",
    "handle_session_join_post",
    "handle_has_joined_get",
]


TEXTURE_PROPERTY_LOOKUP_TIMEOUT_SECONDS = 18.0


OFFICIAL_SESSION_JOIN_URL = "https://sessionserver.mojang.com/session/minecraft/join"


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


def _official_join_urls() -> list[str]:
    urls: list[str] = []
    try:
        proxied = _apply_url_proxy(OFFICIAL_SESSION_JOIN_URL)
    except Exception:
        proxied = OFFICIAL_SESSION_JOIN_URL
    if proxied:
        urls.append(proxied)
    if OFFICIAL_SESSION_JOIN_URL not in urls:
        urls.append(OFFICIAL_SESSION_JOIN_URL)
    return urls


def _forward_microsoft_session_join(data: dict) -> bool:
    if not _microsoft_account_enabled():
        return False

    server_id = str(data.get("serverId") or "").strip()
    requested_profile = _normalize_uuid_hex(data.get("selectedProfile"))
    if not server_id:
        return False

    try:
        from server.auth.microsoft import get_microsoft_launch_account

        success, account, error = get_microsoft_launch_account()
    except Exception as exc:
        print(colorize_log(
            f"[yggdrasil] Could not load Microsoft join token: {exc}"
        ))
        return False

    if not success or not account:
        detail = str(error or "Microsoft account is not authenticated.").strip()
        print(colorize_log(
            f"[yggdrasil] Could not load Microsoft join token: {detail}"
        ))
        return False

    access_token = str(account.get("access_token") or "").strip()
    selected_profile = _normalize_uuid_hex(account.get("uuid")) or requested_profile
    if not access_token or not selected_profile:
        return False

    if requested_profile and requested_profile != selected_profile:
        print(colorize_log(
            "[yggdrasil] Microsoft join requested a stale profile id; using the active Microsoft account profile"
        ))

    body = json.dumps({
        "accessToken": access_token,
        "selectedProfile": selected_profile,
        "serverId": server_id,
    }).encode("utf-8")
    for url in _official_join_urls():
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Histolauncher",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                if getattr(resp, "status", 0) == 204:
                    print(colorize_log("[yggdrasil] Microsoft session join forwarded to Mojang"))
                    return True
        except urllib.error.HTTPError as exc:
            print(colorize_log(
                f"[yggdrasil] Mojang session join returned HTTP {exc.code}; local join remains cached"
            ))
        except Exception as exc:
            print(colorize_log(
                f"[yggdrasil] Mojang session join forward failed: {exc}; local join remains cached"
            ))
    return False


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
        timeout_seconds=TEXTURE_PROPERTY_LOOKUP_TIMEOUT_SECONDS,
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
    microsoft_enabled = _microsoft_account_enabled()
    u_with_dashes = _uuid_hex_to_dashed(u_hex)
    remote_metadata = _resolve_remote_texture_metadata(u_hex, username)
    microsoft_metadata = _resolve_microsoft_texture_metadata(u_hex, username)
    skin_model = (
        (remote_metadata or {}).get("model")
        or (microsoft_metadata or {}).get("model")
        or _resolve_skin_model(u_hex, username)
    )
    cape_url = (remote_metadata or {}).get("cape") or (
        None if microsoft_enabled else _resolve_local_cape_url(u_hex, username, port)
    ) or (microsoft_metadata or {}).get("cape")
    if (
        cape_url
        and port
        and port > 0
        and _cape_requires_minecraft_texture_host()
        and not _is_minecraft_texture_url(cape_url)
        and (microsoft_metadata or {}).get("cape")
    ):
        cape_url = (microsoft_metadata or {}).get("cape") or cape_url

    skin_url: str | None = None
    if (not microsoft_enabled) and _has_local_skin_file(u_hex, username):
        skin_url = _build_public_skin_url(u_with_dashes, port)
    else:
        skin_url = (remote_metadata or {}).get("skin")
        microsoft_local_skin_id = str((microsoft_metadata or {}).get("local_skin_id") or "").strip()
        microsoft_default_skin_id = str((microsoft_metadata or {}).get("default_skin_id") or "").strip()
        if microsoft_local_skin_id and port and port > 0:
            skin_url = _build_public_skin_url(microsoft_local_skin_id, port)
            skin_model = (microsoft_metadata or {}).get("model") or skin_model
        elif microsoft_default_skin_id and port and port > 0:
            skin_url = _build_public_skin_url(microsoft_default_skin_id, port)
            skin_model = (microsoft_metadata or {}).get("model") or skin_model
        elif not skin_url:
            skin_url = (microsoft_metadata or {}).get("skin")
        if not skin_url and _histolauncher_account_enabled():
            skin_url = _build_public_skin_url(u_with_dashes, port)
        if (
            skin_url
            and port
            and port > 0
            and not microsoft_local_skin_id
            and not microsoft_default_skin_id
        ):
            skin_url = _build_public_skin_url(u_with_dashes, port)

    cape_url = _build_texture_property_cape_url(cape_url, u_hex, username, port)

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


def handle_player_certificates():
    if not _microsoft_account_enabled():
        return 404, {
            "error": "Not Found",
            "errorMessage": "Minecraft player certificates are only available for Microsoft accounts.",
        }

    try:
        from server.auth.microsoft import get_microsoft_player_certificates

        success, payload, error = get_microsoft_player_certificates()
    except Exception as exc:
        return 503, {
            "error": "ServiceUnavailableException",
            "errorMessage": str(exc),
        }

    if success and payload:
        print(colorize_log("[yggdrasil] Microsoft player certificate served"))
        return 200, payload

    return 503, {
        "error": "ServiceUnavailableException",
        "errorMessage": error or "Could not fetch Minecraft player certificates.",
    }


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
    _forward_microsoft_session_join(data)
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
        timeout_seconds=TEXTURE_PROPERTY_LOOKUP_TIMEOUT_SECONDS,
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
