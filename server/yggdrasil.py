# server/yggdrasil.py

import json
import uuid
import base64
import time
import os
import urllib.parse
import urllib.request
import re
import hashlib

from typing import Tuple
from urllib.parse import urlparse

from server.auth import get_verified_account
from core.settings import load_global_settings, _apply_url_proxy
from core.logger import colorize_log

_MODEL_CACHE = {}
_MODEL_CACHE_TTL_SECONDS = 30
_CAPE_CACHE = {}
_CAPE_CACHE_TTL_SECONDS = 30
_TEXTURE_METADATA_CACHE = {}
_TEXTURE_METADATA_CACHE_TTL_SECONDS = 30
_TEXTURE_PROP_CACHE = {}
_TEXTURE_PROP_CACHE_TTL_SECONDS = 30
_SESSION_JOIN_TTL_SECONDS = 300
_SESSION_JOIN_CACHE = {}
_UUID_NAME_CACHE = {}
_PRIVATE_KEY_CACHE = None


def _ensure_uuid(username: str) -> str:
    digest = hashlib.md5(("OfflinePlayer:" + (username or "")).encode("utf-8")).digest()
    as_list = bytearray(digest)
    as_list[6] = (as_list[6] & 0x0F) | 0x30
    as_list[8] = (as_list[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(as_list)))


def _get_username_and_uuid() -> Tuple[str, str]:
    settings = load_global_settings()
    account_type = settings.get("account_type", "Local")

    if account_type == "Histolauncher":
        try:
            success, account_data, error = get_verified_account()
            if success and account_data:
                username = account_data.get("username", "Player")
                u = account_data.get("uuid", "").replace("-", "")
                if u:
                    try:
                        uuid.UUID(account_data.get("uuid", ""))
                        return username, u
                    except Exception:
                        pass
        except Exception as e:
                print(colorize_log(f"[yggdrasil] Failed to verify Histolauncher session: {e}"))
    username = (settings.get("username") or "Player").strip() or "Player"
    u = _ensure_uuid(username)
    return username, u.replace("-", "")


def _normalize_uuid_hex(value: str | None) -> str:
    raw = str(value or "").strip().replace("-", "")
    if len(raw) != 32:
        return ""
    try:
        uuid.UUID(raw)
    except Exception:
        return ""
    return raw.lower()


def _uuid_hex_to_dashed(u_hex: str) -> str:
    return (
        f"{u_hex[0:8]}-{u_hex[8:12]}-{u_hex[12:16]}-"
        f"{u_hex[16:20]}-{u_hex[20:]}"
    )


def _build_public_skin_url(u_with_dashes: str, port: int = 0) -> str:
    if port > 0:
        return f"http://127.0.0.1:{port}/textures/skin/{u_with_dashes}"
    return f"https://textures.histolauncher.workers.dev/skin/{u_with_dashes}"


def _build_public_cape_url(identifier: str, port: int = 0) -> str:
    if port > 0:
        return f"http://127.0.0.1:{port}/textures/cape/{urllib.parse.quote(str(identifier or '').strip(), safe='')}"
    return f"https://textures.histolauncher.workers.dev/cape/{urllib.parse.quote(str(identifier or '').strip(), safe='')}"


