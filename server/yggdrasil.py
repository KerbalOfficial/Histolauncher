# server/yggdrasil.py
import json
import uuid
import base64
import os
from typing import Tuple

from core.settings import load_global_settings, save_global_settings, get_base_dir


def _ensure_uuid(settings: dict) -> str:
    u = (settings.get("offline_uuid") or "").strip()
    try:
        if u:
            uuid.UUID(u)
            return u
    except Exception:
        pass
    new_u = str(uuid.uuid4())
    settings["offline_uuid"] = new_u
    save_global_settings(settings)
    return new_u


def _get_username_and_uuid() -> Tuple[str, str]:
    settings = load_global_settings()
    username = (settings.get("username") or "Player").strip() or "Player"
    u = _ensure_uuid(settings)
    return username, u.replace("-", "")


def _get_skin_property(port: int) -> dict | None:
    base = get_base_dir()
    skin_path = os.path.join(base, "skins", "current.png")
    if not os.path.exists(skin_path):
        return None

    username, u_hex = _get_username_and_uuid()
    url = f"http://127.0.0.1:{port}/skins/current.png"
    tex = {
        "timestamp": 0,
        "profileId": u_hex,
        "profileName": username,
        "textures": {
            "SKIN": {
                "url": url
            }
        }
    }
    encoded = base64.b64encode(json.dumps(tex).encode("utf-8")).decode("utf-8")
    return {
        "name": "textures",
        "value": encoded
    }


def handle_auth_post(path: str, body: str, port: int):
    try:
        data = json.loads(body) if body else {}
    except Exception:
        data = {}

    username, u_hex = _get_username_and_uuid()
    access_token = "offline-" + u_hex
    client_token = data.get("clientToken") or "offline-client"

    profile = {
        "id": u_hex,
        "name": username,
    }

    resp = {
        "accessToken": access_token,
        "clientToken": client_token,
        "selectedProfile": profile,
        "availableProfiles": [profile],
    }
    return 200, resp


def handle_session_get(path: str, port: int):
    parts = path.split("/")
    if len(parts) < 5:
        return 404, {"error": "Not Found"}

    req_uuid = parts[-1]
    username, u_hex = _get_username_and_uuid()
    if req_uuid.lower() != u_hex.lower():
        return 404, {"error": "Not Found"}

    props = []
    skin_prop = _get_skin_property(port)
    if skin_prop:
        props.append(skin_prop)

    resp = {
        "id": u_hex,
        "name": username,
        "properties": props,
    }
    return 200, resp
