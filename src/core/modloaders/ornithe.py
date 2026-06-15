from __future__ import annotations

import urllib.parse
from typing import Any

from core.logger import safe_print
from core.modloaders._endpoints import ORNITHE_META_API
from core.modloaders._http import _http_get_json
from core.modloaders._versions import (
    current_library_os_name,
    loader_version_is_stable,
    loader_version_sort_key,
)
from core.modloaders.cache import TTLCache, register_cache

__all__ = [
    "fetch_ornithe_game_versions",
    "fetch_ornithe_loader_profile_libraries",
    "fetch_ornithe_loaders",
    "get_ornithe_loader_libraries",
    "get_ornithe_loaders_for_version",
    "ornithe_generation",
    "resolve_ornithe_game_version",
    "resolve_ornithe_target",
    "supported_ornithe_mc_versions",
    "supports_ornithe_mc_version",
]


_GEN1 = "gen1"
_GEN2 = "gen2"

_GAME_VERSION_SUFFIXES: tuple[str, ...] = ("", "-client", "-merged", "-server")

_DEFAULT_ORNITHE_MAVEN = "https://maven.ornithemc.net/releases/"
_FABRIC_MAVEN = "https://maven.fabricmc.net/"
_MAVEN_CENTRAL = "https://repo1.maven.org/maven2/"

_intermediary_cache: TTLCache[set[str]] = register_cache(TTLCache())
_loaders_cache: TTLCache[list[dict[str, Any]]] = register_cache(TTLCache())


def _gen_path(generation: str) -> str:
    return "gen2/" if generation == _GEN2 else ""


def _fetch_intermediary_names(generation: str) -> set[str]:
    cached = _intermediary_cache.get(generation)
    if cached is not None:
        return cached
    try:
        data = _http_get_json(
            f"{ORNITHE_META_API}/versions/{_gen_path(generation)}intermediary"
        )
    except RuntimeError as exc:
        safe_print(
            f"[modloaders] Failed to fetch Ornithe {generation} intermediary list: {exc}"
        )
        return set()
    names: set[str] = set()
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and entry.get("version"):
                names.add(str(entry["version"]))
    if names:
        _intermediary_cache.set(generation, names)
    safe_print(
        f"[modloaders] Fetched {len(names)} Ornithe {generation} intermediary versions"
    )
    return names


def resolve_ornithe_target(mc_version: str) -> tuple[str, str] | None:
    value = str(mc_version or "").strip()
    if not value:
        return None

    gen2 = _fetch_intermediary_names(_GEN2)
    if value in gen2:
        return (_GEN2, value)

    gen1 = _fetch_intermediary_names(_GEN1)
    for suffix in _GAME_VERSION_SUFFIXES:
        if value + suffix in gen1:
            return (_GEN1, value + suffix)

    return None


def ornithe_generation(mc_version: str) -> str | None:
    target = resolve_ornithe_target(mc_version)
    return target[0] if target else None


def resolve_ornithe_game_version(mc_version: str) -> str | None:
    target = resolve_ornithe_target(mc_version)
    return target[1] if target else None


def supports_ornithe_mc_version(mc_version: str) -> bool:
    return resolve_ornithe_target(mc_version) is not None


