from __future__ import annotations

import mimetypes
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import unquote, urlparse, quote
from xml.sax.saxutils import escape as _xml_escape

from core.logger import colorize_log
from core.settings import _apply_url_proxy, get_base_dir

from server import yggdrasil
from server.http._constants import BASE_DIR


__all__ = ["ProxyMixin"]


class ProxyMixin:
    def _get_histolauncher_auth_cookie_header(self) -> str:
        try:
            from server.auth import load_histolauncher_cookie_header

            return load_histolauncher_cookie_header()
        except Exception:
            return ""

    def _rewrite_histolauncher_texture_metadata_payload(self, payload: bytes) -> bytes:
        import json

        try:
            data = json.loads((payload or b"").decode("utf-8", errors="replace"))
        except Exception:
            return payload

        if not isinstance(data, dict):
            return payload

        def rewrite_texture_url(raw_url: str) -> str:
            parsed = urlparse(str(raw_url or "").strip())
            host = str(parsed.netloc or "").strip().lower()
            if host != "textures.histolauncher.org":
                return raw_url

            proxied = f"/histolauncher-proxy/textures{parsed.path or '/'}"
            if parsed.query:
                proxied += f"?{parsed.query}"
            return proxied

        for key in ("skin", "cape"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                data[key] = rewrite_texture_url(value)

        return json.dumps(data).encode("utf-8")

    def _proxy_histolauncher_remote_request(
        self,
        base_url: str,
        upstream_path: str,
        *,
        method: str = "GET",
        body_bytes: bytes | None = None,
        content_type: str = "",
        include_auth_cookie: bool = False,
    ) -> bool:
        safe_path = "/" + str(upstream_path or "").lstrip("/")
        target_url = base_url.rstrip("/") + safe_path
        candidate_urls = []

        proxied = _apply_url_proxy(target_url)
        if proxied:
            candidate_urls.append(proxied)
        if target_url not in candidate_urls:
            candidate_urls.append(target_url)

        for idx, url in enumerate(candidate_urls):
            try:
                headers = {"User-Agent": "Histolauncher/1.0"}
                if content_type:
                    headers["Content-Type"] = content_type

                if include_auth_cookie:
                    cookie_header = self._get_histolauncher_auth_cookie_header()
                    if cookie_header:
                        headers["Cookie"] = cookie_header

                req = urllib.request.Request(
                    url,
                    data=body_bytes,
                    headers=headers,
                    method=method,
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    payload = resp.read()
                    status = getattr(resp, "status", None) or resp.getcode()
                    response_headers = resp.headers

                if (
                    base_url.rstrip("/").endswith("textures.histolauncher.org")
                    and safe_path.split("?", 1)[0].startswith("/model/")
                ):
                    payload = self._rewrite_histolauncher_texture_metadata_payload(payload)

                self.send_response(status)
                for header_name in (
                    "Content-Type",
                    "Cache-Control",
                    "ETag",
                    "Last-Modified",
                    "Content-Disposition",
                ):
                    header_value = response_headers.get(header_name)
                    if header_value:
                        self.send_header(header_name, header_value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if method.upper() != "HEAD":
                    self.wfile.write(payload)
                return True
            except urllib.error.HTTPError as e:
                should_retry = idx == 0 and len(candidate_urls) > 1 and e.code >= 500
                if should_retry:
                    continue

                try:
                    payload = e.read()
                except Exception:
                    payload = b""

                self.send_response(e.code)
                response_headers = getattr(e, "headers", None)
                if response_headers:
                    for header_name in (
                        "Content-Type",
                        "Cache-Control",
                        "ETag",
                        "Last-Modified",
                        "Content-Disposition",
                    ):
                        header_value = response_headers.get(header_name)
                        if header_value:
                            self.send_header(header_name, header_value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if method.upper() != "HEAD" and payload:
                    self.wfile.write(payload)
                return True
            except Exception as e:
                if idx < len(candidate_urls) - 1:
                    continue
                print(colorize_log(
                    f"[http_server] remote Histolauncher proxy failed: {target_url} - {e}"
                ))
                try:
                    self.send_error(502, "Bad Gateway")
                except Exception:
                    pass
                return True

        return False

    def _handle_allowlisted_remote_proxy(self, scheme: str, target: str) -> bool:
        target_clean = str(target or "").lstrip("/")
        if not target_clean:
            return False

        if self._try_bridge_modern_profile_lookup_get(target_clean):
            return True

        if self._try_bridge_classic_world_list(target_clean):
            return True

        if self._try_bridge_legacy_skin_target(target_clean):
            return True

        domain = target_clean.split("/", 1)[0].lower()
        allowed_hosts = {
            "s3.amazonaws.com",
            "minecraft.net",
            "www.minecraft.net",
            "skins.minecraft.net",
            "textures.minecraft.net",
            "resources.download.minecraft.net",
            "textures.histolauncher.org",
        }
        if domain not in allowed_hosts:
            return False

        if self._try_serve_legacy_resource_fallback(target_clean):
            return True

        url = f"{scheme}://{target_clean}"
        candidate_urls = []
        proxied_url = _apply_url_proxy(url)
        if proxied_url:
            candidate_urls.append(proxied_url)
        if url not in candidate_urls:
            candidate_urls.append(url)

        for idx, candidate_url in enumerate(candidate_urls):
            try:
                req = urllib.request.Request(
                    candidate_url, headers={"User-Agent": "Histolauncher/1.0"}
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    payload = resp.read()
                    ctype = resp.headers.get("Content-Type", "application/octet-stream")
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    try:
                        p = urlparse(url)
                        if "image/" in str(ctype).lower():
                            ident = os.path.splitext(os.path.basename(p.path))[0]
                            tex_type = None
                            if re.search(r"(?i)minecraftskins|/skin/", p.path):
                                tex_type = "skin"
                            elif re.search(r"(?i)minecraftcloaks|/cloak|/cape/", p.path):
                                tex_type = "cape"

                            if tex_type and ident:
                                try:
                                    cache_dir = os.path.join(get_base_dir(), "skins")
                                    os.makedirs(cache_dir, exist_ok=True)
                                    cache_name = os.path.join(
                                        cache_dir, f"{ident}+{tex_type}.png"
                                    )
                                    with open(cache_name, "wb") as wf:
                                        wf.write(payload)
                                    print(colorize_log(
                                        f"[http_server] cached proxied {tex_type}: {cache_name}"
                                    ))
                                except Exception as e:
                                    print(colorize_log(
                                        f"[http_server] failed to cache proxied texture: {e}"
                                    ))
                    except Exception:
                        pass
                    print(colorize_log(
                        f"[http_server] proxied external resource: {url} via {candidate_url}"
                    ))
                    return True
            except urllib.error.HTTPError as e:
                should_retry = idx == 0 and len(candidate_urls) > 1 and e.code >= 500
                if should_retry:
                    continue
                print(colorize_log(
                    f"[http_server] remote resource not found: {url} ({e.code})"
                ))
                if self._try_serve_legacy_resource_fallback(target_clean):
                    return True
                try:
                    self.send_error(404, "Not Found")
                except Exception:
                    pass
                return True
            except Exception as e:
                if idx < len(candidate_urls) - 1:
                    continue
                print(colorize_log(
                    f"[http_server] remote resource proxy failed: {url} - {e}"
                ))
                if self._try_serve_legacy_resource_fallback(target_clean):
                    return True
                try:
                    self.send_error(502, "Bad Gateway")
                except Exception:
                    pass
                return True

        return True

    def _handle_allowlisted_remote_proxy_post(
        self, scheme: str, target: str, body_bytes: bytes
    ) -> bool:
        target_clean = str(target or "").lstrip("/")
        if not target_clean:
            return False

        domain = target_clean.split("/", 1)[0].lower().split(":", 1)[0]

        if domain in {"snoop.minecraft.net"}:
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True

        if self._try_bridge_modern_profile_lookup_post(target_clean, body_bytes):
            return True

        return False

    def _try_bridge_modern_profile_lookup_get(self, target: str) -> bool:
        parsed = urlparse(f"http://{target}")
        host = (parsed.netloc or "").split(":", 1)[0].lower()
        path = parsed.path or ""

        m = re.match(r"^/users/profiles/minecraft/([^/?]+)$", path)
        if host == "api.mojang.com" and m:
            name = unquote(m.group(1)).strip()
            if not name:
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return True
            current_name, current_uuid = yggdrasil._get_username_and_uuid()
            if (
                str(current_name or "").strip().lower() == name.lower()
                and current_uuid
            ):
                uid_hex = str(current_uuid).replace("-", "")
            else:
                uid_hex = yggdrasil._ensure_uuid(name).replace("-", "")
            self._send_json({"id": uid_hex, "name": name}, status=200)
            print(colorize_log(
                f"[http_server] bridged mojang profile lookup: {name} -> {uid_hex}"
            ))
            return True

        return False

    def _try_bridge_modern_profile_lookup_post(
        self, target: str, body_bytes: bytes
    ) -> bool:
        import json

        parsed = urlparse(f"http://{target}")
        host = (parsed.netloc or "").split(":", 1)[0].lower()
        path = parsed.path or ""

        if host != "api.minecraftservices.com":
            return False

        if not re.match(r"^/minecraft/profile/lookup/bulk/byname$", path):
            return False

        try:
            payload = json.loads((body_bytes or b"").decode("utf-8") or "[]")
        except Exception:
            payload = []

        names = []
        if isinstance(payload, list):
            names = [str(x).strip() for x in payload if str(x).strip()]
        elif isinstance(payload, dict):
            maybe = payload.get("names")
            if isinstance(maybe, list):
                names = [str(x).strip() for x in maybe if str(x).strip()]

        current_name, current_uuid = yggdrasil._get_username_and_uuid()
        out = []
        for name in names:
            if (
                str(current_name or "").strip().lower() == name.lower()
                and current_uuid
            ):
                uid_hex = str(current_uuid).replace("-", "")
            else:
                uid_hex = yggdrasil._ensure_uuid(name).replace("-", "")
            out.append({"id": uid_hex, "name": name})

        self._send_json(out, status=200)
        print(colorize_log(
            f"[http_server] bridged minecraftservices bulk lookup: {len(out)} profile(s)"
        ))
        return True

    def _try_bridge_classic_world_list(self, target: str) -> bool:
        if not re.search(r"(?i)listmaps\.jsp", target):
            return False

        parsed = urlparse(f"http://{target}")
        query = parsed.query or ""
        username = ""

        for param in query.split("&"):
            if "=" in param:
                key, value = param.split("=", 1)
                if key.lower() == "user":
                    username = unquote(value).strip()
                    break

        if not username:
            return False

        try:
            body = b"This system is in development!;-;-;-;Use the button below!"
            ctype = "text/plain; charset=utf-8"

            print(colorize_log(
                f"[http_server] handled listmaps.jsp for user: {username} "
                f"(payload {len(body)} bytes)"
            ))

            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        except Exception as e:
            print(colorize_log(f"[http_server] error listing classic worlds: {e}"))
            self.send_error(500, "Server error")
            return True

    def _try_bridge_legacy_skin_target(self, target: str) -> bool:
        target_norm = str(target or "").replace("\\", "/").lstrip("/")
        if not target_norm:
            return False

        parsed = urlparse(f"http://{target_norm}")
        path = parsed.path or ""
        query = parsed.query or ""

        skin_match = re.search(
            r"(?i)minecraftskins/([^/?]+)\.png(?:\?.*)?$", target_norm
        )
        if skin_match:
            requested_name = unquote(skin_match.group(1)).strip()
            if not requested_name:
                self.send_error(404, "Texture not found")
                return True
            self._handle_texture_proxy(
                f"/texture/skin/{quote(requested_name, safe='')}"
            )
            print(colorize_log(
                f"[http_server] bridged legacy skin URL to texture proxy: {requested_name}"
            ))
            return True

        skin_match_old = re.search(r"(?i)/(?:game/)?skin/([^/?]+)\.png$", path)
        if skin_match_old:
            requested_name = unquote(skin_match_old.group(1)).strip()
            if not requested_name:
                self.send_error(404, "Texture not found")
                return True
            self._handle_texture_proxy(
                f"/texture/skin/{quote(requested_name, safe='')}"
            )
            print(colorize_log(
                f"[http_server] bridged minecraft.net skin URL to texture proxy: "
                f"{requested_name}"
            ))
            return True

        cloak_match = re.search(
            r"(?i)minecraftcloaks/([^/?]+)\.png(?:\?.*)?$", target_norm
        )
        if cloak_match:
            requested_name = unquote(cloak_match.group(1)).strip()
            if not requested_name:
                self.send_error(404, "Cape not found")
                return True
            self._handle_texture_proxy(
                f"/texture/cape/{quote(requested_name, safe='')}"
            )
            print(colorize_log(
                f"[http_server] bridged legacy cloak URL to texture proxy: {requested_name}"
            ))
            return True

        cloak_match_old = re.search(r"(?i)/cloak/get\.jsp$", path)
        if cloak_match_old and query:
            params = dict([p.split("=", 1) for p in query.split("&") if "=" in p])
            if params.get("user"):
                requested_name = unquote(str(params.get("user") or "")).strip()
                if not requested_name:
                    self.send_error(404, "Cape not found")
                    return True
                self._handle_texture_proxy(
                    f"/texture/cape/{quote(requested_name, safe='')}"
                )
                print(colorize_log(
                    f"[http_server] bridged old cloak endpoint to texture proxy: "
                    f"{requested_name}"
                ))
                return True

        return False

    def _legacy_resource_roots(self) -> list[str]:
        return [
            os.path.join(get_base_dir(), "assets", "legacy"),
            os.path.join(get_base_dir(), "legacy_resources"),
            os.path.join(BASE_DIR, "assets", "legacy_resources"),
        ]

    def _legacy_resource_entries(self) -> dict[str, int]:
        audio_roots = ("music", "newmusic", "newsound", "sound", "sound3", "streaming")
        audio_exts = {".mus", ".ogg", ".wav"}
        entries = {}

        for root in self._legacy_resource_roots():
            if not os.path.isdir(root):
                continue
            try:
                for current_dir, _dirs, files in os.walk(root):
                    for filename in files:
                        full_path = os.path.join(current_dir, filename)
                        rel_path = os.path.relpath(full_path, root).replace(os.sep, "/")
                        rel_norm = rel_path.strip("/")
                        if not rel_norm or rel_norm.startswith("../") or "/../" in rel_norm:
                            continue
                        first_part = rel_norm.split("/", 1)[0].lower()
                        ext = os.path.splitext(rel_norm)[1].lower()
                        if first_part not in audio_roots and ext not in audio_exts:
                            continue
                        if rel_norm in entries:
                            continue
                        try:
                            size = os.path.getsize(full_path)
                        except OSError:
                            size = 0
                        entries[rel_norm] = size
            except Exception:
                continue

        return entries

    def _legacy_resource_listing_payload(self) -> bytes:
        entries = self._legacy_resource_entries()

        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">',
            '<Name>MinecraftResources</Name>',
            '<Prefix></Prefix>',
            '<Marker></Marker>',
            f'<MaxKeys>{max(len(entries), 1000)}</MaxKeys>',
            '<IsTruncated>false</IsTruncated>',
        ]
        for key in sorted(entries, key=str.lower):
            escaped_key = _xml_escape(key)
            size = int(entries.get(key) or 0)
            lines.extend([
                '<Contents>',
                f'<Key>{escaped_key}</Key>',
                '<LastModified>2012-03-01T00:00:00.000Z</LastModified>',
                f'<ETag>"{size:x}"</ETag>',
                f'<Size>{size}</Size>',
                '<StorageClass>STANDARD</StorageClass>',
                '</Contents>',
            ])
        lines.append('</ListBucketResult>')
        return ("\n".join(lines) + "\n").encode("utf-8")

    def _legacy_resource_text_listing_payload(self) -> bytes:
        entries = self._legacy_resource_entries()
        lines = [
            f"{key},{int(entries.get(key) or 0)},0"
            for key in sorted(entries, key=str.lower)
        ]
        return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")

    def _try_serve_legacy_resource_fallback(self, target: str) -> bool:
        target_norm = str(target or "").replace("\\", "/").lstrip("/")

        host_match = re.match(r"^([^/]+)/(.*)$", target_norm)
        if host_match:
            first_part = host_match.group(1)
            if "." in first_part or ":" in first_part:
                target_norm = host_match.group(2)

        if re.search(r"(?i)^game/\?[^\s]*\bn=", target_norm):
            try:
                payload = b"0"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(payload)
                print(colorize_log("[http_server] served legacy /game endpoint fallback"))
                return True
            except Exception:
                return False

        if re.search(r"(?i)(?:minecraftresources|resources)/?(?:\?.*)?$", target_norm):
            try:
                is_s3_resource_root = bool(
                    re.search(r"(?i)(?:^|/)minecraftresources/?(?:\?.*)?$", target_norm)
                )
                payload = (
                    self._legacy_resource_listing_payload()
                    if is_s3_resource_root
                    else self._legacy_resource_text_listing_payload()
                )
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/xml; charset=utf-8"
                    if is_s3_resource_root
                    else "text/plain; charset=utf-8",
                )
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(payload)
                if is_s3_resource_root:
                    print(colorize_log(
                        "[http_server] served local legacy resources listing"
                    ))
                else:
                    print(colorize_log(
                        "[http_server] served local legacy resources text listing"
                    ))
                return True
            except Exception:
                return False

        match = re.search(r"(?i)(?:minecraftresources|resources)/(.+)$", target_norm)
        if not match:
            return False

        rel = unquote(match.group(1)).strip().replace("\\", "/")
        rel = rel.lstrip("/")
        if not rel:
            return False

        legacy_roots = self._legacy_resource_roots()
        for root in legacy_roots:
            try:
                candidate = os.path.normpath(
                    os.path.join(root, rel.replace("/", os.sep))
                )
                if os.path.commonpath([root, candidate]) != root:
                    continue
                if os.path.isfile(candidate):
                    with open(candidate, "rb") as f:
                        payload = f.read()
                    ctype = (
                        mimetypes.guess_type(candidate)[0] or "application/octet-stream"
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Cache-Control", "public, max-age=3600")
                    self.end_headers()
                    self.wfile.write(payload)
                    print(colorize_log(
                        f"[http_server] served local legacy resource: {rel}"
                    ))
                    return True
            except Exception:
                continue

        ext = os.path.splitext(rel)[1].lower()
        placeholder = os.path.join(BASE_DIR, "ui", "assets", "images", "placeholder.png")
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp") and os.path.isfile(placeholder):
            try:
                with open(placeholder, "rb") as f:
                    payload = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(payload)
                print(colorize_log(
                    f"[http_server] served placeholder legacy image: {rel}"
                ))
                return True
            except Exception:
                return False

        ctype = mimetypes.guess_type(rel)[0] or "application/octet-stream"
        try:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            print(colorize_log(f"[http_server] served empty legacy fallback: {rel}"))
            return True
        except Exception:
            return False
