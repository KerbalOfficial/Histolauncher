from __future__ import annotations

import socketserver
import sys
import threading
from http.server import HTTPServer

from server.http.handler import RequestHandler


__all__ = ["ThreadingHTTPServer", "start_server"]


class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 256

    def handle_error(self, request, client_address):
        exc_value = sys.exc_info()[1]
        if isinstance(exc_value, (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def start_server(port):
    server = ThreadingHTTPServer(("127.0.0.1", port), RequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
