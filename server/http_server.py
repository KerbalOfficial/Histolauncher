# server/http_server.py

import os
import sys
import json
import threading
import re
import mimetypes
import urllib.request
import urllib.error
import platform

from http.server import SimpleHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, unquote, quote
import socketserver

from .api_handler import (
    handle_api_request,
    read_local_version,
    MAX_PAYLOAD_SIZE,
    MAX_VERSIONS_IMPORT_PAYLOAD,
    MAX_MODS_IMPORT_PAYLOAD,
    MAX_MODPACKS_IMPORT_PAYLOAD,
)
from . import yggdrasil
from core.version_manager import get_clients_dir
from core.settings import get_base_dir
from core import mod_manager
from core.logger import colorize_log, dim_line


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(BASE_DIR, "ui")


def parse_multipart_form(body_bytes, content_type_header):
    """Parse multipart/form-data without using the cgi module."""
    try:
        # Extract boundary from Content-Type header
        # e.g., "multipart/form-data; boundary=----WebKitFormBoundary..."
        boundary_match = content_type_header.split("boundary=")
        if len(boundary_match) < 2:
            return None
        
        boundary = boundary_match[1].strip('"').encode('utf-8')
        form_data = {}
        
        # Split body by boundary
        parts = body_bytes.split(b'--' + boundary)
        
        for part in parts[1:-1]:  # Skip first (empty) and last (closing boundary)
            if not part.strip():
                continue
            
            # Split headers from content
            header_end = part.find(b'\r\n\r\n')
            if header_end == -1:
                header_end = part.find(b'\n\n')
                if header_end == -1:
                    continue
                headers_section = part[:header_end]
                content = part[header_end + 2:]
            else:
                headers_section = part[:header_end]
                content = part[header_end + 4:]
            
            # Remove trailing \r\n or \n from content
            if content.endswith(b'\r\n'):
                content = content[:-2]
            elif content.endswith(b'\n'):
                content = content[:-1]
            
            # Parse headers to get field name
            headers_text = headers_section.decode('utf-8', errors='ignore')
            field_name = None
            is_file = False
            
            for header_line in headers_text.split('\n'):
                if 'Content-Disposition' in header_line:
                    # Extract field name
                    if 'name=' in header_line:
                        start = header_line.find('name="') + 6
                        end = header_line.find('"', start)
                        if start > 5 and end > start:
                            field_name = header_line[start:end]
                    
                    # Check if it's a file upload
                    if 'filename=' in header_line:
                        is_file = True
            
            if field_name:
                if is_file:
                    form_data[field_name] = content  # Binary data for files
                else:
                    form_data[field_name] = content.decode('utf-8', errors='ignore')
        
        return form_data
    except Exception as e:
        print(f"[HTTP] Error parsing multipart form: {e}")
        return None


