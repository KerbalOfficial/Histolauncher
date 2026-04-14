# core/manifest.py

import json
import re
import urllib.request

from typing         import Dict, Any, List
from core.settings  import _apply_url_proxy

DEFAULT_MANIFEST_URLS: List[Dict[str, str]] = [
    {
        "source": "mojang",
        "url": "https://piston-meta.mojang.com/mc/game/version_manifest.json",
    },
    {
        "source": "mojang",
        "url": "https://launchermeta.mojang.com/mc/game/version_manifest.json",
    },
]

OMNIARCHIVE_MANIFEST_URL = "https://meta.omniarchive.uk/v1/manifest.json"


def _is_omniarchive_allowed_version(entry: Dict[str, Any]) -> bool:
    if not isinstance(entry, dict):
        return False

    vid = str(entry.get("id") or "").strip()
    if not vid:
        return False

    if vid.lower().endswith("-launcher"):
        return False

    vtype = str(entry.get("type") or "").strip().lower()
    if vtype == "special":
        return True

    patterns = (
        r"^c0",
        r"^in-",
        r"^inf-",
        r"^a1",
        r"^b1",
    )
    return any(re.match(p, vid, flags=re.IGNORECASE) for p in patterns)


def _merge_versions_with_source(
    mojang_versions: List[Dict[str, Any]],
    omniarchive_versions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen_ids = set()

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


def _http_get_json(url: str, timeout: int) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    try:
        return json.loads(data.decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"failed to parse json from {url}: {e}")


def _http_get_json_with_proxy_fallback(url: str, timeout: int) -> Dict[str, Any]:
    candidates: List[str] = []
    proxied_url = _apply_url_proxy(url)
    if proxied_url:
        candidates.append(proxied_url)
    if url not in candidates:
        candidates.append(url)

    last_error = None
    for candidate in candidates:
        try:
            return _http_get_json(candidate, timeout=timeout)
        except Exception as e:
            last_error = e
            continue

    if last_error:
        raise last_error
    raise RuntimeError(f"failed to fetch json from {url}")


def fetch_manifest(timeout: int = 6, include_third_party: bool = False) -> Dict[str, Any]:
    urls: List[Dict[str, str]] = []
    urls.extend(DEFAULT_MANIFEST_URLS)

    mojang_data = None

    for entry in urls:
        raw_url = entry.get("url")
        if not raw_url:
            continue

        try:
            data = _http_get_json_with_proxy_fallback(raw_url, timeout=timeout)
            if isinstance(data, dict) and "versions" in data and isinstance(data["versions"], list):
                mojang_data = data
                break
        except Exception:
            continue

    omniarchive_data = None
    if include_third_party:
        try:
            data = _http_get_json_with_proxy_fallback(OMNIARCHIVE_MANIFEST_URL, timeout=timeout)
            if isinstance(data, dict) and isinstance(data.get("versions"), list):
                omniarchive_data = data
        except Exception:
            omniarchive_data = None

    if not isinstance(mojang_data, dict) and not isinstance(omniarchive_data, dict):
        return {"data": None, "source": None}

    if not include_third_party:
        versions = []
        for raw in mojang_data.get("versions", []):
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            item["source"] = "mojang"
            versions.append(item)

        out = dict(mojang_data)
        out["versions"] = versions
        return {"data": out, "source": "mojang"}

    if not isinstance(mojang_data, dict) and isinstance(omniarchive_data, dict):
        out = {
            "latest": {},
            "versions": _merge_versions_with_source([], omniarchive_data.get("versions", [])),
        }
        return {"data": out, "source": "omniarchive"}

    merged_versions = _merge_versions_with_source(
        mojang_data.get("versions", []),
        (omniarchive_data or {}).get("versions", []),
    )

    out = dict(mojang_data)
    out["versions"] = merged_versions
    return {"data": out, "source": "mixed" if omniarchive_data else "mojang"}


def get_version_entry(version_id: str, timeout: int = 6, include_third_party: bool = False) -> Dict[str, Any]:
    mf = fetch_manifest(timeout=timeout, include_third_party=include_third_party)
    data = mf.get("data")
    if not isinstance(data, dict):
        raise KeyError("manifest not available")

    versions = data.get("versions") or []
    for v in versions:
        if v.get("id") == version_id:
            return v
    raise KeyError(f"version not found: {version_id}")


def fetch_version_json(version_url: str, timeout: int = 10) -> Dict[str, Any]:
    proxied = _apply_url_proxy(version_url)
    try:
        data = _http_get_json(proxied, timeout=timeout)
        if isinstance(data, dict):
            return data
        raise ValueError("version json is not an object")
    except Exception as e:
        raise RuntimeError(f"failed to fetch version json from url: {version_url}: {e}")
