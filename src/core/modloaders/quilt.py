from __future__ import annotations

import urllib.parse
from typing import Any

from core.logger import colorize_log
from core.modloaders._endpoints import QUILT_META_API
from core.modloaders._http import _http_get_json
from core.modloaders._versions import (
    loader_version_is_stable,
    loader_version_sort_key,
)
from core.modloaders.cache import TTLCache, register_cache

__all__ = [
    "fetch_quilt_game_versions",
    "fetch_quilt_loader_profile_libraries",
    "fetch_quilt_loaders",
    "get_quilt_installer_url",
    "get_quilt_loader_libraries",
    "get_quilt_loaders_for_version",
]


_loaders_cache: TTLCache[list[dict[str, Any]]] = register_cache(TTLCache())


def fetch_quilt_loaders(mc_version: str) -> list[dict[str, Any]] | None:
    cache_key = f"loaders:{mc_version}"
    cached = _loaders_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        encoded_mc = urllib.parse.quote(str(mc_version or "").strip(), safe="")
        data = _http_get_json(f"{QUILT_META_API}/versions/loader/{encoded_mc}")
    except RuntimeError as exc:
        print(
            colorize_log(f"[modloaders] Failed to fetch Quilt loaders for {mc_version}: {exc}")
        )
        return None
    if not isinstance(data, list):
        print(colorize_log("[modloaders] Unexpected Quilt response format"))
        return None
    _loaders_cache.set(cache_key, data)
    print(
        colorize_log(f"[modloaders] Fetched {len(data)} Quilt loader versions for {mc_version}")
    )
    return data


def fetch_quilt_game_versions() -> list[dict[str, Any]] | None:
    try:
        data = _http_get_json(f"{QUILT_META_API}/versions/game")
    except RuntimeError as exc:
        print(colorize_log(f"[modloaders] Failed to fetch Quilt game versions: {exc}"))
        return None
    if not isinstance(data, list):
        print(colorize_log("[modloaders] Unexpected Quilt game versions response format"))
        return None
    print(colorize_log(f"[modloaders] Fetched {len(data)} Quilt game versions"))
    return data


def get_quilt_loaders_for_version(
    mc_version: str, stable_only: bool = False
) -> list[dict[str, Any]]:
    loaders = fetch_quilt_loaders(mc_version)
    if not loaders:
        return []

    result: list[dict[str, Any]] = []
    for entry in loaders:
        loader_data = entry.get("loader") if isinstance(entry, dict) else None
        version = (loader_data or {}).get("version") if isinstance(loader_data, dict) else None
        if not version:
            continue
        stable = loader_version_is_stable(version)
        if stable_only and not stable:
            continue
        result.append(
            {
                "version": version,
                "stable": stable,
                "loader": loader_data or {},
                "launcherMeta": entry.get("launcherMeta") if isinstance(entry, dict) else {},
            }
        )

    result.sort(key=lambda item: loader_version_sort_key(item.get("version", "")), reverse=True)
    return result


def get_quilt_installer_url(mc_version: str, loader_version: str) -> str | None:
    del mc_version, loader_version
    fallback = (
        "https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/"
        "0.12.1/quilt-installer-0.12.1.jar"
    )
    try:
        installers = _http_get_json(f"{QUILT_META_API}/versions/installer")
    except RuntimeError:
        return fallback
    if not isinstance(installers, list) or not installers:
        return fallback
    latest = installers[0].get("url") if isinstance(installers[0], dict) else None
    return latest or fallback


def fetch_quilt_loader_profile_libraries(
    loader_version: str, mc_version: str
) -> list[tuple[str, str]] | None:
    try:
        mc_enc = urllib.parse.quote(mc_version, safe="")
        loader_enc = urllib.parse.quote(loader_version, safe="")
        profile = _http_get_json(
            f"{QUILT_META_API}/versions/loader/{mc_enc}/{loader_enc}/profile/json"
        )
    except RuntimeError as exc:
        print(
            colorize_log(
                "[modloaders] Failed to fetch Quilt profile libraries for "
                f"{mc_version}/{loader_version}: {exc}"
            )
        )
        return None

    deps: list[tuple[str, str]] = []
    for lib_entry in (profile or {}).get("libraries", []):
        lib_name = str(lib_entry.get("name") or "").strip()
        if not lib_name:
            continue
        lib_url = str(
            lib_entry.get("url") or "https://maven.quiltmc.org/repository/release/"
        ).strip()
        deps.append((lib_name, lib_url))

    if deps:
        print(
            colorize_log(
                f"[modloaders] Extracted {len(deps)} official Quilt libraries "
                f"from profile {mc_version}/{loader_version}"
            )
        )
        return deps

    print(
        colorize_log(f"[modloaders] Quilt profile {mc_version}/{loader_version} had no libraries")
    )
    return None


def get_quilt_loader_libraries(
    loader_version: str, mc_version: str
) -> list[tuple[str, str]]:
    print(
        colorize_log(f"[modloaders] Fetching official Quilt libraries for {loader_version}...")
    )
    profile_deps = fetch_quilt_loader_profile_libraries(loader_version, mc_version)
    if profile_deps:
        return profile_deps

    print(colorize_log(f"[modloaders] Using fallback dependencies for Quilt {loader_version}"))
    return [
        (
            f"org.quiltmc:quilt-loader:{loader_version}",
            "https://maven.quiltmc.org/repository/release/",
        ),
        (
            "org.quiltmc:quilt-json5:1.0.4+final",
            "https://maven.quiltmc.org/repository/release/",
        ),
        (f"net.fabricmc:intermediary:{mc_version}", "https://maven.fabricmc.net"),
        ("net.fabricmc:sponge-mixin:0.17.0+mixin.0.8.7", "https://maven.fabricmc.net"),
        ("org.ow2.asm:asm:9.9", "https://maven.fabricmc.net"),
        ("org.ow2.asm:asm-analysis:9.9", "https://maven.fabricmc.net"),
        ("org.ow2.asm:asm-commons:9.9", "https://maven.fabricmc.net"),
        ("org.ow2.asm:asm-tree:9.9", "https://maven.fabricmc.net"),
        ("org.ow2.asm:asm-util:9.9", "https://maven.fabricmc.net"),
    ]
