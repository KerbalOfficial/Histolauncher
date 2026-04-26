from __future__ import annotations

import json
import os
import queue
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.downloader._paths import PROGRESS_DIR, ensure_progress_dir
from core.logger import colorize_log

#: Minimum interval between disk flushes, seconds.
DEFAULT_FLUSH_INTERVAL: float = 0.1


# ---------------------------------------------------------------------------
# Global SSE PubSub implementation
# ---------------------------------------------------------------------------

_listeners_lock = threading.Lock()
_listeners: List[queue.Queue] = []

def add_progress_listener(q: queue.Queue) -> None:
    with _listeners_lock:
        _listeners.append(q)

def remove_progress_listener(q: queue.Queue) -> None:
    with _listeners_lock:
        if q in _listeners:
            _listeners.remove(q)

def _broadcast_progress(key: str, data: Dict[str, Any]) -> None:
    payload = {"version_key": _encode_key(key), **data}
    with _listeners_lock:
        for q in _listeners:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass


# ---------------------------------------------------------------------------
# On-disk store (preserves legacy JSON shape and filename encoding)
# ---------------------------------------------------------------------------


def _encode_key(key: str) -> str:
    return urllib.parse.quote(key, safe="")


def _decode_key(name: str) -> str:
    return urllib.parse.unquote(name)


def progress_file_path(key: str) -> str:
    ensure_progress_dir()
    return os.path.join(PROGRESS_DIR, f"{_encode_key(key)}.json")


