from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
from urllib.parse import urlparse

from server.yggdrasil.identity import (
    _uuid_hex_to_dashed,
)
from server.yggdrasil.state import TEXTURES_API_HOSTNAME

from core.settings import _apply_url_proxy, load_global_settings


__all__ = [
    "_build_public_skin_url",
    "_build_public_cape_url",
    "_build_histolauncher_texture_url",
    "_build_minecraft_texture_url",
    "_collect_texture_identifiers",
    "_build_texture_property_skin_url",
    "_build_texture_property_cape_url",
    "_cape_requires_minecraft_texture_host",
    "_get_active_launch_version_identifier",
    "_is_minecraft_texture_url",
    "_looks_like_minecraft_texture_id",
    "_minecraft_texture_id_from_url",
    "_normalize_skin_model",
    "_normalize_remote_texture_url",
    "_normalize_remote_texture_metadata",
    "_remote_texture_exists",
]


_MINECRAFT_TEXTURE_ID_RE = re.compile(r"^[0-9a-fA-F]{40,128}$")


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


def _build_histolauncher_texture_url(texture_type: str, identifier: str | None) -> str | None:
    safe_type = str(texture_type or "").strip().lower()
    safe_id = str(identifier or "").strip()
    if safe_type not in {"skin", "cape"} or not safe_id:
        return None
    return (
        f"https://{TEXTURES_API_HOSTNAME}/{safe_type}/"
        f"{urllib.parse.quote(safe_id, safe='')}"
    )


def _looks_like_minecraft_texture_id(value: str | None) -> bool:
    return bool(_MINECRAFT_TEXTURE_ID_RE.match(str(value or "").strip()))


def _build_minecraft_texture_url(texture_id: str | None) -> str | None:
    ident = str(texture_id or "").strip()
    if not _looks_like_minecraft_texture_id(ident):
        return None
    return f"https://textures.minecraft.net/texture/{ident}"


def _minecraft_texture_id_from_url(url: str | None) -> str | None:
    raw = str(url or "").strip()
    if not raw:
        return None

    try:
        parsed = urlparse(raw)
    except Exception:
        return None

    if str(parsed.netloc or "").strip().lower() != "textures.minecraft.net":
        return None

    path_parts = [part for part in (parsed.path or "").split("/") if part]
    if len(path_parts) < 2 or path_parts[-2].lower() != "texture":
        return None

    ident = urllib.parse.unquote(path_parts[-1]).strip()
    return ident if _looks_like_minecraft_texture_id(ident) else None


def _get_active_launch_version_identifier() -> str:
    env_value = str(os.environ.get("HISTOLAUNCHER_ACTIVE_VERSION_IDENTIFIER") or "").strip()
    if env_value:
        return env_value
    try:
        settings = load_global_settings() or {}
        return str(settings.get("selected_version") or "").strip()
    except Exception:
        return ""


def _parse_release_version(value: str) -> tuple[int, int, int] | None:
    raw = str(value or "").replace("\\", "/").strip().lower()
    if not raw:
        return None
    base = raw.split("/", 1)[1] if "/" in raw else raw
    base = base.split("-", 1)[0]
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?$", base)
    if not match:
        return None
    try:
        major = int(match.group(1))
        minor = int(match.group(2))
        patch = int(match.group(3) or 0)
        return major, minor, patch
    except Exception:
        return None


def _cape_requires_minecraft_texture_host(version_identifier: str = "") -> bool:
    version = _parse_release_version(
        version_identifier or _get_active_launch_version_identifier()
    )
    if not version:
        return True

    major, minor, patch = version
    if major != 1:
        return False
    if minor < 7:
        return False
    if minor == 7:
        return patch >= 3
    if minor < 19:
        return True
    if minor == 19:
        return patch <= 4
    return False


def _is_minecraft_texture_url(url: str | None) -> bool:
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return False
    return str(parsed.netloc or "").strip().lower() == "textures.minecraft.net"


def _build_texture_property_skin_url(
    skin_url: str | None,
    uuid_hex: str,
    username: str = "",
    port: int = 0,
    version_identifier: str = "",
) -> str | None:
    raw = str(skin_url or "").strip()
    if not raw:
        return None
    if raw.startswith("http://127.0.0.1:") or raw.startswith("http://localhost:"):
        return raw

    identifiers = _collect_texture_identifiers(uuid_hex, username)
    ident = identifiers[0] if identifiers else ""

    minecraft_texture_id = _minecraft_texture_id_from_url(raw)
    if port and port > 0 and minecraft_texture_id:
        return _build_public_skin_url(minecraft_texture_id, port)

    if port and port > 0 and ident:
        return _build_public_skin_url(ident, port)

    if _is_minecraft_texture_url(raw):
        normalized = _normalize_remote_texture_url(raw)
        return normalized or raw

    return raw


def _build_texture_property_cape_url(
    cape_url: str | None,
    uuid_hex: str,
    username: str = "",
    port: int = 0,
    version_identifier: str = "",
) -> str | None:
    raw = str(cape_url or "").strip()
    if not raw:
        return None

    if port and port > 0:
        minecraft_texture_id = _minecraft_texture_id_from_url(raw)
        if minecraft_texture_id:
            ident = minecraft_texture_id
            if _cape_requires_minecraft_texture_host(version_identifier):
                ident = f"{ident}_cape"
            return _build_public_cape_url(ident, port)

        identifiers = _collect_texture_identifiers(uuid_hex, username)
        ident = identifiers[0] if identifiers else ""
        if ident:
            if _cape_requires_minecraft_texture_host(version_identifier):
                # Old SkinManagers cache textures by MinecraftProfileTexture.getHash(),
                # which is the URL basename; keep cape distinct from skin.
                ident = f"{ident}_cape"
            return _build_public_cape_url(ident, port)

    if _is_minecraft_texture_url(raw):
        normalized = _normalize_remote_texture_url(raw)
        return normalized or raw

    return raw


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
    safe_type = str(texture_type or "").strip().lower()
    safe_id = str(identifier or "").strip()
    if safe_type not in {"skin", "cape"} or not safe_id:
        return False

    remote_url = _build_histolauncher_texture_url(safe_type, safe_id)
    if not remote_url:
        return False
    probe_urls = []
    proxied_url = _apply_url_proxy(remote_url)
    if proxied_url:
        probe_urls.append(proxied_url)
    if remote_url not in probe_urls:
        probe_urls.append(remote_url)

    for probe_url in probe_urls:
        try:
            req = urllib.request.Request(
                probe_url, headers={"User-Agent": "Histolauncher/1.0"}
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                ctype = str(resp.headers.get("Content-Type", "")).lower()
                if "image/" not in ctype:
                    continue
                resp.read(1)
            return True
        except Exception:
            continue
    return False
