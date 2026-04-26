from __future__ import annotations

import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.settings import _apply_url_proxy

from core.mod_manager._constants import (
    CURSEFORGE_MINECRAFT_GAME_ID,
    CURSEFORGE_MODLOADER_TYPE_FABRIC,
    CURSEFORGE_MODLOADER_TYPE_FORGE,
    CURSEFORGE_MODLOADER_TYPE_NEOFORGE,
    CURSEFORGE_MODLOADER_TYPE_QUILT,
    MODRINTH_PROJECT_TYPES,
    _CURSEFORGE_CLASS_ID_CACHE,
    _MODRINTH_DETAIL_TTL,
    _MODRINTH_SEARCH_TTL,
    logger,
)
from core.mod_manager._http import (
    _curseforge_request,
    _modrinth_cache_get,
    _modrinth_cache_set,
    _modrinth_request,
    _modrinth_response_looks_like_project,
)
from core.mod_manager._validation import (
    _is_within_dir,
    _normalize_download_url,
    _validate_addon_filename,
    normalize_addon_compatibility_types,
    normalize_addon_type,
)
from core.mod_manager.storage import get_addon_version_dir


_CURSEFORGE_CATEGORY_CACHE: Dict[str, Dict[str, Any]] = {}


def _normalize_category_lookup_value(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _normalize_project_sort(value: Any) -> str:
    sort_by = str(value or "relevance").strip().lower()
    if sort_by in {"relevance", "downloads", "name", "updated"}:
        return sort_by
    return "relevance"


def _normalize_class_lookup_value(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _get_curseforge_class_id(addon_type: str, api_key: str = None) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    normalized_type = normalize_addon_type(addon_type)
    if normalized_type == "mods":
        return 6, None
    if normalized_type == "modpacks":
        return 4471, None

    if normalized_type in _CURSEFORGE_CLASS_ID_CACHE:
        return _CURSEFORGE_CLASS_ID_CACHE[normalized_type], None

    response = _curseforge_request("/categories", {
        "gameId": CURSEFORGE_MINECRAFT_GAME_ID,
        "classesOnly": "true",
    }, api_key)
    if not response or "data" not in response:
        return None, response if isinstance(response, dict) else None

    candidates = {
        "resourcepacks": {
            "resourcepacks", "resourcepack", "resource-packs", "resource-pack",
            "texturepacks", "texturepack", "texture-packs", "texture-pack",
        },
        "shaderpacks": {
            "shaderpacks", "shaderpack", "shaders", "shader",
            "shader-packs", "shader-pack",
        },
        "modpacks": {
            "modpacks", "modpack", "mod-packs", "mod-pack",
        },
    }
    target_candidates = candidates.get(normalized_type, set())

    for item in response.get("data", []):
        if not isinstance(item, dict):
            continue
        match_values = {
            _normalize_class_lookup_value(item.get("name")),
            _normalize_class_lookup_value(item.get("slug")),
            _normalize_class_lookup_value(item.get("url")),
        }
        if match_values.intersection(target_candidates):
            try:
                class_id = int(item.get("id"))
            except Exception:
                continue
            _CURSEFORGE_CLASS_ID_CACHE[normalized_type] = class_id
            return class_id, None

    _CURSEFORGE_CLASS_ID_CACHE[normalized_type] = None
    return None, {"error": f"CurseForge class not found for addon type: {normalized_type}", "requires_api_key": False}


def _get_curseforge_category_lookup(addon_type: str, api_key: str = None) -> Tuple[List[str], Dict[str, int]]:
    normalized_type = normalize_addon_type(addon_type)
    cache_key = f"{normalized_type}:{bool(str(api_key or '').strip())}"
    cached = _CURSEFORGE_CATEGORY_CACHE.get(cache_key)
    if cached is not None:
        return list(cached.get("names") or []), dict(cached.get("lookup") or {})

    class_id, class_error = _get_curseforge_class_id(normalized_type, api_key=api_key)
    if class_id is None:
        _CURSEFORGE_CATEGORY_CACHE[cache_key] = {"names": [], "lookup": {}}
        return [], {}

    response = _curseforge_request("/categories", {
        "gameId": CURSEFORGE_MINECRAFT_GAME_ID,
        "classId": class_id,
    }, api_key)
    if not response or "data" not in response:
        _CURSEFORGE_CATEGORY_CACHE[cache_key] = {"names": [], "lookup": {}}
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
            normalized_key = _normalize_category_lookup_value(key_value)
            if normalized_key:
                lookup[normalized_key] = category_id

    names.sort(key=lambda value: value.lower())
    _CURSEFORGE_CATEGORY_CACHE[cache_key] = {"names": names, "lookup": lookup}
    return list(names), dict(lookup)


def list_project_categories_curseforge(addon_type: str = "mods", api_key: str = None) -> List[str]:
    names, _lookup = _get_curseforge_category_lookup(addon_type, api_key=api_key)
    return names


def list_project_categories_modrinth(addon_type: str = "mods") -> List[str]:
    normalized_type = normalize_addon_type(addon_type)
    project_type = MODRINTH_PROJECT_TYPES.get(normalized_type, "mod")
    cache_key = f"categories:{project_type}"
    cached = _modrinth_cache_get(cache_key)
    if cached is not None:
        return list(cached)

    response = _modrinth_request("/tag/category")
    if not isinstance(response, list):
        return []

    categories: List[str] = []
    for item in response:
        if not isinstance(item, dict):
            continue
        if str(item.get("project_type") or "").strip().lower() != project_type:
            continue
        name = str(item.get("name") or "").strip()
        if name and name not in categories:
            categories.append(name)

    categories.sort(key=lambda value: value.lower())
    _modrinth_cache_set(cache_key, categories, _MODRINTH_DETAIL_TTL)
    return list(categories)


def get_project_detail_modrinth(mod_id: str, addon_type: str = "mods") -> Optional[Dict[str, Any]]:
    normalized_type = normalize_addon_type(addon_type)
    expected_type = MODRINTH_PROJECT_TYPES.get(normalized_type, "mod")
    cache_key = f"detail:{expected_type}:{mod_id}"
    cached = _modrinth_cache_get(cache_key)
    if cached is not None:
        return cached

    response = _modrinth_request(f"/project/{mod_id}")
    if not _modrinth_response_looks_like_project(response, expected_project_type=expected_type):
        return None
    if str(response.get("project_type") or expected_type).strip().lower() != expected_type:
        return None
    result = {
        "title": response.get("title", ""),
        "description": response.get("description", ""),
        "body": response.get("body", ""),
        "icon_url": response.get("icon_url", ""),
        "gallery": response.get("gallery", []),
        "downloads": response.get("downloads", 0),
        "categories": response.get("categories", []),
        "source_url": response.get("source_url", ""),
        "issues_url": response.get("issues_url", ""),
        "wiki_url": response.get("wiki_url", ""),
    }
    _modrinth_cache_set(cache_key, result, _MODRINTH_DETAIL_TTL)
    return result


def get_mod_detail_modrinth(mod_id: str) -> Optional[Dict[str, Any]]:
    return get_project_detail_modrinth(mod_id, addon_type="mods")


def get_project_detail_curseforge(mod_id: str) -> Optional[Dict[str, Any]]:
    response = _curseforge_request(f"/mods/{mod_id}")
    if not response or "data" not in response:
        return None
    mod = response["data"]

    screenshots = []
    for ss in (mod.get("screenshots") or []):
        if isinstance(ss, dict) and ss.get("url"):
            screenshots.append({"url": ss["url"], "title": ss.get("title", "")})

    desc_resp = _curseforge_request(f"/mods/{mod_id}/description")
    body_html = ""
    if desc_resp and "data" in desc_resp:
        body_html = desc_resp["data"]

    return {
        "title": mod.get("name", ""),
        "description": mod.get("summary", ""),
        "body": body_html,
        "icon_url": (mod.get("logo") or {}).get("url", ""),
        "gallery": screenshots,
        "downloads": mod.get("downloadCount", 0),
        "categories": [c.get("name", "") for c in (mod.get("categories") or []) if isinstance(c, dict)],
        "source_url": (mod.get("links") or {}).get("sourceUrl", ""),
        "issues_url": (mod.get("links") or {}).get("issuesUrl", ""),
        "wiki_url": (mod.get("links") or {}).get("wikiUrl", ""),
    }


def get_mod_detail_curseforge(mod_id: str) -> Optional[Dict[str, Any]]:
    return get_project_detail_curseforge(mod_id)


def search_projects_curseforge(
    addon_type: str = "mods",
    search_query: str = "",
    game_version: str = None,
    mod_loader_type: str = None,
    category: str = "",
    sort_by: str = "relevance",
    page_size: int = 20,
    index: int = 0,
    api_key: str = None
) -> Dict[str, Any]:
    safe_page_size = max(1, min(int(page_size or 20), 50))
    safe_index = max(0, int(index or 0))
    offset = safe_index * safe_page_size
    normalized_type = normalize_addon_type(addon_type)
    normalized_filter_values = normalize_addon_compatibility_types(normalized_type, mod_loader_type)
    normalized_filter = normalized_filter_values[0] if normalized_filter_values else ""
    normalized_sort = _normalize_project_sort(sort_by)
    selected_category = str(category or "").strip()

    class_id, class_error = _get_curseforge_class_id(normalized_type, api_key=api_key)
    if class_id is None:
        return {
            "mods": [],
            "total": 0,
            "has_more": False,
            "categories": [],
            "error": (class_error or {}).get("error") or "Unable to resolve CurseForge class",
            "requires_api_key": bool((class_error or {}).get("requires_api_key")),
        }

    available_categories, category_lookup = _get_curseforge_category_lookup(normalized_type, api_key=api_key)

    params = {
        "gameId": CURSEFORGE_MINECRAFT_GAME_ID,
        "classId": class_id,
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
        category_id = category_lookup.get(_normalize_category_lookup_value(selected_category))
        if not category_id:
            return {
                "mods": [],
                "total": 0,
                "has_more": False,
                "categories": available_categories,
                "error": None,
                "requires_api_key": False,
            }
        params["categoryId"] = category_id

    if normalized_type in ("mods", "modpacks") and normalized_filter:
        if normalized_filter == "forge":
            params["modLoaderType"] = CURSEFORGE_MODLOADER_TYPE_FORGE
        elif normalized_filter == "fabric":
            params["modLoaderType"] = CURSEFORGE_MODLOADER_TYPE_FABRIC
        elif normalized_filter == "quilt":
            params["modLoaderType"] = CURSEFORGE_MODLOADER_TYPE_QUILT
        elif normalized_filter == "neoforge":
            params["modLoaderType"] = CURSEFORGE_MODLOADER_TYPE_NEOFORGE

    response = _curseforge_request("/mods/search", params, api_key)

    if not response or "data" not in response:
        return {
            "mods": [],
            "total": 0,
            "has_more": False,
            "categories": available_categories,
            "error": (response or {}).get("error"),
            "requires_api_key": bool((response or {}).get("requires_api_key")),
        }

    mods = []
    for mod in response.get("data", []):
        categories = []
        for cat in (mod.get("categories") or []):
            if isinstance(cat, dict):
                name = (cat.get("name") or "").strip()
                if name:
                    categories.append(name)

        if normalized_type == "shaderpacks" and normalized_filter:
            category_matches = normalize_addon_compatibility_types(normalized_type, categories)
            if normalized_filter not in category_matches:
                continue

        mods.append({
            "mod_id": str(mod.get("id")),
            "mod_slug": mod.get("slug", ""),
            "name": mod.get("name", ""),
            "summary": mod.get("summary", ""),
            "icon_url": mod.get("logo", {}).get("url", ""),
            "download_count": mod.get("downloadCount", 0),
            "date_modified": mod.get("dateModified", ""),
            "categories": categories,
            "provider": "curseforge",
        })

    pagination = response.get("pagination", {})
    total = pagination.get("totalCount", 0)

    return {
        "mods": mods,
        "total": total,
        "has_more": offset + len(mods) < total,
        "categories": available_categories,
        "error": None,
        "requires_api_key": False,
    }


def search_mods_curseforge(
    search_query: str = "",
    game_version: str = None,
    mod_loader_type: str = None,
    page_size: int = 20,
    index: int = 0,
    api_key: str = None
) -> Dict[str, Any]:
    return search_projects_curseforge(
        addon_type="mods",
        search_query=search_query,
        game_version=game_version,
        mod_loader_type=mod_loader_type,
        page_size=page_size,
        index=index,
        api_key=api_key,
    )


def get_mod_files_curseforge(
    mod_id: str,
    game_version: str = None,
    mod_loader_type: str = None,
    api_key: str = None,
    addon_type: str = "mods",
) -> List[Dict[str, Any]]:
    PAGE_SIZE = 50
    params = {"pageSize": PAGE_SIZE, "index": 0}
    normalized_type = normalize_addon_type(addon_type)
    normalized_filter_values = normalize_addon_compatibility_types(normalized_type, mod_loader_type)
    normalized_filter = normalized_filter_values[0] if normalized_filter_values else ""

    if game_version:
        params["gameVersion"] = game_version

    if normalized_filter:
        if normalized_filter == "forge":
            params["modLoaderType"] = CURSEFORGE_MODLOADER_TYPE_FORGE
        elif normalized_filter == "fabric":
            params["modLoaderType"] = CURSEFORGE_MODLOADER_TYPE_FABRIC
        elif normalized_filter == "quilt":
            params["modLoaderType"] = CURSEFORGE_MODLOADER_TYPE_QUILT
        elif normalized_filter == "neoforge":
            params["modLoaderType"] = CURSEFORGE_MODLOADER_TYPE_NEOFORGE

    all_file_data = []
    while True:
        response = _curseforge_request(f"/mods/{mod_id}/files", params, api_key)
        if not response or "data" not in response:
            break
        page = response.get("data", [])
        all_file_data.extend(page)
        pagination = response.get("pagination", {})
        total_count = pagination.get("totalCount", len(all_file_data))
        if len(all_file_data) >= total_count or len(page) < PAGE_SIZE:
            break
        params["index"] += PAGE_SIZE

    files = []
    for file_data in all_file_data:
        game_versions = file_data.get("gameVersions", [])
        loaders = []
        clean_versions = []
        for gv in game_versions:
            normalized_loader_values = normalize_addon_compatibility_types(normalized_type, [gv])
            if normalized_loader_values:
                loaders.extend(normalized_loader_values)
            else:
                clean_versions.append(gv)

        cf_release_type = file_data.get("releaseType", 1)
        if cf_release_type == 1:
            version_type = "release"
        elif cf_release_type == 2:
            version_type = "beta"
        else:
            version_type = "alpha"

        files.append({
            "file_id": str(file_data.get("id")),
            "file_name": file_data.get("fileName", ""),
            "display_name": file_data.get("displayName", ""),
            "version_number": file_data.get("displayName", file_data.get("fileName", "")),
            "version_type": version_type,
            "file_date": file_data.get("fileDate", ""),
            "download_url": _cf_resolve_download_url(file_data),
            "file_length": file_data.get("fileLength", 0),
            "game_versions": clean_versions,
            "loaders": loaders,
        })

    if normalized_filter:
        files = [
            file_info for file_info in files
            if normalized_filter in normalize_addon_compatibility_types(normalized_type, file_info.get("loaders", []))
        ]

    return files


def _cf_resolve_download_url(file_data: Dict[str, Any]) -> str:
    url = file_data.get("downloadUrl") or ""
    if url:
        return url
    file_id = file_data.get("id", 0)
    file_name = file_data.get("fileName", "")
    if file_id and file_name:
        file_id_str = str(int(file_id))
        if len(file_id_str) >= 4:
            part1 = file_id_str[:-3]
            part2 = str(int(file_id_str[-3:]))
            encoded_name = urllib.parse.quote(str(file_name), safe="")
            return f"https://edge.forgecdn.net/files/{part1}/{part2}/{encoded_name}"
    return ""


def search_projects_modrinth(
    addon_type: str = "mods",
    search_query: str = "",
    game_version: str = None,
    mod_loader: str = None,
    category: str = "",
    sort_by: str = "relevance",
    limit: int = 20,
    offset: int = 0
) -> Dict[str, Any]:
    normalized_type = normalize_addon_type(addon_type)
    project_type = MODRINTH_PROJECT_TYPES.get(normalized_type, "mod")
    safe_limit = max(1, min(int(limit or 20), 100))
    safe_offset = max(0, int(offset or 0))
    facets = [[f"project_type:{project_type}"]]
    normalized_filter_values = normalize_addon_compatibility_types(normalized_type, mod_loader)
    normalized_filter = normalized_filter_values[0] if normalized_filter_values else ""
    normalized_sort = _normalize_project_sort(sort_by)
    selected_category = str(category or "").strip()
    available_categories = list_project_categories_modrinth(normalized_type)

    if game_version:
        facets.append([f"versions:{game_version}"])

    if normalized_filter:
        facets.append([f"categories:{normalized_filter}"])

    if selected_category:
        facets.append([f"categories:{selected_category}"])

    params = {
        "query": search_query,
        "limit": safe_limit,
        "offset": safe_offset,
        "facets": json.dumps(facets, separators=(",", ":")),
    }

    if normalized_sort == "downloads":
        params["index"] = "downloads"
    elif normalized_sort == "updated":
        params["index"] = "updated"
    elif normalized_sort == "relevance" and (search_query or "").strip():
        params["index"] = "relevance"
    elif not (search_query or "").strip():
        params["index"] = "downloads"

    cache_key = f"search:{json.dumps(params, sort_keys=True)}"
    cached = _modrinth_cache_get(cache_key)
    if cached is not None:
        return cached

    response = _modrinth_request("/search", params)

    if not response:
        return {"mods": [], "total": 0, "has_more": False, "categories": available_categories}

    mods = []
    for hit in response.get("hits", []):
        pt = (hit.get("project_type") or project_type).lower()
        if pt != project_type:
            continue
        mods.append({
            "mod_id": hit.get("project_id", ""),
            "mod_slug": hit.get("slug", ""),
            "name": hit.get("title", ""),
            "summary": hit.get("description", ""),
            "icon_url": hit.get("icon_url", ""),
            "download_count": hit.get("downloads", 0),
            "date_modified": hit.get("date_modified", ""),
            "project_type": hit.get("project_type", ""),
            "categories": hit.get("categories", []) or [],
            "provider": "modrinth",
        })

    if normalized_sort == "name":
        mods.sort(key=lambda mod: str(mod.get("name") or "").lower())

    total = response.get("total_hits", 0)

    result = {
        "mods": mods,
        "total": total,
        "has_more": safe_offset + len(mods) < total,
        "categories": available_categories,
    }
    _modrinth_cache_set(cache_key, result, _MODRINTH_SEARCH_TTL)
    return result


def search_mods_modrinth(
    search_query: str = "",
    game_version: str = None,
    mod_loader: str = None,
    limit: int = 20,
    offset: int = 0
) -> Dict[str, Any]:
    return search_projects_modrinth(
        addon_type="mods",
        search_query=search_query,
        game_version=game_version,
        mod_loader=mod_loader,
        limit=limit,
        offset=offset,
    )


def get_mod_versions_modrinth(mod_id: str, game_version: str = None, mod_loader: str = None) -> Optional[List[Dict[str, Any]]]:
    params = {}

    loaders = []
    if mod_loader:
        loaders.append(mod_loader.lower())

    game_versions = []
    if game_version:
        game_versions.append(game_version)

    if loaders:
        params["loaders"] = json.dumps(loaders)

    if game_versions:
        params["game_versions"] = json.dumps(game_versions)

    cache_key = f"versions:{mod_id}:{game_version}:{mod_loader}"
    cached = _modrinth_cache_get(cache_key)
    if cached is not None:
        return cached

    response = _modrinth_request(f"/project/{mod_id}/version", params)

    if not response or not isinstance(response, list):
        return None

    versions = []
    for version_data in response:
        files = version_data.get("files", [])
        if not files:
            continue

        primary_file = files[0]

        versions.append({
            "version_id": version_data.get("id", ""),
            "version_number": version_data.get("version_number", ""),
            "name": version_data.get("name", ""),
            "version_type": version_data.get("version_type", "release"),
            "date_published": version_data.get("date_published", ""),
            "download_url": primary_file.get("url", ""),
            "file_name": primary_file.get("filename", ""),
            "file_size": primary_file.get("size", 0),
            "game_versions": version_data.get("game_versions", []),
            "loaders": version_data.get("loaders", []),
        })

    _modrinth_cache_set(cache_key, versions, _MODRINTH_DETAIL_TTL)
    return versions


def download_addon_file(
    download_url: str,
    addon_type: str,
    mod_slug: str,
    version_label: str,
    file_name: str,
    mod_loader: str = "",
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
) -> bool:
    normalized_type = normalize_addon_type(addon_type)
    if not _validate_addon_filename(file_name, normalized_type):
        logger.error(f"Refusing unsafe addon filename: {file_name}")
        return False

    ver_dir = get_addon_version_dir(normalized_type, mod_slug, version_label, mod_loader=mod_loader)
    safe_file_name = os.path.basename(file_name)
    file_path = os.path.join(ver_dir, safe_file_name)

    if not _is_within_dir(ver_dir, file_path):
        logger.error(f"Refusing unsafe output path for mod file: {file_name}")
        return False

    normalized_url = _normalize_download_url(download_url)
    if not normalized_url:
        logger.error(f"Refusing addon download with empty URL: {file_name}")
        return False

    try:
        from core.downloader.http import CLIENT
        from core.downloader.errors import DownloadCancelled

        CLIENT.download(normalized_url, file_path, progress_cb=progress_cb)
        logger.info(f"Downloaded addon file: {safe_file_name} to {ver_dir}")
        return True
    except DownloadCancelled:
        raise
    except Exception as e:
        logger.error(f"Failed to download addon file {file_name}: {e}")
        return False


def download_mod_file(download_url: str, mod_loader: str, mod_slug: str, version_label: str, file_name: str) -> bool:
    return download_addon_file(
        download_url,
        "mods",
        mod_slug,
        version_label,
        file_name,
        mod_loader=mod_loader,
    )
