from __future__ import annotations

import socketserver
import threading
from http.server import HTTPServer

from server.http.handler import RequestHandler


__all__ = ["ThreadingHTTPServer", "start_server"]


class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


def start_server(port):
    server = ThreadingHTTPServer(("127.0.0.1", port), RequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
