from __future__ import annotations

import re

from core.modloaders.babric import fetch_babric_game_versions
from core.modloaders.fabric import fetch_fabric_game_versions
from core.modloaders.forge import fetch_forge_versions
from core.modloaders.neoforge import fetch_neoforge_versions
from core.modloaders.quilt import fetch_quilt_game_versions

__all__ = ["list_supported_mc_versions"]


_NEOFORGE_MC_RE = re.compile(r"^(\d+)\.(\d+)(?:\.|$)")


def _safe_versions(fetch) -> list:
    try:
        result = fetch()
    except Exception:
        return []
    return result or []


def list_supported_mc_versions() -> tuple[list[str], list[str]]:
    fabric_like: list[str] = []
    for fetch in (
        fetch_fabric_game_versions,
        fetch_quilt_game_versions,
        fetch_babric_game_versions,
    ):
        for entry in _safe_versions(fetch):
            if isinstance(entry, dict) and entry.get("version"):
                fabric_like.append(str(entry["version"]))

    forge_like: list[str] = []
    seen: set[str] = set()
    for entry in _safe_versions(fetch_forge_versions):
        if not isinstance(entry, str) or "-" not in entry:
            continue
        mc_ver = entry.rsplit("-", 1)[0]
        if mc_ver and mc_ver not in seen:
            forge_like.append(mc_ver)
            seen.add(mc_ver)

    for entry in _safe_versions(fetch_neoforge_versions):
        if not entry:
            continue
        match = _NEOFORGE_MC_RE.match(str(entry).split("-", 1)[0])
        if not match:
            continue
        major, minor = match.group(1), match.group(2)
        mc_ver = f"1.{major}" if minor == "0" else f"1.{major}.{minor}"
        if mc_ver not in seen:
            forge_like.append(mc_ver)
            seen.add(mc_ver)

    return sorted(set(fabric_like)), sorted(set(forge_like), reverse=True)
