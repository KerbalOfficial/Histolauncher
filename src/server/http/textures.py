from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
from urllib.parse import parse_qs, unquote, urlparse, quote

from core.logger import colorize_log
from core.skin_legacy import (
    convert_skin_to_legacy_format,
    merge_skin_overlay_into_base,
    normalize_skin_limb_mirror,
    normalize_skin_overlay_parts,
    normalize_skin_overlay_parts_for_texture_type,
    normalize_skin_texture_type,
)
from core.settings import _apply_url_proxy, get_base_dir

from server import yggdrasil
from server.yggdrasil.textures.local import _is_valid_local_texture_file
from server.yggdrasil.textures.urls import (
    _build_minecraft_texture_url,
    _looks_like_minecraft_texture_id,
)


__all__ = ["TextureMixin"]


TEXTURE_ENDPOINT_METADATA_TIMEOUT_SECONDS = 8.0
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


def _crop_skin_to_legacy_format(
    png_data: bytes,
    overlay_parts=None,
    arm_mirror="right",
    leg_mirror="right",
) -> bytes:
    return convert_skin_to_legacy_format(
        png_data,
        overlay_parts=overlay_parts,
        arm_mirror=arm_mirror,
        leg_mirror=leg_mirror,
    )


def _query_value(query: dict, *keys: str) -> str:
    for key in keys:
        values = query.get(key)
        if values:
            return str(values[0] or "").strip()
    return ""


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
            # Strip query string and detect legacy (Classic) format flag before
            # splitting the path into its components.
            _qs_sep = path.find("?")
            _qs = path[_qs_sep + 1 :] if _qs_sep >= 0 else ""
            path_clean = path[:_qs_sep] if _qs_sep >= 0 else path
            legacy_format = "legacy=1" in _qs
            legacy_overlay_parts = []
            legacy_arm_mirror = "right"
            legacy_leg_mirror = "right"
            explicit_legacy_overlay_parts = False
            explicit_legacy_arm_mirror = False
            explicit_legacy_leg_mirror = False
            if legacy_format:
                query = parse_qs(_qs, keep_blank_values=True)
                explicit_legacy_overlay_parts = bool(
                    query.get("overlay") or query.get("overlays") or query.get("parts")
                )
                legacy_overlay_parts = normalize_skin_overlay_parts(
                    query.get("overlay") or query.get("overlays") or query.get("parts")
                )
                raw_arm_mirror = _query_value(query, "arm_mirror", "armMirror", "arm")
                raw_leg_mirror = _query_value(query, "leg_mirror", "legMirror", "leg")
                explicit_legacy_arm_mirror = bool(raw_arm_mirror)
                explicit_legacy_leg_mirror = bool(raw_leg_mirror)
                legacy_arm_mirror = normalize_skin_limb_mirror(raw_arm_mirror)
                legacy_leg_mirror = normalize_skin_limb_mirror(raw_leg_mirror)

            parts = path_clean.lstrip("/").split("/")
            if len(parts) < 3:
                self.send_error(404, "Invalid texture path")
                return

            texture_type = parts[1].strip().lower()
            texture_id_raw = unquote("/".join(parts[2:])).strip()
            texture_id = texture_id_raw

            if texture_type not in {"skin", "cape", "raw"}:
                self.send_error(404, "Texture type not supported")
                return
            if texture_type == "raw" and not _looks_like_minecraft_texture_id(texture_id_raw):
                self.send_error(404, "Invalid raw texture id")
                return

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
                cached_name = str(
                    yggdrasil.STATE.uuid_name_cache.get(texture_uuid_hex) or ""
                ).strip() if texture_uuid_hex else ""
                if cached_name:
                    username_fallback = cached_name
                else:
                    current_name, current_uuid = yggdrasil._get_username_and_uuid()
                    if yggdrasil._profile_matches_active_player(texture_uuid_hex, current_name):
                        username_fallback = (current_name or "").strip()
            else:
                username_fallback = texture_id
                texture_id = yggdrasil._ensure_uuid(username_fallback).replace("-", "")

            if not is_current_profile and texture_type != "raw":
                is_current_profile = yggdrasil._profile_matches_active_player(
                    texture_id,
                    username_fallback,
                )

            base_dir = get_base_dir()
            skins_dir = os.path.join(base_dir, "skins")

            microsoft_enabled = False
            microsoft_auth = None
            microsoft_lookup_id = texture_id if uuid_like else ""
            microsoft_lookup_name = username_fallback
            try:
                import server.auth.microsoft as microsoft_auth

                microsoft_enabled = microsoft_auth.microsoft_account_enabled()
            except Exception:
                microsoft_enabled = False
                microsoft_auth = None

            if microsoft_enabled and is_current_profile:
                try:
                    active_name, active_uuid = yggdrasil._get_username_and_uuid()
                    microsoft_lookup_id = str(active_uuid or "")
                    microsoft_lookup_name = str(active_name or "").strip()
                except Exception:
                    pass

            dashed = _ensure_dashed_uuid(texture_id)
            local_path = None
            microsoft_metadata = None
            microsoft_metadata_loaded = False
            use_microsoft_profile_metadata = bool(uuid_like or username_fallback)

            if texture_type == "raw":
                raw_candidates: list[tuple[str, str]] = []
                for candidate_type in ("skin", "cape"):
                    path = _texture_cache_path(
                        skins_dir,
                        texture_id,
                        candidate_type,
                        microsoft=microsoft_enabled,
                    )
                    if path:
                        raw_candidates.append((path, candidate_type))
                    path = _texture_cache_path(skins_dir, texture_id, candidate_type)
                    if path:
                        raw_candidates.append((path, candidate_type))
                seen_raw_paths: set[str] = set()
                for candidate, candidate_type in raw_candidates:
                    if not candidate or candidate in seen_raw_paths:
                        continue
                    seen_raw_paths.add(candidate)
                    if _is_valid_local_texture_file(candidate, candidate_type):
                        local_path = candidate
                        texture_type = candidate_type
                        texture_id = os.path.splitext(os.path.basename(candidate))[0]
                        break

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
                        microsoft_lookup_id,
                        microsoft_lookup_name,
                    )
                except Exception:
                    microsoft_metadata = None
                return microsoft_metadata

            def get_legacy_conversion_options():
                overlay_parts = list(legacy_overlay_parts)
                arm_mirror = legacy_arm_mirror
                leg_mirror = legacy_leg_mirror
                try:
                    metadata = get_microsoft_metadata() or {}
                    source_height = int(metadata.get("texture_height") or 0) or None
                    metadata_arm_mirror = normalize_skin_limb_mirror(
                        metadata.get("legacy_arm_mirror")
                    )
                    metadata_leg_mirror = normalize_skin_limb_mirror(
                        metadata.get("legacy_leg_mirror")
                    )
                    metadata_texture_type = normalize_skin_texture_type(
                        metadata.get("texture_type"),
                        source_height=source_height,
                    )
                    if not explicit_legacy_overlay_parts:
                        overlay_parts = normalize_skin_overlay_parts_for_texture_type(
                            metadata.get("legacy_overlay_parts"),
                            texture_type=metadata_texture_type,
                            source_height=source_height,
                            arm_mirror=metadata_arm_mirror,
                            leg_mirror=metadata_leg_mirror,
                        )
                    if not explicit_legacy_arm_mirror:
                        arm_mirror = metadata_arm_mirror
                    if not explicit_legacy_leg_mirror:
                        leg_mirror = metadata_leg_mirror
                except Exception:
                    pass
                return overlay_parts, arm_mirror, leg_mirror

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

                    if texture_type == "skin":
                        if legacy_format:
                            overlay_parts, arm_mirror, leg_mirror = get_legacy_conversion_options()
                            texture_data = _crop_skin_to_legacy_format(
                                texture_data,
                                overlay_parts=overlay_parts,
                                arm_mirror=arm_mirror,
                                leg_mirror=leg_mirror,
                            )
                        else:
                            try:
                                metadata = get_microsoft_metadata() or {}
                                source_height = int(metadata.get("texture_height") or 0) or None
                                metadata_texture_type = normalize_skin_texture_type(
                                    metadata.get("texture_type"),
                                    source_height=source_height,
                                )
                                overlay_parts = normalize_skin_overlay_parts_for_texture_type(
                                    metadata.get("legacy_overlay_parts"),
                                    texture_type=metadata_texture_type,
                                    source_height=source_height,
                                    arm_mirror=metadata.get("legacy_arm_mirror"),
                                    leg_mirror=metadata.get("legacy_leg_mirror"),
                                )
                                if overlay_parts:
                                    texture_data = merge_skin_overlay_into_base(
                                        texture_data,
                                        overlay_parts=overlay_parts,
                                    )
                            except Exception:
                                pass

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
                if texture_type != "raw" and microsoft_enabled and microsoft_auth and use_microsoft_profile_metadata:
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
            if texture_type != "raw" and not minecraft_texture_id:
                metadata_remote_url = yggdrasil._resolve_remote_texture_url(
                    texture_type,
                    texture_id if uuid_like else "",
                    username_fallback,
                    timeout_seconds=TEXTURE_ENDPOINT_METADATA_TIMEOUT_SECONDS,
                    force_refresh_missing=False,
                )
                if not metadata_remote_url:
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

            allow_histolauncher_fallback = not minecraft_texture_id

            for rid in remote_identifiers:
                if _looks_like_minecraft_texture_id(rid):
                    continue
                if texture_type == "raw":
                    continue
                if not allow_histolauncher_fallback:
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
                skip_direct = bool(
                    proxied_url
                    and "textures.histolauncher.org" in remote_url.lower()
                )
                if remote_url not in probe_urls and not skip_direct:
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

                        response_texture_type = texture_type
                        if texture_type == "raw":
                            if _is_valid_texture_payload(payload, "skin"):
                                response_texture_type = "skin"
                            elif _is_valid_texture_payload(payload, "cape"):
                                response_texture_type = "cape"
                            else:
                                print(colorize_log(
                                    f"[http_server] remote raw texture was not a valid "
                                    f"Minecraft skin or cape: {remote_url} "
                                    f"(content-type={resp_ctype or 'unknown'})"
                                ))
                                continue
                        elif not _is_valid_texture_payload(payload, texture_type):
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
                                    fname = _texture_cache_path(
                                        skins_dir,
                                        sid,
                                        response_texture_type,
                                        microsoft=microsoft_cache,
                                    )
                                    if not fname:
                                        continue
                                    os.makedirs(os.path.dirname(fname), exist_ok=True)
                                    with open(fname, "wb") as wf:
                                        wf.write(payload)
                                    print(colorize_log(
                                        f"[http_server] cached remote {response_texture_type} "
                                        f"-> {fname}"
                                    ))
                                except Exception as e:
                                    print(colorize_log(
                                        f"[http_server] failed to cache {response_texture_type} "
                                        f"-> {sid}: {e}"
                                    ))
                        except Exception:
                            pass

                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
                        serve_payload = payload
                        if legacy_format and response_texture_type == "skin":
                            overlay_parts, arm_mirror, leg_mirror = get_legacy_conversion_options()
                            serve_payload = _crop_skin_to_legacy_format(
                                payload,
                                overlay_parts=overlay_parts,
                                arm_mirror=arm_mirror,
                                leg_mirror=leg_mirror,
                            )
                        self.send_header("Content-Length", str(len(serve_payload)))
                        self.send_header("Cache-Control", f"public, max-age={cache_age}")
                        self.end_headers()
                        self.wfile.write(serve_payload)
                        print(colorize_log(
                            f"[http_server] proxied remote {response_texture_type}: "
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
                    self.send_error(404, "Cape not found" if texture_type == "cape" else "Texture not found")
                except Exception:
                    pass
                return
            try:
                is_network_failure = (
                    last_network_error is not None and last_http_error is None
                )
                if not is_network_failure:
                    print(colorize_log(
                        f"[http_server] skin not available; letting Minecraft use default skin: {texture_id_raw}"
                    ))
                self.send_error(
                    502 if is_network_failure else 404,
                    "Texture proxy error" if is_network_failure else "Texture not found",
                )
            except Exception:
                pass
        except Exception as e:
            print(colorize_log(f"[http_server] error handling texture request: {e}"))
            self.send_error(500, "Internal server error")
