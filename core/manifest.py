# core/manifest.py
import json
import urllib.request
from typing import Dict, Any, List

from core.settings import load_global_settings

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


def _get_url_proxy_prefix() -> str:
    try:
        cfg = load_global_settings()
        return (cfg.get("url_proxy") or "").strip()
    except Exception:
        return ""


def _apply_url_proxy(url: str) -> str:
    prefix = _get_url_proxy_prefix()
    if not prefix:
        return url
    return prefix + url


def _http_get_json(url: str, timeout: int) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    try:
        return json.loads(data.decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"failed to parse json from {url}: {e}")


def fetch_manifest(timeout: int = 6) -> Dict[str, Any]:
    urls: List[Dict[str, str]] = []
    urls.extend(DEFAULT_MANIFEST_URLS)

    for entry in urls:
        src = entry.get("source") or "unknown"
        raw_url = entry.get("url")
        if not raw_url:
            continue

        proxied_url = _apply_url_proxy(raw_url)

        try:
            data = _http_get_json(proxied_url, timeout=timeout)
            if isinstance(data, dict) and "versions" in data and isinstance(data["versions"], list):
                return {"data": data, "source": src}
        except Exception:
            continue

    return {"data": None, "source": None}


def get_version_entry(version_id: str, timeout: int = 6) -> Dict[str, Any]:
    mf = fetch_manifest(timeout=timeout)
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
