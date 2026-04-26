from __future__ import annotations

import ipaddress
import json
import re
import select
import socket
import sys
import urllib.parse
from http.server import SimpleHTTPRequestHandler
from urllib.parse import unquote, urlparse, quote

from core.logger import colorize_log, dim_line

from server import yggdrasil
from server.api import handle_api_request
from server.api._constants import (
    MAX_MODPACKS_IMPORT_PAYLOAD,
    MAX_MODS_IMPORT_PAYLOAD,
    MAX_PAYLOAD_SIZE,
    MAX_VERSIONS_IMPORT_PAYLOAD,
    MAX_WORLDS_IMPORT_PAYLOAD,
)
from server.api.version_check import read_local_version

from server.http._constants import BASE_DIR
from server.http.multipart import parse_multipart_form
from server.http.proxy import ProxyMixin
from server.http.static_paths import StaticPathsMixin
from server.http.textures import TextureMixin


__all__ = ["RequestHandler"]


class RequestHandler(
    ProxyMixin,
    TextureMixin,
    StaticPathsMixin,
    SimpleHTTPRequestHandler,
):
    def handle_error(self):
        try:
            exc_type, exc_value = sys.exc_info()[:2]
            if isinstance(exc_value, ConnectionResetError):
                return
        except Exception:
            pass
        super().handle_error()

    def log_message(self, format, *args):
        if len(args) > 0 and isinstance(args[0], str):
            if (
                "/api/status/" in args[0]
                or "/api/launch_status/" in args[0]
                or "/api/game_window_visible/" in args[0]
            ):
                return
        message = self.log_date_time_string() + " - " + format % args
        print(dim_line(message))

    def _parse_connect_target(self, target: str):
        raw = str(target or "").strip()
        if not raw:
            return "", 0

        host = ""
        port = 443

        # IPv6 literals are expected in bracket form: [::1]:443
        if raw.startswith("["):
            end = raw.find("]")
            if end <= 1:
                return "", 0
            host = raw[1:end].strip()
            remainder = raw[end + 1:].strip()
            if remainder:
                if not remainder.startswith(":"):
                    return "", 0
                port_text = remainder[1:].strip()
                if not port_text:
                    return "", 0
                try:
                    port = int(port_text)
                except Exception:
                    return "", 0
        else:
            if ":" in raw:
                host_part, port_text = raw.rsplit(":", 1)
                host = host_part.strip()
                if not port_text:
                    return "", 0
                try:
                    port = int(port_text)
                except Exception:
                    return "", 0
            else:
                host = raw

        if not host or port < 1 or port > 65535:
            return "", 0

        return host, port

    def _is_loopback_connect_target(self, host: str) -> bool:
        host_clean = str(host or "").strip().strip("[]").strip().lower()
        if not host_clean:
            return True

        if host_clean == "localhost" or host_clean.endswith(".localhost"):
            return True

        try:
            ip = ipaddress.ip_address(host_clean)
            return ip.is_loopback
        except Exception:
            return False

    def _relay_connect_tunnel(self, upstream: socket.socket):
        sockets = [self.connection, upstream]
        while True:
            readable, _, exceptional = select.select(sockets, [], sockets, 60)
            if exceptional:
                return
            if not readable:
                # Idle timeout; let the client reopen if needed.
                return

            for src in readable:
                dst = upstream if src is self.connection else self.connection
                try:
                    data = src.recv(65536)
                except Exception:
                    return

                if not data:
                    return

                try:
                    dst.sendall(data)
                except Exception:
                    return

    def do_CONNECT(self):
        host, port = self._parse_connect_target(self.path)
        if not host or not port:
            self.send_error(400, "Bad CONNECT target")
            return

        if self._is_loopback_connect_target(host):
            self.send_error(403, "Forbidden CONNECT target")
            return

        try:
            upstream = socket.create_connection((host, port), timeout=15)
        except Exception as e:
            print(colorize_log(
                f"[http_server] CONNECT failed to {host}:{port} - {e}"
            ))
            self.send_error(502, "Bad Gateway")
            return

        try:
            self.connection.settimeout(60)
            upstream.settimeout(60)
            self.wfile.write(
                b"HTTP/1.1 200 Connection Established\r\n"
                b"Proxy-Agent: Histolauncher\r\n\r\n"
            )
            self.wfile.flush()
            self._relay_connect_tunnel(upstream)
        except Exception as e:
            print(colorize_log(
                f"[http_server] CONNECT tunnel error for {host}:{port} - {e}"
            ))
        finally:
            try:
                upstream.close()
            except Exception:
                pass

    def _client_requires_signature(self) -> bool:
        try:
            ua = str(self.headers.get("User-Agent") or "").strip()
            if not ua:
                return False

            m = re.search(
                r"Minecraft(?:/| )?([0-9]+(?:\.[0-9]+){0,2})", ua, flags=re.IGNORECASE
            )
            ver = m.group(1) if m else None
            if not ver:
                m2 = re.search(r"([0-9]+(?:\.[0-9]+){0,2})", ua)
                ver = m2.group(1) if m2 else None

            if not ver:
                if re.search(r"\d+w\d+[a-z]?", ua, flags=re.IGNORECASE):
                    return True
                return False

            parts = [int(x) for x in ver.split(".")]
            while len(parts) < 3:
                parts.append(0)

            return tuple(parts) >= (1, 20, 2)
        except Exception:
            return False

    def _request_requires_signature(self) -> bool:
        try:
            parsed = urlparse(getattr(self, "path", "") or "")
            query = urllib.parse.parse_qs(parsed.query or "")
            unsigned_flag = str((query.get("unsigned") or [""])[0]).strip().lower()
            if unsigned_flag == "true":
                return False
            if unsigned_flag == "false":
                return True
        except Exception:
            pass

        try:
            return (
                yggdrasil.get_public_key_pem() is not None
                or self._client_requires_signature()
            )
        except Exception:
            return self._client_requires_signature()

    def end_headers(self):
        parsed = urlparse(getattr(self, "path", "") or "")
        if parsed.path == "/account-settings-frame":
            self.send_header("X-Frame-Options", "SAMEORIGIN")
        else:
            self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-XSS-Protection", "1; mode=block")
        super().end_headers()

    def _check_content_length(self, max_size: int = MAX_PAYLOAD_SIZE) -> bool:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > max_size:
                self.send_error(
                    413, f"Payload Too Large (max {max_size} bytes)"
                )
                return False
            return True
        except (ValueError, TypeError):
            self.send_error(400, "Invalid Content-Length header")
            return False

    def _send_json(self, obj, status: int = 200):
        encoded = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_ygg_metadata(self):
        launcher_version = read_local_version(base_dir=BASE_DIR)

        public_key = yggdrasil.get_public_key_pem()

        data = {
            "meta": {
                "serverName": f"Histolauncher {launcher_version}",
                "implementationName": "Histolauncher",
                "implementationVersion": launcher_version,
                "usesSignature": public_key is not None,
                "feature.non_email_login": True,
                "feature.enable_profile_key": False,
            },
            "skinDomains": [
                "127.0.0.1",
                "textures.histolauncher.org",
            ],
            "signaturePublickey": public_key,
            "links": {
                "homepage": "https://histolauncher.org",
                "register": "https://histolauncher.org/signup",
            },
        }

        return data

    def _handle_install_stream(self, target_version_key: str):
        import queue
        from core.downloader.progress import add_progress_listener, remove_progress_listener, _encode_key
        from server.api.routes.installer import api_status

        encoded_target = _encode_key(target_version_key)

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        q = queue.Queue(maxsize=100)
        add_progress_listener(q)
        try:
            # Send immediate initial status
            initial_status = api_status(target_version_key)
            if initial_status and initial_status.get("status"):
                initial_status["version_key"] = encoded_target
                self.wfile.write(b"data: ")
                self.wfile.write(json.dumps(initial_status).encode("utf-8"))
                self.wfile.write(b"\n\n")
                self.wfile.flush()

            while True:
                try:
                    event_data = q.get(timeout=2.0)
                    if event_data.get("version_key") == encoded_target:
                        self.wfile.write(b"data: ")
                        self.wfile.write(json.dumps(event_data).encode("utf-8"))
                        self.wfile.write(b"\n\n")
                        self.wfile.flush()
                except queue.Empty:
                    try:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    except BrokenPipeError:
                        break
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            remove_progress_listener(q)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/account-settings-frame":
            response = handle_api_request("/api/account/settings-iframe", None)
            if response and response.get("ok") and response.get("html"):
                payload = str(response.get("html") or "").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)
                return

            error_message = (
                (response or {}).get("error") or "Failed to load account settings"
            )
            error_html = (
                "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                "<title>Account Settings Error</title></head>"
                "<body style=\"margin:0;background:#111;color:#e5e7eb;display:flex;"
                "align-items:center;justify-content:center;min-height:100vh;"
                "text-align:center;padding:24px;box-sizing:border-box;\">"
                f"<div><h2 style=\"margin-top:0;font-style='Arial';\">"
                f"Account Settings Unavailable</h2><p>{error_message}</p></div>"
                "</body></html>"
            ).encode("utf-8", errors="replace")
            self.send_response(502)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(error_html)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(error_html)
            return

        if path.startswith("/histolauncher-proxy/accounts/"):
            upstream_path = path[len("/histolauncher-proxy/accounts"):] or "/"
            if parsed.query:
                upstream_path += f"?{parsed.query}"
            self._proxy_histolauncher_remote_request(
                "https://accounts.histolauncher.org",
                upstream_path,
                include_auth_cookie=True,
            )
            return

        if path.startswith("/histolauncher-proxy/textures/"):
            upstream_path = path[len("/histolauncher-proxy/textures"):] or "/"
            if parsed.query:
                upstream_path += f"?{parsed.query}"
            self._proxy_histolauncher_remote_request(
                "https://textures.histolauncher.org",
                upstream_path,
            )
            return

        if parsed.scheme in ("http", "https") and parsed.netloc:
            target = parsed.netloc + (parsed.path or "/")
            if parsed.query:
                target += "?" + parsed.query
            if self._handle_allowlisted_remote_proxy(parsed.scheme, target):
                return
            self.send_error(403, "Forbidden")
            return

        if path.startswith("/MinecraftResources/"):
            if self._try_serve_legacy_resource_fallback(path):
                return
            self.send_error(404, "Not Found")
            return

        if path.startswith("/http/") or path.startswith("/https/"):
            scheme = "http" if path.startswith("/http/") else "https"
            remainder = path.split("/", 2)
            if len(remainder) < 3 or not remainder[2]:
                self.send_error(404, "Not Found")
                return
            target = remainder[2]
            if self._handle_allowlisted_remote_proxy(scheme, target):
                return
            self.send_error(403, "Forbidden")
            return

        # version.dat (local launcher version)
        if path == "/launcher/version.dat":
            try:
                data = read_local_version(base_dir=BASE_DIR).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                self.send_error(404, "version.dat not found")
            return

        # Yggdrasil metadata
        if path == "/authserver" or path == "/authserver/":
            data = self._send_ygg_metadata()
            encoded = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        # Yggdrasil authenticate
        if path == "/authserver/authenticate":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            status, resp = yggdrasil.handle_auth_post(
                path, body, self.server.server_port
            )
            self._send_json(resp, status=status)
            return

        if (
            path.startswith("/authserver/session/minecraft/profile/")
            or path.startswith("/authserver/sessionserver/session/minecraft/profile/")
            or path.startswith("/authserver/authserver/session/minecraft/profile/")
            or path.startswith(
                "/authserver/authserver/sessionserver/session/minecraft/profile/"
            )
            or path.startswith("/sessionserver/session/minecraft/profile/")
        ):
            req_sig = self._request_requires_signature()
            status, resp = yggdrasil.handle_session_get(
                self.path, self.server.server_port, require_signature=req_sig
            )
            self._send_json(resp, status=status)
            return

        if (
            path.startswith("/authserver/session/minecraft/hasJoined")
            or path.startswith("/authserver/sessionserver/session/minecraft/hasJoined")
            or path.startswith("/sessionserver/session/minecraft/hasJoined")
        ):
            req_sig = self._request_requires_signature()
            status, resp = yggdrasil.handle_has_joined_get(
                self.path, self.server.server_port, require_signature=req_sig
            )
            if status == 204:
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._send_json(resp, status=status)
            return

        legacy_skin_prefixes = [
            "/authserver/skins/MinecraftSkins/",
            "/skins/MinecraftSkins/",
            "/MinecraftSkins/",
            "/http/skins.minecraft.net/MinecraftSkins/",
            "/https/skins.minecraft.net/MinecraftSkins/",
            "/http/s3.amazonaws.com/MinecraftSkins/",
            "/https/s3.amazonaws.com/MinecraftSkins/",
        ]
        legacy_cloak_prefixes = [
            "/authserver/skins/MinecraftCloaks/",
            "/skins/MinecraftCloaks/",
            "/MinecraftCloaks/",
            "/http/skins.minecraft.net/MinecraftCloaks/",
            "/https/skins.minecraft.net/MinecraftCloaks/",
            "/http/s3.amazonaws.com/MinecraftCloaks/",
            "/https/s3.amazonaws.com/MinecraftCloaks/",
        ]

        matched_skin_prefix = next(
            (pfx for pfx in legacy_skin_prefixes if path.startswith(pfx)), None
        )
        if matched_skin_prefix and path.lower().endswith(".png"):
            try:
                requested_name = unquote(
                    path[len(matched_skin_prefix):-4]
                ).strip()
                if not requested_name:
                    self.send_error(404, "Texture not found")
                    return

                self._handle_texture_proxy(
                    f"/texture/skin/{quote(requested_name)}"
                )
                return
            except Exception:
                self.send_error(404, "Texture not found")
                return

        matched_cloak_prefix = next(
            (pfx for pfx in legacy_cloak_prefixes if path.startswith(pfx)), None
        )
        if matched_cloak_prefix and path.lower().endswith(".png"):
            try:
                requested_name = unquote(
                    path[len(matched_cloak_prefix):-4]
                ).strip()
                if not requested_name:
                    self.send_error(404, "Cape not found")
                    return

                self._handle_texture_proxy(
                    f"/texture/cape/{quote(requested_name)}"
                )
                return
            except Exception:
                self.send_error(404, "Cape not found")
                return

        if path.startswith("/texture/"):
            self._handle_texture_proxy(path)
            return

        if (
            path == "/authserver/minecraft/profile"
            or path == "/authserver/minecraft/profile/"
        ):
            status, resp = yggdrasil.handle_services_profile_get(
                self.server.server_port
            )
            self._send_json(resp, status=status)
            return

        if path.startswith("/authserver/player/certificates"):
            self._send_json(
                {
                    "keyPair": None,
                    "publicKeySignature": None,
                    "expiresAt": None,
                },
                status=200,
            )
            return

        # API endpoints
        if path.startswith("/api/stream/install/"):
            version_key = unquote(path[len("/api/stream/install/"):])
            self._handle_install_stream(version_key)
            return

        if path.startswith("/api/"):
            response = handle_api_request(self.path, None)
            self._send_json(response)
            return

        # Serve UI root
        if self.path == "/":
            self.path = "/index.html"

        return super().do_GET()

    def do_HEAD(self):
        try:
            self.do_GET()
        except Exception:
            pass

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/histolauncher-proxy/accounts/"):
            if not self._check_content_length(max_size=MAX_PAYLOAD_SIZE):
                return

            length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(length)
            upstream_path = path[len("/histolauncher-proxy/accounts"):] or "/"
            if parsed.query:
                upstream_path += f"?{parsed.query}"
            self._proxy_histolauncher_remote_request(
                "https://accounts.histolauncher.org",
                upstream_path,
                method="POST",
                body_bytes=body_bytes,
                content_type=self.headers.get("Content-Type", ""),
                include_auth_cookie=True,
            )
            return

        max_payload_size = MAX_PAYLOAD_SIZE
        if path.startswith("/api/versions/import"):
            max_payload_size = MAX_VERSIONS_IMPORT_PAYLOAD
        elif path.startswith("/api/mods/import"):
            max_payload_size = MAX_MODS_IMPORT_PAYLOAD
        elif path.startswith("/api/modpacks/import"):
            max_payload_size = MAX_MODPACKS_IMPORT_PAYLOAD
        elif path.startswith("/api/worlds/import"):
            max_payload_size = MAX_WORLDS_IMPORT_PAYLOAD

        # Validate payload size before reading body
        if not self._check_content_length(max_size=max_payload_size):
            return

        # Handle proxy-form absolute POSTs (modern services + legacy telemetry).
        if parsed.scheme in ("http", "https") and parsed.netloc:
            length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(length)
            target = parsed.netloc + (parsed.path or "")
            if parsed.query:
                target += f"?{parsed.query}"
            if self._handle_allowlisted_remote_proxy_post(
                parsed.scheme, target, body_bytes
            ):
                return
            self.send_error(403, "Forbidden")
            return

        if path.startswith("/authserver/api/profiles/minecraft"):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                payload = json.loads(body) if body else None
            except Exception:
                payload = None

            names = []
            if isinstance(payload, list):
                names = [str(n) for n in payload if n]
            elif isinstance(payload, dict):
                maybe = payload.get("names") or payload.get("usernames")
                if isinstance(maybe, list):
                    names = [str(n) for n in maybe if n]
            elif isinstance(payload, str) and payload:
                names = [payload]

            out = []
            try:
                current_name, current_uuid = yggdrasil._get_username_and_uuid()
                current_name_norm = str(current_name or "").strip().lower()
                for nm in names:
                    nm_clean = (nm or "").strip()
                    if not nm_clean:
                        continue
                    if (
                        nm_clean.lower() == current_name_norm and current_uuid
                    ):
                        uid_hex = str(current_uuid).replace("-", "")
                    else:
                        uid_hex = yggdrasil._ensure_uuid(nm_clean).replace("-", "")
                    out.append({"id": uid_hex, "name": nm_clean})
                self._send_json(out, status=200)
                return
            except Exception:
                self._send_json([], status=200)
                return

        # Yggdrasil authenticate
        if path == "/authserver/authenticate":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            status, resp = yggdrasil.handle_auth_post(
                path, body, self.server.server_port
            )
            self._send_json(resp, status=status)
            return

        # Session join endpoint used in modern multiplayer auth flow.
        if (
            path.startswith("/authserver/session/minecraft/join")
            or path.startswith("/authserver/sessionserver/session/minecraft/join")
            or path.startswith("/sessionserver/session/minecraft/join")
        ):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            status, resp = yggdrasil.handle_session_join_post(path, body)
            if status == 204:
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._send_json(resp, status=status)
            return

        # Own profile endpoint used by 1.20.2+ via servicesHost
        if (
            path == "/authserver/minecraft/profile"
            or path == "/authserver/minecraft/profile/"
        ):
            status, resp = yggdrasil.handle_services_profile_get(
                self.server.server_port
            )
            self._send_json(resp, status=status)
            return

        # API POSTs
        if path.startswith("/api/"):
            length = int(self.headers.get("Content-Length", 0))
            content_type = self.headers.get("Content-Type", "")

            if (
                path.startswith("/api/versions/import")
                and "multipart/form-data" in content_type
            ):
                try:
                    body_bytes = self.rfile.read(length)
                    form_data = parse_multipart_form(body_bytes, content_type)

                    if form_data:
                        version_name = (
                            form_data.get("version_name", "").strip()
                            if isinstance(form_data.get("version_name"), str)
                            else ""
                        )
                        zip_data_binary = form_data.get("zip_file")
                        operation_id = (
                            form_data.get("operation_id", "").strip()
                            if isinstance(form_data.get("operation_id"), str)
                            else ""
                        )

                        if zip_data_binary:
                            data = {
                                "version_name": version_name,
                                "zip_bytes": zip_data_binary,
                                "operation_id": operation_id,
                            }
                        else:
                            data = {
                                "version_name": version_name,
                                "operation_id": operation_id,
                            }

                        print(
                            f"[HTTP] POST /api/versions/import (multipart) - "
                            f"version_name: '{version_name}', "
                            f"operation_id: '{operation_id}', "
                            f"zip_bytes length: "
                            f"{len(zip_data_binary) if zip_data_binary else 0}"
                        )
                    else:
                        data = None

                except Exception as e:
                    print(f"[HTTP] Error parsing multipart form data: {e}")
                    data = None
            elif (
                path.startswith("/api/mods/import")
                and "multipart/form-data" in content_type
            ):
                try:
                    body_bytes = self.rfile.read(length)
                    form_data = parse_multipart_form(body_bytes, content_type)

                    if form_data:
                        addon_type = (
                            form_data.get("addon_type", "").strip()
                            if isinstance(form_data.get("addon_type"), str)
                            else ""
                        )
                        mod_loader = (
                            form_data.get("mod_loader", "").strip()
                            if isinstance(form_data.get("mod_loader"), str)
                            else ""
                        )
                        file_data = form_data.get("mod_file")
                        if file_data is None:
                            file_data = form_data.get("jar_file")
                        file_name = (
                            form_data.get("file_name", "").strip()
                            if isinstance(form_data.get("file_name"), str)
                            else ""
                        )
                        if not file_name and isinstance(
                            form_data.get("jar_name"), str
                        ):
                            file_name = form_data.get("jar_name", "").strip()
                        data = {
                            "addon_type": addon_type,
                            "mod_loader": mod_loader,
                            "file_name": file_name,
                            "file_data": file_data,
                        }
                        print(
                            f"[HTTP] POST /api/mods/import (multipart) - "
                            f"addon_type: '{addon_type}', "
                            f"mod_loader: '{mod_loader}', "
                            f"file_name: '{file_name}', "
                            f"file_data length: "
                            f"{len(file_data) if file_data else 0}"
                        )
                    else:
                        data = None
                except Exception as e:
                    print(
                        f"[HTTP] Error parsing multipart form data for mods import: {e}"
                    )
                    data = None
            elif (
                path.startswith("/api/modpacks/import")
                and "multipart/form-data" in content_type
            ):
                try:
                    body_bytes = self.rfile.read(length)
                    form_data = parse_multipart_form(body_bytes, content_type)

                    if form_data:
                        archive_data = form_data.get("modpack_file")
                        if archive_data is None:
                            archive_data = form_data.get("hlmp_file")

                        file_name = (
                            form_data.get("file_name", "").strip()
                            if isinstance(form_data.get("file_name"), str)
                            else ""
                        )

                        source_format = (
                            form_data.get("source_format", "").strip().lower()
                            if isinstance(form_data.get("source_format"), str)
                            else ""
                        )
                        import_id = (
                            form_data.get("import_id", "").strip()
                            if isinstance(form_data.get("import_id"), str)
                            else ""
                        )
                        operation_id = (
                            form_data.get("operation_id", "").strip()
                            if isinstance(form_data.get("operation_id"), str)
                            else ""
                        )

                        data = {
                            "hlmp_data": archive_data,
                            "modpack_data": archive_data,
                            "file_name": file_name,
                            "source_format": source_format,
                            "import_id": import_id,
                            "operation_id": operation_id or import_id,
                        }
                        print(
                            f"[HTTP] POST /api/modpacks/import (multipart) - "
                            f"file_name: '{file_name}', "
                            f"source_format: '{source_format}', "
                            f"import_id: '{import_id}', "
                            f"operation_id: '{operation_id or import_id}', "
                            f"archive_data length: "
                            f"{len(archive_data) if archive_data else 0}"
                        )
                    else:
                        data = None
                except Exception as e:
                    print(
                        f"[HTTP] Error parsing multipart form data for "
                        f"modpacks import: {e}"
                    )
                    data = None
            elif (
                (path.startswith("/api/worlds/import") or path.startswith("/api/worlds/import-scan"))
                and "multipart/form-data" in content_type
            ):
                try:
                    body_bytes = self.rfile.read(length)
                    form_data = parse_multipart_form(body_bytes, content_type)

                    if form_data:
                        zip_data_binary = form_data.get("world_file")
                        if zip_data_binary is None:
                            zip_data_binary = form_data.get("zip_file")

                        storage_target = (
                            form_data.get("storage_target", "").strip()
                            if isinstance(form_data.get("storage_target"), str)
                            else ""
                        )
                        custom_path = (
                            form_data.get("custom_path", "").strip()
                            if isinstance(form_data.get("custom_path"), str)
                            else ""
                        )
                        selected_roots_raw = (
                            form_data.get("selected_roots", "")
                            if isinstance(form_data.get("selected_roots"), str)
                            else ""
                        )
                        selected_roots = None
                        if selected_roots_raw:
                            try:
                                parsed_selected = json.loads(selected_roots_raw)
                                if isinstance(parsed_selected, list):
                                    selected_roots = [str(item or "") for item in parsed_selected]
                            except Exception:
                                selected_roots = [
                                    item.strip()
                                    for item in selected_roots_raw.split("|")
                                    if item.strip()
                                ]

                        data = {
                            "zip_bytes": zip_data_binary,
                            "storage_target": storage_target or "default",
                            "custom_path": custom_path,
                        }
                        if selected_roots is not None:
                            data["selected_roots"] = selected_roots

                        print(
                            f"[HTTP] POST {path} (multipart) - "
                            f"storage_target: '{storage_target}', "
                            f"custom_path: '{custom_path}', "
                            f"selected_roots: "
                            f"{selected_roots if selected_roots is not None else 'all'}, "
                            f"zip_bytes length: "
                            f"{len(zip_data_binary) if zip_data_binary else 0}"
                        )
                    else:
                        data = None
                except Exception as e:
                    print(
                        f"[HTTP] Error parsing multipart form data for "
                        f"worlds import: {e}"
                    )
                    data = None
            else:
                body = self.rfile.read(length).decode("utf-8")

                if path.startswith("/api/versions/import"):
                    print(
                        f"[HTTP] POST /api/versions/import - "
                        f"Body length: {len(body)}, "
                        f"First 100 chars: {body[:100]}"
                    )

                try:
                    data = json.loads(body) if body else None
                except json.JSONDecodeError as e:
                    print(f"[HTTP] JSON decode error on {path}: {e}")
                    data = None

            response = handle_api_request(self.path, data)
            self._send_json(response)
            return

        self.send_error(405, "Method Not Allowed")