def _strip_env_suffix(name: str) -> str:
    for suffix in ("-client", "-merged", "-server"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def supported_ornithe_mc_versions() -> set[str]:
    names: set[str] = set()
    for version in _fetch_intermediary_names(_GEN1):
        names.add(_strip_env_suffix(version))
    names |= _fetch_intermediary_names(_GEN2)
    return names


def fetch_ornithe_game_versions() -> list[dict[str, Any]] | None:
    names = supported_ornithe_mc_versions()
    if not names:
        return None
    return [{"version": version} for version in sorted(names)]


def fetch_ornithe_loaders(mc_version: str) -> list[dict[str, Any]] | None:
    target = resolve_ornithe_target(mc_version)
    if not target:
        return None
    generation, game_version = target
    cache_key = f"loaders:{generation}:{game_version}"
    cached = _loaders_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        encoded_mc = urllib.parse.quote(game_version, safe="")
        data = _http_get_json(
            f"{ORNITHE_META_API}/versions/{_gen_path(generation)}fabric-loader/{encoded_mc}"
        )
    except RuntimeError as exc:
        safe_print(
            f"[modloaders] Failed to fetch Ornithe loaders for {mc_version}: {exc}")
        return None
    if not isinstance(data, list):
        safe_print("[modloaders] Unexpected Ornithe response format")
        return None
    _loaders_cache.set(cache_key, data)
    safe_print(
        f"[modloaders] Fetched {len(data)} Ornithe loader versions for "
        f"{game_version} ({generation})"
    )
    return data


def get_ornithe_loaders_for_version(
    mc_version: str, stable_only: bool = False
) -> list[dict[str, Any]]:
    if not supports_ornithe_mc_version(mc_version):
        return []

    loaders = fetch_ornithe_loaders(mc_version)
    if not loaders:
        return []

    result: list[dict[str, Any]] = []
    for entry in loaders:
        loader_data = entry.get("loader") if isinstance(entry, dict) else None
        version = (loader_data or {}).get("version") if isinstance(loader_data, dict) else None
        if not version:
            continue
        stable = bool(
            (loader_data or {}).get("stable", loader_version_is_stable(version))
        )
        if stable_only and not stable:
            continue
        result.append(
            {
                "version": version,
                "stable": stable,
                "loader": loader_data or {},
                "intermediary": entry.get("intermediary") if isinstance(entry, dict) else {},
                "launcherMeta": entry.get("launcherMeta") if isinstance(entry, dict) else {},
            }
        )

    result.sort(key=lambda item: loader_version_sort_key(item.get("version", "")), reverse=True)
    return result


def fetch_ornithe_loader_profile_libraries(
    loader_version: str, mc_version: str
) -> list[tuple[str, str]] | None:
    target = resolve_ornithe_target(mc_version)
    if not target:
        return None
    generation, game_version = target
    try:
        mc_enc = urllib.parse.quote(game_version, safe="")
        loader_enc = urllib.parse.quote(loader_version, safe="")
        profile = _http_get_json(
            f"{ORNITHE_META_API}/versions/{_gen_path(generation)}fabric-loader/"
            f"{mc_enc}/{loader_enc}/profile/json"
        )
    except RuntimeError as exc:
        safe_print(
            "[modloaders] Failed to fetch Ornithe profile libraries for "
            f"{game_version}/{loader_version}: {exc}"
        )
        return None

    deps: list[tuple[str, str]] = []
    current_os = current_library_os_name()
    for lib_entry in (profile or {}).get("libraries", []):
        if not isinstance(lib_entry, dict):
            continue
        downloads = lib_entry.get("downloads") if isinstance(lib_entry.get("downloads"), dict) else {}
        classifiers = downloads.get("classifiers") if isinstance(downloads, dict) else None
        artifact_download = (downloads.get("artifact") if isinstance(downloads, dict) else {}) or {}
        artifact_url = artifact_download.get("url")

        lib_name = str(lib_entry.get("name") or "").strip()
        lib_url = str(lib_entry.get("url") or _DEFAULT_ORNITHE_MAVEN).strip()

        if classifiers and not artifact_url:
            natives = lib_entry.get("natives") if isinstance(lib_entry.get("natives"), dict) else {}
            classifier = str((natives or {}).get(current_os) or "").strip()
            if not classifier:
                continue
            lib_name = f"{lib_name}:{classifier}"

        if lib_name:
            deps.append((lib_name, lib_url))

    if deps:
        safe_print(
            f"[modloaders] Extracted {len(deps)} official Ornithe libraries "
            f"from profile {game_version}/{loader_version} ({generation})"
        )
        return deps

    safe_print(
        f"[modloaders] Ornithe profile {game_version}/{loader_version} had no libraries")
    return None


def get_ornithe_loader_libraries(
    loader_version: str, mc_version: str
) -> list[tuple[str, str]]:
    safe_print(
        f"[modloaders] Fetching official Ornithe libraries for {loader_version}...")
    profile_deps = fetch_ornithe_loader_profile_libraries(loader_version, mc_version)
    if profile_deps:
        return profile_deps

    target = resolve_ornithe_target(mc_version)
    generation, game_version = target if target else (_GEN1, str(mc_version or "").strip())
    calamus = "calamus-intermediary-gen2" if generation == _GEN2 else "calamus-intermediary"
    safe_print(
        f"[modloaders] Using fallback dependencies for Ornithe {loader_version}")
    return [
        (f"net.fabricmc:fabric-loader:{loader_version}", _FABRIC_MAVEN),
        (f"net.ornithemc:{calamus}:{game_version}", _DEFAULT_ORNITHE_MAVEN),
        ("net.fabricmc:sponge-mixin:0.17.3+mixin.0.8.7", _FABRIC_MAVEN),
        ("org.ow2.asm:asm:9.10.1", _FABRIC_MAVEN),
        ("org.ow2.asm:asm-analysis:9.10.1", _FABRIC_MAVEN),
        ("org.ow2.asm:asm-commons:9.10.1", _FABRIC_MAVEN),
        ("org.ow2.asm:asm-tree:9.10.1", _FABRIC_MAVEN),
        ("org.ow2.asm:asm-util:9.10.1", _FABRIC_MAVEN),
        ("org.apache.logging.log4j:log4j-api:2.17.1", _MAVEN_CENTRAL),
        ("org.apache.logging.log4j:log4j-core:2.17.1", _MAVEN_CENTRAL),
    ]
