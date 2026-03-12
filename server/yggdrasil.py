# server/yggdrasil.py

import json
import uuid
import base64
import time
import os
import urllib.parse
import urllib.request

from typing import Tuple
from urllib.parse import urlparse
from core.settings import load_global_settings, _apply_url_proxy
from core.logger import colorize_log

_MODEL_CACHE = {}
_MODEL_CACHE_TTL_SECONDS = 30


def _ensure_uuid(username: str) -> str:
    offline_uuid = uuid.uuid3(uuid.NAMESPACE_DNS, "OfflinePlayer:" + username)
    return str(offline_uuid)


def _get_username_and_uuid() -> Tuple[str, str]:
    """
    Get the current user's username and UUID.
    
    For Histolauncher accounts: Verifies session with Cloudflare API (secure)
    For Local accounts: Uses settings.ini (offline mode)
    """
    settings = load_global_settings()
    account_type = settings.get("account_type", "Local")
    
    # For Histolauncher accounts, verify the session at Cloudflare
    # This prevents someone from editing settings.ini to impersonate another user
    if account_type == "Histolauncher":
        try:
            from server.auth import get_verified_account
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
    # Fallback for local accounts or if verification fails
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


def _resolve_skin_model(uuid_hex: str, username: str = "") -> str:
    cache_key = f"{uuid_hex}|{(username or '').strip().lower()}"
    cached = _MODEL_CACHE.get(cache_key)
    now = time.time()
    if cached and (now - cached.get("at", 0) <= _MODEL_CACHE_TTL_SECONDS):
        return cached.get("model", "default")

    identifiers = []
    if uuid_hex:
        identifiers.append(_uuid_hex_to_dashed(uuid_hex))
        identifiers.append(uuid_hex)
    clean_username = (username or "").strip()
    if clean_username:
        identifiers.append(clean_username)

    seen = set()
    found_classic = False
    found_classic_identifier = ""

    for identifier in identifiers:
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        try:
            model_url = _apply_url_proxy(f"https://textures.histolauncher.workers.dev/model/{urllib.parse.quote(identifier)}")
            req = urllib.request.Request(model_url, headers={"User-Agent": "Histolauncher/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            payload_obj = payload if isinstance(payload, dict) else {}
            api_model = str(
                payload_obj.get("model")
                or (payload_obj.get("data") or {}).get("model")
                or ""
            ).strip().lower()
            if api_model in ("slim", "classic", "default", "alex", "steve"):
                normalized = "slim" if api_model in ("slim", "alex") else "default"
                if normalized == "slim":
                    print(colorize_log(f"[yggdrasil] Skin model resolved slim via identifier: {identifier}"))
                    _MODEL_CACHE[cache_key] = {"model": "slim", "at": now}
                    return "slim"
                found_classic = True
                found_classic_identifier = identifier
        except Exception:
            continue

    if found_classic:
        if found_classic_identifier:
            print(colorize_log(f"[yggdrasil] Skin model resolved classic via identifier: {found_classic_identifier}"))
        _MODEL_CACHE[cache_key] = {"model": "default", "at": now}
        return "default"

    # Fallback: local metadata file (used by some offline/test setups).
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
            model = str(meta.get("model") or meta.get("skin_model") or "").strip().lower()
            if model in ("slim", "alex"):
                _MODEL_CACHE[cache_key] = {"model": "slim", "at": now}
                return "slim"
            if model in ("default", "steve"):
                _MODEL_CACHE[cache_key] = {"model": "default", "at": now}
                return "default"
        except Exception:
            continue

    _MODEL_CACHE[cache_key] = {"model": "default", "at": now}
    return "default"


def _get_skin_property(port: int, target_uuid_hex: str = "", target_username: str = "") -> dict | None:
    username, current_u_hex = _get_username_and_uuid()
    u_hex = _normalize_uuid_hex(target_uuid_hex) or current_u_hex
    profile_name = (target_username or username or "Player").strip() or "Player"
    u_with_dashes = _uuid_hex_to_dashed(u_hex)
    
    url = f"http://127.0.0.1:{port}/textures/skin/{u_with_dashes}"
    skin_model = _resolve_skin_model(u_hex, profile_name)

    # Per Mojang API: metadata with {"model": "slim"} ONLY exists for slim/Alex skins.
    # For classic/Steve skins, the metadata key must be completely absent.
    skin_data = {"url": url}
    if skin_model == "slim":
        skin_data["metadata"] = {"model": "slim"}

    tex = {
        "timestamp": int(time.time() * 1000),
        "profileId": u_hex,
        "profileName": profile_name,
        "textures": {"SKIN": skin_data},
    }
    json_bytes = json.dumps(tex).encode("utf-8")
    encoded = base64.b64encode(json_bytes).decode("utf-8")
    data_to_sign = encoded.encode("utf-8")
    
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
        priv_path = os.path.join(os.path.dirname(__file__), "..", "assets", "skins-signature-privkey.pem")
        with open(priv_path, "rb") as f:
            priv = serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())
        sig = priv.sign(data_to_sign, padding.PKCS1v15(), hashes.SHA1())
        sig_b64 = base64.b64encode(sig).decode("utf-8")
        return {"name": "textures", "value": encoded, "signature": sig_b64}
    except Exception as e:
        print(colorize_log(f"[yggdrasil] failed to sign textures property: {e}"))
        return {"name": "textures", "value": encoded}


def ensure_signature_keys_ready():
    key_path = os.path.join(os.path.dirname(__file__), "..", "assets", "skins-signature-pubkey.der")
    key_path = os.path.abspath(key_path)
    if not os.path.exists(key_path):
        return False
    return True
    

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
    parts = [p for p in path_only.split("/") if p]
    if len(parts) < 5: return 404, {"error": "Not Found"}
    raw_req_id = parts[-1]
    req_uuid = _normalize_uuid_hex(raw_req_id)
    username, u_hex = _get_username_and_uuid()

    if not req_uuid:
        return 404, {"error": "Not Found"}

    if req_uuid == "00000000000000000000000000000000":
        req_uuid = u_hex

    query = urllib.parse.parse_qs(parsed.query or "")
    query_name = (query.get("username") or [""])[0].strip()
    profile_name = username if req_uuid == u_hex else (query_name or f"Player-{req_uuid[:8]}")

    props = []
    skin_prop = _get_skin_property(port, target_uuid_hex=req_uuid, target_username=profile_name)
    if skin_prop:
        props.append(skin_prop)
    resp = {
        "id": req_uuid,
        "name": profile_name,
        "properties": props,
        "signatureRequired": True,
    }
    return 200, resp