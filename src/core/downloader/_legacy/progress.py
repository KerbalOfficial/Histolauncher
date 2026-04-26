from __future__ import annotations

import json
import os
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from core.downloader._legacy._constants import (
    ASSETS_DIR,
    ASSETS_INDEXES_DIR,
    ASSETS_OBJECTS_DIR,
    CACHE_LIBRARIES_DIR,
    PROGRESS_DIR,
    STAGE_WEIGHTS,
)
from core.downloader._legacy._state import STATE
from core.logger import colorize_log
from core.settings import get_versions_profile_dir


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


def ensure_dirs() -> None:
    os.makedirs(get_versions_profile_dir(), exist_ok=True)
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    os.makedirs(CACHE_LIBRARIES_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(ASSETS_INDEXES_DIR, exist_ok=True)
    os.makedirs(ASSETS_OBJECTS_DIR, exist_ok=True)


def encode_key(key: str) -> str:
    return urllib.parse.quote(key, safe="")


def progress_path(version_key: str) -> str:
    ensure_dirs()
    return os.path.join(PROGRESS_DIR, f"{encode_key(version_key)}.json")


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------


def write_progress(version_key: str, data: Dict[str, Any]) -> None:
    path = progress_path(version_key)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        try:
            from core.downloader.progress import _broadcast_progress

            _broadcast_progress(version_key, data)
        except Exception:
            pass
    except Exception:
        pass


def read_progress(version_key: str) -> Optional[Dict[str, Any]]:
    path = progress_path(version_key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def delete_progress(version_key: str) -> None:
    try:
        path = progress_path(version_key)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def list_progress_files() -> List[Tuple[str, Dict[str, Any]]]:
    ensure_dirs()
    out: List[Tuple[str, Dict[str, Any]]] = []
    for name in os.listdir(PROGRESS_DIR):
        if not name.endswith(".json"):
            continue
        path = os.path.join(PROGRESS_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = urllib.parse.unquote(name[:-5])
            out.append((key, data))
        except Exception:
            continue
    return out


def cleanup_orphaned_progress_files(max_age_seconds: int = 3600) -> None:
    try:
        ensure_dirs()
        current_time = time.time()

        for name in os.listdir(PROGRESS_DIR):
            if not name.endswith(".json"):
                continue
            path = os.path.join(PROGRESS_DIR, name)
            try:
                age_seconds = current_time - os.path.getmtime(path)
                if age_seconds <= max_age_seconds:
                    continue
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    status = str(data.get("status") or "").lower()
                    if status in ("downloading", "starting", "paused", "error"):
                        os.remove(path)
                        key = urllib.parse.unquote(name[:-5])
                        print(colorize_log(
                            f"[cleanup] Removed orphaned progress file for {key} "
                            f"(age: {age_seconds:.0f}s)"
                        ))
                except Exception:
                    pass
            except Exception:
                continue
    except Exception as e:
        print(colorize_log(f"[cleanup] Error cleaning orphaned progress files: {e}"))


# ---------------------------------------------------------------------------
# Cancellation / pause gates
# ---------------------------------------------------------------------------


def _check_pause(version_key: str) -> None:
    if not STATE.pause_flags.get(version_key):
        return

    prog = read_progress(version_key) or {}
    write_progress(
        version_key,
        {
            "status": "paused",
            "stage": prog.get("stage", "downloading"),
            "stage_percent": prog.get("stage_percent", 0),
            "overall_percent": prog.get("overall_percent", 0),
            "message": "Paused",
            "bytes_done": prog.get("bytes_done", 0),
            "bytes_total": prog.get("bytes_total", 0),
        },
    )

    while STATE.pause_flags.get(version_key):
        time.sleep(0.1)


def _maybe_abort(version_key: Optional[str]) -> None:
    if version_key:
        if STATE.cancel_flags.get(version_key):
            raise RuntimeError("Download cancelled by user")
        _check_pause(version_key)


# ---------------------------------------------------------------------------
# Overall % computation + atomic update
# ---------------------------------------------------------------------------


def _compute_overall(stage: str, stage_percent: float, version_key: str | None = None) -> float:
    if version_key and "modloader-" in version_key:
        loader_seq = ["download", "downloading_libs", "extracting_loader", "finalize"]
        loader_weights = {k: STAGE_WEIGHTS[k] for k in loader_seq if k in STAGE_WEIGHTS}
        total = 0.0
        for key, weight in loader_weights.items():
            if key == stage:
                total += weight * (stage_percent / 100.0)
                break
            total += weight
        return min(100.0, max(0.0, total))

    total = 0.0
    for key, weight in STAGE_WEIGHTS.items():
        if key == stage:
            total += weight * (stage_percent / 100.0)
            break
        total += weight
    return min(100.0, max(0.0, total))


def _update_progress(
    version_key: str,
    stage: str,
    stage_percent: float,
    message: str,
    bytes_done: int = 0,
    bytes_total: int = 0,
) -> None:
    overall = _compute_overall(stage, stage_percent, version_key)
    write_progress(
        version_key,
        {
            "status": "downloading",
            "stage": stage,
            "stage_percent": int(stage_percent),
            "overall_percent": int(overall),
            "message": message,
            "bytes_done": int(bytes_done),
            "bytes_total": int(bytes_total),
        },
    )
    print(
        colorize_log(
            f"[progress] {version_key} | {stage} {stage_percent:.1f}% "
            f"(overall {overall:.1f}%) - {message}"
        )
    )


__all__ = [
    "_check_pause",
    "_compute_overall",
    "_maybe_abort",
    "_update_progress",
    "cleanup_orphaned_progress_files",
    "delete_progress",
    "encode_key",
    "ensure_dirs",
    "list_progress_files",
    "progress_path",
    "read_progress",
    "write_progress",
]
