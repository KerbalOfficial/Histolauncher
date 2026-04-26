from __future__ import annotations

import threading
from typing import Tuple


class ThreadSafeProgress:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.bytes_done = 0
        self.bytes_total = 0

    def add_done(self, delta: int) -> None:
        with self._lock:
            self.bytes_done += delta

    def add_total(self, delta: int) -> None:
        with self._lock:
            self.bytes_total += delta

    def set_totals(self, done: int, total: int) -> None:
        with self._lock:
            self.bytes_done = done
            self.bytes_total = total

    def get_totals(self) -> Tuple[int, int]:
        with self._lock:
            return (self.bytes_done, self.bytes_total)

    def reset(self) -> None:
        with self._lock:
            self.bytes_done = 0
            self.bytes_total = 0


class DownloadState:
    def __init__(self) -> None:
        self.workers: dict[str, threading.Thread] = {}
        self.cancel_flags: dict[str, bool] = {}
        self.pause_flags: dict[str, bool] = {}
        self.file_locks: dict[str, threading.Lock] = {}
        self.file_locks_lock: threading.Lock = threading.Lock()

    def reset(self) -> None:
        self.workers.clear()
        self.cancel_flags.clear()
        self.pause_flags.clear()
        with self.file_locks_lock:
            self.file_locks.clear()


#: Singleton state used by the entire downloader package.
STATE = DownloadState()


__all__ = ["STATE", "DownloadState", "ThreadSafeProgress"]
