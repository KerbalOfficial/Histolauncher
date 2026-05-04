from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
from urllib.parse import unquote, urlparse, quote

from core.logger import colorize_log
from core.settings import _apply_url_proxy, get_base_dir

from server import yggdrasil
from server.http._constants import BASE_DIR
from server.yggdrasil.textures.local import _is_valid_local_texture_file
from server.yggdrasil.textures.urls import (
    _build_minecraft_texture_url,
    _looks_like_minecraft_texture_id,
)


__all__ = ["TextureMixin"]


TEXTURE_ENDPOINT_METADATA_TIMEOUT_SECONDS = 6.0
TEXTURE_ENDPOINT_FETCH_TIMEOUT_SECONDS = 8.0


def _png_dimensions_from_bytes(payload: bytes | None) -> tuple[int, int] | None:
    data = bytes(payload or b"")
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    try:
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
    except Exception:
        return None
    return width, height


def _is_valid_texture_payload(payload: bytes | None, texture_type: str) -> bool:
    dimensions = _png_dimensions_from_bytes(payload)
    if not dimensions:
        return False

    width, height = dimensions
    safe_type = str(texture_type or "").strip().lower()
    if safe_type == "skin":
        if width < 64 or height < 32 or (width % 64) != 0:
            return False
        is_legacy = width == (height * 2) and (height % 32) == 0
        is_modern = width == height and (height % 64) == 0
        return is_legacy or is_modern
    if safe_type == "cape":
        if width < 64 or height < 32:
            return False
        return width == (height * 2) and (width % 64) == 0
    return False


def _ensure_dashed_uuid(u: str) -> str:
    if not u:
        return u
    if "-" in u:
        return u
    s = u.strip()
    if len(s) == 32:
        return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"
    return u


def _safe_texture_cache_identifier(value: str | None) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 160:
        return ""
    if not re.match(r"^[A-Za-z0-9_. -]+$", text):
        return ""
    return text


def _texture_cache_path(
    skins_dir: str,
    identifier: str | None,
    suffix: str,
    *,
    microsoft: bool = False,
) -> str:
    clean_identifier = _safe_texture_cache_identifier(identifier)
    clean_suffix = "skin" if suffix == "skin" else "cape"
    if not clean_identifier:
        return ""
    if microsoft:
        try:
            from server.auth.microsoft import ensure_microsoft_texture_cache_path

            return ensure_microsoft_texture_cache_path(clean_identifier, clean_suffix)
        except Exception:
            return ""
    return os.path.join(skins_dir, f"{clean_identifier}+{clean_suffix}.png")


def _append_texture_cache_candidate(
    candidates: list[str],
    skins_dir: str,
    identifier: str | None,
    suffix: str,
    *,
    microsoft: bool = False,
) -> None:
    path = _texture_cache_path(skins_dir, identifier, suffix, microsoft=microsoft)
    if path and path not in candidates:
        candidates.append(path)


def _append_texture_url_cache_candidates(
    candidates: list[str],
    skins_dir: str,
    remote_url: str | None,
    suffix: str,
    *,
    microsoft: bool = False,
) -> None:
    try:
        parsed = urlparse(str(remote_url or "").strip())
        basename = unquote(os.path.basename(parsed.path or "")).strip()
        identifier = os.path.splitext(basename)[0].strip()
    except Exception:
        identifier = ""
    if identifier:
        _append_texture_cache_candidate(
            candidates,
            skins_dir,
            identifier,
            suffix,
            microsoft=microsoft,
        )