class RequestHandler(SimpleHTTPRequestHandler):
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
            if "/api/status/" in args[0] or "/api/launch_status/" in args[0] or "/api/game_window_visible/" in args[0]:
                return
        message = self.log_date_time_string() + " - " + format % args
        print(dim_line(message))

    def end_headers(self):
        """Override to add security headers to all responses."""
        # Add security headers to every response
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-XSS-Protection", "1; mode=block")
        super().end_headers()

    def _check_content_length(self, max_size: int = MAX_PAYLOAD_SIZE) -> bool:
        """Validate Content-Length header against maximum payload size."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > max_size:
                self.send_error(413, f"Payload Too Large (max {max_size} bytes)")
                return False
            return True
        except (ValueError, TypeError):
            self.send_error(400, "Invalid Content-Length header")
            return False

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

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
            status, resp = yggdrasil.handle_auth_post(path, body, self.server.server_port)
            self._send_json(resp, status=status)
            return

        if (
            path.startswith("/authserver/session/minecraft/profile/")
            or path.startswith("/authserver/sessionserver/session/minecraft/profile/")
            or path.startswith("/authserver/authserver/session/minecraft/profile/")
            or path.startswith("/authserver/authserver/sessionserver/session/minecraft/profile/")
            or path.startswith("/sessionserver/session/minecraft/profile/")
        ):
            status, resp = yggdrasil.handle_session_get(self.path, self.server.server_port)
            self._send_json(resp, status=status)
            return

        if (
            path.startswith("/authserver/session/minecraft/hasJoined")
            or path.startswith("/authserver/sessionserver/session/minecraft/hasJoined")
            or path.startswith("/sessionserver/session/minecraft/hasJoined")
        ):
            status, resp = yggdrasil.handle_has_joined_get(self.path, self.server.server_port)
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

        matched_skin_prefix = next((pfx for pfx in legacy_skin_prefixes if path.startswith(pfx)), None)
        if matched_skin_prefix and path.lower().endswith(".png"):
            try:
                requested_name = unquote(path[len(matched_skin_prefix):-4]).strip()
                if not requested_name:
                    self.send_error(404, "Texture not found")
                    return

                self._handle_texture_proxy(f"/textures/skin/{quote(requested_name)}")
                return
            except Exception:
                self.send_error(404, "Texture not found")
                return

        matched_cloak_prefix = next((pfx for pfx in legacy_cloak_prefixes if path.startswith(pfx)), None)
        if matched_cloak_prefix and path.lower().endswith(".png"):
            try:
                requested_name = unquote(path[len(matched_cloak_prefix):-4]).strip()
                if not requested_name:
                    self.send_error(404, "Cape not found")
                    return

                self._handle_texture_proxy(f"/textures/cape/{quote(requested_name)}")
                return
            except Exception:
                self.send_error(404, "Cape not found")
                return

        if path.startswith("/textures/"):
            self._handle_texture_proxy(path)
            return

        if (
            path == "/authserver/minecraft/profile"
            or path == "/authserver/minecraft/profile/"
        ):
            status, resp = yggdrasil.handle_services_profile_get(self.server.server_port)
            self._send_json(resp, status=status)
            return

        if path.startswith("/authserver/player/certificates"):
            self._send_json({"keyPair": None, "publicKeySignature": None, "expiresAt": None}, status=200)
            return

        # API endpoints
        if path.startswith("/api/"):
            response = handle_api_request(self.path, None)
            self._send_json(response)
            return

        # Serve UI root
        if self.path == "/":
            self.path = "/index.html"

        # Fallback to default static file handling (UI)
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        max_payload_size = MAX_PAYLOAD_SIZE
        if path.startswith("/api/versions/import"):
            max_payload_size = MAX_VERSIONS_IMPORT_PAYLOAD
        elif path.startswith("/api/mods/import"):
            max_payload_size = MAX_MODS_IMPORT_PAYLOAD
        elif path.startswith("/api/modpacks/import"):
            max_payload_size = MAX_MODPACKS_IMPORT_PAYLOAD

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
            if self._handle_allowlisted_remote_proxy_post(parsed.scheme, target, body_bytes):
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
                    if nm_clean.lower() == current_name_norm and current_uuid:
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
            status, resp = yggdrasil.handle_auth_post(path, body, self.server.server_port)
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
            status, resp = yggdrasil.handle_services_profile_get(self.server.server_port)
            self._send_json(resp, status=status)
            return

        # API POSTs
        if path.startswith("/api/"):
            length = int(self.headers.get("Content-Length", 0))
            
            if path.startswith("/api/versions/import") and "multipart/form-data" in self.headers.get("Content-Type", ""):
                try:
                    body_bytes = self.rfile.read(length)
                    form_data = parse_multipart_form(body_bytes, self.headers.get("Content-Type", ""))
                    
                    if form_data:
                        version_name = form_data.get('version_name', '').strip() if isinstance(form_data.get('version_name'), str) else ''
                        zip_data_binary = form_data.get('zip_file')
                        
                        if zip_data_binary:
                            data = {
                                'version_name': version_name,
                                'zip_bytes': zip_data_binary
                            }
                        else:
                            data = {'version_name': version_name}
                        
                        print(f"[HTTP] POST /api/versions/import (multipart) - version_name: '{version_name}', zip_bytes length: {len(zip_data_binary) if zip_data_binary else 0}")
                    else:
                        data = None
                    
                except Exception as e:
                    print(f"[HTTP] Error parsing multipart form data: {e}")
                    data = None
            elif path.startswith("/api/mods/import") and "multipart/form-data" in self.headers.get("Content-Type", ""):
                try:
                    body_bytes = self.rfile.read(length)
                    form_data = parse_multipart_form(body_bytes, self.headers.get("Content-Type", ""))

                    if form_data:
                        mod_loader = form_data.get('mod_loader', '').strip() if isinstance(form_data.get('mod_loader'), str) else ''
                        jar_data = form_data.get('jar_file')
                        jar_name = form_data.get('jar_name', '').strip() if isinstance(form_data.get('jar_name'), str) else ''
                        data = {
                            'mod_loader': mod_loader,
                            'jar_name': jar_name,
                            'jar_data': jar_data,  # raw bytes, handled by api_handler
                        }
                        print(f"[HTTP] POST /api/mods/import (multipart) - mod_loader: '{mod_loader}', jar_name: '{jar_name}', jar_data length: {len(jar_data) if jar_data else 0}")
                    else:
                        data = None
                except Exception as e:
                    print(f"[HTTP] Error parsing multipart form data for mods import: {e}")
                    data = None
            elif path.startswith("/api/modpacks/import") and "multipart/form-data" in self.headers.get("Content-Type", ""):
                try:
                    body_bytes = self.rfile.read(length)
                    form_data = parse_multipart_form(body_bytes, self.headers.get("Content-Type", ""))

                    if form_data:
                        hlmp_data = form_data.get('hlmp_file')
                        data = {
                            'hlmp_data': hlmp_data,  # raw bytes
                        }
                        print(f"[HTTP] POST /api/modpacks/import (multipart) - hlmp_data length: {len(hlmp_data) if hlmp_data else 0}")
                    else:
                        data = None
                except Exception as e:
                    print(f"[HTTP] Error parsing multipart form data for modpacks import: {e}")
                    data = None
            else:
                body = self.rfile.read(length).decode("utf-8")
                
                if path.startswith("/api/versions/import"):
                    print(f"[HTTP] POST /api/versions/import - Body length: {len(body)}, First 100 chars: {body[:100]}")
                
                try:
                    data = json.loads(body) if body else None
                except json.JSONDecodeError as e:
                    print(f"[HTTP] JSON decode error on {path}: {e}")
                    data = None

            response = handle_api_request(self.path, data)
            self._send_json(response)
            return

        self.send_error(405, "Method Not Allowed")

    def translate_path(self, path):
        path = path.split("?", 1)[0]

        if path.startswith("/clients/"):
            client_rel = unquote(path[len("/clients/"):]).replace("/", os.sep)
            clients_root = get_clients_dir()
            target_path = os.path.normpath(os.path.join(clients_root, client_rel))

            try:
                if os.path.commonpath([clients_root, target_path]) != clients_root:
                    return os.path.join(UI_DIR, "__invalid_clients_path__")
            except ValueError:
                return os.path.join(UI_DIR, "__invalid_clients_path__")

            return target_path

        if path.startswith("/mods-cache/"):
            rel_path = unquote(path[len("/mods-cache/"):]).replace("/", os.sep)
            mods_root = mod_manager.get_mods_storage_dir()
            target_path = os.path.normpath(os.path.join(mods_root, rel_path))

            try:
                if os.path.commonpath([mods_root, target_path]) != mods_root:
                    return os.path.join(UI_DIR, "__invalid_mod_cache_path__")
            except ValueError:
                return os.path.join(UI_DIR, "__invalid_mod_cache_path__")

            return target_path

        if path.startswith("/modpacks-cache/"):
            rel_path = unquote(path[len("/modpacks-cache/"):]).replace("/", os.sep)
            packs_root = mod_manager.get_modpacks_storage_dir()
            target_path = os.path.normpath(os.path.join(packs_root, rel_path))

            try:
                if os.path.commonpath([packs_root, target_path]) != packs_root:
                    return os.path.join(UI_DIR, "__invalid_modpack_cache_path__")
            except ValueError:
                return os.path.join(UI_DIR, "__invalid_modpack_cache_path__")

            return target_path

        return os.path.join(UI_DIR, path.lstrip("/"))

    def _get_worlds_directory(self) -> str:
        try:
            from core.settings import load_global_settings, get_versions_profile_dir
        except Exception:
            load_global_settings = None

        game_dir = os.path.expanduser(os.path.join("~", ".minecraft"))

        try:
            if load_global_settings:
                gs = load_global_settings() or {}
                storage_mode = (gs.get("storage_directory") or "global").strip().lower()
                if storage_mode == "version":
                    sel = str(gs.get("selected_version") or "").strip()
                    if sel:
                        base_versions = get_versions_profile_dir()
                        cand = os.path.join(base_versions, sel)
                        if os.path.isdir(cand):
                            game_dir = os.path.join(cand, "data")
                        else:
                            game_dir = os.path.join(base_versions, "data") if os.path.isdir(os.path.join(base_versions, "data")) else base_versions
                    else:
                        game_dir = os.path.expanduser(os.path.join("~", ".minecraft"))
                else:
                    system = platform.system().lower()
                    if "windows" in system:
                        user_profile = os.environ.get("APPDATA")
                        game_dir = os.path.join(user_profile, ".minecraft")
                    else:
                        game_dir = os.path.expanduser(os.path.join("~", ".minecraft"))
        except Exception:
            pass

        worlds_dir = os.path.join(game_dir, "legacy_worlds")
        os.makedirs(worlds_dir, exist_ok=True)
        return worlds_dir

    def _send_json(self, obj, status: int = 200):

        encoded = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _handle_allowlisted_remote_proxy(self, scheme: str, target: str) -> bool:
        target_clean = str(target or "").lstrip('/')
        if not target_clean:
            return False

        if self._try_bridge_modern_profile_lookup_get(target_clean):
            return True

        if self._try_bridge_classic_world_list(target_clean):
            return True

        if self._try_bridge_legacy_skin_target(target_clean):
            return True

        domain = target_clean.split('/', 1)[0].lower()
        allowed_hosts = {
            's3.amazonaws.com',
            'minecraft.net',
            'www.minecraft.net',
            'skins.minecraft.net',
            'textures.minecraft.net',
            'resources.download.minecraft.net',
            'textures.histolauncher.workers.dev',
        }
        if domain not in allowed_hosts:
            return False

        url = f"{scheme}://{target_clean}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                payload = resp.read()
                ctype = resp.headers.get('Content-Type', 'application/octet-stream')
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                print(colorize_log(f"[http_server] proxied external resource: {url}"))
                return True
        except urllib.error.HTTPError as e:
            print(colorize_log(f"[http_server] remote resource not found: {url} ({e.code})"))
            if self._try_serve_legacy_resource_fallback(target_clean):
                return True
            try:
                self.send_error(404, "Not Found")
            except Exception:
                pass
            return True
        except Exception as e:
            print(colorize_log(f"[http_server] remote resource proxy failed: {url} - {e}"))
            if self._try_serve_legacy_resource_fallback(target_clean):
                return True
            try:
                self.send_error(502, "Bad Gateway")
            except Exception:
                pass
            return True

    def _handle_allowlisted_remote_proxy_post(self, scheme: str, target: str, body_bytes: bytes) -> bool:
        target_clean = str(target or "").lstrip('/')
        if not target_clean:
            return False

        domain = target_clean.split('/', 1)[0].lower().split(':', 1)[0]

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
        host = (parsed.netloc or "").split(':', 1)[0].lower()
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
            if str(current_name or "").strip().lower() == name.lower() and current_uuid:
                uid_hex = str(current_uuid).replace("-", "")
            else:
                uid_hex = yggdrasil._ensure_uuid(name).replace("-", "")
            self._send_json({"id": uid_hex, "name": name}, status=200)
            print(colorize_log(f"[http_server] bridged mojang profile lookup: {name} -> {uid_hex}"))
            return True

        return False

    def _try_bridge_modern_profile_lookup_post(self, target: str, body_bytes: bytes) -> bool:
        parsed = urlparse(f"http://{target}")
        host = (parsed.netloc or "").split(':', 1)[0].lower()
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
            if str(current_name or "").strip().lower() == name.lower() and current_uuid:
                uid_hex = str(current_uuid).replace("-", "")
            else:
                uid_hex = yggdrasil._ensure_uuid(name).replace("-", "")
            out.append({"id": uid_hex, "name": name})

        self._send_json(out, status=200)
        print(colorize_log(f"[http_server] bridged minecraftservices bulk lookup: {len(out)} profile(s)"))
        return True

    def _try_bridge_classic_world_list(self, target: str) -> bool:
        if not re.search(r'(?i)listmaps\.jsp', target):
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
            body = b'This system is in development!;-;-;-;Use the button below!'
            ctype = 'text/plain; charset=utf-8'

            print(colorize_log(f"[http_server] handled listmaps.jsp for user: {username} (payload {len(body)} bytes)"))

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
        target_norm = str(target or "").replace('\\', '/').lstrip('/')
        if not target_norm:
            return False

        parsed = urlparse(f"http://{target_norm}")
        path = parsed.path or ""
        query = parsed.query or ""

        skin_match = re.search(r'(?i)minecraftskins/([^/?]+)\.png(?:\?.*)?$', target_norm)
        if skin_match:
            requested_name = unquote(skin_match.group(1)).strip()
            if not requested_name:
                self.send_error(404, "Texture not found")
                return True
            self._handle_texture_proxy(f"/textures/skin/{quote(requested_name, safe='')}")
            print(colorize_log(f"[http_server] bridged legacy skin URL to texture proxy: {requested_name}"))
            return True

        skin_match_old = re.search(r'(?i)/(?:game/)?skin/([^/?]+)\.png$', path)
        if skin_match_old:
            requested_name = unquote(skin_match_old.group(1)).strip()
            if not requested_name:
                self.send_error(404, "Texture not found")
                return True
            self._handle_texture_proxy(f"/textures/skin/{quote(requested_name, safe='')}")
            print(colorize_log(f"[http_server] bridged minecraft.net skin URL to texture proxy: {requested_name}"))
            return True

        cloak_match = re.search(r'(?i)minecraftcloaks/([^/?]+)\.png(?:\?.*)?$', target_norm)
        if cloak_match:
            requested_name = unquote(cloak_match.group(1)).strip()
            if not requested_name:
                self.send_error(404, "Cape not found")
                return True
            self._handle_texture_proxy(f"/textures/cape/{quote(requested_name, safe='')}")
            print(colorize_log(f"[http_server] bridged legacy cloak URL to texture proxy: {requested_name}"))
            return True

        cloak_match_old = re.search(r'(?i)/cloak/get\.jsp$', path)
        if cloak_match_old and query:
            params = dict([p.split('=', 1) for p in query.split('&') if '=' in p])
            if params.get('user'):
                requested_name = unquote(str(params.get('user') or '')).strip()
                if not requested_name:
                    self.send_error(404, "Cape not found")
                    return True
                self._handle_texture_proxy(f"/textures/cape/{quote(requested_name, safe='')}")
                print(colorize_log(f"[http_server] bridged old cloak endpoint to texture proxy: {requested_name}"))
                return True

        return False

    def _try_serve_legacy_resource_fallback(self, target: str) -> bool:
        target_norm = str(target or "").replace('\\', '/').lstrip('/')

        host_match = re.match(r'^[^/]+/(.*)$', target_norm)
        if host_match:
            target_norm = host_match.group(1)

        if re.search(r'(?i)^game/\?[^\s]*\bn=', target_norm):
            try:
                payload = b"0"
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(payload)
                print(colorize_log("[http_server] served legacy /game endpoint fallback"))
                return True
            except Exception:
                return False

        if re.search(r'(?i)(?:minecraftresources|resources)/?(?:\?.*)?$', target_norm):
            try:
                payload = b""
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(payload)
                print(colorize_log("[http_server] served empty legacy resources root fallback"))
                return True
            except Exception:
                return False

        match = re.search(r'(?i)(?:minecraftresources|resources)/(.+)$', target_norm)
        if not match:
            return False

        rel = unquote(match.group(1)).strip().replace('\\', '/')
        rel = rel.lstrip('/')
        if not rel:
            return False

        legacy_roots = [
            os.path.join(BASE_DIR, 'assets', 'legacy_resources'),
            os.path.join(get_base_dir(), 'legacy_resources'),
        ]
        for root in legacy_roots:
            try:
                candidate = os.path.normpath(os.path.join(root, rel.replace('/', os.sep)))
                if os.path.commonpath([root, candidate]) != root:
                    continue
                if os.path.isfile(candidate):
                    with open(candidate, 'rb') as f:
                        payload = f.read()
                    ctype = mimetypes.guess_type(candidate)[0] or 'application/octet-stream'
                    self.send_response(200)
                    self.send_header('Content-Type', ctype)
                    self.send_header('Content-Length', str(len(payload)))
                    self.send_header('Cache-Control', 'public, max-age=3600')
                    self.end_headers()
                    self.wfile.write(payload)
                    print(colorize_log(f"[http_server] served local legacy resource: {rel}"))
                    return True
            except Exception:
                continue

        ext = os.path.splitext(rel)[1].lower()
        placeholder = os.path.join(BASE_DIR, 'ui', 'assets', 'images', 'placeholder.png')
        if ext in ('.png', '.jpg', '.jpeg', '.gif', '.bmp') and os.path.isfile(placeholder):
            try:
                with open(placeholder, 'rb') as f:
                    payload = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.end_headers()
                self.wfile.write(payload)
                print(colorize_log(f"[http_server] served placeholder legacy image: {rel}"))
                return True
            except Exception:
                return False

        ctype = mimetypes.guess_type(rel)[0] or 'application/octet-stream'
        try:
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', '0')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            print(colorize_log(f"[http_server] served empty legacy fallback: {rel}"))
            return True
        except Exception:
            return False

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
            
            uuid_like = bool(re.match(r'^[a-fA-F0-9\-]{32,36}$', texture_id))
            username_fallback = ""

            if uuid_like:
                current_name, current_uuid = yggdrasil._get_username_and_uuid()
                if texture_id.replace("-", "").lower() == str(current_uuid or "").replace("-", "").lower():
                    username_fallback = (current_name or "").strip()
            else:
                username_fallback = texture_id
                texture_id = yggdrasil._ensure_uuid(username_fallback).replace("-", "")
            
            base_dir = get_base_dir()
            skins_dir = os.path.join(base_dir, "skins")

            def _ensure_dashed_uuid(u: str) -> str:
                if not u:
                    return u
                if '-' in u:
                    return u
                s = u.strip()
                if len(s) == 32:
                    return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"
                return u

            dashed = _ensure_dashed_uuid(texture_id)
            local_path = None

            if texture_type == "skin":
                skin_path_candidates = [
                    os.path.join(skins_dir, f"{dashed}.png"),
                    os.path.join(skins_dir, f"{texture_id}.png"),
                ]

                if username_fallback:
                    skin_path_candidates.append(os.path.join(skins_dir, f"{username_fallback}.png"))

                for candidate in skin_path_candidates:
                    if os.path.exists(candidate) and os.path.isfile(candidate):
                        local_path = candidate
                        texture_id = os.path.splitext(os.path.basename(candidate))[0]
                        break

            if local_path:
                try:
                    with open(local_path, 'rb') as f:
                        texture_data = f.read()
                    
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(texture_data)))
                    self.send_header("Cache-Control", "public, max-age=3600")
                    self.end_headers()
                    self.wfile.write(texture_data)
                    print(colorize_log(f"[http_server] served local {texture_type}: {texture_id}"))
                except Exception as e:
                    print(colorize_log(f"[http_server] error reading {texture_type} file: {e}"))
                    self.send_error(500, f"Error reading {texture_type}")
            else:
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
                    fallback_remote_url = f"https://textures.histolauncher.workers.dev/{texture_type}/{quote(str(rid), safe='')}"
                    if fallback_remote_url not in remote_urls:
                        remote_urls.append(fallback_remote_url)

                for remote_url in remote_urls:
                    try:
                        req = urllib.request.Request(
                            remote_url,
                            headers={"User-Agent": "Histolauncher/1.0"},
                        )
                        with urllib.request.urlopen(req, timeout=6) as resp:
                            payload = resp.read()

                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Content-Length", str(len(payload)))
                        self.send_header("Cache-Control", "public, max-age=3600")
                        self.end_headers()
                        self.wfile.write(payload)
                        print(colorize_log(f"[http_server] proxied remote {texture_type}: {remote_url}"))
                        return
                    except urllib.error.HTTPError as e:
                        last_http_error = e
                        print(colorize_log(f"[http_server] remote {texture_type} not found: {remote_url} ({e.code})"))
                        continue
                    except Exception as e:
                        print(colorize_log(f"[http_server] remote {texture_type} proxy failed for {remote_url}: {e}"))
                        try:
                            self.send_error(502, "Texture proxy error")
                        except Exception:
                            pass
                        return

                if last_http_error is not None:
                    try:
                        self.send_error(404, "Cape not found" if texture_type == "cape" else "Texture not found")
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
                    placeholder = os.path.join(BASE_DIR, 'ui', 'assets', 'images', 'version_placeholder.png')
                    if os.path.exists(placeholder):
                        with open(placeholder, 'rb') as f:
                            payload = f.read()
                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Content-Length", str(len(payload)))
                        self.send_header("Cache-Control", "public, max-age=3600")
                        self.end_headers()
                        self.wfile.write(payload)
                        print(colorize_log("[http_server] served placeholder skin as final fallback"))
                        return
                except Exception:
                    pass
        except Exception as e:
            print(colorize_log(f"[http_server] error handling texture request: {e}"))
            self.send_error(500, "Internal server error")

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
                "textures.histolauncher.workers.dev"
            ],
            "signaturePublickey": public_key,
            "links": {
                "homepage": "https://histolauncher.pages.dev",
                "register": "https://histolauncher.pages.dev/signup"
            }
        }

        return data


class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


def start_server(port):
    server = ThreadingHTTPServer(("127.0.0.1", port), RequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
