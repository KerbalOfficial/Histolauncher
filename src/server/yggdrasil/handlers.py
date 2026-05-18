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
from core.settings import _apply_url_proxy, load_global_settings

from server.yggdrasil.identity import (
    _ensure_uuid,
    _get_username_and_uuid,
    _normalize_uuid_hex,
    _uuid_hex_to_dashed,
)
from server.yggdrasil.textures.local import (
    _has_local_skin_file,
    _resolve_local_cape_url,
)
from server.yggdrasil.state import STATE, SESSION_JOIN_TTL_SECONDS
from server.yggdrasil.textures.metadata import _resolve_remote_texture_metadata
from server.yggdrasil.textures.property import (
    _get_skin_property_fast_fallback,
    _schedule_skin_property_cache_refresh,
)
from server.yggdrasil.textures.resolver import _resolve_skin_model
from server.yggdrasil.textures.urls import (
    _build_public_skin_url,
    _build_texture_property_cape_url,
    _build_texture_property_skin_url,
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


OFFICIAL_SESSION_JOIN_URL = "https://sessionserver.mojang.com/session/minecraft/join"


def _settings_profile_name_for_uuid(uuid_hex: str) -> str:
    req_uuid = _normalize_uuid_hex(uuid_hex)
    if not req_uuid:
        return ""
    try:
        settings = load_global_settings() or {}
        username = str(settings.get("username") or "").strip()
        settings_uuid = _normalize_uuid_hex(settings.get("uuid"))
        if settings_uuid and settings_uuid == req_uuid and username:
            return username
        if username and _normalize_uuid_hex(_ensure_uuid(username)) == req_uuid:
            return username
    except Exception:
        pass
    return ""


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

    if not req_uuid:
        return 404, {"error": "Not Found"}

    query = urllib.parse.parse_qs(parsed.query or "")
    query_name = (query.get("username") or [""])[0].strip()

    if req_uuid == "00000000000000000000000000000000":
        username, u_hex = _get_username_and_uuid()
        req_uuid = u_hex
        current_name = (username or "Player").strip() or "Player"
        profile_name = current_name
    else:
        cached_name = str(STATE.uuid_name_cache.get(req_uuid) or "").strip()
        settings_name = _settings_profile_name_for_uuid(req_uuid)
        if query_name or cached_name or settings_name:
            profile_name = query_name or cached_name or settings_name
            current_name = profile_name or "Player"
        else:
            current_name = "Player"
            profile_name = ""

    if profile_name:
        STATE.uuid_name_cache[req_uuid] = profile_name

    props = []
    skin_prop = _get_skin_property_fast_fallback(
        port,
        target_uuid_hex=req_uuid,
        target_username=profile_name,
        require_signature=require_signature,
    )
    if skin_prop:
        props.append(skin_prop)
    _schedule_skin_property_cache_refresh(
        port,
        target_uuid_hex=req_uuid,
        target_username=profile_name,
        require_signature=require_signature,
    )

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
    remote_metadata = _resolve_remote_texture_metadata(u_hex, username)
    microsoft_metadata = _resolve_microsoft_texture_metadata(u_hex, username)
    skin_model = (
        (remote_metadata or {}).get("model")
        or (microsoft_metadata or {}).get("model")
        or _resolve_skin_model(u_hex, username)
    )
    cape_url = (remote_metadata or {}).get("cape") or (microsoft_metadata or {}).get("cape")
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

    if not microsoft_enabled and port and port > 0:
        if not skin_url and _has_local_skin_file(u_hex, username):
            skin_url = _build_public_skin_url(_uuid_hex_to_dashed(u_hex), port)
        if not cape_url:
            cape_url = _resolve_local_cape_url(u_hex, username, port) or None

    if skin_url and port and port > 0 and not microsoft_local_skin_id and not microsoft_default_skin_id:
        skin_url = _build_texture_property_skin_url(skin_url, u_hex, username, port)

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
        # Log the full exception locally but do not echo internal details to
        # the Minecraft client – the exception text can leak file paths,
        # tokens, or library internals to log scrapers and crash reporters.
        print(colorize_log(
            f"[yggdrasil] Microsoft player certificate fetch failed: {exc}"
        ))
        return 503, {
            "error": "ServiceUnavailableException",
            "errorMessage": "Could not fetch Minecraft player certificates.",
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

    if _microsoft_account_enabled() and not _forward_microsoft_session_join(data):
        return 503, {
            "error": "ServiceUnavailableException",
            "errorMessage": "Could not forward Microsoft session join to Mojang.",
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

    joined = STATE.session_join_cache.get(server_id) or {}
    joined_uuid = _normalize_uuid_hex(joined.get("uuid"))
    joined_name = str(joined.get("name") or "").strip()
    try:
        joined_at = float(joined.get("at", 0) or 0)
    except (TypeError, ValueError):
        joined_at = 0

    if not joined_uuid or time.time() - joined_at > SESSION_JOIN_TTL_SECONDS:
        STATE.session_join_cache.pop(server_id, None)
        return 204, None

    if joined_name and joined_name.lower() != username_q.lower():
        return 204, None

    out_uuid = joined_uuid
    out_name = joined_name or username_q

    STATE.uuid_name_cache[out_uuid] = out_name

    props = []
    skin_prop = _get_skin_property_fast_fallback(
        port,
        target_uuid_hex=out_uuid,
        target_username=out_name,
        require_signature=require_signature,
    )
    if skin_prop:
        props.append(skin_prop)
    _schedule_skin_property_cache_refresh(
        port,
        target_uuid_hex=out_uuid,
        target_username=out_name,
        require_signature=require_signature,
    )

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
