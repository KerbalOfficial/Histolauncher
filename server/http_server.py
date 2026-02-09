# server/http_server.py
import os
import json
import threading

from http.server import SimpleHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from .api_handler import handle_api_request
from . import yggdrasil
from core.settings import get_base_dir

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(BASE_DIR, "ui")


class RequestHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Launcher version file
        if path == "/launcher/version.dat":
            try:
                version_path = os.path.join(BASE_DIR, "version.dat")
                with open(version_path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                self.send_error(404, "version.dat not found")
            return

        # Yggdrasil metadata for authlib-injector
        if path == "/authserver":
            self._send_ygg_metadata()
            return

        # Yggdrasil session profile
        if path.startswith("/sessionserver/session/minecraft/profile/"):
            status, resp = yggdrasil.handle_session_get(path, self.server.server_port)
            self._send_json(resp, status=status)
            return

        # API endpoints
        if path.startswith("/api/"):
            response = handle_api_request(self.path, None)
            self._send_json(response)
            return

        if self.path == "/":
            self.path = "/index.html"

        return super().do_GET()

    def do_POST(self):
        # Yggdrasil authenticate
        if self.path == "/authserver/authenticate":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            status, resp = yggdrasil.handle_auth_post(self.path, body, self.server.server_port)
            self._send_json(resp, status=status)
            return

        if self.path.startswith("/api/"):
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

        if path.startswith("/skins/"):
            skin_rel = path.lstrip("/")
            return os.path.join(get_base_dir(), skin_rel)

        return os.path.join(UI_DIR, path.lstrip("/"))

    def _send_json(self, obj, status: int = 200):
        encoded = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_ygg_metadata(self):
        """
        Minimal Yggdrasil-compatible metadata for authlib-injector.
        Points authenticate + sessionserver to this same HTTP server.
        """
        port = self.server.server_port
        base = f"http://127.0.0.1:{port}"

        data = {
            "meta": {
                "serverName": "Histolauncher Offline",
                "implementationName": "Histolauncher",
                "implementationVersion": "1",
            },
            "links": {
                "authenticate": f"{base}/authserver/authenticate",
                "sessionserver": f"{base}/sessionserver/session/minecraft/profile/",
            }
        }
        self._send_json(data, status=200)


def start_server(port):
    server = HTTPServer(("127.0.0.1", port), RequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
