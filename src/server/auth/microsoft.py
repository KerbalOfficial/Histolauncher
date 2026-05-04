from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from typing import Any

from core.logger import get_logger
from core.settings import (
    _apply_url_proxy,
    get_active_profile_id,
    get_default_minecraft_dir,
    get_versions_profile_dir,
    load_account_token,
    load_cached_account_identity,
    load_global_settings,
    save_account_token,
    save_cached_account_identity,
    save_global_settings,
)
from core.settings.paths import get_profiles_settings_dir
from core.settings.profiles import safe_profile_id


__all__ = [
    "MICROSOFT_CLIENT_ID",
    "api_payload_from_profile",
    "activate_microsoft_cape",
    "activate_microsoft_skin",
    "disable_microsoft_cape",
    "delete_microsoft_local_skin",
    "get_microsoft_launch_account",
    "get_microsoft_player_certificates",
    "get_cached_microsoft_texture_profile",
    "get_microsoft_texture_profile",
    "get_verified_microsoft_account",
    "microsoft_account_enabled",
    "poll_device_code",
    "refresh_microsoft_account",
    "ensure_microsoft_texture_cache_path",
    "microsoft_texture_cache_path",
    "remove_microsoft_texture_cache",
    "resolve_microsoft_local_skin_path",
    "resolve_microsoft_default_skin_path",
    "resolve_microsoft_texture_metadata",
    "resolve_microsoft_texture_url",
    "save_microsoft_local_skin",
    "set_microsoft_skin_favorite",
    "start_device_code",
    "upload_microsoft_skin",
]


MICROSOFT_CLIENT_ID = os.environ.get(
    "HISTOLAUNCHER_MICROSOFT_CLIENT_ID",
    "5908fd8f-362a-4358-ac68-f231e275fd51",
).strip()

MICROSOFT_SCOPE = "XboxLive.signin offline_access"
MICROSOFT_DEVICE_CODE_URL = (
    "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
)
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
XBOX_AUTH_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_AUTH_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MINECRAFT_LAUNCHER_LOGIN_URL = "https://api.minecraftservices.com/launcher/login"
MINECRAFT_LEGACY_LOGIN_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
MINECRAFT_ENTITLEMENTS_URL = "https://api.minecraftservices.com/entitlements/mcstore"
MINECRAFT_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"
MINECRAFT_PROFILE_SKINS_URL = f"{MINECRAFT_PROFILE_URL}/skins"
MINECRAFT_PROFILE_CAPES_URL = f"{MINECRAFT_PROFILE_URL}/capes"
MINECRAFT_PLAYER_CERTIFICATES_URL = "https://api.minecraftservices.com/player/certificates"
MINECRAFT_VERSION_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"

USER_AGENT = "Histolauncher/1.0"
TIMEOUT = 20.0
TOKEN_SKEW_SECONDS = 120
MAX_SKIN_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_MINECRAFT_CLIENT_JAR_BYTES = 80 * 1024 * 1024
TEXTURE_COMPARE_TIMEOUT = 3.0
REMOTE_SKIN_CONFIRMATION_SECONDS = 12.0
REMOTE_SKIN_CONFIRMATION_INTERVAL_SECONDS = 1.0
MICROSOFT_LIBRARY_SKINS_DIR_NAME = "libraryskins"
MICROSOFT_TEXTURE_CACHE_DIR_NAME = "texturecache"
MICROSOFT_LIBRARY_METADATA_SUFFIX = ".microsoft.library.json"
PERSISTED_MICROSOFT_LIBRARY_KEYS = (
    "skin_library",
    "favorite_skin_ids",
    "active_local_skin_id",
    "active_local_skin_selected_at",
    "default_skin_settings",
    "active_default_skin_id",
    "active_default_skin_selected_at",
    "default_skin_remote_ids",
    "texture_aliases",
)
MICROSOFT_TEXTURE_RATE_LIMIT_MESSAGE = "Error applying changes, please try again in a few seconds!"
MINECRAFT_DEFAULT_SKIN_PREFIX = "default-"
MINECRAFT_DEFAULT_SKIN_NAMES: tuple[dict[str, str], ...] = (
    {"key": "steve", "name": "Steve", "variant": "classic"},
    {"key": "alex", "name": "Alex", "variant": "slim"},
    {"key": "zuri", "name": "Zuri", "variant": "slim"},
    {"key": "sunny", "name": "Sunny", "variant": "classic"},
    {"key": "noor", "name": "Noor", "variant": "classic"},
    {"key": "makena", "name": "Makena", "variant": "slim"},
    {"key": "kai", "name": "Kai", "variant": "slim"},
    {"key": "efe", "name": "Efe", "variant": "slim"},
    {"key": "ari", "name": "Ari", "variant": "slim"},
)
MINECRAFT_DEFAULT_SKIN_KEYS = {
    str(entry["key"]): dict(entry) for entry in MINECRAFT_DEFAULT_SKIN_NAMES
}


class MicrosoftAuthError(RuntimeError):
    pass


def _short_log_value(value: Any, max_len: int = 240) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _debug_log(stage: str, message: str) -> None:
    stage_text = str(stage or "microsoft_auth").strip()
    line = f"[microsoft_auth] {stage_text}: {_short_log_value(message, 600)}"
    try:
        get_logger().debug(line)
    except Exception:
        pass


def _safe_response_detail(data: Any) -> str:
    if isinstance(data, dict):
        parts = []
        for key in ("error", "error_description", "errorMessage", "message", "Message", "XErr"):
            if data.get(key):
                parts.append(f"{key}={_short_log_value(data.get(key))}")
        if parts:
            return "; ".join(parts)
        if data:
            return "keys=" + ",".join(sorted(str(key) for key in data.keys()))
        return "empty response"
    if data:
        return _short_log_value(data)
    return "empty response"


