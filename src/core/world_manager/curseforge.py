from __future__ import annotations

from typing import Any, Dict, List, Optional

import re

from core import mod_manager

from core.world_manager._constants import CURSEFORGE_WORLD_CLASS_ID


_WORLD_CATEGORY_CACHE: Dict[str, Any] = {"names": [], "lookup": {}, "loaded": False}


def _normalize_world_category_lookup_value(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _normalize_world_sort(value: Any) -> str:
    sort_by = str(value or "relevance").strip().lower()
    if sort_by in {"relevance", "downloads", "name", "updated"}:
        return sort_by
    return "relevance"


def _get_world_category_lookup(api_key: str = None) -> tuple[List[str], Dict[str, int]]:
    if _WORLD_CATEGORY_CACHE.get("loaded"):
        return list(_WORLD_CATEGORY_CACHE.get("names") or []), dict(_WORLD_CATEGORY_CACHE.get("lookup") or {})

    response = mod_manager._curseforge_request("/categories", {
        "gameId": mod_manager.CURSEFORGE_MINECRAFT_GAME_ID,
        "classId": CURSEFORGE_WORLD_CLASS_ID,
    }, api_key)
    if not response or "data" not in response:
        _WORLD_CATEGORY_CACHE.update({"names": [], "lookup": {}, "loaded": True})
        return [], {}

    names: List[str] = []
    lookup: Dict[str, int] = {}
    for item in response.get("data", []):
        if not isinstance(item, dict):
            continue
        try:
            category_id = int(item.get("id"))
        except Exception:
            continue
        name = str(item.get("name") or "").strip()
        slug = str(item.get("slug") or "").strip()
        if name and name not in names:
            names.append(name)
        for key_value in (name, slug, item.get("url")):
            normalized_key = _normalize_world_category_lookup_value(key_value)
            if normalized_key:
                lookup[normalized_key] = category_id

    names.sort(key=lambda value: value.lower())
    _WORLD_CATEGORY_CACHE.update({"names": names, "lookup": lookup, "loaded": True})
    return list(names), dict(lookup)


def list_world_categories_curseforge(api_key: str = None) -> List[str]:
    names, _lookup = _get_world_category_lookup(api_key=api_key)
    return names


def search_worlds_curseforge(
    search_query: str = "",
    game_version: str = "",
    category: str = "",
    sort_by: str = "relevance",
    page_size: int = 20,
    index: int = 0,
    api_key: str = None,
) -> Dict[str, Any]:
    safe_page_size = max(1, min(int(page_size or 20), 50))
    safe_index = max(0, int(index or 0))
    offset = safe_index * safe_page_size
    selected_category = str(category or "").strip()
    normalized_sort = _normalize_world_sort(sort_by)
    available_categories, category_lookup = _get_world_category_lookup(api_key=api_key)

    params = {
        "gameId": mod_manager.CURSEFORGE_MINECRAFT_GAME_ID,
        "classId": CURSEFORGE_WORLD_CLASS_ID,
        "pageSize": safe_page_size,
        "index": offset,
        "sortField": 1 if search_query else 2,
        "sortOrder": "desc",
    }
    if normalized_sort == "downloads":
        params["sortField"] = 6
        params["sortOrder"] = "desc"
    elif normalized_sort == "name":
        params["sortField"] = 4
        params["sortOrder"] = "asc"
    elif normalized_sort == "updated":
        params["sortField"] = 3
        params["sortOrder"] = "desc"

    if search_query:
        params["searchFilter"] = search_query
    if game_version:
        params["gameVersion"] = game_version
    if selected_category:
        category_id = category_lookup.get(_normalize_world_category_lookup_value(selected_category))
        if not category_id:
            return {
                "worlds": [],
                "total": 0,
                "has_more": False,
                "categories": available_categories,
                "error": None,
                "requires_api_key": False,
            }
        params["categoryId"] = category_id

    response = mod_manager._curseforge_request("/mods/search", params, api_key)
    if not response or "data" not in response:
        return {
            "worlds": [],
            "total": 0,
            "has_more": False,
            "categories": available_categories,
            "error": (response or {}).get("error") if isinstance(response, dict) else "CurseForge request failed",
            "requires_api_key": bool((response or {}).get("requires_api_key")) if isinstance(response, dict) else False,
        }

    worlds = []
    for world in response.get("data", []):
        categories = []
        for category in (world.get("categories") or []):
            if isinstance(category, dict):
                name = str(category.get("name") or "").strip()
                if name:
                    categories.append(name)
        worlds.append({
            "project_id": str(world.get("id") or ""),
            "world_slug": str(world.get("slug") or ""),
            "name": str(world.get("name") or ""),
            "summary": str(world.get("summary") or ""),
            "icon_url": ((world.get("logo") or {}).get("url") or ""),
            "download_count": world.get("downloadCount", 0),
            "date_modified": str(world.get("dateModified") or ""),
            "categories": categories,
            "provider": "curseforge",
        })

    pagination = response.get("pagination", {})
    total = int(pagination.get("totalCount", 0) or 0)
    return {
        "worlds": worlds,
        "total": total,
        "has_more": offset + len(worlds) < total,
        "categories": available_categories,
        "error": None,
        "requires_api_key": False,
    }


def get_world_files_curseforge(
    project_id: str,
    game_version: str = "",
    api_key: str = None,
) -> List[Dict[str, Any]]:
    page_size = 50
    params = {"pageSize": page_size, "index": 0}
    if game_version:
        params["gameVersion"] = game_version

    all_file_data = []
    while True:
        response = mod_manager._curseforge_request(f"/mods/{project_id}/files", params, api_key)
        if not response or "data" not in response:
            break
        page = response.get("data", [])
        all_file_data.extend(page)
        pagination = response.get("pagination", {})
        total_count = int(pagination.get("totalCount", len(all_file_data)) or len(all_file_data))
        if len(all_file_data) >= total_count or len(page) < page_size:
            break
        params["index"] += page_size

    files = []
    for file_data in all_file_data:
        release_type = int(file_data.get("releaseType", 1) or 1)
        if release_type == 1:
            version_type = "release"
        elif release_type == 2:
            version_type = "beta"
        else:
            version_type = "alpha"

        clean_versions = []
        for game_ver in (file_data.get("gameVersions") or []):
            raw = str(game_ver or "").strip()
            if not raw:
                continue
            normalized = mod_manager.normalize_addon_compatibility_types("mods", [raw])
            if normalized:
                continue
            clean_versions.append(raw)

        files.append({
            "file_id": str(file_data.get("id") or ""),
            "file_name": str(file_data.get("fileName") or ""),
            "display_name": str(file_data.get("displayName") or ""),
            "version_number": str(file_data.get("displayName") or file_data.get("fileName") or ""),
            "version_type": version_type,
            "file_date": str(file_data.get("fileDate") or ""),
            "download_url": mod_manager._cf_resolve_download_url(file_data),
            "file_length": int(file_data.get("fileLength", 0) or 0),
            "game_versions": clean_versions,
        })

    return files


def get_world_detail_curseforge(project_id: str) -> Optional[Dict[str, Any]]:
    return mod_manager.get_project_detail_curseforge(project_id)


__all__ = [
    "search_worlds_curseforge",
    "get_world_files_curseforge",
    "get_world_detail_curseforge",
]
