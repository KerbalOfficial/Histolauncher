from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from core.http_client import HttpClient, HttpClientError
from core.logger import colorize_log
from core.modloaders.cache import TTLCache, register_cache

__all__ = [
    "MODLOADER_HTTP_TIMEOUT_S",
    "_http_get_json",
    "fetch_maven_metadata_versions",
]


MODLOADER_HTTP_TIMEOUT_S: float = 10.0


def _client() -> HttpClient:
    return HttpClient(timeout=MODLOADER_HTTP_TIMEOUT_S)


def _http_get_json(url: str, timeout: float = MODLOADER_HTTP_TIMEOUT_S) -> Any:
    client = HttpClient(timeout=timeout)
    try:
        return client.get_json(url)
    except HttpClientError as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc


_maven_metadata_cache: TTLCache[list[str]] = register_cache(TTLCache())


def fetch_maven_metadata_versions(url: str, cache_key: str, label: str) -> list[str] | None:
    cached = _maven_metadata_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        xml_data = _client().get_bytes(url)
    except HttpClientError as exc:
        print(colorize_log(f"[modloaders] Failed to fetch {label} versions: {exc}"))
        return None

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as exc:
        print(colorize_log(f"[modloaders] Failed to parse {label} maven-metadata.xml: {exc}"))
        return None

    versions = [el.text for el in root.findall(".//version") if el.text]
    if not versions:
        print(colorize_log(f"[modloaders] No {label} versions found in metadata"))
        return None

    _maven_metadata_cache.set(cache_key, versions)
    print(colorize_log(f"[modloaders] Fetched {len(versions)} {label} versions"))
    return versions