def write_progress_dict(key: str, data: Dict[str, Any]) -> None:
    path = progress_file_path(key)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def read_progress_dict(key: str) -> Optional[Dict[str, Any]]:
    path = progress_file_path(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def delete_progress(key: str) -> None:
    try:
        path = progress_file_path(key)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def list_progress_files() -> List[Tuple[str, Dict[str, Any]]]:
    ensure_progress_dir()
    out: List[Tuple[str, Dict[str, Any]]] = []
    for name in os.listdir(PROGRESS_DIR):
        if not name.endswith(".json"):
            continue
        path = os.path.join(PROGRESS_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            out.append((_decode_key(name[:-5]), data))
        except Exception:
            continue
    return out


def cleanup_orphaned_progress_files(max_age_seconds: int = 3600) -> None:
    try:
        ensure_progress_dir()
        now = time.time()
        for name in os.listdir(PROGRESS_DIR):
            if not name.endswith(".json"):
                continue
            path = os.path.join(PROGRESS_DIR, name)
            try:
                if (now - os.path.getmtime(path)) <= max_age_seconds:
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                status = str(data.get("status") or "").lower()
                if status in ("downloading", "starting", "paused", "error"):
                    os.remove(path)
                    print(colorize_log(
                        f"[cleanup] Removed orphaned progress for "
                        f"{_decode_key(name[:-5])}"
                    ))
            except Exception:
                continue
    except Exception as exc:  # noqa: BLE001
        print(colorize_log(f"[cleanup] Error scanning progress dir: {exc}"))


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------


@dataclass
class StageWeight:
    name: str
    weight: int


# Legacy weights, retained verbatim so saved progress files are interpreted
# the same way by the current UI.
VANILLA_STAGES: Tuple[StageWeight, ...] = (
    StageWeight("version_json", 5),
    StageWeight("client", 20),
    StageWeight("libraries", 25),
    StageWeight("natives", 15),
    StageWeight("assets", 25),
    StageWeight("finalize", 10),
)

LOADER_STAGES: Tuple[StageWeight, ...] = (
    StageWeight("download", 20),
    StageWeight("downloading_libs", 40),
    StageWeight("extracting_loader", 30),
    StageWeight("finalize", 10),
)


def stage_weights_for_kind(kind: str) -> Tuple[StageWeight, ...]:
    if kind == "loader":
        return LOADER_STAGES
    return VANILLA_STAGES


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------


@dataclass
class _StageState:
    name: str
    percent: float = 0.0
    message: str = ""


class ProgressTracker:
    def __init__(
        self,
        key: str,
        *,
        kind: str = "vanilla",
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
        stages: Optional[Tuple[StageWeight, ...]] = None,
    ) -> None:
        self.key = key
        self.kind = kind
        self._stages: Tuple[StageWeight, ...] = stages or stage_weights_for_kind(kind)
        self._stage_index = {s.name: i for i, s in enumerate(self._stages)}
        self._lock = threading.RLock()
        self._current = _StageState(name=self._stages[0].name)
        self._bytes_done = 0
        self._bytes_total = 0
        self._status = "starting"
        self._dirty = False
        self._flush_interval = max(0.0, flush_interval)
        self._last_flush = 0.0

    # ---- mutation ----------------------------------------------------------

    def set_total_bytes(self, total: int) -> None:
        with self._lock:
            self._bytes_total = max(0, int(total))
            self._dirty = True
        self._maybe_flush()

    def add_bytes(self, delta: int) -> None:
        if delta <= 0:
            return
        with self._lock:
            self._bytes_done += int(delta)
            if self._bytes_total and self._bytes_done > self._bytes_total:
                # Allow over-shoot rather than clamp — legacy code did the same.
                pass
            self._dirty = True
        self._maybe_flush()

    def update(
        self,
        stage: str,
        percent: float,
        message: str,
        *,
        bytes_done: Optional[int] = None,
        bytes_total: Optional[int] = None,
    ) -> None:
        with self._lock:
            self._current = _StageState(
                name=stage, percent=max(0.0, min(100.0, float(percent))), message=message
            )
            if bytes_done is not None:
                self._bytes_done = int(bytes_done)
            if bytes_total is not None:
                self._bytes_total = int(bytes_total)
            self._status = "downloading"
            self._dirty = True
        self._maybe_flush(force=True)

    def set_status(self, status: str, message: Optional[str] = None) -> None:
        with self._lock:
            self._status = status
            if message is not None:
                self._current.message = message
            self._dirty = True
        self._maybe_flush(force=True)

    # ---- snapshots ---------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            overall = self._compute_overall_locked()
            return {
                "status": self._status,
                "stage": self._current.name,
                "stage_percent": round(float(self._current.percent), 1),
                "overall_percent": round(float(overall), 1),
                "message": self._current.message,
                "bytes_done": int(self._bytes_done),
                "bytes_total": int(self._bytes_total),
            }

    def _compute_overall_locked(self) -> float:
        # Prefer byte-accurate overall when totals are known.
        if self._bytes_total > 0:
            pct = (self._bytes_done * 100.0) / self._bytes_total
            return max(0.0, min(100.0, pct))

        # Fall back to weighted-stage approach (matches legacy semantics).
        total_weight = sum(s.weight for s in self._stages) or 1
        accumulated = 0.0
        for stage in self._stages:
            if stage.name == self._current.name:
                accumulated += stage.weight * (self._current.percent / 100.0)
                break
            accumulated += stage.weight
        return max(0.0, min(100.0, (accumulated / total_weight) * 100.0))

    # ---- persistence -------------------------------------------------------

    def _maybe_flush(self, *, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_flush) < self._flush_interval:
            return
        with self._lock:
            if not self._dirty:
                return
            data = self.snapshot()
            self._dirty = False
            self._last_flush = now
        write_progress_dict(self.key, data)
        _broadcast_progress(self.key, data)

    def flush(self) -> None:
        self._maybe_flush(force=True)

    def finish(self, *, status: str, message: str, keep_seconds: float = 0.5) -> None:
        with self._lock:
            self._status = status
            self._current = _StageState(
                name=self._current.name,
                percent=100.0 if status == "installed" else self._current.percent,
                message=message,
            )
            self._dirty = True
        self.flush()

        if keep_seconds > 0:
            def _cleanup() -> None:
                time.sleep(keep_seconds)
                delete_progress(self.key)

            threading.Thread(target=_cleanup, daemon=True).start()
        else:
            delete_progress(self.key)


__all__ = [
    "DEFAULT_FLUSH_INTERVAL",
    "LOADER_STAGES",
    "ProgressTracker",
    "StageWeight",
    "VANILLA_STAGES",
    "cleanup_orphaned_progress_files",
    "delete_progress",
    "list_progress_files",
    "progress_file_path",
    "read_progress_dict",
    "stage_weights_for_kind",
    "write_progress_dict",
]
