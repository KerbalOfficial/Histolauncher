from __future__ import annotations

import threading
from typing import Any, Dict


__all__ = ["STATE", "CancelledOperationError"]


class CancelledOperationError(RuntimeError):
    pass


class _ApiState:
    def __init__(self) -> None:
        self.operation_cancel_lock: threading.Lock = threading.Lock()
        self.operation_cancel_flags: Dict[str, bool] = {}
        self.file_import_lock: threading.Lock = threading.Lock()
        self.pending_file_imports: Dict[str, Dict[str, Any]] = {}
        self.rpc_install_started_at: Dict[str, float] = {}
        self.loader_install_lock: threading.Lock = threading.Lock()
        self.active_loader_install_keys: set[str] = set()
        self.corrupted_versions_checked: bool = False
        self.import_progress: Dict[str, Dict[str, Any]] = {}

    def reset(self) -> None:
        with self.operation_cancel_lock:
            self.operation_cancel_flags.clear()
            self.rpc_install_started_at.clear()
        with self.loader_install_lock:
            self.active_loader_install_keys.clear()
        with self.file_import_lock:
            self.pending_file_imports.clear()
        self.corrupted_versions_checked = False
        self.import_progress.clear()


STATE = _ApiState()
