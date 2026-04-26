from __future__ import annotations

import json
import os
import tempfile
import urllib.parse
import zipfile
from typing import Any

from core.http_client import HttpClient, HttpClientError
from core.logger import colorize_log
from core.modloaders._endpoints import FABRIC_META_API
from core.modloaders._http import MODLOADER_HTTP_TIMEOUT_S, _http_get_json
from core.modloaders._versions import fabric_version_meets_minimum
from core.modloaders.cache import TTLCache, register_cache

__all__ = [
    "fetch_fabric_game_versions",
    "fetch_fabric_loader_dependencies",
    "fetch_fabric_loader_profile_libraries",
    "fetch_fabric_loaders",
    "get_fabric_installer_url",
    "get_fabric_loader_libraries",
    "get_fabric_loaders_for_version",
    "supports_fabric_mc_version",
]


_loaders_cache: TTLCache[list[dict[str, Any]]] = register_cache(TTLCache())
_game_versions_cache: TTLCache[list[dict[str, Any]]] = register_cache(TTLCache())


def fetch_fabric_loaders() -> list[dict[str, Any]] | None:
    cached = _loaders_cache.get("loaders")
    if cached is not None:
        return cached
    try:
        data = _http_get_json(f"{FABRIC_META_API}/versions/loader")
    except RuntimeError as exc:
        print(colorize_log(f"[modloaders] Failed to fetch Fabric loaders: {exc}"))
        return None
    if not isinstance(data, list):
        print(colorize_log("[modloaders] Unexpected Fabric response format"))
        return None
    _loaders_cache.set("loaders", data)
    print(colorize_log(f"[modloaders] Fetched {len(data)} Fabric loader versions"))
    return data


def fetch_fabric_game_versions() -> list[dict[str, Any]] | None:
    cached = _game_versions_cache.get("game")
    if cached is not None:
        return cached
    try:
        data = _http_get_json(f"{FABRIC_META_API}/versions/game")
    except RuntimeError as exc:
        print(colorize_log(f"[modloaders] Failed to fetch Fabric game versions: {exc}"))
        return None
    if not isinstance(data, list):
        print(colorize_log("[modloaders] Unexpected Fabric game versions response format"))
        return None
    _game_versions_cache.set("game", data)
    print(colorize_log(f"[modloaders] Fetched {len(data)} Fabric game versions"))
    return data


def supports_fabric_mc_version(mc_version: str) -> bool:
    value = str(mc_version or "").strip()
    if not value or not fabric_version_meets_minimum(value):
        return False
    game_versions = fetch_fabric_game_versions()
    if not game_versions:
        return False
    return any(
        isinstance(entry, dict) and (entry.get("version") == value)
        for entry in game_versions
    )


def get_fabric_loaders_for_version(
    mc_version: str, stable_only: bool = False
) -> list[dict[str, Any]]:
    if not supports_fabric_mc_version(mc_version):
        return []
    loaders = fetch_fabric_loaders()
    if not loaders:
        return []
    if stable_only:
        return [loader for loader in loaders if loader.get("stable", False)]
    return loaders


# ---------------------------------------------------------------------------
# Library / installer resolution
# ---------------------------------------------------------------------------


def get_fabric_installer_url(mc_version: str, loader_version: str) -> str | None:
    del mc_version, loader_version
    fallback = "https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.0.1/fabric-installer-1.0.1.jar"
    try:
        installers = _http_get_json(f"{FABRIC_META_API}/versions/installer")
    except RuntimeError:
        return fallback
    if not isinstance(installers, list) or not installers:
        return fallback
    latest = installers[0].get("version") if isinstance(installers[0], dict) else None
    if not latest:
        return fallback
    return (
        "https://maven.fabricmc.net/net/fabricmc/fabric-installer/"
        f"{latest}/fabric-installer-{latest}.jar"
    )


