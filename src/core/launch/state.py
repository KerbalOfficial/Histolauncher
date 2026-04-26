from __future__ import annotations

import threading
from typing import Any


class _LaunchState:
    def __init__(self) -> None:
        self.active_processes: dict[str, dict[str, Any]] = {}
        self.process_lock: threading.Lock = threading.Lock()
        self.last_launch_errors: dict[str, str] = {}
        self.last_launch_diagnostics: dict[str, dict[str, Any]] = {}
        self.last_launch_error_lock: threading.Lock = threading.Lock()

    def reset(self) -> None:
        with self.process_lock:
            self.active_processes.clear()
        with self.last_launch_error_lock:
            self.last_launch_errors.clear()
            self.last_launch_diagnostics.clear()


STATE = _LaunchState()

__all__ = ["STATE"]