def _remote_texture_exists(texture_type: str, identifier: str, timeout_seconds: float = 1.2) -> bool:
    safe_type = str(texture_type or "").strip().lower()
    safe_id = str(identifier or "").strip()
    if safe_type not in {"skin", "cape"} or not safe_id:
        return False

    remote_url = f"https://textures.histolauncher.workers.dev/{safe_type}/{urllib.parse.quote(safe_id, safe='')}"
    probe_url = _apply_url_proxy(remote_url)
    try:
        req = urllib.request.Request(probe_url, headers={"User-Agent": "Histolauncher/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            ctype = str(resp.headers.get("Content-Type", "")).lower()
            if "image/" not in ctype:
                return False
            resp.read(1)
        return True
    except Exception:
        return False


def _normalize_skin_model(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    if raw == "slim":
        return "slim"
    if raw == "classic":
        return "classic"
    return None


def _normalize_remote_texture_url(url: str | None) -> str | None:
    raw = str(url or "").strip()
    if not raw:
        return None

    try:
        parsed = urlparse(raw)
    except Exception:
        return None

    host = str(parsed.netloc or "").strip().lower()
    if host not in {"textures.histolauncher.workers.dev", "textures.minecraft.net"}:
        return None

    scheme = "https" if host == "textures.minecraft.net" else (parsed.scheme or "https")
    normalized = parsed._replace(scheme=scheme)
    return urllib.parse.urlunparse(normalized)


def _normalize_remote_texture_metadata(payload: dict | None) -> dict | None:
    obj = payload if isinstance(payload, dict) else {}
    nested = obj.get("data") if isinstance(obj.get("data"), dict) else {}

    skin = _normalize_remote_texture_url(obj.get("skin"))
    cape = _normalize_remote_texture_url(obj.get("cape"))
    model = _normalize_skin_model(obj.get("model") or nested.get("model")) or "classic"

    if not skin and not cape and not obj and not nested:
        return None

    return {
        "skin": skin,
        "cape": cape,
        "model": model,
    }


def _collect_texture_identifiers(uuid_hex: str, username: str = "") -> list[str]:
    identifiers = []
    if uuid_hex:
        identifiers.append(_uuid_hex_to_dashed(uuid_hex))
        identifiers.append(uuid_hex)

    clean_username = (username or "").strip()
    if clean_username:
        identifiers.append(clean_username)

    seen = set()
    ordered = []
    for identifier in identifiers:
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        ordered.append(identifier)
    return ordered


def _fetch_remote_texture_metadata(identifier: str, timeout_seconds: float = 1.2) -> dict | None:
    ident = str(identifier or "").strip()
    if not ident:
        return None

    remote_url = f"https://textures.histolauncher.workers.dev/model/{urllib.parse.quote(ident, safe='')}"
    probe_url = _apply_url_proxy(remote_url)
    try:
        req = urllib.request.Request(probe_url, headers={"User-Agent": "Histolauncher/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        return _normalize_remote_texture_metadata(payload)
    except Exception:
        return None


def _resolve_remote_texture_metadata(uuid_hex: str, username: str = "") -> dict | None:
    cache_key = f"{uuid_hex}|{(username or '').strip().lower()}"
    now = time.time()
    cached = _TEXTURE_METADATA_CACHE.get(cache_key)
    if cached and (now - cached.get("at", 0) <= _TEXTURE_METADATA_CACHE_TTL_SECONDS):
        return cached.get("meta")

    for identifier in _collect_texture_identifiers(uuid_hex, username):
        metadata = _fetch_remote_texture_metadata(identifier, timeout_seconds=1.2)
        if metadata is None:
            continue

        _TEXTURE_METADATA_CACHE[cache_key] = {"meta": metadata, "at": now}
        if uuid_hex:
            _persist_cached_skin_model(uuid_hex, metadata.get("model") or "classic", username)
        return metadata

    return cached.get("meta") if cached else None


def _resolve_remote_texture_url(texture_type: str, uuid_hex: str = "", username: str = "") -> str | None:
    safe_type = str(texture_type or "").strip().lower()
    if safe_type not in {"skin", "cape"}:
        return None

    metadata = _resolve_remote_texture_metadata(uuid_hex, username)
    if not metadata:
        return None

    value = metadata.get(safe_type)
    return str(value).strip() if value else None


def _fetch_remote_skin_model(identifier: str, timeout_seconds: float = 1.2) -> str | None:
    metadata = _fetch_remote_texture_metadata(identifier, timeout_seconds=timeout_seconds)
    return (metadata or {}).get("model")


def _persist_cached_skin_model(uuid_hex: str, model: str, username: str = "") -> None:
    normalized = _normalize_skin_model(model)
    if normalized is None:
        return

    base_dir = os.path.expanduser("~/.histolauncher")
    skins_dir = os.path.join(base_dir, "skins")
    os.makedirs(skins_dir, exist_ok=True)

    dashed = _uuid_hex_to_dashed(uuid_hex) if uuid_hex else ""
    targets = []
    if dashed:
        targets.append(os.path.join(skins_dir, f"{dashed}.json"))
    if uuid_hex:
        targets.append(os.path.join(skins_dir, f"{uuid_hex}.json"))

    payload = {
        "model": normalized,
        "skin_model": normalized,
        "username": str(username or "").strip(),
        "updated_at": int(time.time()),
    }

    for path in targets:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except Exception:
            continue


def _has_local_skin_file(uuid_hex: str, username: str = "") -> bool:
    base_dir = os.path.expanduser("~/.histolauncher")
    skins_dir = os.path.join(base_dir, "skins")
    dashed = _uuid_hex_to_dashed(uuid_hex) if uuid_hex else ""

    candidates = []
    if dashed:
        candidates.append(os.path.join(skins_dir, f"{dashed}.png"))
    if uuid_hex:
        candidates.append(os.path.join(skins_dir, f"{uuid_hex}.png"))

    clean_username = (username or "").strip()
    if clean_username:
        candidates.append(os.path.join(skins_dir, f"{clean_username}.png"))

    return any(candidate and os.path.isfile(candidate) for candidate in candidates)


def _resolve_local_cape_url(uuid_hex: str, username: str = "", port: int = 0) -> str | None:
    identifiers = _collect_texture_identifiers(uuid_hex, username)
    base_dir = os.path.expanduser("~/.histolauncher")
    skins_dir = os.path.join(base_dir, "skins")
    dashed = _uuid_hex_to_dashed(uuid_hex) if uuid_hex else ""

    for identifier in identifiers:
        local_candidates = []
        if dashed:
            local_candidates.append(os.path.join(skins_dir, f"{dashed}.png"))
        if uuid_hex:
            local_candidates.append(os.path.join(skins_dir, f"{uuid_hex}.png"))
        if identifier:
            local_candidates.append(os.path.join(skins_dir, f"{identifier}.png"))

        for candidate in local_candidates:
            if candidate and os.path.isfile(candidate):
                return _build_public_cape_url(identifier, port)

    return None


def _resolve_cape_url(uuid_hex: str, username: str = "", port: int = 0, probe_remote: bool = True) -> str | None:
    cache_key = f"{uuid_hex}|{(username or '').strip().lower()}"
    cached = _CAPE_CACHE.get(cache_key)
    now = time.time()
    if cached and (now - cached.get("at", 0) <= _CAPE_CACHE_TTL_SECONDS):
        return cached.get("url")

    if probe_remote:
        remote_url = _resolve_remote_texture_url("cape", uuid_hex, username)
        if remote_url:
            print(colorize_log(f"[yggdrasil] Cape resolved via texture metadata: {remote_url}"))
            _CAPE_CACHE[cache_key] = {"url": remote_url, "at": now}
            return remote_url

    local_url = _resolve_local_cape_url(uuid_hex, username, port)
    if local_url:
        _CAPE_CACHE[cache_key] = {"url": local_url, "at": now}
        return local_url

    _CAPE_CACHE[cache_key] = {"url": None, "at": now}
    return None


def _resolve_skin_model(uuid_hex: str, username: str = "") -> str:
    cache_key = f"{uuid_hex}|{(username or '').strip().lower()}"
    cached = _MODEL_CACHE.get(cache_key)
    now = time.time()

    clean_username = (username or "").strip()
    remote_metadata = _resolve_remote_texture_metadata(uuid_hex, clean_username)
    if remote_metadata and remote_metadata.get("model") in ("slim", "classic"):
        remote_model = remote_metadata.get("model")
        _MODEL_CACHE[cache_key] = {"model": remote_model, "at": now}
        _persist_cached_skin_model(uuid_hex, remote_model, clean_username)
        return remote_model

    if cached and (now - cached.get("at", 0) <= _MODEL_CACHE_TTL_SECONDS):
        return cached.get("model", "classic")

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
                _MODEL_CACHE[cache_key] = {"model": model, "at": now}
                return model
        except Exception:
            continue

    _MODEL_CACHE[cache_key] = {"model": "classic", "at": now}
    return "classic"



def _get_private_key():
    global _PRIVATE_KEY_CACHE
    if _PRIVATE_KEY_CACHE is not None:
        return _PRIVATE_KEY_CACHE

    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        return None

    key_path = os.path.expanduser("~/.histolauncher/.yggdrasil_key")
    os.makedirs(os.path.dirname(key_path), exist_ok=True)

    if os.path.exists(key_path):
        try:
            with open(key_path, "rb") as key_file:
                _PRIVATE_KEY_CACHE = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None,
                    backend=default_backend()
                )
                return _PRIVATE_KEY_CACHE
        except Exception as e:
            print(colorize_log(f"[yggdrasil] Failed to load existing key: {e}"))

    try:
        print(colorize_log("[yggdrasil] Generating new 4096-bit RSA key for texture signing, this may take a moment..."))
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
            backend=default_backend()
        )
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        with open(key_path, "wb") as key_file:
            key_file.write(pem)
        _PRIVATE_KEY_CACHE = private_key
        return _PRIVATE_KEY_CACHE
    except Exception as e:
        print(colorize_log(f"[yggdrasil] Failed to generate key: {e}"))
        return None


def get_public_key_pem() -> str | None:
    private_key = _get_private_key()
    if not private_key:
        return None
    try:
        from cryptography.hazmat.primitives import serialization
        pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return pem.decode('utf-8')
    except Exception as e:
        print(colorize_log(f"[yggdrasil] Failed to get public key: {e}"))
        return None


def _sign_texture_property(encoded_value: str) -> str | None:
    private_key = _get_private_key()
    if not private_key:
        return None

    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        return None

    try:
        signature = private_key.sign(
            encoded_value.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA1()
        )
        return base64.b64encode(signature).decode("utf-8")
    except Exception as e:
        print(colorize_log(f"[yggdrasil] Failed to sign texture property: {e}"))
        return None


def _get_skin_property(port: int, target_uuid_hex: str = "", target_username: str = "") -> dict | None:
    username, current_u_hex = _get_username_and_uuid()
    u_hex = _normalize_uuid_hex(target_uuid_hex) or current_u_hex
    profile_name = (target_username or username or "").strip()
    u_with_dashes = _uuid_hex_to_dashed(u_hex)
    remote_metadata = _resolve_remote_texture_metadata(u_hex, profile_name)

    url = (remote_metadata or {}).get("skin") or None
    skin_model = (remote_metadata or {}).get("model") or _resolve_skin_model(u_hex, profile_name)
    cape_url = (remote_metadata or {}).get("cape") or _resolve_local_cape_url(u_hex, profile_name, port)

    skin_exists = bool(url)
    if not skin_exists and _has_local_skin_file(u_hex, profile_name):
        skin_exists = True
        url = _build_public_skin_url(u_with_dashes, port)

    if not skin_exists:
        skin_exists = _remote_texture_exists("skin", u_with_dashes or u_hex or profile_name)
        if skin_exists:
            url = _build_public_skin_url(u_with_dashes, port)

    textures = {}
    if skin_exists and url:
        skin_data = {"url": url}
        if skin_model == "slim":
            skin_data["metadata"] = {"model": "slim"}
        textures["SKIN"] = skin_data

    if cape_url:
        textures["CAPE"] = {"url": cape_url}

    # Cache signed texture properties to avoid expensive RSA signing on every request.
    cache_key = f"{u_hex}|{profile_name}|{url}|{cape_url or ''}"
    cached = _TEXTURE_PROP_CACHE.get(cache_key)
    now = time.time()
    if cached and (now - cached.get("at", 0) <= _TEXTURE_PROP_CACHE_TTL_SECONDS):
        return cached.get("prop")

    # Use a stable timestamp per cache period to allow caching.
    timestamp = int(now // _TEXTURE_PROP_CACHE_TTL_SECONDS) * _TEXTURE_PROP_CACHE_TTL_SECONDS * 1000

    tex = {
        "timestamp": timestamp,
        "profileId": u_hex,
        "signatureRequired": True,
        "textures": textures,
    }
    if profile_name:
        tex["profileName"] = profile_name
    json_bytes = json.dumps(tex).encode("utf-8")
    encoded = base64.b64encode(json_bytes).decode("utf-8")
    signature = _sign_texture_property(encoded)

    if not signature:
        tex["signatureRequired"] = False
        signature = ""

    prop = {
        "name": "textures",
        "value": encoded,
        "signature": signature,
    }

    _TEXTURE_PROP_CACHE[cache_key] = {"prop": prop, "at": now}
    return prop




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


def handle_session_get(path: str, port: int):
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
        cached_name = str(_UUID_NAME_CACHE.get(req_uuid) or "").strip()
        profile_name = query_name or cached_name

    if profile_name:
        _UUID_NAME_CACHE[req_uuid] = profile_name

    props = []
    skin_prop = _get_skin_property(port, target_uuid_hex=req_uuid, target_username=profile_name)
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
        f"[yggdrasil] session profile served: uuid={req_uuid}, signed skins enabled"
    ))
    return 200, resp


def handle_services_profile_get(port: int):
    username, u_hex = _get_username_and_uuid()
    u_with_dashes = _uuid_hex_to_dashed(u_hex)
    remote_metadata = _resolve_remote_texture_metadata(u_hex, username)
    skin_model = (remote_metadata or {}).get("model") or _resolve_skin_model(u_hex, username)
    cape_url = (remote_metadata or {}).get("cape") or _resolve_local_cape_url(u_hex, username, port)

    skin_url = (remote_metadata or {}).get("skin")
    if not skin_url:
        skin_url = _build_public_skin_url(u_with_dashes, port)
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
        "skins": [
            {
                "id": str(uuid.uuid4()),
                "state": "ACTIVE",
                "url": skin_url,
                "variant": variant,
            }
        ],
        "capes": capes,
        "signatureRequired": signature_required,
    }
    print(colorize_log(f"[yggdrasil] services profile served: uuid={u_hex}, variant={variant}"))
    return 200, resp


def handle_session_join_post(path: str, body: str):
    try:
        data = json.loads(body) if body else {}
    except Exception:
        data = {}

    server_id = str(data.get("serverId") or "").strip()
    selected_profile = str(data.get("selectedProfile") or "").strip()

    if not server_id:
        return 400, {"error": "IllegalArgumentException", "errorMessage": "Missing serverId"}

    username, current_uuid_hex = _get_username_and_uuid()
    current_uuid_hex = _normalize_uuid_hex(current_uuid_hex) or _normalize_uuid_hex(selected_profile)
    if not current_uuid_hex:
        return 403, {"error": "ForbiddenOperationException", "errorMessage": "Invalid profile"}

    now = time.time()
    stale = [k for k, v in _SESSION_JOIN_CACHE.items() if now - float(v.get("at", 0)) > _SESSION_JOIN_TTL_SECONDS]
    for k in stale:
        _SESSION_JOIN_CACHE.pop(k, None)

    _SESSION_JOIN_CACHE[server_id] = {
        "uuid": current_uuid_hex,
        "name": (username or "Player").strip() or "Player",
        "at": now,
    }
    _UUID_NAME_CACHE[current_uuid_hex] = (username or "Player").strip() or "Player"
    print(colorize_log(f"[yggdrasil] session join accepted: serverId={server_id}, uuid={current_uuid_hex}"))
    return 204, None


def handle_has_joined_get(path: str, port: int):
    parsed = urlparse(path)
    query = urllib.parse.parse_qs(parsed.query or "")
    server_id = str((query.get("serverId") or [""])[0]).strip()
    username_q = str((query.get("username") or [""])[0]).strip()

    if not server_id or not username_q:
        return 400, {"error": "IllegalArgumentException", "errorMessage": "Missing username/serverId"}

    username, current_uuid_hex = _get_username_and_uuid()
    current_name = (username or "Player").strip() or "Player"
    current_uuid_hex = _normalize_uuid_hex(current_uuid_hex)

    joined = _SESSION_JOIN_CACHE.get(server_id) or {}
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

    _UUID_NAME_CACHE[out_uuid] = out_name

    props = []
    skin_prop = _get_skin_property(port, target_uuid_hex=out_uuid, target_username=out_name)
    if skin_prop:
        props.append(skin_prop)

    resp = {
        "id": out_uuid,
        "name": out_name,
        "properties": props,
        "signatureRequired": True,  # Required for 1.20.2+ servers/plugins that inspect this field.
        "profileActions": [],
    }
    print(colorize_log(f"[yggdrasil] hasJoined served: serverId={server_id}, username={out_name}, uuid={out_uuid}"))
    return 200, resp
