# server/http_server.py
import os
import sys
import json
import threading

from http.server import SimpleHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from .api_handler import handle_api_request, read_local_version
from . import yggdrasil
from core.settings import get_base_dir

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(BASE_DIR, "ui")


class RequestHandler(SimpleHTTPRequestHandler):
    def handle_error(self):
        # Suppress benign connection reset errors that occur during startup or client cancellations
        try:
            exc_type, exc_value = sys.exc_info()[:2]
            if isinstance(exc_value, ConnectionResetError):
                return
        except Exception:
            pass
        super().handle_error()

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
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body) if body else None

            response = handle_api_request(self.path, data)
            self._send_json(response)
            return

        self.send_error(405, "Method Not Allowed")

    def translate_path(self, path):
        path = path.split("?", 1)[0]

        if path.startswith("/clients/"):
            client_rel = path.lstrip("/")
            return os.path.join(get_base_dir(), client_rel)

        return os.path.join(UI_DIR, path.lstrip("/"))

    def _send_json(self, obj, status: int = 200):
        encoded = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _handle_texture_proxy(self, path):
        """
        Serve textures from local storage.
        Skins can be stored at: ~/.histolauncher/skins/{uuid}.png
        """
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
                    print(f"[http_server] served local skin: {texture_id}")
                except Exception as e:
                    print(f"[http_server] error reading skin file: {e}")
                    self.send_error(500, "Error reading skin")
            else:
                # Skin not found - return 404
                print(f"[http_server] skin not found: {texture_id}")
                try:
                    self.send_error(404, "Texture not found")
                except Exception:
                    # Client may have disconnected - ignore
                    pass
        except Exception as e:
            print(f"[http_server] error handling texture request: {e}")
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
