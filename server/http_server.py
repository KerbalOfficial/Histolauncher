# server/http_server.py
import os
import sys
import json
import threading
import io
import base64

from http.server import SimpleHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, unquote

from .api_handler import handle_api_request, read_local_version, MAX_PAYLOAD_SIZE
from . import yggdrasil
from core.settings import get_base_dir
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
            self._send_ygg_metadata()
            return

        # Yggdrasil authenticate
        if path == "/authserver/authenticate":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            status, resp = yggdrasil.handle_auth_post(path, body, self.server.server_port)
            self._send_json(resp, status=status)
            return
        

        # Handle session profile lookups. Some proxies (authlib-injector)
        # prefix requests with an extra `sessionserver` segment, so accept
        # both `/authserver/session/minecraft/profile/...` and
        # `/authserver/sessionserver/session/minecraft/profile/...`.
        if (
            path.startswith("/authserver/session/minecraft/profile/")
            or path.startswith("/authserver/sessionserver/session/minecraft/profile/")
        ):
            status, resp = yggdrasil.handle_session_get(path, self.server.server_port)
            self._send_json(resp, status=status)
            return

        # Texture endpoint (serve skins from local storage)
        # Avoids Minecraft 1.21+ domain whitelist restrictions by serving from localhost
        if path.startswith("/textures/"):
            self._handle_texture_proxy(path)
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

        # Validate payload size before reading body
        if not self._check_content_length():
            return

        # Yggdrasil authenticate
        if path == "/authserver/authenticate":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            status, resp = yggdrasil.handle_auth_post(path, body, self.server.server_port)
            self._send_json(resp, status=status)
            return

        # API POSTs
        if path.startswith("/api/"):
            length = int(self.headers.get("Content-Length", 0))
            
            # Special handling for multipart/form-data (file upload for import)
            if path.startswith("/api/versions/import") and "multipart/form-data" in self.headers.get("Content-Type", ""):
                try:
                    # Read multipart form data
                    body_bytes = self.rfile.read(length)
                    form_data = parse_multipart_form(body_bytes, self.headers.get("Content-Type", ""))
                    
                    if form_data:
                        version_name = form_data.get('version_name', '').strip() if isinstance(form_data.get('version_name'), str) else ''
                        zip_data_binary = form_data.get('zip_file')
                        
                        if zip_data_binary:
                            # Encode binary data to base64
                            zip_data_base64 = base64.b64encode(zip_data_binary).decode('utf-8')
                            data = {
                                'version_name': version_name,
                                'zip_data': zip_data_base64
                            }
                        else:
                            data = {'version_name': version_name}
                        
                        print(f"[HTTP] POST /api/versions/import (multipart) - version_name: '{version_name}', zip_data length: {len(zip_data_binary) if zip_data_binary else 0}")
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
                # Regular JSON POST
                body = self.rfile.read(length).decode("utf-8")
                
                # Debug logging for import endpoint
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
            client_rel = path.lstrip("/")
            return os.path.join(get_base_dir(), client_rel)

        if path.startswith("/mods-cache/"):
            rel_path = unquote(path[len("/mods-cache/"):]).replace("/", os.sep)
            mods_root = os.path.join(get_base_dir(), "mods")
            target_path = os.path.normpath(os.path.join(mods_root, rel_path))

            try:
                if os.path.commonpath([mods_root, target_path]) != mods_root:
                    return os.path.join(UI_DIR, "__invalid_mod_cache_path__")
            except ValueError:
                return os.path.join(UI_DIR, "__invalid_mod_cache_path__")

            return target_path

        if path.startswith("/modpacks-cache/"):
            rel_path = unquote(path[len("/modpacks-cache/"):]).replace("/", os.sep)
            packs_root = os.path.join(get_base_dir(), "modpacks")
            target_path = os.path.normpath(os.path.join(packs_root, rel_path))

            try:
                if os.path.commonpath([packs_root, target_path]) != packs_root:
                    return os.path.join(UI_DIR, "__invalid_modpack_cache_path__")
            except ValueError:
                return os.path.join(UI_DIR, "__invalid_modpack_cache_path__")

            return target_path

        return os.path.join(UI_DIR, path.lstrip("/"))

    def _send_json(self, obj, status: int = 200):
        encoded = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _handle_texture_proxy(self, path):
        try:
            # Parse the requested texture path: /textures/skin/{uuid}
            parts = path.lstrip("/").split("/")
            if len(parts) < 3:
                self.send_error(404, "Invalid texture path")
                return
            
            texture_type = parts[1]  # 'skin', 'cape', 'head', etc.
            texture_id = "/".join(parts[2:])  # UUID or identifier
            
            # For now, only support skin textures
            if texture_type != "skin":
                self.send_error(404, "Texture type not supported")
                return
            
            # Validate texture_id to prevent path traversal
            # UUIDs should only contain hex characters and hyphens
            import re
            if not re.match(r'^[a-fA-F0-9\-]+$', texture_id):
                self.send_error(400, "Invalid texture ID")
                return
            
            # Try to load skin from local storage
            import os
            from core.settings import get_base_dir
            base_dir = get_base_dir()
            skins_dir = os.path.join(base_dir, "skins")

            # Normalize texture id: accept both dashed and undashed UUIDs
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
            # Prefer dashed filename (Histolauncher storage uses dashed UUIDs)
            skin_path_candidates = [
                os.path.join(skins_dir, f"{dashed}.png"),
                os.path.join(skins_dir, f"{texture_id}.png"),
            ]

            skin_path = None
            for candidate in skin_path_candidates:
                if os.path.exists(candidate) and os.path.isfile(candidate):
                    skin_path = candidate
                    texture_id = os.path.splitext(os.path.basename(candidate))[0]
                    break

            # Check if skin file exists
            if skin_path:
                try:
                    with open(skin_path, 'rb') as f:
                        texture_data = f.read()
                    
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(texture_data)))
                    self.send_header("Cache-Control", "public, max-age=3600")
                    self.end_headers()
                    self.wfile.write(texture_data)
                    print(colorize_log(f"[http_server] served local skin: {texture_id}"))
                except Exception as e:
                    print(colorize_log(f"[http_server] error reading skin file: {e}"))
                    self.send_error(500, "Error reading skin")
            else:
                # Fallback: proxy remote skin so multiplayer players' skins
                # still render even when not cached locally.
                import urllib.request
                import urllib.error

                remote_url = f"https://textures.histolauncher.workers.dev/skin/{dashed}"
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
                    print(colorize_log(f"[http_server] proxied remote skin: {dashed}"))
                except urllib.error.HTTPError as e:
                    print(colorize_log(f"[http_server] remote skin not found: {dashed} ({e.code})"))
                    try:
                        self.send_error(404, "Texture not found")
                    except Exception:
                        pass
                except Exception as e:
                    print(colorize_log(f"[http_server] remote skin proxy failed: {e}"))
                    try:
                        self.send_error(502, "Texture proxy error")
                    except Exception:
                        pass
        except Exception as e:
            print(colorize_log(f"[http_server] error handling texture request: {e}"))
            self.send_error(500, "Internal server error")

    def _send_ygg_metadata(self):
        port = self.server.server_port
        base = f"http://127.0.0.1:{port}/authserver"

        meta = {
            "serverName": f"Histolauncher {read_local_version(base_dir=BASE_DIR)}",
            "implementationName": "Histolauncher",
            "implementationVersion": "1",
        }
        # Use local reverse proxy URL
        skin_link = f"http://127.0.0.1:{port}/textures/skin/"
        links = {
            "authenticate": f"{base}/authenticate",
            "sessionserver": f"{base}/session/minecraft/profile/",
            "skin": skin_link,
        }
        # Whitelist localhost and external texture server as trusted domains
        skin_domains = [
            "127.0.0.1",
            "localhost",
            "textures.histolauncher.workers.dev",
        ]
        # Try to load a locally-generated public key. Prefer base64 DER (what
        # authlib/authlib-injector expects) and fall back to PEM if only PEM is present.
        pub_key = ""
        pub_key_source = None
        try:
            pub_b64_path = os.path.join(get_base_dir(), "signature_public.b64")
            pub_pem_path = os.path.join(get_base_dir(), "signature_public.pem")
            if os.path.exists(pub_b64_path):
                with open(pub_b64_path, "r", encoding="utf-8") as f:
                    pub_key = f.read().strip()
                pub_key_source = "b64"
            elif os.path.exists(pub_pem_path):
                # If only PEM exists, strip header/footer and use inner base64
                with open(pub_pem_path, "r", encoding="utf-8") as f:
                    pem = f.read().strip()
                lines = [l for l in pem.splitlines() if not l.startswith("-----")]
                pub_key = "".join(lines)
                pub_key_source = "pem"
        except Exception:
            pub_key = ""

        data = {
            "meta": meta,
            "links": links,
            "skinDomains": skin_domains,
        }
        if pub_key:
            # authlib/authlib-injector expects `signaturePublicKey` (capital K)
            data["signaturePublicKey"] = pub_key

            # Also expose PEM form if available so clients that prefer PEM can use it
            try:
                pem_path = os.path.join(get_base_dir(), "signature_public.pem")
                if os.path.exists(pem_path):
                    with open(pem_path, "r", encoding="utf-8") as f:
                        pem_text = f.read().strip()
                    data["signaturePublicKeyPem"] = pem_text
            except Exception:
                pass

        self._send_json(data, status=200)


def start_server(port):
    server = HTTPServer(("127.0.0.1", port), RequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
