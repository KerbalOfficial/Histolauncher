from __future__ import annotations

from server.api.dispatch import handle_api_request
from server.api.version_check import is_launcher_outdated


__all__ = ["handle_api_request", "is_launcher_outdated"]