def _endpoint_for_log(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path or "/"
        return f"{parsed.netloc}{path}"
    except Exception:
        return _short_log_value(url)


def microsoft_account_enabled() -> bool:
    try:
        settings = load_global_settings() or {}
        return str(settings.get("account_type") or "Local").strip().lower() == "microsoft"
    except Exception:
        return False


def _candidate_urls(url: str) -> list[str]:
    raw = str(url or "").strip()
    if not raw:
        return []

    candidates: list[str] = []
    proxied = _apply_url_proxy(raw)
    if proxied:
        candidates.append(proxied)
    if raw not in candidates:
        candidates.append(raw)
    return candidates


def _decode_response_body(payload: bytes) -> Any:
    text = payload.decode("utf-8", errors="replace")
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _response_headers(response: Any) -> dict[str, str]:
    try:
        return dict(response.getheaders())
    except Exception:
        try:
            return dict(response.headers.items()) if hasattr(response, "headers") else {}
        except Exception:
            return {}


def _request_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
    form: bool = False,
    bearer_token: str = "",
    timeout: float = TIMEOUT,
    stage: str = "",
) -> tuple[int, Any, dict[str, str], str | None]:
    request_headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if headers:
        request_headers.update(headers)
    if bearer_token:
        request_headers["Authorization"] = f"Bearer {bearer_token}"

    request_body = None
    if body is not None:
        if form:
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
            request_body = urllib.parse.urlencode(body).encode("utf-8")
        else:
            request_headers["Content-Type"] = "application/json"
            request_body = json.dumps(body).encode("utf-8")

    last_error: str | None = None
    last_status = 0
    last_data: Any = None
    last_headers: dict[str, str] = {}

    candidates = _candidate_urls(url)
    if stage:
        _debug_log(
            stage,
            f"request method={str(method or 'GET').upper()} endpoint={_endpoint_for_log(url)} "
            f"proxy_candidates={len(candidates)} form={bool(form)} bearer={bool(bearer_token)}",
        )
    for index, candidate in enumerate(candidates):
        req = urllib.request.Request(
            candidate,
            data=request_body,
            headers=request_headers,
            method=str(method or "GET").upper(),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = response.read()
                status = getattr(response, "status", None) or response.getcode()
                if stage:
                    _debug_log(stage, f"response status={status} detail={_safe_response_detail(_decode_response_body(payload))}")
                return status, _decode_response_body(payload), _response_headers(response), None
        except urllib.error.HTTPError as e:
            payload = e.read()
            data = _decode_response_body(payload)
            headers_out = _response_headers(e)
            last_status = int(e.code or 0)
            last_data = data
            last_headers = headers_out
            if stage:
                _debug_log(stage, f"http_error status={last_status} detail={_safe_response_detail(data)}")

            can_try_direct = (
                index == 0
                and len(candidates) > 1
                and last_status in {403, 500, 502, 503, 504}
            )
            if can_try_direct:
                last_error = _extract_error(data, f"Remote request failed ({last_status})")
                if stage:
                    _debug_log(stage, "retrying direct endpoint after proxied request failed")
                continue
            return last_status, data, headers_out, None
        except Exception as e:
            last_error = str(e)
            if stage:
                _debug_log(stage, f"network_error type={type(e).__name__} detail={_short_log_value(e)}")
            continue

    return last_status, last_data, last_headers, last_error or "Request failed"


def _multipart_escape(value: Any) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', "\\\"").replace("\r", " ").replace("\n", " ")


def _request_multipart_json(
    method: str,
    url: str,
    *,
    fields: dict[str, Any] | None = None,
    files: dict[str, tuple[str, str, bytes]] | None = None,
    bearer_token: str = "",
    timeout: float = TIMEOUT,
    stage: str = "",
) -> tuple[int, Any, dict[str, str], str | None]:
    boundary = f"----Histolauncher{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    for name, value in (fields or {}).items():
        chunks.append(
            (
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"{_multipart_escape(name)}\"\r\n\r\n"
                f"{str(value or '')}\r\n"
            ).encode("utf-8")
        )

    for name, file_info in (files or {}).items():
        filename, content_type, payload = file_info
        chunks.append(
            (
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"{_multipart_escape(name)}\"; "
                f"filename=\"{_multipart_escape(filename)}\"\r\n"
                f"Content-Type: {content_type or 'application/octet-stream'}\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(payload or b"")
        chunks.append(b"\r\n")

    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    request_body = b"".join(chunks)
    request_headers = {
        "Accept": "application/json",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": USER_AGENT,
    }
    if bearer_token:
        request_headers["Authorization"] = f"Bearer {bearer_token}"

    last_error: str | None = None
    last_status = 0
    last_data: Any = None
    last_headers: dict[str, str] = {}

    candidates = _candidate_urls(url)
    if stage:
        _debug_log(
            stage,
            f"multipart_request method={str(method or 'POST').upper()} endpoint={_endpoint_for_log(url)} "
            f"proxy_candidates={len(candidates)} bytes={len(request_body)} bearer={bool(bearer_token)}",
        )

    for index, candidate in enumerate(candidates):
        req = urllib.request.Request(
            candidate,
            data=request_body,
            headers=request_headers,
            method=str(method or "POST").upper(),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = response.read()
                status = getattr(response, "status", None) or response.getcode()
                data = _decode_response_body(payload)
                if stage:
                    _debug_log(stage, f"multipart_response status={status} detail={_safe_response_detail(data)}")
                return status, data, _response_headers(response), None
        except urllib.error.HTTPError as e:
            payload = e.read()
            data = _decode_response_body(payload)
            headers_out = _response_headers(e)
            last_status = int(e.code or 0)
            last_data = data
            last_headers = headers_out
            if stage:
                _debug_log(stage, f"multipart_http_error status={last_status} detail={_safe_response_detail(data)}")

            can_try_direct = (
                index == 0
                and len(candidates) > 1
                and last_status in {403, 500, 502, 503, 504}
            )
            if can_try_direct:
                last_error = _extract_error(data, f"Remote request failed ({last_status})")
                if stage:
                    _debug_log(stage, "retrying direct endpoint after proxied multipart request failed")
                continue
            return last_status, data, headers_out, None
        except Exception as e:
            last_error = str(e)
            if stage:
                _debug_log(stage, f"multipart_network_error type={type(e).__name__} detail={_short_log_value(e)}")
            continue

    return last_status, last_data, last_headers, last_error or "Request failed"


def _extract_error(data: Any, fallback: str = "Request failed") -> str:
    message = ""
    if isinstance(data, dict):
        for key in ("error_description", "errorMessage", "message", "error"):
            value = data.get(key)
            if value:
                message = str(value)
                break
    if not message:
        message = fallback

    if "AADSTS70002" in message and "mobile" in message.lower():
        return (
            "Microsoft rejected this client ID for device-code login. Enable "
            "'Allow public client flows' for the Azure app registration, or provide "
            "a public desktop/mobile client ID."
        )
    if "invalid app registration" in message.lower() or "aka.ms/appreginfo" in message.lower():
        return (
            "Microsoft rejected this app registration. In the Azure app registration, "
            "make sure personal Microsoft accounts are supported and enable "
            "'Allow public client flows' for desktop/device-code login."
        )
    return message


def _is_app_registration_error(message: Any) -> bool:
    text = str(message or "").lower()
    return (
        "invalid app registration" in text
        or "aka.ms/appreginfo" in text
        or "rejected this app registration" in text
    )


def _expires_at(expires_in: Any) -> int:
    try:
        seconds = int(float(expires_in))
    except Exception:
        seconds = 3600
    return int(time.time()) + max(0, seconds)


def _token_fresh(expires_at: Any, min_lifetime: int = TOKEN_SKEW_SECONDS) -> bool:
    try:
        return int(float(expires_at or 0)) - int(time.time()) > min_lifetime
    except Exception:
        return False


def _normalize_uuid_hex(value: Any) -> str:
    raw = str(value or "").strip().replace("-", "")
    if len(raw) != 32:
        return ""
    try:
        return uuid.UUID(raw).hex
    except Exception:
        return ""


def _microsoft_library_metadata_path(profile_id: str | None = None) -> str:
    active_profile = safe_profile_id(profile_id or get_active_profile_id())
    return os.path.join(get_profiles_settings_dir(), f"{active_profile}{MICROSOFT_LIBRARY_METADATA_SUFFIX}")


def _extract_persisted_library_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    out: dict[str, Any] = {}
    for key in PERSISTED_MICROSOFT_LIBRARY_KEYS:
        value = payload.get(key)
        if value is None:
            continue
        if key in {"skin_library", "favorite_skin_ids"} and not isinstance(value, list):
            continue
        if key in {"default_skin_settings", "default_skin_remote_ids", "texture_aliases"} and not isinstance(value, dict):
            continue
        if key in {"active_local_skin_selected_at", "active_default_skin_selected_at"}:
            try:
                out[key] = int(value)
            except Exception:
                continue
            continue
        if key in {"active_local_skin_id", "active_default_skin_id"}:
            text = str(value or "").strip()
            if text:
                out[key] = text
            continue
        out[key] = value
    return out


def _load_persisted_library_payload() -> dict[str, Any]:
    path = _microsoft_library_metadata_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return _extract_persisted_library_payload(raw)


def _save_persisted_library_payload(payload: dict[str, Any] | None) -> None:
    path = _microsoft_library_metadata_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = _extract_persisted_library_payload(payload)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _merge_persisted_library_payload(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    persisted = _load_persisted_library_payload()
    if not persisted:
        return False

    changed = False
    for key, value in persisted.items():
        current = payload.get(key)
        if key in {"skin_library", "favorite_skin_ids"}:
            should_replace = not isinstance(current, list) or (not current and bool(value))
        elif key in {"default_skin_settings", "default_skin_remote_ids", "texture_aliases"}:
            should_replace = not isinstance(current, dict) or (not current and bool(value))
        else:
            should_replace = current in (None, "", 0)
        if should_replace:
            payload[key] = value
            changed = True
    return changed


def _load_token_payload() -> dict[str, Any] | None:
    token = load_account_token()
    if not token:
        return None
    try:
        payload = json.loads(token)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("type") or "").strip().lower() != "microsoft":
        return None
    _merge_persisted_library_payload(payload)
    return payload


def _save_token_payload(payload: dict[str, Any]) -> None:
    payload["type"] = "Microsoft"
    payload["updated_at"] = int(time.time())
    save_account_token(json.dumps(payload, separators=(",", ":")))
    _save_persisted_library_payload(payload)


def api_payload_from_profile(
    profile: dict[str, Any] | None,
    *,
    access_token: str = "",
    xuid: str = "",
    client_id: str = MICROSOFT_CLIENT_ID,
) -> dict[str, Any] | None:
    if not isinstance(profile, dict):
        return None

    username = str(profile.get("name") or profile.get("username") or "").strip()
    uuid_hex = _normalize_uuid_hex(profile.get("id") or profile.get("uuid"))
    if not username or not uuid_hex:
        return None

    account = {
        "account_type": "Microsoft",
        "username": username,
        "uuid": uuid_hex,
        "access_token": str(access_token or ""),
        "user_type": "msa",
        "xuid": str(xuid or ""),
        "client_id": str(client_id or MICROSOFT_CLIENT_ID),
        "skins": profile.get("skins") if isinstance(profile.get("skins"), list) else [],
        "capes": profile.get("capes") if isinstance(profile.get("capes"), list) else [],
    }
    return account


def _account_from_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    minecraft = payload.get("minecraft") if isinstance(payload.get("minecraft"), dict) else {}
    xbox = payload.get("xbox") if isinstance(payload.get("xbox"), dict) else {}
    return api_payload_from_profile(
        profile,
        access_token=str(minecraft.get("access_token") or ""),
        xuid=str(xbox.get("xuid") or ""),
        client_id=str(payload.get("client_id") or MICROSOFT_CLIENT_ID),
    )


def _save_account_identity(account: dict[str, Any]) -> None:
    username = str(account.get("username") or "").strip()
    uuid_hex = _normalize_uuid_hex(account.get("uuid"))
    if not username or not uuid_hex:
        return

    settings = load_global_settings() or {}
    settings["account_type"] = "Microsoft"
    settings["username"] = username
    settings["uuid"] = uuid_hex
    save_global_settings(settings)
    save_cached_account_identity({"username": username, "uuid": uuid_hex})


def start_device_code() -> dict[str, Any]:
    if not MICROSOFT_CLIENT_ID:
        return {"ok": False, "error": "Microsoft client ID is not configured."}

    _debug_log(
        "oauth_device_code",
        f"starting device-code flow client_id={MICROSOFT_CLIENT_ID} scope={MICROSOFT_SCOPE}",
    )

    status, data, _headers, error = _request_json(
        "POST",
        MICROSOFT_DEVICE_CODE_URL,
        {
            "client_id": MICROSOFT_CLIENT_ID,
            "scope": MICROSOFT_SCOPE,
        },
        form=True,
        stage="oauth_device_code",
    )
    if status == 200 and isinstance(data, dict) and data.get("device_code"):
        _debug_log(
            "oauth_device_code",
            f"device-code created expires_in={data.get('expires_in')} interval={data.get('interval') or 5}",
        )
        return {
            "ok": True,
            "device_code": data.get("device_code"),
            "user_code": data.get("user_code"),
            "verification_uri": data.get("verification_uri"),
            "verification_uri_complete": data.get("verification_uri_complete"),
            "expires_in": data.get("expires_in"),
            "interval": data.get("interval") or 5,
            "message": data.get("message"),
        }

    message = error or _extract_error(data, "Failed to start Microsoft login.")
    return {"ok": False, "error": f"OAuth device-code start failed: {message}"}


def poll_device_code(device_code: str, interval: int | None = None) -> dict[str, Any]:
    code = str(device_code or "").strip()
    if not code:
        return {"ok": False, "error": "Missing Microsoft device code."}

    _debug_log("oauth_device_poll", f"polling token endpoint interval={interval or 5}")

    status, data, _headers, error = _request_json(
        "POST",
        MICROSOFT_TOKEN_URL,
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": MICROSOFT_CLIENT_ID,
            "device_code": code,
        },
        form=True,
        stage="oauth_device_poll",
    )

    if status == 200 and isinstance(data, dict) and data.get("access_token"):
        try:
            _debug_log("oauth_device_poll", "token exchange succeeded; continuing to Xbox/Minecraft services")
            account = _complete_oauth_login(data)
            return {
                "ok": True,
                "authenticated": True,
                "username": account.get("username"),
                "uuid": account.get("uuid"),
                "account_type": "Microsoft",
            }
        except Exception as e:
            _debug_log("oauth_complete", f"failed detail={_short_log_value(e)}")
            return {"ok": False, "error": str(e)}

    err_code = str(data.get("error") if isinstance(data, dict) else "").strip()
    if err_code == "authorization_pending":
        _debug_log("oauth_device_poll", "authorization still pending")
        return {"ok": False, "pending": True, "interval": interval or 5}
    if err_code == "slow_down":
        _debug_log("oauth_device_poll", "server requested slower polling")
        return {"ok": False, "pending": True, "interval": int(interval or 5) + 5}
    if err_code in {"authorization_declined", "access_denied"}:
        return {"ok": False, "cancelled": True, "error": "Microsoft login was cancelled."}
    if err_code == "expired_token":
        return {"ok": False, "expired": True, "error": "Microsoft login code expired."}

    message = error or _extract_error(data, "Microsoft login failed.")
    return {"ok": False, "error": f"OAuth device-code token exchange failed: {message}"}


def _complete_oauth_login(oauth_data: dict[str, Any]) -> dict[str, Any]:
    now = int(time.time())
    _debug_log("oauth_complete", "building Microsoft session payload")
    microsoft = {
        "access_token": str(oauth_data.get("access_token") or ""),
        "refresh_token": str(oauth_data.get("refresh_token") or ""),
        "expires_at": _expires_at(oauth_data.get("expires_in")),
        "scope": str(oauth_data.get("scope") or MICROSOFT_SCOPE),
    }
    if not microsoft["access_token"]:
        raise MicrosoftAuthError("Microsoft did not return an access token.")
    if not microsoft["refresh_token"]:
        raise MicrosoftAuthError("Microsoft did not return a refresh token.")

    payload: dict[str, Any] = {
        "type": "Microsoft",
        "client_id": MICROSOFT_CLIENT_ID,
        "created_at": now,
        "updated_at": now,
        "microsoft": microsoft,
    }
    payload = _authenticate_minecraft_services(payload)
    _save_token_payload(payload)

    account = _account_from_payload(payload)
    if not account:
        raise MicrosoftAuthError("Minecraft profile response was missing username or UUID.")
    _save_account_identity(account)
    _debug_log("oauth_complete", f"account verified username={account['username']} uuid={account['uuid']}")
    return account


def _refresh_oauth(payload: dict[str, Any]) -> dict[str, Any]:
    microsoft = payload.get("microsoft") if isinstance(payload.get("microsoft"), dict) else {}
    refresh_token = str(microsoft.get("refresh_token") or "").strip()
    if not refresh_token:
        raise MicrosoftAuthError("Microsoft session expired. Please sign in again.")

    status, data, _headers, error = _request_json(
        "POST",
        MICROSOFT_TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "client_id": str(payload.get("client_id") or MICROSOFT_CLIENT_ID),
            "refresh_token": refresh_token,
            "scope": MICROSOFT_SCOPE,
        },
        form=True,
        stage="oauth_refresh",
    )
    if status != 200 or not isinstance(data, dict) or not data.get("access_token"):
        message = error or _extract_error(data, "Microsoft session expired. Please sign in again.")
        raise MicrosoftAuthError(f"OAuth refresh failed: {message}")

    payload["microsoft"] = {
        "access_token": str(data.get("access_token") or ""),
        "refresh_token": str(data.get("refresh_token") or refresh_token),
        "expires_at": _expires_at(data.get("expires_in")),
        "scope": str(data.get("scope") or MICROSOFT_SCOPE),
    }
    return payload


def _extract_xui(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    claims = data.get("DisplayClaims") if isinstance(data.get("DisplayClaims"), dict) else {}
    xui = claims.get("xui") if isinstance(claims.get("xui"), list) else []
    first = xui[0] if xui and isinstance(xui[0], dict) else {}
    return first


def _xsts_error(data: Any) -> str:
    if not isinstance(data, dict):
        return "Xbox Live authentication failed."
    xerr = str(data.get("XErr") or "").strip()
    known = {
        "2148916233": "This Microsoft account does not have an Xbox profile.",
        "2148916235": "Xbox Live is not available for this Microsoft account region.",
        "2148916236": "This Microsoft account needs adult verification before Xbox Live can be used.",
        "2148916237": "This Microsoft account needs adult verification before Xbox Live can be used.",
        "2148916238": "This Microsoft account is underage and cannot use Xbox Live for Minecraft.",
    }
    if xerr in known:
        return known[xerr]
    return _extract_error(data, "Xbox Live authentication failed.")


def _authenticate_xbox_live(ms_access_token: str) -> dict[str, Any]:
    last_error = "Xbox Live authentication failed."
    for label, rps_ticket in (
        ("t", f"t={ms_access_token}"),
        ("d", f"d={ms_access_token}"),
        ("raw", ms_access_token),
    ):
        stage = f"xbox_user_auth_{label}"
        _debug_log(stage, f"attempting Xbox Live user auth ticket_format={label}")
        body = {
            "Properties": {
                "AuthMethod": "RPS",
                "SiteName": "user.auth.xboxlive.com",
                "RpsTicket": rps_ticket,
            },
            "RelyingParty": "http://auth.xboxlive.com",
            "TokenType": "JWT",
        }
        status, data, _headers, error = _request_json("POST", XBOX_AUTH_URL, body, stage=stage)
        if status == 200 and isinstance(data, dict) and data.get("Token"):
            _debug_log(stage, "Xbox Live user auth succeeded")
            return data
        last_error = error or _extract_error(data, "Xbox Live authentication failed.")
        _debug_log(stage, f"Xbox Live user auth rejected ticket_format={label} detail={last_error}")
    raise MicrosoftAuthError(
        "Xbox Live authentication failed after trying t=, d=, and raw ticket formats: "
        f"{last_error}"
    )


def _authorize_xsts(xbox_token: str) -> dict[str, Any]:
    _debug_log("xsts_authorize", "requesting XSTS token for Minecraft services")
    body = {
        "Properties": {
            "SandboxId": "RETAIL",
            "UserTokens": [xbox_token],
        },
        "RelyingParty": "rp://api.minecraftservices.com/",
        "TokenType": "JWT",
    }
    status, data, _headers, error = _request_json("POST", XSTS_AUTH_URL, body, stage="xsts_authorize")
    if status != 200 or not isinstance(data, dict) or not data.get("Token"):
        raise MicrosoftAuthError(f"XSTS authorization failed: {error or _xsts_error(data)}")
    _debug_log("xsts_authorize", "XSTS authorization succeeded")
    return data


def _login_minecraft(uhs: str, xsts_token: str) -> dict[str, Any]:
    identity_token = f"XBL3.0 x={uhs};{xsts_token}"
    _debug_log("minecraft_launcher_login", f"requesting Minecraft launcher token uhs_present={bool(uhs)}")
    launcher_body = {
        "xtoken": identity_token,
        "platform": "PC_LAUNCHER",
    }
    status, data, _headers, error = _request_json(
        "POST",
        MINECRAFT_LAUNCHER_LOGIN_URL,
        launcher_body,
        stage="minecraft_launcher_login",
    )
    if status == 200 and isinstance(data, dict) and data.get("access_token"):
        _debug_log("minecraft_launcher_login", "Minecraft launcher token received")
        return data

    launcher_error = error or _extract_error(data, "Minecraft launcher login failed.")
    _debug_log("minecraft_launcher_login", f"launcher login failed detail={launcher_error}")

    _debug_log("minecraft_legacy_login", "trying legacy Minecraft login_with_xbox endpoint")
    legacy_body = {"identityToken": identity_token}
    legacy_status, legacy_data, _headers, legacy_error = _request_json(
        "POST",
        MINECRAFT_LEGACY_LOGIN_URL,
        legacy_body,
        stage="minecraft_legacy_login",
    )
    if legacy_status == 200 and isinstance(legacy_data, dict) and legacy_data.get("access_token"):
        _debug_log("minecraft_legacy_login", "Minecraft legacy token received")
        return legacy_data

    legacy_message = legacy_error or _extract_error(legacy_data, "Minecraft services login failed.")
    if _is_app_registration_error(launcher_error) or _is_app_registration_error(legacy_message):
        raise MicrosoftAuthError(
            "Minecraft Services rejected this Azure app registration. Something must of went terribly wrong! "
            "Please report this to the Histolauncher developers immediatly!"
        )
    raise MicrosoftAuthError(
        "Minecraft services login failed. "
        f"launcher/login: {launcher_error}; login_with_xbox: {legacy_message}"
    )


def _has_minecraft_entitlement(entitlements: Any) -> bool:
    if not isinstance(entitlements, dict):
        return False
    items = entitlements.get("items")
    if not isinstance(items, list):
        return False
    owned_names = {
        str(item.get("name") or "").strip().lower()
        for item in items
        if isinstance(item, dict)
    }
    return bool(owned_names.intersection({"game_minecraft", "product_minecraft"}))


def _fetch_entitlements(minecraft_token: str) -> dict[str, Any]:
    status, data, _headers, error = _request_json(
        "GET",
        MINECRAFT_ENTITLEMENTS_URL,
        bearer_token=minecraft_token,
        stage="minecraft_entitlements",
    )
    if status != 200 or not isinstance(data, dict):
        raise MicrosoftAuthError(
            f"Minecraft ownership check failed: {error or _extract_error(data, 'Could not verify Minecraft ownership.')}"
        )
    if not _has_minecraft_entitlement(data):
        raise MicrosoftAuthError("This Microsoft account does not own Minecraft: Java Edition.")
    _debug_log("minecraft_entitlements", "Minecraft Java entitlement verified")
    return data


def _fetch_profile(minecraft_token: str) -> dict[str, Any]:
    status, data, _headers, error = _request_json(
        "GET",
        MINECRAFT_PROFILE_URL,
        bearer_token=minecraft_token,
        stage="minecraft_profile",
    )
    if status == 429:
        raise MicrosoftAuthError(MICROSOFT_TEXTURE_RATE_LIMIT_MESSAGE)
    if status != 200 or not isinstance(data, dict):
        raise MicrosoftAuthError(
            f"Minecraft profile load failed: {error or _extract_error(data, 'Could not load Minecraft profile.')}"
        )

    profile_id = _normalize_uuid_hex(data.get("id"))
    name = str(data.get("name") or "").strip()
    if not profile_id or not name:
        raise MicrosoftAuthError("Minecraft profile is missing a player name. Create a Java profile first, then try again.")

    data["id"] = profile_id
    data["name"] = name
    _debug_log("minecraft_profile", f"Minecraft profile loaded username={name} uuid={profile_id}")
    return data


def _authenticate_minecraft_services(payload: dict[str, Any]) -> dict[str, Any]:
    _debug_log("minecraft_services", "starting Xbox Live and Minecraft services authentication")
    microsoft = payload.get("microsoft") if isinstance(payload.get("microsoft"), dict) else {}
    ms_access_token = str(microsoft.get("access_token") or "").strip()
    if not ms_access_token:
        raise MicrosoftAuthError("Microsoft access token is missing.")

    xbox_data = _authenticate_xbox_live(ms_access_token)
    xbox_token = str(xbox_data.get("Token") or "")
    xbox_xui = _extract_xui(xbox_data)

    xsts_data = _authorize_xsts(xbox_token)
    xsts_token = str(xsts_data.get("Token") or "")
    xsts_xui = _extract_xui(xsts_data)
    uhs = str(xsts_xui.get("uhs") or xbox_xui.get("uhs") or "").strip()
    xuid = str(xsts_xui.get("xid") or xbox_xui.get("xid") or "").strip()
    if not uhs:
        raise MicrosoftAuthError("Xbox Live authentication did not return a user hash.")
    _debug_log("minecraft_services", f"Xbox identity resolved uhs_present={bool(uhs)} xuid_present={bool(xuid)}")

    minecraft_data = _login_minecraft(uhs, xsts_token)
    minecraft_token = str(minecraft_data.get("access_token") or "")
    entitlements = _fetch_entitlements(minecraft_token)
    profile = _fetch_profile(minecraft_token)

    payload["xbox"] = {
        "uhs": uhs,
        "xuid": xuid,
    }
    payload["minecraft"] = {
        "access_token": minecraft_token,
        "expires_at": _expires_at(minecraft_data.get("expires_in")),
        "token_type": str(minecraft_data.get("token_type") or "Bearer"),
    }
    payload["entitlements"] = entitlements
    payload["profile"] = profile
    _debug_log("minecraft_services", "Microsoft account authentication chain completed")
    return payload


def refresh_microsoft_account(*, force_profile: bool = False) -> dict[str, Any]:
    payload = _load_token_payload()
    if not payload:
        raise MicrosoftAuthError("Not logged in with a Microsoft account.")

    microsoft = payload.get("microsoft") if isinstance(payload.get("microsoft"), dict) else {}
    minecraft = payload.get("minecraft") if isinstance(payload.get("minecraft"), dict) else {}
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}

    needs_refresh = force_profile or not _token_fresh(minecraft.get("expires_at")) or not profile
    if needs_refresh:
        if not _token_fresh(microsoft.get("expires_at")):
            payload = _refresh_oauth(payload)
        payload = _authenticate_minecraft_services(payload)
        _save_token_payload(payload)

    account = _account_from_payload(payload)
    if not account:
        raise MicrosoftAuthError("Stored Microsoft account data is incomplete. Please sign in again.")
    _save_account_identity(account)
    return account


def get_microsoft_launch_account() -> tuple[bool, dict[str, Any] | None, str | None]:
    if not microsoft_account_enabled():
        return False, None, "Microsoft account not enabled"
    try:
        return True, refresh_microsoft_account(force_profile=False), None
    except Exception as e:
        return False, None, str(e)


def get_verified_microsoft_account() -> tuple[bool, dict[str, Any] | None, str | None]:
    if not microsoft_account_enabled():
        return False, None, "Microsoft account not enabled"

    payload = _load_token_payload()
    if not payload:
        return False, None, "Not logged in"

    try:
        account = refresh_microsoft_account(force_profile=False)
        return True, account, None
    except Exception as e:
        err = str(e).lower()
        if (
            "expired" in err
            or "sign in again" in err
            or "invalid_grant" in err
            or "unauthorized" in err
        ):
            return False, None, str(e)

        cached = _account_from_payload(payload)
        if cached:
            return True, cached, None

        cached_identity = load_cached_account_identity()
        if cached_identity:
            account = api_payload_from_profile(cached_identity)
            if account:
                return True, account, None
        return False, None, str(e)


def _is_player_certificate_payload(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    key_pair = data.get("keyPair")
    if not isinstance(key_pair, dict):
        return False
    private_key = str(key_pair.get("privateKey") or "").strip()
    public_key = str(key_pair.get("publicKey") or "").strip()
    signature = str(data.get("publicKeySignatureV2") or data.get("publicKeySignature") or "").strip()
    expires_at = str(data.get("expiresAt") or "").strip()
    return bool(private_key and public_key and signature and expires_at)


def get_microsoft_player_certificates() -> tuple[bool, dict[str, Any] | None, str | None]:
    if not microsoft_account_enabled():
        return False, None, "Microsoft account not enabled"

    last_error = "Could not fetch Minecraft player certificates."
    for force_profile in (False, True):
        try:
            account = refresh_microsoft_account(force_profile=force_profile)
            minecraft_token = str(account.get("access_token") or "").strip()
            if not minecraft_token:
                raise MicrosoftAuthError("Microsoft account launch token is missing.")
        except Exception as e:
            last_error = str(e)
            continue

        for method in ("POST", "GET"):
            status, data, _headers, error = _request_json(
                method,
                MINECRAFT_PLAYER_CERTIFICATES_URL,
                bearer_token=minecraft_token,
                timeout=TIMEOUT,
                stage="minecraft_player_certificates",
            )
            if status == 200 and _is_player_certificate_payload(data):
                return True, data, None

            last_error = error or _extract_error(
                data,
                f"Minecraft player certificate request failed ({status or 'no status'}).",
            )
            if status in {401, 403} and not force_profile:
                break

    return False, None, last_error


def _normalize_minecraft_texture_url(url: Any) -> str | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    try:
        parsed = urllib.parse.urlparse(raw)
    except Exception:
        return None
    if str(parsed.netloc or "").strip().lower() != "textures.minecraft.net":
        return None
    return urllib.parse.urlunparse(parsed._replace(scheme="https"))


def _active_texture_entries(entries: Any) -> list[dict[str, Any]]:
    items = [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []
    active = [entry for entry in items if str(entry.get("state") or "").strip().upper() == "ACTIVE"]
    return active or items


def _texture_model(entry: dict[str, Any] | None) -> str:
    if not isinstance(entry, dict):
        return "classic"
    variant = str(entry.get("variant") or "").strip().lower()
    if variant == "slim":
        return "slim"
    metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    model = str(metadata.get("model") or "").strip().lower()
    return "slim" if model == "slim" else "classic"


def _texture_hash_from_url(url: Any) -> str:
    normalized = _normalize_minecraft_texture_url(url)
    if not normalized:
        return ""
    try:
        basename = os.path.basename(urllib.parse.urlparse(normalized).path or "")
    except Exception:
        return ""
    value = urllib.parse.unquote(str(basename or "")).strip().lower()
    if re.match(r"^[a-f0-9]{32,128}$", value):
        return value
    return ""


def _safe_texture_entry_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 160:
        return ""
    if not re.match(r"^[A-Za-z0-9_.:-]+$", text):
        return ""
    return text


def _normalize_local_skin_id(value: Any) -> str:
    raw = _safe_texture_entry_id(value).strip().lower()
    return raw if re.match(r"^[a-f0-9]{32}$", raw) else ""


def _is_local_skin_id(value: Any) -> bool:
    return bool(_normalize_local_skin_id(value))


def _new_local_skin_id() -> str:
    return uuid.uuid4().hex


def _active_settings_profile_id(profile_id: str | None = None) -> str:
    return safe_profile_id(profile_id or get_active_profile_id())


def _microsoft_profile_storage_dir(dir_name: str, profile_id: str | None = None) -> str:
    return os.path.join(
        get_profiles_settings_dir(),
        dir_name,
        _active_settings_profile_id(profile_id),
    )


def _local_skin_library_dir(profile_id: str | None = None) -> str:
    return _microsoft_profile_storage_dir(MICROSOFT_LIBRARY_SKINS_DIR_NAME, profile_id)


def _local_skin_path(skin_id: str, profile_id: str | None = None) -> str:
    clean_id = _normalize_local_skin_id(skin_id)
    if not clean_id:
        return ""
    return os.path.join(_local_skin_library_dir(profile_id), f"{clean_id}.png")


def _ensure_local_skin_path(skin_id: str, profile_id: str | None = None) -> str:
    return _local_skin_path(skin_id, profile_id)


def _remove_local_skin_paths(skin_id: str) -> None:
    path = _local_skin_path(skin_id)
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def resolve_microsoft_local_skin_path(skin_id: str) -> str:
    clean_id = _normalize_local_skin_id(skin_id)
    if not clean_id:
        return ""
    payload = _load_token_payload()
    if not _find_skin_library_entry(payload, clean_id):
        return ""
    path = _ensure_local_skin_path(clean_id)
    return path if path and os.path.isfile(path) else ""


def _safe_texture_cache_identifier(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 160:
        return ""
    if not re.match(r"^[A-Za-z0-9_. -]+$", text):
        return ""
    return text


def _microsoft_texture_cache_dir(profile_id: str | None = None) -> str:
    return _microsoft_profile_storage_dir(MICROSOFT_TEXTURE_CACHE_DIR_NAME, profile_id)


def microsoft_texture_cache_path(
    identifier: Any,
    texture_type: str,
    *,
    profile_id: str | None = None,
) -> str:
    clean_identifier = _safe_texture_cache_identifier(identifier)
    if not clean_identifier:
        return ""
    suffix = "skin" if str(texture_type or "").strip().lower() == "skin" else "cape"
    return os.path.join(_microsoft_texture_cache_dir(profile_id), f"{clean_identifier}+{suffix}.png")


def ensure_microsoft_texture_cache_path(identifier: Any, texture_type: str) -> str:
    return microsoft_texture_cache_path(identifier, texture_type)


def remove_microsoft_texture_cache(identifier: Any, texture_type: str) -> None:
    path = microsoft_texture_cache_path(identifier, texture_type)
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def _normalize_library_skin_variant(value: Any) -> str:
    model = str(value or "classic").strip().lower()
    if model in {"wide", "default"}:
        return "classic"
    return "slim" if model == "slim" else "classic"


def _default_skin_id(key: Any) -> str:
    clean_key = str(key or "").strip().lower()
    return f"{MINECRAFT_DEFAULT_SKIN_PREFIX}{clean_key}" if clean_key in MINECRAFT_DEFAULT_SKIN_KEYS else ""


def _default_skin_texture_identifier(key: Any, variant: Any = "classic") -> str:
    skin_id = _default_skin_id(key)
    if not skin_id:
        return ""
    return f"{skin_id}-{_normalize_library_skin_variant(variant)}"


def _default_skin_asset_path(key: Any, variant: Any = "classic") -> str:
    clean_key = str(key or "").strip().lower()
    if clean_key not in MINECRAFT_DEFAULT_SKIN_KEYS:
        return ""
    family = "slim" if _normalize_library_skin_variant(variant) == "slim" else "wide"
    return f"assets/minecraft/textures/entity/player/{family}/{clean_key}.png"


def _default_skin_definition(value: Any) -> dict[str, str] | None:
    raw = _safe_texture_entry_id(value).strip().lower()
    if not raw:
        return None
    if raw.startswith(MINECRAFT_DEFAULT_SKIN_PREFIX):
        raw = raw[len(MINECRAFT_DEFAULT_SKIN_PREFIX):]
    for suffix in ("-classic", "-wide", "-default", "-slim"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    definition = MINECRAFT_DEFAULT_SKIN_KEYS.get(raw)
    if not definition:
        return None
    return {
        "id": _default_skin_id(raw),
        "key": raw,
        "name": str(definition.get("name") or raw.title()),
        "variant": _normalize_library_skin_variant(definition.get("variant")),
    }


def _normalize_default_skin_id(value: Any) -> str:
    definition = _default_skin_definition(value)
    return str((definition or {}).get("id") or "")


def _default_skin_variant_from_identifier(value: Any, fallback: Any = "classic") -> str:
    raw = _safe_texture_entry_id(value).strip().lower()
    if raw.endswith("-slim"):
        return "slim"
    if raw.endswith(("-classic", "-wide", "-default")):
        return "classic"
    return _normalize_library_skin_variant(fallback)


def _png_dimensions_from_bytes(payload: bytes | None) -> tuple[int, int] | None:
    data = bytes(payload or b"")
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    try:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    except Exception:
        return None


def _is_allowed_skin_dimensions(payload: bytes | None) -> bool:
    dimensions = _png_dimensions_from_bytes(payload)
    if not dimensions:
        return False
    width, height = dimensions
    return (width, height) in {(64, 64), (64, 32)}


def _is_valid_default_skin_payload(payload: bytes | None) -> bool:
    dimensions = _png_dimensions_from_bytes(payload)
    if not dimensions:
        return False
    width, height = dimensions
    if width < 64 or height < 32 or (width % 64) != 0:
        return False
    return (width == height and (height % 64) == 0) or (width == height * 2 and (height % 32) == 0)


def _default_skin_cache_identifier(key: Any, variant: Any = "classic") -> str:
    return _default_skin_texture_identifier(key, variant)


def _default_skin_cache_path(key: Any, variant: Any = "classic") -> str:
    identifier = _default_skin_cache_identifier(key, variant)
    return microsoft_texture_cache_path(identifier, "skin") if identifier else ""


def _write_default_skin_cache(key: Any, variant: Any, payload: bytes | None) -> str:
    if not _is_valid_default_skin_payload(payload):
        return ""
    path = _default_skin_cache_path(key, variant)
    if not path:
        return ""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(bytes(payload or b""))
        return path
    except Exception:
        return ""


def _read_default_skin_from_zip(zf: zipfile.ZipFile, key: Any, variant: Any) -> bytes | None:
    asset_path = _default_skin_asset_path(key, variant)
    if not asset_path:
        return None
    try:
        payload = zf.read(asset_path)
    except Exception:
        return None
    return payload if _is_valid_default_skin_payload(payload) else None


def _cache_default_skins_from_zip(zf: zipfile.ZipFile) -> bool:
    cached_any = False
    for definition in MINECRAFT_DEFAULT_SKIN_NAMES:
        key = definition["key"]
        for variant in ("classic", "slim"):
            payload = _read_default_skin_from_zip(zf, key, variant)
            if payload and _write_default_skin_cache(key, variant, payload):
                cached_any = True
    return cached_any


def _cache_default_skins_from_jar(path: str) -> bool:
    try:
        if not path or not os.path.isfile(path):
            return False
        with zipfile.ZipFile(path) as zf:
            return _cache_default_skins_from_zip(zf)
    except Exception:
        return False


def _candidate_default_skin_jars() -> list[str]:
    candidates: list[str] = []

    def add(path: str | None) -> None:
        value = str(path or "").strip()
        if value and value not in candidates and os.path.isfile(value):
            candidates.append(value)

    try:
        settings = load_global_settings() or {}
    except Exception:
        settings = {}

    selected = str(settings.get("selected_version") or "").replace("\\", "/").strip()
    try:
        versions_root = get_versions_profile_dir()
    except Exception:
        versions_root = ""

    if versions_root:
        if selected:
            selected_parts = [part for part in selected.split("/") if part]
            add(os.path.join(versions_root, *selected_parts, "client.jar"))
            if len(selected_parts) == 1:
                for category in ("vanilla", "release", "snapshot", "modded", "custom"):
                    add(os.path.join(versions_root, category, selected_parts[0], "client.jar"))
        try:
            for root, _dirs, files in os.walk(versions_root):
                if "client.jar" in files:
                    add(os.path.join(root, "client.jar"))
                if len(candidates) >= 12:
                    break
        except Exception:
            pass

    try:
        vanilla_versions = os.path.join(get_default_minecraft_dir(), "versions")
        if os.path.isdir(vanilla_versions):
            for name in sorted(os.listdir(vanilla_versions), reverse=True):
                add(os.path.join(vanilla_versions, name, f"{name}.jar"))
                add(os.path.join(vanilla_versions, name, "client.jar"))
                if len(candidates) >= 24:
                    break
    except Exception:
        pass

    return candidates


def _download_latest_client_default_skins() -> bool:
    status, manifest, _headers, error = _request_json(
        "GET",
        MINECRAFT_VERSION_MANIFEST_URL,
        timeout=TIMEOUT,
        stage="minecraft_version_manifest",
    )
    if status not in {200, 201} or not isinstance(manifest, dict):
        _debug_log("minecraft_default_skins", error or f"manifest failed ({status or 'no status'})")
        return False

    latest_release = str(((manifest.get("latest") or {}).get("release")) or "").strip()
    versions = manifest.get("versions") if isinstance(manifest.get("versions"), list) else []
    version_entry = next(
        (
            item for item in versions
            if isinstance(item, dict) and str(item.get("id") or "").strip() == latest_release
        ),
        None,
    )
    version_url = str((version_entry or {}).get("url") or "").strip()
    if not version_url:
        return False

    status, version_data, _headers, error = _request_json(
        "GET",
        version_url,
        timeout=TIMEOUT,
        stage="minecraft_version_json",
    )
    if status not in {200, 201} or not isinstance(version_data, dict):
        _debug_log("minecraft_default_skins", error or f"version json failed ({status or 'no status'})")
        return False

    client_url = str(
        (((version_data.get("downloads") or {}).get("client") or {}).get("url")) or ""
    ).strip()
    if not client_url:
        return False

    for candidate in _candidate_urls(client_url):
        temp_path = ""
        try:
            req = urllib.request.Request(candidate, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT * 4) as resp:
                payload = resp.read(MAX_MINECRAFT_CLIENT_JAR_BYTES + 1)
            if len(payload) > MAX_MINECRAFT_CLIENT_JAR_BYTES:
                continue
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                if _cache_default_skins_from_zip(zf):
                    return True
        except Exception as exc:
            _debug_log("minecraft_default_skins", f"client jar fetch failed: {exc}")
            try:
                if temp_path and os.path.isfile(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            continue
    return False


def _ensure_default_skin_cached(key: Any, variant: Any = "classic") -> str:
    clean_variant = _normalize_library_skin_variant(variant)
    path = _default_skin_cache_path(key, clean_variant)
    try:
        if path and os.path.isfile(path):
            with open(path, "rb") as f:
                if _is_valid_default_skin_payload(f.read(MAX_SKIN_UPLOAD_BYTES + 1)):
                    return path
    except Exception:
        pass

    for jar_path in _candidate_default_skin_jars():
        if _cache_default_skins_from_jar(jar_path):
            if path and os.path.isfile(path):
                return path

    if _download_latest_client_default_skins() and path and os.path.isfile(path):
        return path
    return ""


def _read_default_skin_bytes(skin_id: Any, variant: Any = "classic") -> bytes | None:
    definition = _default_skin_definition(skin_id)
    if not definition:
        return None
    path = _ensure_default_skin_cached(definition["key"], variant)
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            payload = f.read(MAX_SKIN_UPLOAD_BYTES + 1)
    except Exception:
        return None
    return payload if _is_valid_default_skin_payload(payload) else None


def resolve_microsoft_default_skin_path(identifier: str) -> str:
    definition = _default_skin_definition(identifier)
    if not definition:
        return ""
    variant = _default_skin_variant_from_identifier(identifier, definition.get("variant"))
    return _ensure_default_skin_cached(definition["key"], variant)


def _normalize_library_cape_id(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.lower() in {"", "none", "null", "__none__"}:
        return ""
    return _safe_texture_entry_id(raw)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _favorite_skin_ids(payload: dict[str, Any] | None) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    raw = payload.get("favorite_skin_ids")
    if isinstance(raw, str):
        values = raw.split(",")
    elif isinstance(raw, list):
        values = raw
    else:
        values = []
    out: set[str] = set()
    for value in values:
        clean = _safe_texture_entry_id(value)
        if not clean:
            continue
        out.add(_normalize_local_skin_id(clean) or clean)
    return out


def _normalize_texture_hash_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_values = value.split(",")
    elif isinstance(value, list):
        raw_values = value
    else:
        raw_values = []
    out: list[str] = []
    for raw in raw_values:
        clean = str(raw or "").strip().lower()
        if re.match(r"^[a-f0-9]{32,128}$", clean) and clean not in out:
            out.append(clean)
    return out


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(bytes(data or b"")).hexdigest()


def _read_local_skin_bytes(skin_id: str) -> bytes | None:
    path = _local_skin_path(skin_id)
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None


def _fetch_minecraft_texture_bytes(url: Any) -> bytes | None:
    normalized = _normalize_minecraft_texture_url(url)
    if not normalized:
        return None
    for candidate in _candidate_urls(normalized):
        try:
            req = urllib.request.Request(
                candidate,
                headers={"Accept": "image/*", "User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=TEXTURE_COMPARE_TIMEOUT) as resp:
                ctype = str(resp.headers.get("Content-Type") or "").lower()
                if ctype and "image/" not in ctype:
                    continue
                payload = resp.read(MAX_SKIN_UPLOAD_BYTES + 1)
            if payload.startswith(b"\x89PNG\r\n\x1a\n") and len(payload) <= MAX_SKIN_UPLOAD_BYTES:
                return payload
        except Exception:
            continue
    return None


def _update_skin_library_entry(
    payload: dict[str, Any] | None,
    skin_id: str,
    updates: dict[str, Any],
) -> bool:
    if not isinstance(payload, dict):
        return False
    clean_id = _normalize_local_skin_id(skin_id)
    if not clean_id:
        return False
    entries = []
    changed = False
    for entry in _skin_library_entries(payload):
        if entry.get("id") == clean_id:
            updated = {**entry, **updates}
            if updated != entry:
                changed = True
            entry = updated
        entries.append(entry)
    if changed:
        payload["skin_library"] = entries
    return changed


def _active_profile_skin_matches_bytes(profile: dict[str, Any], expected_sha256: str) -> bool:
    if not expected_sha256:
        return False
    skin_entry = next(iter(_active_texture_entries(profile.get("skins"))), None)
    active_url = _normalize_minecraft_texture_url((skin_entry or {}).get("url"))
    if not active_url:
        return False
    remote_bytes = _fetch_minecraft_texture_bytes(active_url)
    return bool(remote_bytes and _sha256_hex(remote_bytes) == expected_sha256)


def _remote_skin_entry_for_texture_hash(
    profile: dict[str, Any] | None,
    texture_hash: Any,
) -> dict[str, Any] | None:
    clean_hash = str(texture_hash or "").strip().lower()
    if not re.match(r"^[a-f0-9]{32,128}$", clean_hash):
        return None
    skins = profile.get("skins") if isinstance(profile, dict) and isinstance(profile.get("skins"), list) else []
    for entry in skins:
        if not isinstance(entry, dict):
            continue
        if _texture_hash_from_url(entry.get("url")) == clean_hash:
            return entry
    return None


def _remote_skin_entry_id(entry: dict[str, Any] | None) -> str:
    if not isinstance(entry, dict):
        return ""
    return _safe_texture_entry_id(entry.get("id") or entry.get("textureId") or entry.get("texture_id"))


def _rate_limited_error(error: Exception) -> bool:
    return MICROSOFT_TEXTURE_RATE_LIMIT_MESSAGE.lower() in str(error or "").lower()


def _profile_response_payload(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    profile_id = _normalize_uuid_hex(data.get("id"))
    name = str(data.get("name") or "").strip()
    if not profile_id or not name:
        return None
    skins = data.get("skins") if isinstance(data.get("skins"), list) else None
    capes = data.get("capes") if isinstance(data.get("capes"), list) else None
    if skins is None and capes is None:
        return None
    profile = dict(data)
    profile["id"] = profile_id
    profile["name"] = name
    if skins is not None:
        profile["skins"] = skins
    if capes is not None:
        profile["capes"] = capes
    return profile


def _clean_skin_library_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    entry_id = _normalize_local_skin_id(entry.get("id") or entry.get("skin_id"))
    if not entry_id:
        return None
    if not os.path.isfile(_ensure_local_skin_path(entry_id)):
        return None

    name = str(entry.get("name") or entry.get("display_name") or "").strip()[:80]
    file_name = os.path.basename(str(entry.get("file_name") or "skin.png").strip()) or "skin.png"
    if not file_name.lower().endswith(".png"):
        file_name = "skin.png"
    minecraft_texture_hash = _texture_hash_from_url(entry.get("minecraft_texture_url"))
    if not minecraft_texture_hash:
        raw_texture_hash = str(entry.get("minecraft_texture_hash") or "").strip().lower()
        minecraft_texture_hash = raw_texture_hash if re.match(r"^[a-f0-9]{32,128}$", raw_texture_hash) else ""
    file_sha256 = str(entry.get("file_sha256") or "").strip().lower()
    if not re.match(r"^[a-f0-9]{64}$", file_sha256):
        file_sha256 = ""
    return {
        "id": entry_id,
        "name": name or "Skin",
        "variant": _normalize_library_skin_variant(entry.get("variant") or entry.get("model")),
        "cape_id": _normalize_library_cape_id(entry.get("cape_id") or entry.get("capeId")),
        "favorite": _coerce_bool(entry.get("favorite")),
        "file_name": file_name,
        "minecraft_texture_hash": minecraft_texture_hash,
        "file_sha256": file_sha256,
        "dedupe_texture_hashes": _normalize_texture_hash_list(
            entry.get("dedupe_texture_hashes") or entry.get("replaced_minecraft_texture_hashes")
        ),
        "updated_at": int(entry.get("updated_at") or 0),
    }


def _skin_library_entries_from_disk(profile_id: str | None = None) -> list[dict[str, Any]]:
    base_dir = _local_skin_library_dir(profile_id)
    if not os.path.isdir(base_dir):
        return []

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        file_names = sorted(os.listdir(base_dir))
    except OSError:
        return []

    for file_name in file_names:
        if not str(file_name).lower().endswith(".png"):
            continue
        entry_id = _normalize_local_skin_id(os.path.splitext(file_name)[0])
        if not entry_id or entry_id in seen:
            continue
        path = _local_skin_path(entry_id, profile_id)
        if not path or not os.path.isfile(path):
            continue
        seen.add(entry_id)
        try:
            updated_at = int(os.path.getmtime(path))
        except OSError:
            updated_at = 0
        entries.append({
            "id": entry_id,
            "name": "Skin",
            "variant": "classic",
            "cape_id": "",
            "favorite": False,
            "file_name": f"{entry_id}.png",
            "minecraft_texture_hash": "",
            "file_sha256": "",
            "dedupe_texture_hashes": [],
            "updated_at": updated_at,
        })
    return entries


def _skin_library_entries(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw_entries = payload.get("skin_library") if isinstance(payload.get("skin_library"), list) else []
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_entry in raw_entries:
        entry = _clean_skin_library_entry(raw_entry)
        if not entry or entry["id"] in seen:
            continue
        seen.add(entry["id"])
        entries.append(entry)
    for disk_entry in _skin_library_entries_from_disk():
        if disk_entry["id"] in seen:
            continue
        seen.add(disk_entry["id"])
        entries.append(disk_entry)
    entries.sort(key=lambda item: (bool(item.get("favorite")), int(item.get("updated_at") or 0)), reverse=True)
    return entries


def _default_skin_setting(payload: dict[str, Any] | None, skin_id: Any) -> dict[str, str]:
    definition = _default_skin_definition(skin_id)
    if not definition:
        return {"variant": "classic", "cape_id": ""}
    raw_settings = (
        payload.get("default_skin_settings")
        if isinstance(payload, dict) and isinstance(payload.get("default_skin_settings"), dict)
        else {}
    )
    raw = raw_settings.get(definition["id"]) if isinstance(raw_settings.get(definition["id"]), dict) else {}
    return {
        "variant": _normalize_library_skin_variant(raw.get("variant") or definition.get("variant")),
        "cape_id": _normalize_library_cape_id(raw.get("cape_id") or raw.get("capeId")),
    }


def _set_default_skin_setting(
    payload: dict[str, Any],
    skin_id: Any,
    *,
    variant: Any = None,
    cape_id: Any = None,
) -> dict[str, str]:
    definition = _default_skin_definition(skin_id)
    if not definition:
        raise MicrosoftAuthError("Choose a Minecraft default skin.")
    raw_settings = payload.get("default_skin_settings") if isinstance(payload.get("default_skin_settings"), dict) else {}
    current = _default_skin_setting(payload, definition["id"])
    next_setting = {
        "variant": _normalize_library_skin_variant(variant if variant is not None else current.get("variant")),
        "cape_id": _normalize_library_cape_id(cape_id) if cape_id is not None else str(current.get("cape_id") or ""),
    }
    raw_settings[definition["id"]] = next_setting
    payload["default_skin_settings"] = raw_settings
    return next_setting


def _set_default_skin_remote_id(
    payload: dict[str, Any],
    skin_id: Any,
    variant: Any,
    remote_id: Any,
    texture_hash: Any = "",
) -> None:
    definition = _default_skin_definition(skin_id)
    clean_remote_id = _safe_texture_entry_id(remote_id)
    if not definition or not clean_remote_id:
        return
    clean_variant = _normalize_library_skin_variant(variant)
    raw = payload.get("default_skin_remote_ids") if isinstance(payload.get("default_skin_remote_ids"), dict) else {}
    skin_map = raw.get(definition["id"]) if isinstance(raw.get(definition["id"]), dict) else {}
    remote_entry = {"id": clean_remote_id}
    clean_hash = str(texture_hash or "").strip().lower()
    if re.match(r"^[a-f0-9]{32,128}$", clean_hash):
        remote_entry["texture_hash"] = clean_hash
    skin_map[clean_variant] = remote_entry
    raw[definition["id"]] = skin_map
    payload["default_skin_remote_ids"] = raw


def _default_skin_remote_id(payload: dict[str, Any] | None, skin_id: Any, variant: Any) -> str:
    definition = _default_skin_definition(skin_id)
    if not definition or not isinstance(payload, dict):
        return ""
    raw = payload.get("default_skin_remote_ids") if isinstance(payload.get("default_skin_remote_ids"), dict) else {}
    skin_map = raw.get(definition["id"]) if isinstance(raw.get(definition["id"]), dict) else {}
    entry = skin_map.get(_normalize_library_skin_variant(variant))
    if isinstance(entry, dict):
        return _safe_texture_entry_id(entry.get("id"))
    return _safe_texture_entry_id(entry)


def _default_remote_skin_ids(payload: dict[str, Any] | None) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    raw = payload.get("default_skin_remote_ids") if isinstance(payload.get("default_skin_remote_ids"), dict) else {}
    out: set[str] = set()
    for skin_map in raw.values():
        if not isinstance(skin_map, dict):
            continue
        for entry in skin_map.values():
            clean_id = _safe_texture_entry_id(entry.get("id") if isinstance(entry, dict) else entry)
            if clean_id:
                out.add(clean_id)
    return out


def _default_skin_entries(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    active_id = _normalize_default_skin_id((payload or {}).get("active_default_skin_id")) if isinstance(payload, dict) else ""
    entries: list[dict[str, Any]] = []
    for definition in MINECRAFT_DEFAULT_SKIN_NAMES:
        base_id = _default_skin_id(definition["key"])
        setting = _default_skin_setting(payload, base_id)
        variant = setting.get("variant") or _normalize_library_skin_variant(definition.get("variant"))
        entries.append({
            "id": base_id,
            "texture_id": _default_skin_texture_identifier(definition["key"], variant),
            "texture_ids": {
                "classic": _default_skin_texture_identifier(definition["key"], "classic"),
                "slim": _default_skin_texture_identifier(definition["key"], "slim"),
            },
            "texture_hash": "",
            "url": "",
            "name": str(definition.get("name") or definition["key"].title()),
            "state": "",
            "active": base_id == active_id,
            "variant": variant,
            "cape_id": setting.get("cape_id") or "",
            "favorite": False,
            "default": True,
            "builtin": True,
            "source": "Minecraft",
        })
    return entries


def _active_default_skin_entry(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    active_id = _normalize_default_skin_id(payload.get("active_default_skin_id"))
    if not active_id:
        return None
    return next((entry for entry in _default_skin_entries(payload) if entry.get("id") == active_id), None)


def _sync_skin_library_payload(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False

    changed = False
    entries = _skin_library_entries(payload)
    if payload.get("skin_library") != entries:
        payload["skin_library"] = entries
        changed = True

    active_local_skin_id = _normalize_local_skin_id(payload.get("active_local_skin_id"))
    if active_local_skin_id and not any(entry.get("id") == active_local_skin_id for entry in entries):
        active_local_skin_id = ""
    if active_local_skin_id:
        if payload.get("active_local_skin_id") != active_local_skin_id:
            payload["active_local_skin_id"] = active_local_skin_id
            changed = True
    elif payload.pop("active_local_skin_id", None) is not None:
        changed = True
        payload.pop("active_local_skin_selected_at", None)
    elif payload.pop("active_local_skin_selected_at", None) is not None:
        changed = True

    favorite_ids = sorted(_favorite_skin_ids(payload))
    raw_favorites = payload.get("favorite_skin_ids")
    if favorite_ids:
        if raw_favorites != favorite_ids:
            payload["favorite_skin_ids"] = favorite_ids
            changed = True
    elif raw_favorites:
        payload.pop("favorite_skin_ids", None)
        changed = True

    default_settings = {}
    raw_default_settings = payload.get("default_skin_settings") if isinstance(payload.get("default_skin_settings"), dict) else {}
    for definition in MINECRAFT_DEFAULT_SKIN_NAMES:
        base_id = _default_skin_id(definition["key"])
        raw = raw_default_settings.get(base_id) if isinstance(raw_default_settings.get(base_id), dict) else {}
        setting = _default_skin_setting(payload, base_id)
        default_value = {
            "variant": _normalize_library_skin_variant(definition.get("variant")),
            "cape_id": "",
        }
        if setting != default_value or raw:
            default_settings[base_id] = setting
    if default_settings:
        if payload.get("default_skin_settings") != default_settings:
            payload["default_skin_settings"] = default_settings
            changed = True
    elif payload.pop("default_skin_settings", None) is not None:
        changed = True

    active_default_skin_id = _normalize_default_skin_id(payload.get("active_default_skin_id"))
    if active_default_skin_id:
        if payload.get("active_default_skin_id") != active_default_skin_id:
            payload["active_default_skin_id"] = active_default_skin_id
            changed = True
    elif payload.pop("active_default_skin_id", None) is not None:
        changed = True
        payload.pop("active_default_skin_selected_at", None)
    elif payload.pop("active_default_skin_selected_at", None) is not None:
        changed = True

    return changed


def _find_skin_library_entry(payload: dict[str, Any] | None, skin_id: str) -> dict[str, Any] | None:
    clean_id = _normalize_local_skin_id(skin_id)
    if not clean_id:
        return None
    return next((entry for entry in _skin_library_entries(payload) if entry.get("id") == clean_id), None)


def _active_local_skin_entry(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    active_id = _normalize_local_skin_id(payload.get("active_local_skin_id"))
    if not active_id:
        return None
    return _find_skin_library_entry(payload, active_id)


def _upsert_skin_library_entry(
    payload: dict[str, Any],
    *,
    skin_id: str = "",
    skin_bytes: bytes | None = None,
    variant: str = "classic",
    file_name: str = "skin.png",
    display_name: str = "",
    minecraft_texture_hash: str | None = "",
    cape_id: Any = None,
    favorite: Any = None,
    set_active: bool = True,
) -> dict[str, Any]:
    existing = _find_skin_library_entry(payload, skin_id)
    if not existing and skin_bytes is None:
        raise MicrosoftAuthError("Choose a skin PNG before saving.")
    entry_id = existing.get("id") if existing else _new_local_skin_id()
    safe_file_name = os.path.basename(str(file_name or "skin.png").strip()) or "skin.png"
    if not safe_file_name.lower().endswith(".png"):
        safe_file_name = "skin.png"

    path = _local_skin_path(entry_id)
    if not path:
        raise MicrosoftAuthError("Could not save the skin library entry.")
    if skin_bytes is not None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(bytes(skin_bytes or b""))
    else:
        path = _ensure_local_skin_path(entry_id)
    if not os.path.isfile(path):
        raise MicrosoftAuthError("Could not read the saved skin from the launcher library.")

    existing_dedupe_hashes = list((existing or {}).get("dedupe_texture_hashes") or [])
    if minecraft_texture_hash is None:
        previous_hash = str((existing or {}).get("minecraft_texture_hash") or "").strip().lower()
        if re.match(r"^[a-f0-9]{32,128}$", previous_hash) and previous_hash not in existing_dedupe_hashes:
            existing_dedupe_hashes.append(previous_hash)
        clean_minecraft_texture_hash = ""
    else:
        clean_minecraft_texture_hash = str(minecraft_texture_hash or (existing or {}).get("minecraft_texture_hash") or "").strip().lower()
    if not re.match(r"^[a-f0-9]{32,128}$", clean_minecraft_texture_hash):
        clean_minecraft_texture_hash = ""
    dedupe_texture_hashes = [value for value in existing_dedupe_hashes if value != clean_minecraft_texture_hash]
    clean_cape_id = (
        _normalize_library_cape_id(cape_id)
        if cape_id is not None
        else str((existing or {}).get("cape_id") or "")
    )
    saved_skin_bytes = _read_local_skin_bytes(entry_id)
    file_sha256 = _sha256_hex(saved_skin_bytes) if saved_skin_bytes else str((existing or {}).get("file_sha256") or "")

    entry = {
        "id": entry_id,
        "name": (str(display_name or "").strip() or (existing or {}).get("name") or os.path.splitext(safe_file_name)[0] or "Skin")[:80],
        "variant": _normalize_library_skin_variant(variant or (existing or {}).get("variant")),
        "cape_id": clean_cape_id,
        "favorite": _coerce_bool(favorite) if favorite is not None else _coerce_bool((existing or {}).get("favorite")),
        "file_name": safe_file_name,
        "minecraft_texture_hash": clean_minecraft_texture_hash,
        "file_sha256": file_sha256,
        "dedupe_texture_hashes": dedupe_texture_hashes,
        "updated_at": int(time.time()),
    }

    entries = [item for item in _skin_library_entries(payload) if item.get("id") != entry_id]
    entries.insert(0, entry)
    payload["skin_library"] = entries
    return entry


def _clear_active_local_skin(payload: dict[str, Any] | None) -> None:
    if isinstance(payload, dict):
        payload.pop("active_local_skin_id", None)
        payload.pop("active_local_skin_selected_at", None)


def _clear_active_default_skin(payload: dict[str, Any] | None) -> None:
    if isinstance(payload, dict):
        payload.pop("active_default_skin_id", None)
        payload.pop("active_default_skin_selected_at", None)


def _set_active_local_skin(
    payload: dict[str, Any],
    skin_id: str,
    *,
    cape_id: Any = None,
) -> dict[str, Any]:
    clean_id = _normalize_local_skin_id(skin_id)
    entry = _find_skin_library_entry(payload, clean_id)
    if not entry:
        raise MicrosoftAuthError("Choose a saved launcher library skin.")
    if cape_id is not None:
        _update_skin_library_entry(
            payload,
            clean_id,
            {"cape_id": _normalize_library_cape_id(cape_id)},
        )
        entry = _find_skin_library_entry(payload, clean_id) or entry
    _clear_active_default_skin(payload)
    payload["active_local_skin_id"] = clean_id
    payload["active_local_skin_selected_at"] = int(time.time())
    return entry


def _set_active_default_skin(
    payload: dict[str, Any],
    skin_id: str,
    *,
    variant: Any = None,
    cape_id: Any = None,
) -> dict[str, Any]:
    definition = _default_skin_definition(skin_id)
    if not definition:
        raise MicrosoftAuthError("Choose a Minecraft default skin.")
    setting = _set_default_skin_setting(payload, definition["id"], variant=variant, cape_id=cape_id)
    _clear_active_local_skin(payload)
    payload["active_default_skin_id"] = definition["id"]
    payload["active_default_skin_selected_at"] = int(time.time())
    return next(
        (
            entry for entry in _default_skin_entries(payload)
            if entry.get("id") == definition["id"]
        ),
        {
            "id": definition["id"],
            "name": definition["name"],
            "variant": setting.get("variant") or definition.get("variant") or "classic",
            "cape_id": setting.get("cape_id") or "",
            "default": True,
        },
    )


def _texture_aliases(payload: dict[str, Any] | None, kind: str) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    aliases = payload.get("texture_aliases") if isinstance(payload.get("texture_aliases"), dict) else {}
    kind_aliases = aliases.get(kind) if isinstance(aliases.get(kind), dict) else {}
    result: dict[str, str] = {}
    for key, value in kind_aliases.items():
        clean_key = str(key or "").strip().lower()
        clean_value = str(value or "").strip()
        if clean_key and clean_value:
            result[clean_key] = clean_value[:80]
    return result


def _remember_texture_alias(
    payload: dict[str, Any],
    kind: str,
    entry: dict[str, Any] | None,
    display_name: str,
) -> None:
    clean_name = str(display_name or "").strip()[:80]
    if not clean_name or not isinstance(entry, dict):
        return

    keys = []
    entry_id = _safe_texture_entry_id(entry.get("id") or entry.get("textureId") or entry.get("texture_id"))
    texture_hash = _texture_hash_from_url(entry.get("url"))
    for key in (entry_id, texture_hash):
        if key and key.lower() not in keys:
            keys.append(key.lower())
    if not keys:
        return

    aliases = payload.get("texture_aliases") if isinstance(payload.get("texture_aliases"), dict) else {}
    kind_aliases = aliases.get(kind) if isinstance(aliases.get(kind), dict) else {}
    for key in keys:
        kind_aliases[key] = clean_name
    aliases[kind] = kind_aliases
    payload["texture_aliases"] = aliases


def _normalize_texture_entry(
    entry: dict[str, Any],
    *,
    kind: str,
    index: int,
    aliases: dict[str, str],
) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None

    entry_id = _safe_texture_entry_id(
        entry.get("id") or entry.get("textureId") or entry.get("texture_id")
    )
    url = _normalize_minecraft_texture_url(entry.get("url")) or ""
    texture_hash = _texture_hash_from_url(url)
    alias_keys = [key.lower() for key in (entry_id, texture_hash) if key]
    local_alias = next((aliases.get(key) for key in alias_keys if aliases.get(key)), "")
    api_alias = str(entry.get("alias") or entry.get("name") or entry.get("displayName") or "").strip()
    state = str(entry.get("state") or "").strip().upper()
    active = state == "ACTIVE" or bool(entry.get("active"))
    fallback_name = "Skin" if kind == "skins" else "Cape"
    display_name = api_alias or local_alias or f"{fallback_name} {index + 1}"

    if not entry_id and not texture_hash and not url:
        return None

    normalized = {
        "id": entry_id or texture_hash,
        "texture_hash": texture_hash,
        "url": url,
        "name": display_name,
        "state": state,
        "active": active,
    }
    if kind == "skins":
        normalized["variant"] = _texture_model(entry)
    return normalized


def _normalize_texture_profile(
    profile: dict[str, Any] | None,
    account: dict[str, Any] | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile_data = profile if isinstance(profile, dict) else {}
    account_data = account if isinstance(account, dict) else {}
    skins_raw = profile_data.get("skins") if isinstance(profile_data.get("skins"), list) else []
    capes_raw = profile_data.get("capes") if isinstance(profile_data.get("capes"), list) else []
    skin_aliases = _texture_aliases(payload, "skins")
    cape_aliases = _texture_aliases(payload, "capes")
    favorite_skin_ids = _favorite_skin_ids(payload)

    skins = [
        item
        for item in (
            _normalize_texture_entry(entry, kind="skins", index=index, aliases=skin_aliases)
            for index, entry in enumerate(skins_raw)
        )
        if item
    ]
    capes = [
        item
        for item in (
            _normalize_texture_entry(entry, kind="capes", index=index, aliases=cape_aliases)
            for index, entry in enumerate(capes_raw)
        )
        if item
    ]
    for entry in skins:
        entry_keys = {
            str(entry.get("id") or "").strip(),
            str(entry.get("texture_hash") or "").strip(),
        }
        entry["favorite"] = any(key and key in favorite_skin_ids for key in entry_keys)

    active_local_skin = _active_local_skin_entry(payload)
    active_local_skin_id = str((active_local_skin or {}).get("id") or "")
    remote_active_skin = next((entry for entry in skins if entry.get("active")), None)
    remote_active_skin_hash = str((remote_active_skin or {}).get("texture_hash") or "").strip().lower()
    local_skins = []
    local_texture_hashes: set[str] = set()
    library_entries = _skin_library_entries(payload)
    for entry in library_entries:
        local_texture_hash = str(entry.get("minecraft_texture_hash") or "").strip().lower()
        if local_texture_hash:
            local_texture_hashes.add(local_texture_hash)
        for dedupe_hash in entry.get("dedupe_texture_hashes") or []:
            clean_dedupe_hash = str(dedupe_hash or "").strip().lower()
            if clean_dedupe_hash:
                local_texture_hashes.add(clean_dedupe_hash)
        local_active = bool(
            entry.get("id") == active_local_skin_id
            or (not active_local_skin_id and local_texture_hash and local_texture_hash == remote_active_skin_hash)
        )
        local_skins.append({
            "id": entry["id"],
            "texture_hash": local_texture_hash,
            "url": "",
            "name": entry.get("name") or "Skin",
            "state": "",
            "active": local_active,
            "variant": entry.get("variant") or "classic",
            "cape_id": entry.get("cape_id") or "",
            "favorite": _coerce_bool(entry.get("favorite")) or entry["id"] in favorite_skin_ids,
            "local": True,
            "source": "Histolauncher",
            "file_name": entry.get("file_name") or "skin.png",
            "updated_at": int(entry.get("updated_at") or 0),
        })
    default_skins = _default_skin_entries(payload)
    default_remote_ids = _default_remote_skin_ids(payload)
    if default_remote_ids:
        skins = [
            entry for entry in skins
            if str(entry.get("id") or "").strip() not in default_remote_ids
        ]
    if local_texture_hashes:
        skins = [
            entry for entry in skins
            if not str(entry.get("texture_hash") or "").strip().lower()
            or str(entry.get("texture_hash") or "").strip().lower() not in local_texture_hashes
        ]
    if local_skins or default_skins:
        skins = local_skins + default_skins + skins
    skins.sort(key=lambda item: (0 if item.get("active") else 1, 0 if item.get("favorite") else 1))

    active_skin = (
        next((entry for entry in local_skins if entry.get("active")), None)
        or next((entry for entry in default_skins if entry.get("active")), None)
        or remote_active_skin
        or next((entry for entry in skins if not entry.get("local")), skins[0] if skins else None)
    )
    active_skin_has_own_cape = bool((active_skin or {}).get("local") or (active_skin or {}).get("default"))
    active_cape_id = str((active_skin or {}).get("cape_id") or "") if active_skin_has_own_cape else ""
    active_cape = (
        next((entry for entry in capes if str(entry.get("id") or "") == active_cape_id), None)
        if active_cape_id
        else None
    ) or (None if active_skin_has_own_cape else next((entry for entry in capes if entry.get("active")), None))
    return {
        "account_type": "Microsoft",
        "username": str(profile_data.get("name") or account_data.get("username") or ""),
        "uuid": _normalize_uuid_hex(profile_data.get("id") or account_data.get("uuid")),
        "skins": skins,
        "capes": capes,
        "active_skin": active_skin,
        "active_cape": active_cape,
    }


def _require_microsoft_texture_account() -> dict[str, Any]:
    if not microsoft_account_enabled():
        raise MicrosoftAuthError("Microsoft account not enabled.")
    account = refresh_microsoft_account(force_profile=False)
    minecraft_token = str(account.get("access_token") or "").strip()
    if not minecraft_token:
        raise MicrosoftAuthError("Microsoft account token is missing. Please sign in again.")
    return account


def _refresh_microsoft_texture_profile(
    account: dict[str, Any],
    *,
    alias_kind: str = "",
    display_name: str = "",
) -> dict[str, Any]:
    minecraft_token = str(account.get("access_token") or "").strip()
    profile = _fetch_profile(minecraft_token)
    payload = _load_token_payload()
    if not payload:
        raise MicrosoftAuthError("Stored Microsoft account data is missing. Please sign in again.")
    payload["profile"] = profile
    _sync_skin_library_payload(payload)

    if alias_kind and display_name:
        entries = profile.get(alias_kind) if isinstance(profile.get(alias_kind), list) else []
        active_entry = next(iter(_active_texture_entries(entries)), None)
        _remember_texture_alias(payload, alias_kind, active_entry, display_name)

    _save_token_payload(payload)
    updated_account = api_payload_from_profile(
        profile,
        access_token=minecraft_token,
        xuid=str(account.get("xuid") or ""),
        client_id=str(account.get("client_id") or MICROSOFT_CLIENT_ID),
    )
    if updated_account:
        _save_account_identity(updated_account)
    return _normalize_texture_profile(profile, updated_account or account, payload)


def get_microsoft_texture_profile(
    *,
    force_profile: bool = True,
    return_cache_state: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], bool]:
    payload = _load_token_payload()
    try:
        account = refresh_microsoft_account(force_profile=force_profile)
    except Exception:
        if payload:
            cached = get_cached_microsoft_texture_profile()
            if cached:
                if return_cache_state:
                    return cached, True
                return cached
        raise
    payload = _load_token_payload()
    if _sync_skin_library_payload(payload):
        _save_token_payload(payload)
    profile = payload.get("profile") if isinstance(payload, dict) and isinstance(payload.get("profile"), dict) else {}
    texture_profile = _normalize_texture_profile(profile, account, payload)
    if return_cache_state:
        return texture_profile, False
    return texture_profile


def get_cached_microsoft_texture_profile() -> dict[str, Any] | None:
    payload = _load_token_payload()
    if not isinstance(payload, dict):
        return None

    account = _account_from_payload(payload)
    if not account:
        cached_identity = load_cached_account_identity()
        if cached_identity:
            account = api_payload_from_profile(cached_identity)
    if not account:
        return None

    if _sync_skin_library_payload(payload):
        _save_token_payload(payload)
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    return _normalize_texture_profile(profile, account, payload)


def _validate_local_skin_bytes(skin_bytes: bytes | None) -> bytes | None:
    if skin_bytes is None:
        return None
    payload = bytes(skin_bytes or b"")
    if not payload:
        raise MicrosoftAuthError("Choose a skin PNG before saving.")
    if len(payload) > MAX_SKIN_UPLOAD_BYTES:
        raise MicrosoftAuthError("Skin file is too large. Choose a PNG under 2 MB.")
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise MicrosoftAuthError("Skin file must be a PNG image.")
    if not _is_allowed_skin_dimensions(payload):
        raise MicrosoftAuthError("Skin resolution must be exactly 64x64 or 64x32.")
    return payload


def _texture_profile_from_payload(payload: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    return _normalize_texture_profile(
        payload.get("profile") if isinstance(payload.get("profile"), dict) else {},
        _account_from_payload(payload) or account,
        payload,
    )


def save_microsoft_local_skin(
    skin_bytes: bytes | None = None,
    *,
    variant: str = "classic",
    file_name: str = "skin.png",
    display_name: str = "",
    library_id: str = "",
    cape_id: Any = None,
) -> dict[str, Any]:
    payload_data = _load_token_payload()
    if not payload_data:
        raise MicrosoftAuthError("Stored Microsoft account data is missing. Please sign in again.")

    clean_default_id = _normalize_default_skin_id(library_id)
    if clean_default_id:
        if skin_bytes is not None:
            raise MicrosoftAuthError("Minecraft default skins cannot use a custom skin file.")
        account = _account_from_payload(payload_data)
        if not account:
            cached_identity = load_cached_account_identity()
            account = api_payload_from_profile(cached_identity) if cached_identity else None
        if not account:
            raise MicrosoftAuthError("Stored Microsoft account data is incomplete. Please sign in again.")

        _set_default_skin_setting(payload_data, clean_default_id, variant=variant, cape_id=cape_id)
        active_default_id = _normalize_default_skin_id(payload_data.get("active_default_skin_id"))
        if active_default_id == clean_default_id:
            _set_active_default_skin(payload_data, clean_default_id, variant=variant, cape_id=cape_id)
        _save_token_payload(payload_data)

        if active_default_id == clean_default_id:
            try:
                return activate_microsoft_skin(clean_default_id, variant=variant, cape_id=cape_id)
            except Exception:
                return _texture_profile_from_payload(payload_data, account)
        return _texture_profile_from_payload(payload_data, account)

    account = _require_microsoft_texture_account()
    clean_library_id = _normalize_local_skin_id(library_id)
    existing = _find_skin_library_entry(payload_data, clean_library_id)
    clean_skin_bytes = _validate_local_skin_bytes(skin_bytes)

    _upsert_skin_library_entry(
        payload_data,
        skin_id=clean_library_id if existing else "",
        skin_bytes=clean_skin_bytes,
        variant=variant,
        file_name=file_name,
        display_name=display_name,
        minecraft_texture_hash=None if clean_skin_bytes is not None else "",
        cape_id=cape_id,
        set_active=False,
    )
    _clear_active_local_skin(payload_data)
    _clear_active_default_skin(payload_data)
    _save_token_payload(payload_data)
    return _texture_profile_from_payload(payload_data, account)


def delete_microsoft_local_skin(skin_id: str) -> dict[str, Any]:
    account = _require_microsoft_texture_account()
    payload_data = _load_token_payload()
    if not payload_data:
        raise MicrosoftAuthError("Stored Microsoft account data is missing. Please sign in again.")

    clean_id = _normalize_local_skin_id(skin_id)
    entry = _find_skin_library_entry(payload_data, clean_id)
    if not entry:
        raise MicrosoftAuthError("Only launcher library skins can be deleted.")

    _remove_local_skin_paths(clean_id)

    payload_data["skin_library"] = [item for item in _skin_library_entries(payload_data) if item.get("id") != clean_id]
    _clear_active_local_skin(payload_data)
    _save_token_payload(payload_data)
    return _texture_profile_from_payload(payload_data, account)


def set_microsoft_skin_favorite(skin_id: str, favorite: Any = True) -> dict[str, Any]:
    account = _require_microsoft_texture_account()
    payload_data = _load_token_payload()
    if not payload_data:
        raise MicrosoftAuthError("Stored Microsoft account data is missing. Please sign in again.")

    clean_id = _normalize_local_skin_id(skin_id) or _safe_texture_entry_id(skin_id)
    if not clean_id:
        raise MicrosoftAuthError("Choose a skin from your Microsoft skin library.")
    if _normalize_default_skin_id(clean_id):
        raise MicrosoftAuthError("Minecraft default skins cannot be favorited.")
    enabled = _coerce_bool(favorite)

    changed_local = False
    entries = []
    for entry in _skin_library_entries(payload_data):
        if entry.get("id") == clean_id:
            entry = {**entry, "favorite": enabled}
            changed_local = True
        entries.append(entry)
    payload_data["skin_library"] = entries

    favorite_ids = _favorite_skin_ids(payload_data)
    if changed_local:
        favorite_ids.discard(clean_id)
    elif enabled:
        favorite_ids.add(clean_id)
    else:
        favorite_ids.discard(clean_id)
    payload_data["favorite_skin_ids"] = sorted(favorite_ids)

    _save_token_payload(payload_data)
    return _texture_profile_from_payload(payload_data, account)


def _minecraft_texture_action_failed(data: Any, status: int, fallback: str) -> str:
    if status == 429:
        return MICROSOFT_TEXTURE_RATE_LIMIT_MESSAGE
    if status in {401, 403}:
        return "Minecraft Services rejected the stored Microsoft session. Please sign in again."
    return _extract_error(data, fallback)


def _check_success(status: int, data: Any, error: str | None, fallback: str) -> None:
    if status in {200, 201, 204}:
        return
    if status == 429 or "too many" in str(error or "").lower() or "429" in str(error or ""):
        raise MicrosoftAuthError(MICROSOFT_TEXTURE_RATE_LIMIT_MESSAGE)
    if error:
        raise MicrosoftAuthError(error)
    raise MicrosoftAuthError(_minecraft_texture_action_failed(data, status, fallback))


def upload_microsoft_skin(
    skin_bytes: bytes,
    *,
    variant: str = "classic",
    file_name: str = "skin.png",
    display_name: str = "",
    library_id: str = "",
    cape_id: Any = None,
) -> dict[str, Any]:
    payload = bytes(skin_bytes or b"")
    if not payload:
        raise MicrosoftAuthError("Choose a skin PNG before saving.")
    if len(payload) > MAX_SKIN_UPLOAD_BYTES:
        raise MicrosoftAuthError("Skin file is too large. Choose a PNG under 2 MB.")
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise MicrosoftAuthError("Skin file must be a PNG image.")
    if not _is_allowed_skin_dimensions(payload):
        raise MicrosoftAuthError("Skin resolution must be exactly 64x64 or 64x32.")

    model = str(variant or "classic").strip().lower()
    if model in {"wide", "default"}:
        model = "classic"
    if model not in {"classic", "slim"}:
        model = "classic"

    safe_file_name = os.path.basename(str(file_name or "skin.png").strip()) or "skin.png"
    if not safe_file_name.lower().endswith(".png"):
        safe_file_name = "skin.png"

    account = _require_microsoft_texture_account()
    minecraft_token = str(account.get("access_token") or "").strip()
    status, data, _headers, error = _request_multipart_json(
        "POST",
        MINECRAFT_PROFILE_SKINS_URL,
        fields={"variant": model},
        files={"file": (safe_file_name, "image/png", payload)},
        bearer_token=minecraft_token,
        timeout=TIMEOUT,
        stage="minecraft_skin_upload",
    )
    _check_success(status, data, error, f"Minecraft skin upload failed ({status or 'no status'}).")

    payload_data = _load_token_payload()
    if not payload_data:
        raise MicrosoftAuthError("Stored Microsoft account data is missing. Please sign in again.")

    confirmed_profile = _profile_response_payload(data)
    if confirmed_profile:
        payload_data["profile"] = confirmed_profile
    else:
        confirmed_profile = payload_data.get("profile") if isinstance(payload_data.get("profile"), dict) else {}

    active_entry = next(iter(_active_texture_entries(confirmed_profile.get("skins"))), None)
    active_texture_hash = _texture_hash_from_url((active_entry or {}).get("url"))

    _sync_skin_library_payload(payload_data)
    if active_entry and display_name:
        _remember_texture_alias(payload_data, "skins", active_entry, display_name)
    _upsert_skin_library_entry(
        payload_data,
        skin_id=library_id,
        skin_bytes=payload,
        variant=model,
        file_name=safe_file_name,
        display_name=display_name,
        minecraft_texture_hash=active_texture_hash if active_texture_hash else None,
        cape_id=cape_id,
    )
    _clear_active_local_skin(payload_data)
    _clear_active_default_skin(payload_data)
    _save_token_payload(payload_data)

    updated_account = api_payload_from_profile(
        confirmed_profile,
        access_token=minecraft_token,
        xuid=str(account.get("xuid") or ""),
        client_id=str(account.get("client_id") or MICROSOFT_CLIENT_ID),
    )
    if updated_account:
        _save_account_identity(updated_account)

    if cape_id is not None:
        return _apply_microsoft_cape_selection(
            updated_account or account,
            cape_id,
            preloaded_profile=confirmed_profile,
        )

    return _normalize_texture_profile(
        payload_data.get("profile") if isinstance(payload_data.get("profile"), dict) else {},
        updated_account or _account_from_payload(payload_data) or account,
        payload_data,
    )


def _commit_profile_response(
    account: dict[str, Any],
    data: Any,
    *,
    fallback_to_cached: bool = True,
) -> dict[str, Any] | None:
    """Persist a profile JSON returned from a skin/cape mutation response.

    Returns a normalized texture profile or ``None`` when the response did not
    include a usable profile body.
    """
    profile = _profile_response_payload(data)
    payload_data = _load_token_payload()
    if not payload_data:
        if not fallback_to_cached:
            return None
        raise MicrosoftAuthError(
            "Stored Microsoft account data is missing. Please sign in again."
        )
    if profile:
        payload_data["profile"] = profile
    elif not fallback_to_cached:
        return None

    _sync_skin_library_payload(payload_data)
    _clear_active_local_skin(payload_data)
    _clear_active_default_skin(payload_data)
    _save_token_payload(payload_data)

    minecraft_token = str(account.get("access_token") or "").strip()
    updated_account = api_payload_from_profile(
        profile or payload_data.get("profile") if isinstance(payload_data.get("profile"), dict) else None,
        access_token=minecraft_token,
        xuid=str(account.get("xuid") or ""),
        client_id=str(account.get("client_id") or MICROSOFT_CLIENT_ID),
    ) if profile else None
    if updated_account:
        _save_account_identity(updated_account)

    return _normalize_texture_profile(
        payload_data.get("profile") if isinstance(payload_data.get("profile"), dict) else {},
        updated_account or _account_from_payload(payload_data) or account,
        payload_data,
    )


def _select_microsoft_skin_by_id(
    account: dict[str, Any],
    skin_id: str,
    *,
    allow_missing: bool = False,
) -> dict[str, Any] | None:
    clean_id = _safe_texture_entry_id(skin_id)
    if not clean_id:
        return None

    minecraft_token = str(account.get("access_token") or "").strip()
    attempts = [
        (f"{MINECRAFT_PROFILE_SKINS_URL}/{urllib.parse.quote(clean_id, safe='')}", None),
        (f"{MINECRAFT_PROFILE_SKINS_URL}/active", {"skinId": clean_id}),
    ]
    last_data: Any = None
    last_status = 0
    last_error: str | None = None
    for url, body in attempts:
        status, data, _headers, error = _request_json(
            "PUT",
            url,
            body=body,
            bearer_token=minecraft_token,
            timeout=TIMEOUT,
            stage="minecraft_skin_select",
        )
        if status in {200, 201, 204}:
            return _commit_profile_response(account, data)
        last_status = status
        last_data = data
        last_error = error
        if status in {401, 403}:
            break

    if allow_missing and last_status in {0, 400, 404}:
        return None
    _check_success(last_status, last_data, last_error, f"Minecraft skin selection failed ({last_status or 'no status'}).")
    return None


def _activate_microsoft_default_skin(
    skin_id: str,
    *,
    variant: str = "",
    cape_id: Any = None,
) -> dict[str, Any]:
    payload_data = _load_token_payload()
    if not isinstance(payload_data, dict):
        raise MicrosoftAuthError("Stored Microsoft account data is missing. Please sign in again.")

    definition = _default_skin_definition(skin_id)
    if not definition:
        raise MicrosoftAuthError("Choose a Minecraft default skin.")

    setting = _default_skin_setting(payload_data, definition["id"])
    model = _normalize_library_skin_variant(variant or setting.get("variant") or definition.get("variant"))
    effective_cape_id = cape_id if cape_id is not None else setting.get("cape_id")

    account = _account_from_payload(payload_data)

    def _activate_cached_default_skin() -> dict[str, Any]:
        cached_account = account or _account_from_payload(payload_data)
        if not cached_account:
            cached_identity = load_cached_account_identity()
            cached_account = api_payload_from_profile(cached_identity) if cached_identity else None
        if not cached_account:
            raise MicrosoftAuthError("Stored Microsoft account data is incomplete. Please sign in again.")
        _set_active_default_skin(
            payload_data,
            definition["id"],
            variant=model,
            cape_id=effective_cape_id,
        )
        _save_token_payload(payload_data)
        return _texture_profile_from_payload(payload_data, cached_account)

    try:
        account = _require_microsoft_texture_account()
    except Exception:
        return _activate_cached_default_skin()

    remote_skin_id = _default_skin_remote_id(payload_data, definition["id"], model)
    if remote_skin_id:
        try:
            texture_profile = _select_microsoft_skin_by_id(account, remote_skin_id, allow_missing=True)
        except Exception:
            texture_profile = None
        if texture_profile:
            payload_data = _load_token_payload() or payload_data
            _set_active_default_skin(
                payload_data,
                definition["id"],
                variant=model,
                cape_id=effective_cape_id,
            )
            _save_token_payload(payload_data)
            if effective_cape_id is not None:
                try:
                    _apply_microsoft_cape_selection(account, effective_cape_id)
                    payload_data = _load_token_payload() or payload_data
                    _set_active_default_skin(
                        payload_data,
                        definition["id"],
                        variant=model,
                        cape_id=effective_cape_id,
                    )
                    _save_token_payload(payload_data)
                except Exception:
                    return _activate_cached_default_skin()
            return _texture_profile_from_payload(payload_data, account)

    skin_bytes = _read_default_skin_bytes(definition["id"], model)
    if not skin_bytes:
        return _activate_cached_default_skin()

    minecraft_token = str(account.get("access_token") or "").strip()
    status, data, _headers, error = _request_multipart_json(
        "POST",
        MINECRAFT_PROFILE_SKINS_URL,
        fields={"variant": model},
        files={"file": (f"{definition['key']}-{model}.png", "image/png", skin_bytes)},
        bearer_token=minecraft_token,
        timeout=TIMEOUT,
        stage="minecraft_default_skin_upload",
    )
    try:
        _check_success(status, data, error, f"Minecraft default skin upload failed ({status or 'no status'}).")
    except Exception:
        return _activate_cached_default_skin()

    payload_data = _load_token_payload() or payload_data
    confirmed_profile = _profile_response_payload(data)
    if confirmed_profile:
        payload_data["profile"] = confirmed_profile
    else:
        confirmed_profile = payload_data.get("profile") if isinstance(payload_data.get("profile"), dict) else {}

    active_entry = next(iter(_active_texture_entries(confirmed_profile.get("skins"))), None)
    active_texture_hash = _texture_hash_from_url((active_entry or {}).get("url"))
    active_remote_id = _remote_skin_entry_id(active_entry)
    _sync_skin_library_payload(payload_data)
    if active_remote_id:
        _set_default_skin_remote_id(
            payload_data,
            definition["id"],
            model,
            active_remote_id,
            active_texture_hash,
        )
    _set_active_default_skin(
        payload_data,
        definition["id"],
        variant=model,
        cape_id=effective_cape_id,
    )
    _save_token_payload(payload_data)

    updated_account = api_payload_from_profile(
        confirmed_profile,
        access_token=minecraft_token,
        xuid=str(account.get("xuid") or ""),
        client_id=str(account.get("client_id") or MICROSOFT_CLIENT_ID),
    )
    if updated_account:
        _save_account_identity(updated_account)
        account = updated_account

    if effective_cape_id is not None:
        try:
            _apply_microsoft_cape_selection(account, effective_cape_id)
            payload_data = _load_token_payload() or payload_data
            _set_active_default_skin(
                payload_data,
                definition["id"],
                variant=model,
                cape_id=effective_cape_id,
            )
            _save_token_payload(payload_data)
        except Exception:
            return _activate_cached_default_skin()

    return _texture_profile_from_payload(payload_data, account)


def activate_microsoft_skin(skin_id: str, *, display_name: str = "", variant: str = "", cape_id: Any = None) -> dict[str, Any]:
    clean_id = _normalize_local_skin_id(skin_id) or _safe_texture_entry_id(skin_id)
    if not clean_id:
        raise MicrosoftAuthError("Choose a skin from your Microsoft skin library.")

    payload_data = _load_token_payload()
    clean_default_id = _normalize_default_skin_id(clean_id)
    if clean_default_id:
        return _activate_microsoft_default_skin(clean_default_id, variant=variant, cape_id=cape_id)

    local_entry = _find_skin_library_entry(payload_data, clean_id)
    if local_entry:
        if not isinstance(payload_data, dict):
            raise MicrosoftAuthError("Stored Microsoft account data is missing. Please sign in again.")
        account = _account_from_payload(payload_data)
        def _activate_cached_local_skin() -> dict[str, Any]:
            cached_account = account or _account_from_payload(payload_data)
            if not cached_account:
                raise MicrosoftAuthError("Stored Microsoft account data is incomplete. Please sign in again.")
            _set_active_local_skin(payload_data, clean_id, cape_id=cape_id)
            _save_token_payload(payload_data)
            return _texture_profile_from_payload(payload_data, cached_account)

        try:
            account = _require_microsoft_texture_account()
        except Exception:
            return _activate_cached_local_skin()
        effective_cape_id = cape_id if cape_id is not None else local_entry.get("cape_id")
        profile = payload_data.get("profile") if isinstance(payload_data, dict) and isinstance(payload_data.get("profile"), dict) else {}
        local_texture_hash = str(local_entry.get("minecraft_texture_hash") or "").strip().lower()
        remote_entry = _remote_skin_entry_for_texture_hash(profile, local_texture_hash)
        remote_skin_id = _remote_skin_entry_id(remote_entry)
        if remote_skin_id:
            try:
                texture_profile = _select_microsoft_skin_by_id(account, remote_skin_id, allow_missing=True)
            except Exception:
                return _activate_cached_local_skin()
            if texture_profile:
                if effective_cape_id is not None:
                    try:
                        return _apply_microsoft_cape_selection(account, effective_cape_id)
                    except Exception:
                        return _activate_cached_local_skin()
                return texture_profile

        path = _ensure_local_skin_path(clean_id)
        try:
            with open(path, "rb") as f:
                local_skin_bytes = f.read()
        except Exception as e:
            raise MicrosoftAuthError("Could not read the saved skin from the launcher library.") from e
        if profile and _active_profile_skin_matches_bytes(profile, _sha256_hex(local_skin_bytes)):
            active_entry = next(iter(_active_texture_entries(profile.get("skins"))), None)
            active_texture_hash = _texture_hash_from_url((active_entry or {}).get("url"))
            if active_texture_hash:
                _update_skin_library_entry(payload_data, clean_id, {"minecraft_texture_hash": active_texture_hash})
                _clear_active_local_skin(payload_data)
                _save_token_payload(payload_data)
            if effective_cape_id is not None:
                try:
                    return _apply_microsoft_cape_selection(account, effective_cape_id)
                except Exception:
                    return _activate_cached_local_skin()
            return _texture_profile_from_payload(payload_data, account)
        try:
            return upload_microsoft_skin(
                local_skin_bytes,
                variant=variant or str(local_entry.get("variant") or "classic"),
                file_name=str(local_entry.get("file_name") or "skin.png"),
                display_name=display_name or str(local_entry.get("name") or "Skin"),
                library_id=clean_id,
                cape_id=effective_cape_id,
            )
        except Exception:
            return _activate_cached_local_skin()

    account = _require_microsoft_texture_account()
    texture_profile = _select_microsoft_skin_by_id(account, clean_id)
    if texture_profile:
        return texture_profile
    return _refresh_microsoft_texture_profile(account)


def _apply_microsoft_cape_selection(
    account: dict[str, Any],
    cape_id: Any,
    *,
    preloaded_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_id = _normalize_library_cape_id(cape_id)
    minecraft_token = str(account.get("access_token") or "").strip()
    if not clean_id:
        status, data, _headers, error = _request_json(
            "DELETE",
            f"{MINECRAFT_PROFILE_CAPES_URL}/active",
            bearer_token=minecraft_token,
            timeout=TIMEOUT,
            stage="minecraft_cape_disable",
        )
        _check_success(status, data, error, f"Minecraft cape disable failed ({status or 'no status'}).")
        texture_profile = _commit_profile_response(account, data)
        if texture_profile is None and preloaded_profile is not None:
            texture_profile = _commit_profile_response(account, preloaded_profile)
        if texture_profile is None:
            payload = _load_token_payload() or {}
            texture_profile = _texture_profile_from_payload(payload, account)
        return texture_profile

    attempts = [
        (f"{MINECRAFT_PROFILE_CAPES_URL}/{urllib.parse.quote(clean_id, safe='')}", None),
        (f"{MINECRAFT_PROFILE_CAPES_URL}/active", {"capeId": clean_id}),
    ]
    last_data: Any = None
    last_status = 0
    last_error: str | None = None
    for url, body in attempts:
        status, data, _headers, error = _request_json(
            "PUT",
            url,
            body=body,
            bearer_token=minecraft_token,
            timeout=TIMEOUT,
            stage="minecraft_cape_select",
        )
        if status in {200, 201, 204}:
            texture_profile = _commit_profile_response(account, data)
            if texture_profile is None:
                payload = _load_token_payload() or {}
                texture_profile = _texture_profile_from_payload(payload, account)
            return texture_profile
        last_status = status
        last_data = data
        last_error = error
        if status in {401, 403}:
            break

    _check_success(last_status, last_data, last_error, f"Minecraft cape selection failed ({last_status or 'no status'}).")
    return _refresh_microsoft_texture_profile(account)


def activate_microsoft_cape(cape_id: str) -> dict[str, Any]:
    clean_id = _normalize_library_cape_id(cape_id)
    if not clean_id:
        raise MicrosoftAuthError("Choose a cape from your Microsoft cape library.")
    account = _require_microsoft_texture_account()
    return _apply_microsoft_cape_selection(account, clean_id)


def disable_microsoft_cape() -> dict[str, Any]:
    account = _require_microsoft_texture_account()
    return _apply_microsoft_cape_selection(account, "")


def _matching_microsoft_payload(identifier: str = "", username: str = "") -> dict[str, Any] | None:
    if not microsoft_account_enabled():
        return None

    payload = _load_token_payload()
    account = _account_from_payload(payload)
    if not account:
        return None

    requested_id = str(identifier or "").strip().replace("-", "").lower()
    requested_name = str(username or "").strip().lower()
    account_id = str(account.get("uuid") or "").replace("-", "").lower()
    account_name = str(account.get("username") or "").strip().lower()

    if requested_id and requested_id != account_id:
        return None
    if requested_name and requested_name != account_name:
        return None
    return payload if isinstance(payload, dict) else None


def resolve_microsoft_texture_metadata(identifier: str = "", username: str = "") -> dict[str, str | None] | None:
    payload = _matching_microsoft_payload(identifier, username)
    if not payload:
        return None

    profile = payload.get("profile") if isinstance(payload, dict) and isinstance(payload.get("profile"), dict) else {}
    local_skin = _active_local_skin_entry(payload)
    default_skin = _active_default_skin_entry(payload)
    skin_entry = next(iter(_active_texture_entries(profile.get("skins"))), None)
    if local_skin:
        local_cape_id = _normalize_library_cape_id(local_skin.get("cape_id"))
        capes = profile.get("capes") if isinstance(profile.get("capes"), list) else []
        cape_entry = next(
            (
                entry for entry in capes
                if _safe_texture_entry_id(
                    entry.get("id") or entry.get("textureId") or entry.get("texture_id")
                ) == local_cape_id
            ),
            None,
        )
    elif default_skin:
        default_cape_id = _normalize_library_cape_id(default_skin.get("cape_id"))
        capes = profile.get("capes") if isinstance(profile.get("capes"), list) else []
        cape_entry = next(
            (
                entry for entry in capes
                if _safe_texture_entry_id(
                    entry.get("id") or entry.get("textureId") or entry.get("texture_id")
                ) == default_cape_id
            ),
            None,
        )
    else:
        cape_entry = next(iter(_active_texture_entries(profile.get("capes"))), None)
    skin_url = "" if (local_skin or default_skin) else (_normalize_minecraft_texture_url((skin_entry or {}).get("url")) or "")
    cape_url = _normalize_minecraft_texture_url((cape_entry or {}).get("url"))
    if not local_skin and not default_skin and not skin_url and not cape_url:
        return None
    return {
        "skin": skin_url,
        "cape": cape_url,
        "model": str((local_skin or default_skin or {}).get("variant") or "") or _texture_model(skin_entry),
        "local_skin_id": str((local_skin or {}).get("id") or ""),
        "default_skin_id": str((default_skin or {}).get("texture_id") or ""),
    }


def resolve_microsoft_texture_url(texture_type: str, identifier: str = "", username: str = "") -> str | None:
    metadata = resolve_microsoft_texture_metadata(identifier, username)
    if not metadata:
        return None
    key = "skins" if str(texture_type or "").strip().lower() == "skin" else "capes"
    return str(metadata.get("skin" if key == "skins" else "cape") or "") or None
