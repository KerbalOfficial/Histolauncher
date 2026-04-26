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


__all__ = ["TextureMixin"]


def _ensure_dashed_uuid(u: str) -> str:
    if not u:
        return u
    if "-" in u:
        return u
    s = u.strip()
    if len(s) == 32:
        return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"
    return u


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

            uuid_like = bool(re.match(r"^[a-fA-F0-9\-]{32,36}$", texture_id))
            username_fallback = ""

            if uuid_like:
                current_name, current_uuid = yggdrasil._get_username_and_uuid()
                if (
                    texture_id.replace("-", "").lower()
                    == str(current_uuid or "").replace("-", "").lower()
                ):
                    username_fallback = (current_name or "").strip()
            else:
                username_fallback = texture_id
                texture_id = yggdrasil._ensure_uuid(username_fallback).replace("-", "")

            base_dir = get_base_dir()
            skins_dir = os.path.join(base_dir, "skins")

            dashed = _ensure_dashed_uuid(texture_id)
            local_path = None

            cache_age = 31536000

            if texture_type == "skin":
                skin_path_candidates = [
                    os.path.join(skins_dir, f"{dashed}+skin.png"),
                    os.path.join(skins_dir, f"{texture_id}+skin.png"),
                ]

                if username_fallback:
                    skin_path_candidates.extend([
                        os.path.join(skins_dir, f"{username_fallback}+skin.png"),
                    ])

                for candidate in skin_path_candidates:
                    if os.path.exists(candidate) and os.path.isfile(candidate):
                        local_path = candidate
                        texture_id = os.path.splitext(os.path.basename(candidate))[0]
                        break

            if texture_type == "cape" and not local_path:
                cape_path_candidates = [
                    os.path.join(skins_dir, f"{dashed}+cape.png"),
                    os.path.join(skins_dir, f"{texture_id}+cape.png"),
                ]
                if username_fallback:
                    cape_path_candidates.append(
                        os.path.join(skins_dir, f"{username_fallback}+cape.png")
                    )

                for candidate in cape_path_candidates:
                    if os.path.exists(candidate) and os.path.isfile(candidate):
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

            if not yggdrasil._histolauncher_account_enabled():
                if texture_type != "skin":
                    try:
                        self.send_error(404, "Cape not found")
                    except Exception:
                        pass
                    return
                try:
                    placeholder = os.path.join(
                        BASE_DIR, "ui", "assets", "images", "version_placeholder.png"
                    )
                    if os.path.exists(placeholder):
                        with open(placeholder, "rb") as f:
                            payload = f.read()
                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Content-Length", str(len(payload)))
                        self.send_header(
                            "Cache-Control", f"public, max-age={cache_age}"
                        )
                        self.end_headers()
                        self.wfile.write(payload)
                        print(colorize_log(
                            "[http_server] served placeholder skin with "
                            "Histolauncher account disabled"
                        ))
                        return
                except Exception:
                    pass
                try:
                    self.send_error(404, "Texture not found")
                except Exception:
                    pass
                return

            remote_identifiers = []
            if dashed:
                remote_identifiers.append(dashed)
            if username_fallback and username_fallback not in remote_identifiers:
                remote_identifiers.append(username_fallback)

            last_http_error = None
            metadata_remote_url = yggdrasil._resolve_remote_texture_url(
                texture_type,
                texture_id if uuid_like else "",
                username_fallback,
            )

            remote_urls = []
            if metadata_remote_url:
                remote_urls.append(metadata_remote_url)

            for rid in remote_identifiers:
                fallback_remote_url = (
                    f"https://textures.histolauncher.org/{texture_type}/"
                    f"{quote(str(rid), safe='')}"
                )
                if fallback_remote_url not in remote_urls:
                    remote_urls.append(fallback_remote_url)

            for remote_url in remote_urls:
                try:
                    probe_url = _apply_url_proxy(remote_url)
                    req = urllib.request.Request(
                        probe_url,
                        headers={"User-Agent": "Histolauncher/1.0"},
                    )
                    with urllib.request.urlopen(req, timeout=6) as resp:
                        payload = resp.read()
                        resp_ctype = resp.headers.get("Content-Type", "")

                    try:
                        if "image/" in (resp_ctype or "").lower():
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
                                    fname = os.path.join(
                                        skins_dir, f"{sid}+{suffix}.png"
                                    )
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
                    print(colorize_log(
                        f"[http_server] remote {texture_type} proxy failed for "
                        f"{remote_url}: {e}"
                    ))
                    try:
                        self.send_error(502, "Texture proxy error")
                    except Exception:
                        pass
                    return

            if last_http_error is not None:
                try:
                    self.send_error(
                        404,
                        "Cape not found" if texture_type == "cape" else "Texture not found",
                    )
                except Exception:
                    pass
                return
            if texture_type != "skin":
                try:
                    self.send_error(404, "Cape not found")
                except Exception:
                    pass
                return
            try:
                placeholder = os.path.join(
                    BASE_DIR, "ui", "assets", "images", "version_placeholder.png"
                )
                if os.path.exists(placeholder):
                    with open(placeholder, "rb") as f:
                        payload = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Cache-Control", f"public, max-age={cache_age}")
                    self.end_headers()
                    self.wfile.write(payload)
                    print(colorize_log(
                        "[http_server] served placeholder skin as final fallback"
                    ))
                    return
            except Exception:
                pass
        except Exception as e:
            print(colorize_log(f"[http_server] error handling texture request: {e}"))
            self.send_error(500, "Internal server error")
