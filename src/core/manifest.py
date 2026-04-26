from __future__ import annotations

import re
from typing import Any, Final

from core.constants import HTTP_DEFAULT_TIMEOUT_S
from core.http_client import HttpClient, HttpClientError

__all__ = [
    "DEFAULT_MANIFEST_URLS",
    "OMNIARCHIVE_MANIFEST_URL",
    "fetch_manifest",
    "fetch_version_json",
    "get_version_entry",
]


DEFAULT_MANIFEST_URLS: Final[list[dict[str, str]]] = [
    {
        "source": "mojang",
        "url": "https://piston-meta.mojang.com/mc/game/version_manifest.json",
    },
    {
        "source": "mojang",
        "url": "https://launchermeta.mojang.com/mc/game/version_manifest.json",
    },
]

OMNIARCHIVE_MANIFEST_URL: Final[str] = "https://meta.omniarchive.uk/v1/manifest.json"

_OMNIARCHIVE_ID_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (r"^c0", r"^in-", r"^inf-", r"^a1", r"^b1")
)


def _client() -> HttpClient:
    return HttpClient(timeout=HTTP_DEFAULT_TIMEOUT_S)


def _is_omniarchive_allowed_version(entry: dict[str, Any]) -> bool:
    if not isinstance(entry, dict):
        return False

    vid = str(entry.get("id") or "").strip()
    if not vid or vid.lower().endswith("-launcher"):
        return False

    vtype = str(entry.get("type") or "").strip().lower()
    if vtype == "special":
        return True

    return any(p.match(vid) for p in _OMNIARCHIVE_ID_PATTERNS)


def _merge_versions_with_source(
    mojang_versions: list[dict[str, Any]],
    omniarchive_versions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for raw in mojang_versions:
        if not isinstance(raw, dict):
            continue
        vid = str(raw.get("id") or "").strip()
        if not vid or vid in seen_ids:
            continue
        item = dict(raw)
        item["source"] = "mojang"
        merged.append(item)
        seen_ids.add(vid)

    for raw in omniarchive_versions:
        if not isinstance(raw, dict):
            continue
        if not _is_omniarchive_allowed_version(raw):
            continue
        vid = str(raw.get("id") or "").strip()
        if not vid or vid in seen_ids:
            continue
        item = dict(raw)
        item["source"] = "omniarchive"
        merged.append(item)
        seen_ids.add(vid)

    return merged


def _fetch_first_available_manifest(
    client: HttpClient, urls: list[dict[str, str]]
) -> dict[str, Any] | None:
    for entry in urls:
        raw_url = entry.get("url")
        if not raw_url:
            continue
        try:
            data = client.get_json(raw_url)
        except HttpClientError:
            continue
        if isinstance(data, dict) and isinstance(data.get("versions"), list):
            return data
    return None


def fetch_manifest(
    timeout: float = HTTP_DEFAULT_TIMEOUT_S,
    include_third_party: bool = False,
) -> dict[str, Any]:
    client = HttpClient(timeout=timeout)

    mojang_data = _fetch_first_available_manifest(client, DEFAULT_MANIFEST_URLS)

    omniarchive_data: dict[str, Any] | None = None
    if include_third_party:
        try:
            data = client.get_json(OMNIARCHIVE_MANIFEST_URL)
        except HttpClientError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("versions"), list):
            omniarchive_data = data

    if mojang_data is None and omniarchive_data is None:
        return {"data": None, "source": None}

    if not include_third_party and isinstance(mojang_data, dict):
        versions = [
            {**raw, "source": "mojang"}
            for raw in mojang_data.get("versions", [])
            if isinstance(raw, dict)
        ]
        out = dict(mojang_data)
        out["versions"] = versions
        return {"data": out, "source": "mojang"}

    if mojang_data is None and isinstance(omniarchive_data, dict):
        out = {
            "latest": {},
            "versions": _merge_versions_with_source([], omniarchive_data.get("versions", [])),
        }
        return {"data": out, "source": "omniarchive"}

    assert mojang_data is not None  # narrowed by the branches above
    merged_versions = _merge_versions_with_source(
        mojang_data.get("versions", []),
        (omniarchive_data or {}).get("versions", []),
    )
    out = dict(mojang_data)
    out["versions"] = merged_versions
    return {"data": out, "source": "mixed" if omniarchive_data else "mojang"}


def get_version_entry(
    version_id: str,
    timeout: float = HTTP_DEFAULT_TIMEOUT_S,
    include_third_party: bool = False,
) -> dict[str, Any]:
    mf = fetch_manifest(timeout=timeout, include_third_party=include_third_party)
    data = mf.get("data")
    if not isinstance(data, dict):
        raise KeyError("manifest not available")
    for v in data.get("versions") or []:
        if isinstance(v, dict) and v.get("id") == version_id:
            return v
    raise KeyError(f"version not found: {version_id}")


def fetch_version_json(version_url: str, timeout: float = 10.0) -> dict[str, Any]:
    client = HttpClient(timeout=timeout)
    try:
        data = client.get_json(version_url)
    except HttpClientError as exc:
        raise RuntimeError(
            f"failed to fetch version json from url: {version_url}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError("version json is not an object")
    return data