def fetch_fabric_loader_profile_libraries(
    loader_version: str, mc_version: str
) -> list[tuple[str, str]] | None:
    try:
        mc_enc = urllib.parse.quote(mc_version, safe="")
        loader_enc = urllib.parse.quote(loader_version, safe="")
        profile = _http_get_json(
            f"{FABRIC_META_API}/versions/loader/{mc_enc}/{loader_enc}/profile/json"
        )
    except RuntimeError as exc:
        print(
            colorize_log(
                "[modloaders] Failed to fetch Fabric profile libraries for "
                f"{mc_version}/{loader_version}: {exc}"
            )
        )
        return None

    deps: list[tuple[str, str]] = []
    for lib_entry in (profile or {}).get("libraries", []):
        lib_name = str(lib_entry.get("name") or "").strip()
        if not lib_name:
            continue
        lib_url = str(lib_entry.get("url") or "https://maven.fabricmc.net").strip()
        deps.append((lib_name, lib_url))

    if deps:
        print(
            colorize_log(
                f"[modloaders] Extracted {len(deps)} official Fabric libraries "
                f"from profile {mc_version}/{loader_version}"
            )
        )
        return deps

    print(
        colorize_log(f"[modloaders] Fabric profile {mc_version}/{loader_version} had no libraries")
    )
    return None


def fetch_fabric_loader_dependencies(
    loader_version: str, mc_version: str
) -> list[tuple[str, str]] | None:
    del mc_version  # signature parity only
    loader_enc = urllib.parse.quote(loader_version, safe="")
    lib_url = (
        "https://maven.fabricmc.net/net/fabricmc/fabric-loader/"
        f"{loader_enc}/fabric-loader-{loader_enc}.jar"
    )

    print(
        colorize_log(
            f"[modloaders] Downloading fabric-loader {loader_version} "
            "to extract dependencies..."
        )
    )

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".jar", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            HttpClient(timeout=MODLOADER_HTTP_TIMEOUT_S).stream_to(lib_url, tmp_path)
        except HttpClientError as exc:
            print(colorize_log(f"[modloaders] Failed to download fabric-loader JAR: {exc}"))
            return None

        try:
            with zipfile.ZipFile(tmp_path, "r") as jar:
                installer_json = jar.read("fabric-installer.json").decode("utf-8")
                installer_data = json.loads(installer_json)
        except (KeyError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            print(colorize_log(f"[modloaders] fabric-installer.json missing or invalid: {exc}"))
            return None

        deps: list[tuple[str, str]] = []
        deps.append(
            (f"net.fabricmc:fabric-loader:{loader_version}", "https://maven.fabricmc.net")
        )
        print(
            colorize_log(
                f"[modloaders]   + net.fabricmc:fabric-loader:{loader_version} "
                "from https://maven.fabricmc.net"
            )
        )

        libraries = (installer_data or {}).get("libraries", {}) if isinstance(installer_data, dict) else {}
        for lib_entry in libraries.get("common", []) if isinstance(libraries, dict) else []:
            lib_name = str(lib_entry.get("name") or "").strip()
            if not lib_name:
                continue
            lib_url_override = str(
                lib_entry.get("url") or "https://maven.fabricmc.net"
            ).strip()
            deps.append((lib_name, lib_url_override))
            print(colorize_log(f"[modloaders]   + {lib_name} from {lib_url_override}"))

        if len(deps) > 1:
            print(
                colorize_log(
                    f"[modloaders] Extracted {len(deps)} official dependencies "
                    f"from fabric-loader {loader_version}"
                )
            )
            return deps
        print(colorize_log("[modloaders] No common libraries found in fabric-installer.json"))
        return None
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def get_fabric_loader_libraries(
    loader_version: str, mc_version: str
) -> list[tuple[str, str]]:
    print(
        colorize_log(f"[modloaders] Fetching official Fabric libraries for {loader_version}...")
    )
    profile_deps = fetch_fabric_loader_profile_libraries(loader_version, mc_version)
    if profile_deps:
        return profile_deps

    extracted = fetch_fabric_loader_dependencies(loader_version, mc_version)
    if extracted:
        return extracted

    print(colorize_log(f"[modloaders] Using fallback dependencies for {loader_version}"))
    return [
        (f"net.fabricmc:fabric-loader:{loader_version}", "https://maven.fabricmc.net"),
        ("net.fabricmc:sponge-mixin:0.17.0+mixin.0.8.7", "https://maven.fabricmc.net"),
        ("org.ow2.asm:asm:9.9", "https://maven.fabricmc.net"),
        ("org.ow2.asm:asm-analysis:9.9", "https://maven.fabricmc.net"),
        ("org.ow2.asm:asm-commons:9.9", "https://maven.fabricmc.net"),
        ("org.ow2.asm:asm-tree:9.9", "https://maven.fabricmc.net"),
        ("org.ow2.asm:asm-util:9.9", "https://maven.fabricmc.net"),
    ]
