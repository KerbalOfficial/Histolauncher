from __future__ import annotations

import threading
import time
from typing import Any

from core import manifest as core_manifest
from core.downloader.wiki import _wiki_image_url
from core.settings import load_global_settings
from core.version_manager import scan_categories

from server.api._helpers import (
    _is_enabled_setting,
    _version_identity_key,
)
from server.api.manifest_helpers import (
    _format_mojang_version_entry,
    _get_installing_map_from_progress,
    _map_manifest_entry_to_category,
)


__all__ = ["api_versions", "api_search"]


_AVAILABLE_VERSIONS_CACHE_TTL_SECONDS = 30 * 60
_available_versions_cache_lock = threading.Lock()
_available_versions_cache: dict[bool, dict[str, Any]] = {}


def _copy_remote_versions(remote_versions):
    return [dict(v) for v in (remote_versions or []) if isinstance(v, dict)]


def _load_remote_versions(show_third_party: bool, *, force_refresh: bool = False):
    now = time.time()

    if not force_refresh:
        with _available_versions_cache_lock:
            cached = _available_versions_cache.get(show_third_party)
            if cached and now - cached.get("loaded_at", 0.0) < _AVAILABLE_VERSIONS_CACHE_TTL_SECONDS:
                return (
                    _copy_remote_versions(cached.get("remote_list")),
                    set(cached.get("category_names") or []),
                    False,
                )

    try:
        mf = core_manifest.fetch_manifest(include_third_party=show_third_party)
        manifest = mf.get("data") or {}
        manifest_versions = manifest.get("versions", [])
    except Exception:
        return [], set(), True

    latest_info = manifest.get("latest") if isinstance(manifest.get("latest"), dict) else {}
    recommended_id = str((latest_info or {}).get("release") or "").strip()
    if not recommended_id:
        for m in manifest_versions:
            if str(m.get("type") or "").lower() == "release" and m.get("id"):
                recommended_id = str(m.get("id"))
                break

    remote_list = []
    category_names = set()
    for m in manifest_versions:
        vid = m.get("id")
        vtype = m.get("type", "")
        source = m.get("source") or "mojang"
        mapped_cat = _map_manifest_entry_to_category(vid, vtype, source)
        category_names.add(mapped_cat)
        remote_list.append({
            "display": vid,
            "category": mapped_cat,
            "folder": vid,
            "installed": False,
            "is_remote": True,
            "source": source,
            "image_url": _wiki_image_url(vid, vtype),
            "recommended": bool(recommended_id and vid == recommended_id),
        })

    with _available_versions_cache_lock:
        _available_versions_cache[show_third_party] = {
            "loaded_at": now,
            "remote_list": _copy_remote_versions(remote_list),
            "category_names": sorted(category_names),
        }

    return remote_list, category_names, False


def api_versions(category, *, force_refresh: bool = False):
    categories = scan_categories()
    local_versions = categories.get("* All", [])
    category_names = {
        v.get("category")
        for v in local_versions
        if isinstance(v, dict) and v.get("category")
    }

    settings_dict = load_global_settings()
    show_third_party = _is_enabled_setting(settings_dict.get("show_third_party_versions", "0"))

    remote_list, remote_category_names, manifest_error = _load_remote_versions(
        show_third_party,
        force_refresh=force_refresh,
    )
    category_names.update(remote_category_names)

    installed_set = {
        _version_identity_key(lv.get("category"), lv.get("folder"))
        for lv in local_versions
    }

    installing_map = _get_installing_map_from_progress()
    installing_keys = set()
    for vkey in installing_map.keys():
        if "/" in vkey:
            cat, folder = vkey.split("/", 1)
        else:
            cat, folder = "Unknown", vkey
        installing_keys.add(_version_identity_key(cat, folder))

    def prepare_remote(entry):
        key_str = _version_identity_key(entry.get("category"), entry.get("folder"))
        if key_str in installing_keys:
            return None
        prepared = dict(entry)
        is_installed = key_str in installed_set
        prepared["installed"] = False
        prepared["installed_local"] = is_installed
        prepared["redownload_available"] = is_installed
        return prepared

    if not category or category == "* All":
        installed_out = local_versions
        remote_out = [m for m in (prepare_remote(m) for m in remote_list) if m]
    else:
        category_key = str(category or "").casefold()
        installed_out = [
            lv for lv in local_versions
            if str(lv.get("category") or "").casefold() == category_key
        ]
        remote_out = [
            m for m in (prepare_remote(m) for m in remote_list)
            if m and str(m.get("category") or "").casefold() == category_key
        ]

    return {
        "ok": True,
        "installed": installed_out,
        "available": remote_out,
        "categories": sorted(category_names),
        "manifest_error": manifest_error,
    }


def api_search(data):
    if not isinstance(data, dict):
        return {"results": []}

    q = (data.get("q") or "").strip().lower()
    category = data.get("category") or None

    categories = scan_categories()
    results = []

    if category and category in categories:
        source_list = categories[category]
    else:
        source_list = categories.get("* All", [])

    if not q:
        return {"results": []}

    for v in source_list:
        if (
            q in (v.get("display_name") or "").lower()
            or q in (v.get("folder") or "").lower()
            or q in (v.get("category") or "").lower()
        ):
            results.append({
                "display": f"{v['display_name']}  [{v['category']}/{v['folder']}]",
                "category": v["category"],
                "folder": v["folder"],
                "launch_disabled": v.get("launch_disabled", False),
                "launch_disabled_message": v.get("launch_disabled_message", ""),
                "is_remote": False,
                "source": "local",
            })

    try:
        settings_dict = load_global_settings()
        show_third_party = _is_enabled_setting(
            settings_dict.get("show_third_party_versions", "0")
        )

        mf = core_manifest.fetch_manifest(include_third_party=show_third_party)
        manifest = mf.get("data") or {}
        manifest_source = mf.get("source") or "mojang"
        for m in manifest.get("versions", []):
            vid = m.get("id", "")
            vtype = m.get("type", "")
            source = m.get("source") or manifest_source
            cat = _map_manifest_entry_to_category(vid, vtype, source)
            if q in vid.lower() or q in cat.lower():
                results.append(_format_mojang_version_entry(m, source))
    except Exception:
        pass

    return {"results": results}
