from __future__ import annotations

import re

from core.modloaders.babric import fetch_babric_game_versions
from core.modloaders.fabric import fetch_fabric_game_versions
from core.modloaders.forge import fetch_forge_versions
from core.modloaders.legacyfabric import fetch_legacyfabric_game_versions
from core.modloaders.neoforge import fetch_neoforge_versions
from core.modloaders.ornithe import fetch_ornithe_game_versions
from core.modloaders.quilt import fetch_quilt_game_versions

__all__ = ["list_supported_mc_versions"]


_NEOFORGE_MC_RE = re.compile(r"^(\d+)\.(\d+)(?:\.|$)")

# Ornithe tags its pre-1.3 game versions with the client/server environment
# (e.g. "b1.7.3-client"); strip that so the values line up with the launcher's
# plain version folders.
_ORNITHE_ENV_SUFFIXES = ("-client", "-server", "-merged")


def _strip_ornithe_env_suffix(version: str) -> str:
    for suffix in _ORNITHE_ENV_SUFFIXES:
        if version.endswith(suffix):
            return version[: -len(suffix)]
    return version


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
        fetch_legacyfabric_game_versions,
    ):
        for entry in _safe_versions(fetch):
            if isinstance(entry, dict) and entry.get("version"):
                fabric_like.append(str(entry["version"]))

    for entry in _safe_versions(fetch_ornithe_game_versions):
        if isinstance(entry, dict) and entry.get("version"):
            fabric_like.append(_strip_ornithe_env_suffix(str(entry["version"])))

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
