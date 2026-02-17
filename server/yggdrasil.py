# server/yggdrasil.py
import json
import uuid
import base64
import time
import os
from typing import Tuple
from urllib.parse import urlparse

from core.settings import load_global_settings


def _ensure_uuid(username: str) -> str:
    offline_uuid = uuid.uuid3(uuid.NAMESPACE_DNS, "OfflinePlayer:" + username)
    return str(offline_uuid)


def _get_username_and_uuid() -> Tuple[str, str]:
    settings = load_global_settings()
    username = (settings.get("username") or "Player").strip() or "Player"
    account_type = settings.get("account_type", "Local")
    if account_type == "Histolauncher":
        u = (settings.get("uuid") or "").strip()
        if u:
            try:
                uuid.UUID(u)
                return username, u.replace("-", "")
            except Exception:
                pass
    u = _ensure_uuid(username)
    return username, u.replace("-", "")



def _get_skin_property(port: int) -> dict | None:
    username, u_hex = _get_username_and_uuid()
    u_with_dashes = (
        f"{u_hex[0:8]}-{u_hex[8:12]}-{u_hex[12:16]}-"
        f"{u_hex[16:20]}-{u_hex[20:]}"
    )
    url = f"https://textures.histolauncher.workers.dev/skin/{u_with_dashes}"
    tex = {
        "timestamp": int(time.time() * 1000),
        "profileId": u_with_dashes,
        "profileName": username,
        "textures": {"SKIN": {"url": url, "model": "default"}},
    }
    json_bytes = json.dumps(tex).encode("utf-8")
    encoded = base64.b64encode(json_bytes).decode("utf-8")
    data_to_sign = encoded.encode("utf-8")
    
    # Sign the textures property using our private key
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
        print(f"[yggdrasil] failed to sign textures property: {e}")
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
    if len(parts) < 5:
        return 404, {"error": "Not Found"}
    req_uuid = parts[-1].replace("-", "").lower()
    username, u_hex = _get_username_and_uuid()
    u_hex = u_hex.lower()
    u_with_dashes = (
        f"{u_hex[0:8]}-{u_hex[8:12]}-{u_hex[12:16]}-"
        f"{u_hex[16:20]}-{u_hex[20:]}"
    )
    if req_uuid == "00000000000000000000000000000000":
        req_uuid = u_hex
    if req_uuid != u_hex:
        return 404, {"error": "Not Found"}
    props = []
    skin_prop = _get_skin_property(port)
    if skin_prop:
        props.append(skin_prop)
    resp = {"id": u_hex, "name": username, "properties": props, "signatureRequired": True}
    return 200, resp