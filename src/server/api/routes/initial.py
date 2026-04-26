from __future__ import annotations

from core.settings import (
    get_active_profile_id,
    get_active_scope_profile_id,
    list_profiles,
    list_scope_profiles,
    load_global_settings,
)
from core.downloader.wiki import _wiki_image_url
from core.modloaders import LOADER_DISPLAY_NAMES
from core.version_manager import scan_categories

from server.api._helpers import _prepare_settings_response
from server.api.manifest_helpers import _get_installing_map_from_progress


__all__ = ["api_initial"]


def api_initial():
    settings_dict = _prepare_settings_response(load_global_settings())

    try:
        categories_map = scan_categories()
        local_versions = categories_map.get("* All", [])
        categories = sorted([cat for cat in categories_map.keys() if cat != "* All"])
    except Exception:
        local_versions = []
        categories = []

    installing_map = _get_installing_map_from_progress()
    installing_list = []

    for vkey, prog in installing_map.items():
        source = "installing"
        card_full_id = vkey
        loader_type = ""
        loader_version = ""
        if "/" in vkey:
            parts = vkey.split("/")
            cat = parts[0]
            folder = parts[1] if len(parts) > 1 else vkey
            if len(parts) >= 3 and parts[2].startswith("modloader-"):
                source = "modloader"
                tail = parts[2][len("modloader-"):]
                if "-" in tail:
                    loader_type, loader_version = tail.split("-", 1)
                else:
                    loader_type = tail
                display_name = LOADER_DISPLAY_NAMES.get(loader_type, loader_type.capitalize())
                display = f"{display_name} {loader_version}".strip()
            else:
                display = folder
        else:
            cat, folder = "Unknown", vkey
            display = folder

        image_url = _wiki_image_url(folder, "")
        if source == "modloader" and loader_type:
            image_url = f"assets/images/modloader-{loader_type}-versioncard.png"

        installing_list.append({
            "version_key": vkey,
            "category": cat,
            "folder": folder,
            "display": display,
            "image_url": image_url,
            "source": source,
            "card_full_id": card_full_id,
            "loader_type": loader_type,
            "loader_version": loader_version,
            "overall_percent": prog.get("overall_percent", 0),
            "bytes_done": prog.get("bytes_done", 0),
            "bytes_total": prog.get("bytes_total", 0),
        })

    profiles = list_profiles()
    active_profile = get_active_profile_id()
    versions_profiles = list_scope_profiles("versions")
    active_versions_profile = get_active_scope_profile_id("versions")
    mods_profiles = list_scope_profiles("mods")
    active_mods_profile = get_active_scope_profile_id("mods")

    return {
        "versions": [],
        "installed": local_versions,
        "installing": installing_list,
        "categories": categories,
        "selected_version": settings_dict.get("selected_version", ""),
        "settings": settings_dict,
        "profiles": profiles,
        "active_profile": active_profile,
        "versions_profiles": versions_profiles,
        "active_versions_profile": active_versions_profile,
        "mods_profiles": mods_profiles,
        "active_mods_profile": active_mods_profile,
        "manifest_error": False,
    }
