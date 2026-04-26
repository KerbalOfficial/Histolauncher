from __future__ import annotations

import platform
import re

__all__ = [
    "current_library_os_name",
    "extract_neoforge_mc_channel",
    "fabric_snapshot_is_supported",
    "fabric_version_meets_minimum",
    "loader_version_is_stable",
    "loader_version_sort_key",
    "neoforge_version_matches_mc",
    "normalize_neoforge_mc_channel",
    "parse_loader_type",
]


_FABRIC_SNAPSHOT_RE = re.compile(r"^(\d{2})w(\d{2})[a-z](?:[-_].*)?$")
_FABRIC_RELEASE_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?(?:[-_].*)?$")


def loader_version_sort_key(v: str) -> tuple:
    if not isinstance(v, str):
        return (0,)

    main, sep, suffix = v.partition("-")
    numeric_parts: list[int] = []
    for token in main.split("."):
        try:
            numeric_parts.append(int(token))
        except ValueError:
            numeric_parts.append(0)

    while len(numeric_parts) < 6:
        numeric_parts.append(0)

    suffix_rank = 0 if not sep else -1
    return tuple(numeric_parts + [suffix_rank, suffix.lower() if suffix else ""])


def loader_version_is_stable(version: str) -> bool:
    lower = str(version or "").strip().lower()
    if not lower:
        return False
    return all(token not in lower for token in ("alpha", "beta", "rc", "snapshot"))


def current_library_os_name() -> str:
    system = platform.system().lower()
    if "windows" in system:
        return "windows"
    if "darwin" in system or "mac" in system:
        return "osx"
    if "linux" in system:
        return "linux"
    return system


def normalize_neoforge_mc_channel(mc_version: str) -> str:
    value = str(mc_version or "").strip()
    if not value:
        return ""
    if value.startswith("1."):
        value = value[2:]
    parts = [p for p in value.split(".") if p != ""]
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def extract_neoforge_mc_channel(version_str: str) -> str:
    base = str(version_str or "").strip().split("-", 1)[0]
    raw_parts = [p for p in base.split(".") if p != ""]
    if len(raw_parts) < 2 or any(not p.isdigit() for p in raw_parts):
        return ""
    mc_parts = raw_parts[:-1]
    while len(mc_parts) > 1 and mc_parts[-1] == "0":
        mc_parts.pop()
    return ".".join(mc_parts)


def neoforge_version_matches_mc(version_str: str, mc_version: str) -> bool:
    requested = normalize_neoforge_mc_channel(mc_version)
    candidate = extract_neoforge_mc_channel(version_str)
    return bool(requested and candidate and requested == candidate)


def fabric_snapshot_is_supported(mc_version: str) -> bool:
    match = _FABRIC_SNAPSHOT_RE.match(str(mc_version or "").strip().lower())
    if not match:
        return False
    year = int(match.group(1))
    week = int(match.group(2))
    return year > 18 or (year == 18 and week >= 43)


def fabric_version_meets_minimum(mc_version: str) -> bool:
    value = str(mc_version or "").strip()
    if not value:
        return False
    if fabric_snapshot_is_supported(value):
        return True
    match = _FABRIC_RELEASE_RE.match(value)
    if not match:
        return False
    major = int(match.group(1))
    minor = int(match.group(2))
    if major > 1:
        return True
    if major < 1:
        return False
    return minor >= 14


def parse_loader_type(loader_str: str) -> str | None:
    lower = (loader_str or "").lower().strip()
    if not lower:
        return None
    if "babric" in lower:
        return "babric"
    if "mod loader" in lower or "modloader" in lower or "risugami" in lower:
        return "modloader"
    if "neoforge" in lower:
        return "neoforge"
    if "quilt" in lower:
        return "quilt"
    if "fabric" in lower:
        return "fabric"
    if "forge" in lower:
        return "forge"
    return None