class TextureMixin:
    def _handle_texture_proxy(self, path):
        try:
            parts = path.lstrip("/").split("/")
            if len(parts) < 3:
                self.send_error(404, "Invalid texture path")
                return

            texture_type = parts[1]
            texture_id_raw = unquote("/".join(parts[2:])).strip()
            texture_id = texture_id_raw

            if texture_type not in {"skin", "cape"}:
                self.send_error(404, "Texture type not supported")
                return

            # Old MinecraftSkinManager versions key textures by
            # MinecraftProfileTexture.getHash(), which is the URL basename.
            # The texture property gives the cape a `_cape` suffix so its
            # hash is distinct from the skin's; strip it back out here.
            if texture_type == "cape" and texture_id.endswith("_cape"):
                texture_id = texture_id[: -len("_cape")]

            minecraft_texture_id = ""
            if _looks_like_minecraft_texture_id(texture_id):
                minecraft_texture_id = texture_id.lower()

            uuid_like = bool(
                not minecraft_texture_id
                and re.match(r"^[a-fA-F0-9\-]{32,36}$", texture_id)
            )
            username_fallback = ""
            is_current_profile = False

            if minecraft_texture_id:
                texture_id = minecraft_texture_id
            elif uuid_like:
                texture_uuid_hex = yggdrasil._normalize_uuid_hex(texture_id)
                current_name, current_uuid = yggdrasil._get_username_and_uuid()
                if (
                    str(texture_uuid_hex or texture_id).replace("-", "").lower()
                    == str(current_uuid or "").replace("-", "").lower()
                ):
                    is_current_profile = True
                    username_fallback = (current_name or "").strip()
                elif texture_uuid_hex:
                    username_fallback = str(
                        yggdrasil.STATE.uuid_name_cache.get(texture_uuid_hex) or ""
                    ).strip()
            else:
                username_fallback = texture_id
                texture_id = yggdrasil._ensure_uuid(username_fallback).replace("-", "")

            base_dir = get_base_dir()
            skins_dir = os.path.join(base_dir, "skins")

            microsoft_enabled = False
            microsoft_auth = None
            try:
                import server.auth.microsoft as microsoft_auth

                microsoft_enabled = microsoft_auth.microsoft_account_enabled()
            except Exception:
                microsoft_enabled = False
                microsoft_auth = None

            dashed = _ensure_dashed_uuid(texture_id)
            local_path = None
            microsoft_metadata = None
            microsoft_metadata_loaded = False
            use_microsoft_profile_metadata = bool(uuid_like or username_fallback)

            def get_microsoft_metadata():
                nonlocal microsoft_metadata, microsoft_metadata_loaded
                if microsoft_metadata_loaded:
                    return microsoft_metadata
                microsoft_metadata_loaded = True
                if not (
                    microsoft_enabled
                    and microsoft_auth
                    and use_microsoft_profile_metadata
                ):
                    return None
                try:
                    microsoft_metadata = microsoft_auth.resolve_microsoft_texture_metadata(
                        texture_id if uuid_like else "",
                        username_fallback,
                    )
                except Exception:
                    microsoft_metadata = None
                return microsoft_metadata

            cache_age = 31536000

            if texture_type == "skin" and microsoft_enabled and microsoft_auth:
                for library_id in (texture_id_raw, texture_id):
                    try:
                        library_path = microsoft_auth.resolve_microsoft_local_skin_path(library_id)
                    except Exception:
                        library_path = ""
                    if _is_valid_local_texture_file(library_path, "skin"):
                        local_path = library_path
                        texture_id = os.path.splitext(os.path.basename(library_path))[0]
                        break
                    try:
                        library_path = microsoft_auth.resolve_microsoft_default_skin_path(library_id)
                    except Exception:
                        library_path = ""
                    if _is_valid_local_texture_file(library_path, "skin"):
                        local_path = library_path
                        texture_id = os.path.splitext(os.path.basename(library_path))[0]
                        break
                if not local_path:
                    microsoft_metadata = get_microsoft_metadata()
                    microsoft_local_skin_id = str(
                        (microsoft_metadata or {}).get("local_skin_id") or ""
                    ).strip()
                    microsoft_default_skin_id = str(
                        (microsoft_metadata or {}).get("default_skin_id") or ""
                    ).strip()
                    if microsoft_local_skin_id:
                        try:
                            library_path = microsoft_auth.resolve_microsoft_local_skin_path(
                                microsoft_local_skin_id
                            )
                        except Exception:
                            library_path = ""
                        if _is_valid_local_texture_file(library_path, "skin"):
                            local_path = library_path
                            texture_id = os.path.splitext(os.path.basename(library_path))[0]
                    if not local_path and microsoft_default_skin_id:
                        try:
                            library_path = microsoft_auth.resolve_microsoft_default_skin_path(
                                microsoft_default_skin_id
                            )
                        except Exception:
                            library_path = ""
                        if _is_valid_local_texture_file(library_path, "skin"):
                            local_path = library_path
                            texture_id = os.path.splitext(os.path.basename(library_path))[0]

            if texture_type == "skin" and not local_path:
                skin_path_candidates = []
                if microsoft_enabled:
                    microsoft_metadata = get_microsoft_metadata()
                    _append_texture_url_cache_candidates(
                        skin_path_candidates,
                        skins_dir,
                        (microsoft_metadata or {}).get("skin"),
                        "skin",
                        microsoft=True,
                    )
                    _append_texture_cache_candidate(
                        skin_path_candidates, skins_dir, dashed, "skin", microsoft=True
                    )
                    _append_texture_cache_candidate(
                        skin_path_candidates, skins_dir, texture_id, "skin", microsoft=True
                    )
                    if username_fallback:
                        _append_texture_cache_candidate(
                            skin_path_candidates,
                            skins_dir,
                            username_fallback,
                            "skin",
                            microsoft=True,
                        )

                if not (microsoft_enabled and is_current_profile):
                    _append_texture_cache_candidate(skin_path_candidates, skins_dir, dashed, "skin")
                    _append_texture_cache_candidate(skin_path_candidates, skins_dir, texture_id, "skin")

                    if username_fallback:
                        _append_texture_cache_candidate(
                            skin_path_candidates, skins_dir, username_fallback, "skin"
                        )

                for candidate in skin_path_candidates:
                    if _is_valid_local_texture_file(candidate, "skin"):
                        local_path = candidate
                        texture_id = os.path.splitext(os.path.basename(candidate))[0]
                        break

            if texture_type == "cape" and not local_path:
                cape_path_candidates = []
                if microsoft_enabled:
                    microsoft_metadata = get_microsoft_metadata()
                    _append_texture_url_cache_candidates(
                        cape_path_candidates,
                        skins_dir,
                        (microsoft_metadata or {}).get("cape"),
                        "cape",
                        microsoft=True,
                    )
                    _append_texture_cache_candidate(
                        cape_path_candidates, skins_dir, dashed, "cape", microsoft=True
                    )
                    _append_texture_cache_candidate(
                        cape_path_candidates, skins_dir, texture_id, "cape", microsoft=True
                    )
                    if username_fallback:
                        _append_texture_cache_candidate(
                            cape_path_candidates,
                            skins_dir,
                            username_fallback,
                            "cape",
                            microsoft=True,
                        )

                if not (microsoft_enabled and is_current_profile):
                    _append_texture_cache_candidate(cape_path_candidates, skins_dir, dashed, "cape")
                    _append_texture_cache_candidate(cape_path_candidates, skins_dir, texture_id, "cape")
                    if username_fallback:
                        _append_texture_cache_candidate(
                            cape_path_candidates, skins_dir, username_fallback, "cape"
                        )

                for candidate in cape_path_candidates:
                    if _is_valid_local_texture_file(candidate, "cape"):
                        local_path = candidate
                        texture_id = os.path.splitext(os.path.basename(candidate))[0]
                        break

            if local_path:
                try:
                    with open(local_path, "rb") as f:
                        texture_data = f.read()

                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(texture_data)))
                    self.send_header("Cache-Control", f"public, max-age={cache_age}")
                    self.end_headers()
                    self.wfile.write(texture_data)
                    print(colorize_log(
                        f"[http_server] served local {texture_type}: {texture_id}"
                    ))
                except Exception as e:
                    print(colorize_log(
                        f"[http_server] error reading {texture_type} file: {e}"
                    ))
                    self.send_error(500, f"Error reading {texture_type}")
                return

            microsoft_remote_url = None
            try:
                if microsoft_enabled and microsoft_auth and use_microsoft_profile_metadata:
                    microsoft_metadata = get_microsoft_metadata()
                    microsoft_remote_url = str(
                        (microsoft_metadata or {}).get(texture_type) or ""
                    ).strip() or microsoft_auth.resolve_microsoft_texture_url(
                        texture_type,
                        texture_id if uuid_like else "",
                        username_fallback,
                    )
            except Exception as e:
                print(colorize_log(
                    f"[http_server] Microsoft texture metadata lookup failed: {e}"
                ))

            remote_identifiers = []
            if minecraft_texture_id:
                remote_identifiers.append(minecraft_texture_id)
            elif dashed:
                remote_identifiers.append(dashed)
            if username_fallback and username_fallback not in remote_identifiers:
                remote_identifiers.append(username_fallback)

            last_http_error = None
            metadata_remote_url = None
            if not minecraft_texture_id:
                metadata_remote_url = yggdrasil._resolve_remote_texture_url(
                    texture_type,
                    texture_id if uuid_like else "",
                    username_fallback,
                    timeout_seconds=TEXTURE_ENDPOINT_METADATA_TIMEOUT_SECONDS,
                    force_refresh_missing=True,
                )

            remote_urls = []

            def add_remote_url(candidate: str | None) -> None:
                value = str(candidate or "").strip()
                if value and value not in remote_urls:
                    remote_urls.append(value)

            if minecraft_texture_id:
                minecraft_remote_url = _build_minecraft_texture_url(minecraft_texture_id)
                add_remote_url(minecraft_remote_url)

            add_remote_url(microsoft_remote_url)
            add_remote_url(metadata_remote_url)

            for rid in remote_identifiers:
                if _looks_like_minecraft_texture_id(rid):
                    add_remote_url(_build_minecraft_texture_url(rid))

            for rid in remote_identifiers:
                if _looks_like_minecraft_texture_id(rid):
                    continue
                if microsoft_enabled and is_current_profile:
                    continue
                fallback_remote_url = (
                    f"https://textures.histolauncher.org/{texture_type}/"
                    f"{quote(str(rid), safe='')}"
                )
                add_remote_url(fallback_remote_url)

            last_network_error = None
            for remote_url in remote_urls:
                remote_is_minecraft_texture = False
                try:
                    remote_is_minecraft_texture = (
                        str(urlparse(remote_url).netloc or "").strip().lower()
                        == "textures.minecraft.net"
                    )
                except Exception:
                    remote_is_minecraft_texture = False

                microsoft_cache = bool(
                    microsoft_enabled
                    and (
                        (microsoft_remote_url and remote_url == microsoft_remote_url)
                        or remote_is_minecraft_texture
                    )
                )
                probe_urls = []
                proxied_url = _apply_url_proxy(remote_url)
                if proxied_url:
                    probe_urls.append(proxied_url)
                if remote_url not in probe_urls:
                    probe_urls.append(remote_url)

                for probe_url in probe_urls:
                    try:
                        req = urllib.request.Request(
                            probe_url,
                            headers={"User-Agent": "Histolauncher/1.0"},
                        )
                        with urllib.request.urlopen(
                            req, timeout=TEXTURE_ENDPOINT_FETCH_TIMEOUT_SECONDS
                        ) as resp:
                            payload = resp.read()
                            resp_ctype = resp.headers.get("Content-Type", "")

                        if not _is_valid_texture_payload(payload, texture_type):
                            print(colorize_log(
                                f"[http_server] remote {texture_type} was not a valid "
                                f"Minecraft texture: {remote_url} "
                                f"(content-type={resp_ctype or 'unknown'})"
                            ))
                            continue

                        try:
                            os.makedirs(skins_dir, exist_ok=True)
                            save_ids = []
                            for rid in remote_identifiers:
                                if rid and rid not in save_ids:
                                    save_ids.append(rid)
                            try:
                                parsed_id = urlparse(remote_url)
                                id_from_url = os.path.splitext(
                                    os.path.basename(parsed_id.path)
                                )[0]
                                if id_from_url and id_from_url not in save_ids:
                                    save_ids.append(unquote(id_from_url))
                            except Exception:
                                pass

                            for sid in save_ids:
                                if not sid:
                                    continue
                                try:
                                    suffix = "skin" if texture_type == "skin" else "cape"
                                    fname = _texture_cache_path(
                                        skins_dir,
                                        sid,
                                        suffix,
                                        microsoft=microsoft_cache,
                                    )
                                    if not fname:
                                        continue
                                    os.makedirs(os.path.dirname(fname), exist_ok=True)
                                    with open(fname, "wb") as wf:
                                        wf.write(payload)
                                    print(colorize_log(
                                        f"[http_server] cached remote {texture_type} "
                                        f"-> {fname}"
                                    ))
                                except Exception as e:
                                    print(colorize_log(
                                        f"[http_server] failed to cache {texture_type} "
                                        f"-> {sid}: {e}"
                                    ))
                        except Exception:
                            pass

                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Content-Length", str(len(payload)))
                        self.send_header("Cache-Control", f"public, max-age={cache_age}")
                        self.end_headers()
                        self.wfile.write(payload)
                        print(colorize_log(
                            f"[http_server] proxied remote {texture_type}: "
                            f"{remote_url} via {probe_url}"
                        ))
                        return
                    except urllib.error.HTTPError as e:
                        last_http_error = e
                        print(colorize_log(
                            f"[http_server] remote {texture_type} not found: "
                            f"{remote_url} ({e.code})"
                        ))
                        continue
                    except Exception as e:
                        last_network_error = e
                        print(colorize_log(
                            f"[http_server] remote {texture_type} proxy failed for "
                            f"{remote_url}: {e}"
                        ))
                        continue

            if texture_type != "skin":
                if last_network_error is not None and last_http_error is None:
                    try:
                        self.send_error(502, "Texture proxy error")
                    except Exception:
                        pass
                    return
                try:
                    self.send_error(404, "Cape not found")
                except Exception:
                    pass
                return
            try:
                placeholder = os.path.join(
                    BASE_DIR, "ui", "assets", "images", "unknown_skin.png"
                )
                if os.path.exists(placeholder):
                    with open(placeholder, "rb") as f:
                        payload = f.read()
                    if not _is_valid_texture_payload(payload, "skin"):
                        raise ValueError("unknown skin placeholder is not a valid skin")
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Cache-Control", f"public, max-age={cache_age}")
                    self.end_headers()
                    self.wfile.write(payload)
                    print(colorize_log(
                        "[http_server] served unknown skin as final fallback"
                    ))
                    return
            except Exception:
                pass
            try:
                is_network_failure = (
                    last_network_error is not None and last_http_error is None
                )
                self.send_error(
                    502 if is_network_failure else 404,
                    "Texture proxy error" if is_network_failure else "Texture not found",
                )
            except Exception:
                pass
        except Exception as e:
            print(colorize_log(f"[http_server] error handling texture request: {e}"))
            self.send_error(500, "Internal server error")
