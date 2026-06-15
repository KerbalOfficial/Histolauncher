from __future__ import annotations

import threading
from typing import Any, Final

from core.logger import safe_print
from core.modloaders._endpoints import (
    LITELOADER_MAVEN_BASE,
    LITELOADER_VERSIONS_MANIFEST_URL,
)
from core.modloaders._http import _http_get_json
from core.modloaders.cache import TTLCache, register_cache

__all__ = [
    "LITELOADER_DEFAULT_TWEAK_CLASS",
    "get_liteloader_entry",
    "get_liteloader_versions_for_mc",
]

LITELOADER_DEFAULT_TWEAK_CLASS: Final[str] = (
    "com.mumfrey.liteloader.launch.LiteLoaderTweaker"
)

_LITELOADER_ARTEFACT_KEY: Final[str] = "com.mumfrey:liteloader"

_manifest_cache: TTLCache[dict[str, Any]] = register_cache(TTLCache())

_stale_manifest: dict[str, Any] | None = None
_stale_manifest_lock = threading.Lock()


def _load_manifest() -> dict[str, Any]:
    global _stale_manifest

    cached = _manifest_cache.get("manifest")
    if cached is not None:
        return cached

    try:
        data = _http_get_json(LITELOADER_VERSIONS_MANIFEST_URL)
    except RuntimeError as exc:
        safe_print(f"[modloaders] Failed to fetch LiteLoader versions manifest: {exc}")
        with _stale_manifest_lock:
            return dict(_stale_manifest or {})

    if not isinstance(data, dict) or not isinstance(data.get("versions"), dict):
        safe_print("[modloaders] Unexpected LiteLoader versions manifest format")
        with _stale_manifest_lock:
            return dict(_stale_manifest or {})

    _manifest_cache.set("manifest", data)
    with _stale_manifest_lock:
        _stale_manifest = data
    safe_print(
        f"[modloaders] Fetched LiteLoader manifest with {len(data['versions'])} game versions"
    )
    return data


def _normalize_entry(mc_version: str, raw: dict[str, Any]) -> dict[str, Any] | None:
    version = str(raw.get("version") or "").strip()
    file_name = str(raw.get("file") or "").strip()
    if not version or not file_name:
        return None

    stream = str(raw.get("stream") or "").strip().upper()
    snapshot = stream == "SNAPSHOT"
    repo_dir = f"{mc_version}-SNAPSHOT" if snapshot else mc_version
    download_url = (
        f"{LITELOADER_MAVEN_BASE}com/mumfrey/liteloader/{repo_dir}/{file_name}"
    )

    libraries: list[str] = []
    for lib in raw.get("libraries") or []:
        name = str((lib or {}).get("name") or "").strip() if isinstance(lib, dict) else ""
        if name and not name.startswith("com.mumfrey:liteloader"):
            libraries.append(name)

    return {
        "mc_version": mc_version,
        "version": version,
        "stream": stream or "RELEASE",
        "stable": not snapshot,
        "file_name": file_name,
        "download_url": download_url,
        "md5": str(raw.get("md5") or "").strip().lower(),
        "tweak_class": str(raw.get("tweakClass") or "").strip()
        or LITELOADER_DEFAULT_TWEAK_CLASS,
        "libraries": libraries,
    }


def get_liteloader_versions_for_mc(mc_version: str) -> list[dict[str, Any]]:
    value = str(mc_version or "").strip()
    if not value:
        return []

    manifest = _load_manifest()
    game_entry = (manifest.get("versions") or {}).get(value)
    if not isinstance(game_entry, dict):
        return []

    result: list[dict[str, Any]] = []
    for repo_key in ("artefacts", "snapshots"):
        artefacts = game_entry.get(repo_key)
        if not isinstance(artefacts, dict):
            continue
        latest = (artefacts.get(_LITELOADER_ARTEFACT_KEY) or {}).get("latest")
        if not isinstance(latest, dict):
            continue
        entry = _normalize_entry(value, latest)
        if entry is not None:
            result.append(entry)

    return result


def get_liteloader_entry(mc_version: str, loader_version: str) -> dict[str, Any] | None:
    wanted = str(loader_version or "").strip()
    if not wanted:
        return None
    for entry in get_liteloader_versions_for_mc(mc_version):
        if str(entry.get("version") or "").strip() == wanted:
            return entry
    return None
