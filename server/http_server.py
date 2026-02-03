# server/http_server.py
import os
import json
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from .api_handler import handle_api_request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(BASE_DIR, "ui")

class RequestHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/launcher/version.dat":
            try:
                project_root = BASE_DIR
                version_path = os.path.join(project_root, "version.dat")
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

        if path == "/api/check_launcher_update":
            project_root = BASE_DIR
            local = read_local_version(project_root) if 'read_local_version' in globals() else None
            remote = fetch_remote_version() if 'fetch_remote_version' in globals() else None
            cmp = compare_versions(local, remote) if 'compare_versions' in globals() else {"local": local, "remote": remote}
            cmp["download_url"] = GITHUB_RELEASES_URL if 'GITHUB_RELEASES_URL' in globals() else "https://github.com/KerbalOfficial/Histolauncher/releases"
            cmp["raw_url"] = GITHUB_RAW_VERSION_URL if 'GITHUB_RAW_VERSION_URL' in globals() else "https://raw.githubusercontent.com/KerbalOfficial/Histolauncher/refs/heads/main/version.dat"
            self._send_json(cmp)
            return

        if path.startswith("/api/"):
            response = handle_api_request(self.path, None)
            self._send_json(response)
            return

        if self.path == "/":
            self.path = "/index.html"

        return super().do_GET()

    def do_POST(self):
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
            client_path = path.lstrip("/")
            return os.path.join(BASE_DIR, client_path)

        return os.path.join(UI_DIR, path.lstrip("/"))

    def _send_json(self, obj):
        encoded = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

def start_server(port):
    server = HTTPServer(("127.0.0.1", port), RequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
