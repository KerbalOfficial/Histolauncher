from __future__ import annotations

import urllib.parse
from typing import Any

from core.logger import colorize_log
from core.modloaders._endpoints import BABRIC_META_API
from core.modloaders._http import _http_get_json
from core.modloaders._versions import (
    current_library_os_name,
    loader_version_is_stable,
    loader_version_sort_key,
)
from core.modloaders.cache import TTLCache, register_cache

__all__ = [
    "fetch_babric_game_versions",
    "fetch_babric_loader_profile_libraries",
    "fetch_babric_loaders",
    "get_babric_loader_libraries",
    "get_babric_loaders_for_version",
    "supports_babric_mc_version",
]


_game_cache: TTLCache[list[dict[str, Any]]] = register_cache(TTLCache())
_loaders_cache: TTLCache[list[dict[str, Any]]] = register_cache(TTLCache())


def fetch_babric_game_versions() -> list[dict[str, Any]] | None:
    cached = _game_cache.get("game")
    if cached is not None:
        return cached
    try:
        data = _http_get_json(f"{BABRIC_META_API}/versions/game")
    except RuntimeError as exc:
        print(colorize_log(f"[modloaders] Failed to fetch Babric game versions: {exc}"))
        return None
    if not isinstance(data, list):
        print(colorize_log("[modloaders] Unexpected Babric game versions response format"))
        return None
    _game_cache.set("game", data)
    print(colorize_log(f"[modloaders] Fetched {len(data)} Babric game versions"))
    return data


def supports_babric_mc_version(mc_version: str) -> bool:
    value = str(mc_version or "").strip()
    if not value:
        return False
    game_versions = fetch_babric_game_versions()
    if not game_versions:
        return False
    return any(
        isinstance(entry, dict) and entry.get("version") == value for entry in game_versions
    )


def fetch_babric_loaders(mc_version: str) -> list[dict[str, Any]] | None:
    cache_key = f"loaders:{mc_version}"
    cached = _loaders_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        encoded_mc = urllib.parse.quote(str(mc_version or "").strip(), safe="")
        data = _http_get_json(f"{BABRIC_META_API}/versions/loader/{encoded_mc}")
    except RuntimeError as exc:
        print(
            colorize_log(f"[modloaders] Failed to fetch Babric loaders for {mc_version}: {exc}")
        )
        return None
    if not isinstance(data, list):
        print(colorize_log("[modloaders] Unexpected Babric response format"))
        return None
    _loaders_cache.set(cache_key, data)
    print(
        colorize_log(f"[modloaders] Fetched {len(data)} Babric loader versions for {mc_version}")
    )
    return data


def get_babric_loaders_for_version(
    mc_version: str, stable_only: bool = False
) -> list[dict[str, Any]]:
    if not supports_babric_mc_version(mc_version):
        return []

    loaders = fetch_babric_loaders(mc_version)
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


def fetch_babric_loader_profile_libraries(
    loader_version: str, mc_version: str
) -> list[tuple[str, str]] | None:
    try:
        mc_enc = urllib.parse.quote(mc_version, safe="")
        loader_enc = urllib.parse.quote(loader_version, safe="")
        profile = _http_get_json(
            f"{BABRIC_META_API}/versions/loader/{mc_enc}/{loader_enc}/profile/json"
        )
    except RuntimeError as exc:
        print(
            colorize_log(
                "[modloaders] Failed to fetch Babric profile libraries for "
                f"{mc_version}/{loader_version}: {exc}"
            )
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
        lib_url = str(lib_entry.get("url") or "https://maven.fabricmc.net/").strip()

        if classifiers and not artifact_url:
            natives = lib_entry.get("natives") if isinstance(lib_entry.get("natives"), dict) else {}
            classifier = str((natives or {}).get(current_os) or "").strip()
            if not classifier:
                continue
            lib_name = f"{lib_name}:{classifier}"

        if lib_name:
            deps.append((lib_name, lib_url))

    if deps:
        print(
            colorize_log(
                f"[modloaders] Extracted {len(deps)} official Babric libraries "
                f"from profile {mc_version}/{loader_version}"
            )
        )
        return deps

    print(
        colorize_log(f"[modloaders] Babric profile {mc_version}/{loader_version} had no libraries")
    )
    return None


def get_babric_loader_libraries(
    loader_version: str, mc_version: str
) -> list[tuple[str, str]]:
    print(
        colorize_log(f"[modloaders] Fetching official Babric libraries for {loader_version}...")
    )
    profile_deps = fetch_babric_loader_profile_libraries(loader_version, mc_version)
    if profile_deps:
        return profile_deps

    print(
        colorize_log(f"[modloaders] Using fallback dependencies for Babric {loader_version}")
    )
    deps: list[tuple[str, str]] = [
        (f"net.fabricmc:fabric-loader:{loader_version}", "https://maven.fabricmc.net/"),
        (
            f"babric:intermediary-upstream:{mc_version}",
            "https://maven.glass-launcher.net/babric/",
        ),
        ("babric:log4j-config:1.0.0", "https://maven.glass-launcher.net/babric/"),
        ("net.fabricmc:sponge-mixin:0.17.0+mixin.0.8.7", "https://maven.fabricmc.net/"),
        ("org.ow2.asm:asm:9.9", "https://maven.fabricmc.net/"),
        ("org.ow2.asm:asm-analysis:9.9", "https://maven.fabricmc.net/"),
        ("org.ow2.asm:asm-commons:9.9", "https://maven.fabricmc.net/"),
        ("org.ow2.asm:asm-tree:9.9", "https://maven.fabricmc.net/"),
        ("org.ow2.asm:asm-util:9.9", "https://maven.fabricmc.net/"),
    ]

    native_classifier = {
        "windows": "natives-windows",
        "linux": "natives-linux",
        "osx": "natives-osx",
    }.get(current_library_os_name(), "")
    if native_classifier:
        deps.append(
            (
                f"org.lwjgl.lwjgl:lwjgl-platform:2.9.4-babric.1:{native_classifier}",
                "https://maven.glass-launcher.net/babric/",
            )
        )
    return deps
