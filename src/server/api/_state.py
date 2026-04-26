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
        self.rpc_install_started_at: Dict[str, float] = {}
        self.loader_install_lock: threading.Lock = threading.Lock()
        self.active_loader_install_keys: set[str] = set()
        self.corrupted_versions_checked: bool = False
        self.import_progress: Dict[str, Dict[str, Any]] = {}

    def reset(self) -> None:
        self.operation_cancel_flags.clear()
        self.rpc_install_started_at.clear()
        self.active_loader_install_keys.clear()
        self.corrupted_versions_checked = False
        self.import_progress.clear()
        self.operation_cancel_lock = threading.Lock()
        self.loader_install_lock = threading.Lock()


STATE = _ApiState()
