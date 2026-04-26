from __future__ import annotations

import urllib.parse
import urllib.request
from urllib.parse import urlparse

from server.yggdrasil.identity import (
    _histolauncher_account_enabled,
    _uuid_hex_to_dashed,
)
from server.yggdrasil.state import TEXTURES_API_HOSTNAME

from core.settings import _apply_url_proxy


__all__ = [
    "_build_public_skin_url",
    "_build_public_cape_url",
    "_collect_texture_identifiers",
    "_normalize_skin_model",
    "_normalize_remote_texture_url",
    "_normalize_remote_texture_metadata",
    "_remote_texture_exists",
]


def _build_public_skin_url(u_with_dashes: str, port: int = 0) -> str:
    if port > 0:
        return f"http://127.0.0.1:{port}/texture/skin/{u_with_dashes}"
    return f"https://{TEXTURES_API_HOSTNAME}/skin/{u_with_dashes}"


def _build_public_cape_url(identifier: str, port: int = 0) -> str:
    if port > 0:
        return (
            f"http://127.0.0.1:{port}/texture/cape/"
            f"{urllib.parse.quote(str(identifier or '').strip(), safe='')}"
        )
    return (
        f"https://{TEXTURES_API_HOSTNAME}/cape/"
        f"{urllib.parse.quote(str(identifier or '').strip(), safe='')}"
    )


def _collect_texture_identifiers(uuid_hex: str, username: str = "") -> list[str]:
    identifiers: list[str] = []
    if uuid_hex:
        identifiers.append(_uuid_hex_to_dashed(uuid_hex))
        identifiers.append(uuid_hex)

    clean_username = (username or "").strip()
    if clean_username:
        identifiers.append(clean_username)

    seen: set[str] = set()
    ordered: list[str] = []
    for identifier in identifiers:
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        ordered.append(identifier)
    return ordered


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
    if host not in {TEXTURES_API_HOSTNAME, "textures.minecraft.net"}:
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


def _remote_texture_exists(
    texture_type: str, identifier: str, timeout_seconds: float = 1.2
) -> bool:
    if not _histolauncher_account_enabled():
        return False

    safe_type = str(texture_type or "").strip().lower()
    safe_id = str(identifier or "").strip()
    if safe_type not in {"skin", "cape"} or not safe_id:
        return False

    remote_url = (
        f"https://{TEXTURES_API_HOSTNAME}/{safe_type}/"
        f"{urllib.parse.quote(safe_id, safe='')}"
    )
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
