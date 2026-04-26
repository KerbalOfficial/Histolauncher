from __future__ import annotations

import urllib.parse
from typing import Any, Final

from core.logger import colorize_log
from core.modloaders._endpoints import RISUGAMI_MODLOADER_MANIFEST_URL
from core.modloaders._http import _http_get_json
from core.modloaders._versions import loader_version_sort_key
from core.modloaders.cache import TTLCache, register_cache

__all__ = ["MODLOADER_MANIFEST_CACHE_KEY", "get_modloader_versions_for_mc"]

MODLOADER_MANIFEST_CACHE_KEY: Final[str] = "modloader_manifest"

_manifest_cache: TTLCache[list[dict[str, Any]]] = register_cache(TTLCache())

_stale_manifest: list[dict[str, Any]] | None = None


def _normalize_manifest_entries(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    versions = data.get("versions", [])
    if not isinstance(versions, list):
        return []
    source = str(data.get("source") or "").strip()

    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []

    for raw in versions:
        if not isinstance(raw, dict):
            continue

        mc_version = str(
            raw.get("mc_version") or raw.get("minecraft_version") or ""
        ).strip()
        loader_version = str(raw.get("loader_version") or "").strip()
        if not mc_version or not loader_version:
            continue

        key = (mc_version, loader_version)
        if key in seen:
            continue
        seen.add(key)

        download_url = str(raw.get("download_url") or "").strip()
        download_kind = str(raw.get("download_kind") or "").strip().lower()
        if not download_kind and download_url:
            netloc = urllib.parse.urlparse(download_url).netloc.lower()
            download_kind = "mediafire" if "mediafire.com" in netloc else "direct"

        out.append(
            {
                "mc_version": mc_version,
                "loader_version": loader_version,
                "display_name": str(raw.get("display_name") or loader_version).strip(),
                "file_name": str(raw.get("file_name") or "").strip(),
                "download_url": download_url,
                "sha256": str(raw.get("sha256") or "").strip().lower(),
                "archive_type": str(raw.get("archive_type") or "zip").strip().lower(),
                "download_kind": download_kind,
                "source_page": str(
                    raw.get("source_page") or source or download_url
                ).strip(),
            }
        )
    return out


def _load_manifest() -> list[dict[str, Any]]:
    global _stale_manifest

    cached = _manifest_cache.get(MODLOADER_MANIFEST_CACHE_KEY)
    if cached is not None:
        return cached

    try:
        data = _http_get_json(RISUGAMI_MODLOADER_MANIFEST_URL)
    except RuntimeError as exc:
        print(colorize_log(f"[modloaders] Failed to fetch Risugami ModLoader manifest: {exc}"))
        return _stale_manifest or []

    entries = _normalize_manifest_entries(data)
    if not entries:
        print(colorize_log("[modloaders] Risugami ModLoader manifest was empty"))
        return _stale_manifest or []

    _manifest_cache.set(MODLOADER_MANIFEST_CACHE_KEY, entries)
    _stale_manifest = entries
    print(
        colorize_log(
            f"[modloaders] Fetched {len(entries)} Risugami ModLoader manifest entries"
        )
    )
    return entries


def get_modloader_versions_for_mc(mc_version: str) -> list[dict[str, Any]]:
    value = str(mc_version or "").strip()
    if not value:
        return []

    matching: list[dict[str, Any]] = []
    for entry in _load_manifest():
        if str(entry.get("mc_version") or "").strip() != value:
            continue
        loader_version = str(entry.get("loader_version") or "").strip()
        if not loader_version:
            continue
        matching.append(
            {
                "mc_version": value,
                "modloader_version": loader_version,
                "display_name": str(entry.get("display_name") or loader_version).strip(),
                "file_name": str(entry.get("file_name") or "").strip(),
                "download_url": str(entry.get("download_url") or "").strip(),
                "download_kind": str(entry.get("download_kind") or "").strip().lower(),
                "sha256": str(entry.get("sha256") or "").strip().lower(),
                "archive_type": str(entry.get("archive_type") or "zip").strip().lower(),
                "source_page": str(entry.get("source_page") or "").strip(),
            }
        )

    matching.sort(
        key=lambda item: loader_version_sort_key(str(item.get("modloader_version", ""))),
        reverse=True,
    )
    return matching
