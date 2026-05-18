from __future__ import annotations

import ctypes
import os
import platform
from typing import Any


__all__ = [
    "SMART_SETTINGS_GC_FLAGS",
    "detect_memory_status",
    "recommend_smart_settings",
]


SMART_SETTINGS_GC_FLAGS = (
    "-XX:+UseG1GC "
    "-XX:+UnlockExperimentalVMOptions "
    "-XX:MaxGCPauseMillis=50 "
    "-XX:G1ReservePercent=20 "
    "-XX:InitiatingHeapOccupancyPercent=15 "
    "-XX:+DisableExplicitGC"
)


def _round_down(value: int, step: int = 256) -> int:
    if value <= 0:
        return 0
    return max(step, (int(value) // step) * step)


def _ram_string(megabytes: int) -> str:
    return f"{int(max(1, megabytes))}M"


def _detect_windows_memory() -> dict[str, Any] | None:
    if platform.system().lower() != "windows":
        return None

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
    except Exception:
        return None

    mib = 1024 * 1024
    total_mb = int(status.ullTotalPhys // mib)
    available_mb = int(status.ullAvailPhys // mib)
    used_mb = max(0, total_mb - available_mb)
    return {
        "ok": total_mb > 0,
        "source": "windows",
        "total_mb": total_mb,
        "available_mb": available_mb,
        "used_mb": used_mb,
        "used_percent": int(status.dwMemoryLoad),
    }


def _detect_proc_meminfo() -> dict[str, Any] | None:
    path = "/proc/meminfo"
    if not os.path.isfile(path):
        return None

    values: dict[str, int] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                if ":" not in raw:
                    continue
                key, rest = raw.split(":", 1)
                parts = rest.strip().split()
                if not parts:
                    continue
                values[key] = int(parts[0])
    except Exception:
        return None

    total_kb = int(values.get("MemTotal") or 0)
    available_kb = int(values.get("MemAvailable") or values.get("MemFree") or 0)
    if total_kb <= 0:
        return None

    total_mb = total_kb // 1024
    available_mb = available_kb // 1024
    used_mb = max(0, total_mb - available_mb)
    used_percent = int(round((used_mb / total_mb) * 100)) if total_mb else 0
    return {
        "ok": True,
        "source": "proc_meminfo",
        "total_mb": total_mb,
        "available_mb": available_mb,
        "used_mb": used_mb,
        "used_percent": used_percent,
    }


def _detect_sysconf_memory() -> dict[str, Any] | None:
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None

    mib = 1024 * 1024
    total_mb = int((page_size * pages) // mib)
    available_mb = int((page_size * available_pages) // mib)
    used_mb = max(0, total_mb - available_mb)
    used_percent = int(round((used_mb / total_mb) * 100)) if total_mb else 0
    return {
        "ok": total_mb > 0,
        "source": "sysconf",
        "total_mb": total_mb,
        "available_mb": available_mb,
        "used_mb": used_mb,
        "used_percent": used_percent,
    }


def detect_memory_status() -> dict[str, Any]:
    for detector in (_detect_windows_memory, _detect_proc_meminfo, _detect_sysconf_memory):
        status = detector()
        if status and status.get("ok"):
            return status
    return {
        "ok": False,
        "source": "unknown",
        "total_mb": 0,
        "available_mb": 0,
        "used_mb": 0,
        "used_percent": 0,
    }


def _total_memory_cap(total_mb: int) -> int:
    if total_mb <= 0:
        return 2048
    if total_mb <= 3072:
        return 1024
    if total_mb <= 4096:
        return 1536
    if total_mb <= 6144:
        return 2048
    if total_mb <= 8192:
        return 3072
    if total_mb <= 12288:
        return 4096
    if total_mb <= 16384:
        return 6144
    return min(8192, _round_down(total_mb // 2))


def _reserve_memory(total_mb: int) -> int:
    if total_mb <= 4096:
        return 768
    if total_mb <= 8192:
        return 1536
    if total_mb <= 16384:
        return 2048
    return 3072


def _minimum_game_heap(total_mb: int) -> int:
    return 768 if total_mb and total_mb <= 3072 else 1024


def _initial_heap_for(max_mb: int) -> int:
    if max_mb <= 1024:
        return 512
    if max_mb <= 1536:
        return 768
    if max_mb <= 3072:
        return 1024
    return 1536


def recommend_smart_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    current = dict(settings or {})
    memory = detect_memory_status()
    total_mb = int(memory.get("total_mb") or 0)
    available_mb = int(memory.get("available_mb") or 0)

    total_cap = _total_memory_cap(total_mb)
    reserve_mb = _reserve_memory(total_mb)
    floor_mb = _minimum_game_heap(total_mb)
    available_cap = available_mb - reserve_mb if available_mb > 0 else total_cap
    target_mb = max(floor_mb, min(total_cap, available_cap))
    max_mb = _round_down(target_mb)
    if max_mb < floor_mb:
        max_mb = floor_mb
    if max_mb >= total_cap:
        max_mb = _round_down(total_cap)

    min_mb = min(_initial_heap_for(max_mb), max(512, max_mb - 256))

    return {
        "min_ram": _ram_string(min_mb),
        "max_ram": _ram_string(max_mb),
        "extra_jvm_args": SMART_SETTINGS_GC_FLAGS,
        "memory": memory,
        "previous": {
            "min_ram": str(current.get("min_ram") or ""),
            "max_ram": str(current.get("max_ram") or ""),
            "extra_jvm_args": str(current.get("extra_jvm_args") or ""),
        },
        "reason": (
            f"{available_mb} MB available of {total_mb} MB total"
            if total_mb and available_mb
            else "system memory unavailable; used safe defaults"
        ),
    }
