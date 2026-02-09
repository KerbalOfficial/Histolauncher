# server/api_handler.py
import os
import sys
import json
import shutil
import urllib.request
import urllib.error
from typing import Any, Dict, List

from core.version_manager import scan_categories
from core.java_launcher import launch_version
from core.settings import load_global_settings, save_global_settings, get_base_dir

from core import manifest as core_manifest
from core import downloader as core_downloader

GITHUB_RAW_VERSION_URL = "https://raw.githubusercontent.com/KerbalOfficial/Histolauncher/main/version.dat"
REMOTE_TIMEOUT = 5.0


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


def read_local_version(project_root: str = None, base_dir: str = None) -> str:
    try:
        if project_root is None and base_dir is not None:
            project_root = base_dir
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(project_root, "version.dat")
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None


def fetch_remote_version(timeout=REMOTE_TIMEOUT):
    try:
        url = _apply_url_proxy(GITHUB_RAW_VERSION_URL)
        req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher-Updater/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception:
        return None


def parse_version(ver):
    if not ver or len(ver) < 2:
        return None, None
    letter = ver[0]
    try:
        num = int(ver[1:])
        return letter, num
    except Exception:
        return None, None


def is_launcher_outdated():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local = read_local_version(project_root=project_root)
    remote = fetch_remote_version()

    if not local or not remote:
        return False

    l_letter, l_num = parse_version(local)
    r_letter, r_num = parse_version(remote)

    if l_letter is None or r_letter is None:
        return False

    if l_letter != r_letter:
        return False

    return r_num > l_num


def _map_mojang_type_to_category(mojang_type: str) -> str:
    t = (mojang_type or "").lower()
    if t.startswith("old_"):
        t = t[len("old_"):]
    if t == "release":
        return "Release"
    if t == "snapshot":
        return "Snapshot"
    if t == "beta":
        return "Beta"
    if t == "alpha":
        return "Alpha"
    return t.capitalize()


def _format_mojang_version_entry(manifest_entry: Dict[str, Any], source: str) -> Dict[str, Any]:
    vid = manifest_entry.get("id")
    vtype = manifest_entry.get("type", "")
    category = _map_mojang_type_to_category(vtype)
    display = vid
    return {
        "display": display,
        "category": category,
        "folder": vid,
        "launch_disabled": False,
        "launch_disabled_message": "",
        "is_remote": True,
        "source": source or "mojang",
    }


def handle_api_request(path: str, data: Any):
    p = path.split("?", 1)[0].rstrip("/")

    if p == "/api/is-launcher-outdated":
        return is_launcher_outdated()

    if p == "/api/initial":
        return api_initial()

    if p.startswith("/api/versions"):
        parts = p.split("/api/versions", 1)[1].lstrip("/").split("/")
        category = parts[0] if parts and parts[0] else None
        return api_versions(category)

    if p == "/api/search":
        return api_search(data)

    if p == "/api/launch":
        return api_launch(data)

    if p == "/api/settings":
        return api_settings(data)

    if p == "/api/install":
        return api_install(data)

    if p.startswith("/api/status/"):
        version_id = p[len("/api/status/"):]
        return api_status(version_id)

    if p.startswith("/api/cancel/"):
        version_id = p[len("/api/cancel/"):]
        return api_cancel(version_id)

    if p == "/api/installed":
        return api_installed()

    if p == "/api/open_data_folder":
        return api_open_data_folder()

    if p == "/api/delete":
        return api_delete_version(data)

    return {"error": "Unknown endpoint"}


def wiki_image_url(version_id: str, version_type: str) -> str | None:
    t = (version_type or "").lower()

    if t == "release":
        prefix = "Java_Edition_"
        clean_id = version_id
    elif t == "old_beta":
        prefix = "Beta_"
        clean_id = version_id[1:] if version_id.startswith("b") else version_id
    elif t == "old_alpha":
        prefix = "Alpha_v"
        clean_id = version_id[1:] if version_id.startswith("a") else version_id
    else:
        return None

    return f"https://minecraft.wiki/images/thumb/{prefix}{clean_id}.png/260px-.png"


def api_initial():
    mf = core_manifest.fetch_manifest()
    manifest = mf.get("data")
    manifest_source = mf.get("source") or "mojang"

    manifest_error = False
    versions = []
    categories = set()

    if manifest is None:
        manifest_error = True
    else:
        for m in manifest.get("versions", []):
            vid = m.get("id")
            vtype = m.get("type", "")
            category = _map_mojang_type_to_category(vtype)

            img = wiki_image_url(vid, vtype)

            versions.append({
                "display": vid,
                "category": category,
                "folder": vid,
                "installed": False,
                "is_remote": True,
                "source": manifest_source,
                "image_url": img,
                "total_size": None,
            })
            categories.add(category)

    try:
        categories_map = scan_categories()
        local_versions = categories_map.get("* All", [])
        for lv in local_versions:
            display = lv.get("display_name") or lv.get("folder")
            folder = lv.get("folder")
            cat = lv.get("category", "Local")

            versions.append({
                "display": display,
                "category": cat,
                "folder": folder,
                "installed": True,
                "is_remote": False,
                "source": "local",
                "image_url": None,
                "total_size": None,
            })
            categories.add(cat)
    except Exception:
        pass

    installing_map = core_downloader.list_installing_versions()
    installing_list = []
    for vkey, prog in installing_map.items():
        if "/" in vkey:
            cat, folder = vkey.split("/", 1)
        else:
            cat, folder = "Unknown", vkey
        display = folder
        for v in versions:
            if v["category"].lower() == cat.lower() and v["folder"] == folder:
                display = v["display"]
                break
        installing_list.append({
            "version_key": vkey,
            "category": cat,
            "folder": folder,
            "display": display,
            "overall_percent": prog.get("overall_percent", 0),
            "bytes_done": prog.get("bytes_done", 0),
            "bytes_total": prog.get("bytes_total", 0),
        })

    settings_dict = load_global_settings()

    payload = {
        "versions": versions,
        "categories": sorted(list(categories)),
        "selected_version": settings_dict.get("selected_version", ""),
        "settings": settings_dict,
        "manifest_error": manifest_error,
        "installing": installing_list,
    }
    return payload


def api_versions(category):
    categories = scan_categories()
    local_versions = categories.get("* All", [])

    try:
        mf = core_manifest.fetch_manifest()
        manifest = mf.get("data") or {}
        manifest_source = mf.get("source") or "mojang"
        manifest_versions = manifest.get("versions", [])
    except Exception:
        manifest_versions = []
        manifest_source = "mojang"

    mojang_list = []
    for m in manifest_versions:
        vid = m.get("id")
        vtype = m.get("type", "")
        mapped_cat = _map_mojang_type_to_category(vtype)
        mojang_list.append({
            "display": vid,
            "category": mapped_cat,
            "folder": vid,
            "installed": False,
            "is_remote": True,
            "source": manifest_source,
        })

    combined = []

    if not category or category == "* All":
        for v in local_versions:
            combined.append({
                "display": v["display_name"],
                "category": v["category"],
                "folder": v["folder"],
                "installed": True,
                "is_remote": False,
                "source": "local",
            })
        combined.extend(mojang_list)
        return {"versions": combined}

    for v in categories.get(category, []):
        combined.append({
            "display": v["display_name"],
            "category": category,
            "folder": v["folder"],
            "installed": True,
            "is_remote": False,
            "source": "local",
        })

    for m in mojang_list:
        if m["category"] == category:
            combined.append(m)

    return {"versions": combined}


def api_search(data):
    if not isinstance(data, dict):
        return {"results": []}

    q = (data.get("q") or "").strip().lower()
    category = data.get("category") or None

    categories = scan_categories()
    results = []
    source_list = []

    if category and category in categories:
        source_list = categories[category]
    else:
        source_list = categories.get("* All", [])

    if not q:
        return {"results": []}

    for v in source_list:
        if q in (v.get("display_name") or "").lower() or q in (v.get("folder") or "").lower() or q in (v.get("category") or "").lower():
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
        mf = core_manifest.fetch_manifest()
        manifest = mf.get("data") or {}
        manifest_source = mf.get("source") or "mojang"
        for m in manifest.get("versions", []):
            vid = m.get("id", "")
            vtype = m.get("type", "")
            cat = _map_mojang_type_to_category(vtype)
            if q in vid.lower() or q in cat.lower():
                results.append(_format_mojang_version_entry(m, manifest_source))
    except Exception:
        pass

    return {"results": results}


def api_launch(data):
    category = data.get("category")
    folder = data.get("folder")
    username = data.get("username")

    if not category or not folder:
        return {"ok": False, "message": "Missing category or folder"}

    data_base = get_base_dir()
    clients_dir = os.path.join(data_base, "clients")

    storage_cat = category.lower()
    version_dir = os.path.join(clients_dir, storage_cat, folder)
    jar_path = os.path.join(version_dir, "client.jar")

    if not os.path.exists(jar_path):
        return {"ok": False, "message": "Client not installed. Please download it from Versions first."}

    version_identifier = f"{category}/{folder}"
    ok = launch_version(version_identifier, username_override=username)

    return {
        "ok": ok,
        "message": f"Launched {folder} as {username}" if ok else f"Failed to launch {folder}",
    }


def api_settings(data):
    if not isinstance(data, dict):
        data = {}

    current = load_global_settings()
    current.update(data)
    save_global_settings(current)

    return {"ok": True, "message": "Settings saved.", "settings": current}


def api_install(data):
    if not isinstance(data, dict):
        if isinstance(data, str):
            raw = data.strip()
            if "/" in raw:
                cat, vid = raw.split("/", 1)
                data = {"version": vid, "category": cat}
            else:
                return {"error": "invalid request"}
        else:
            return {"error": "invalid request"}

    version_id = data.get("version") or data.get("folder")
    category = data.get("category") or None
    full_assets = bool(data.get("full_assets", False))

    if not version_id:
        combined = data.get("key") or data.get("version_key") or None
        if isinstance(combined, str) and "/" in combined:
            parts = combined.split("/", 1)
            category = parts[0]
            version_id = parts[1]

    if not version_id:
        return {"error": "missing version"}

    storage_type = _map_mojang_type_to_category(
        (data.get("type") or "").lower()
    ).lower()
    if category:
        storage_type = category.lower()

    version_key = core_downloader.start_download(version_id, storage_type, full_assets=full_assets)
    return {"started": True, "version": version_key}


def api_status(version_key):
    try:
        status = core_downloader.get_status(version_key)
        if not status:
            return {"status": "unknown"}
        return status
    except Exception as e:
        return {"error": str(e)}


def api_cancel(version_key):
    try:
        core_downloader.cancel_download(version_key)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_installed():
    try:
        categories = scan_categories()
        return categories.get("* All", [])
    except Exception:
        return {}


def api_open_data_folder():
    try:
        base = get_base_dir()

        if os.name == "nt":
            os.startfile(base)
        else:
            if sys.platform == "darwin":
                os.system(f'open "{base}"')
            else:
                os.system(f'xdg-open "{base}"')

        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_delete_version(data):
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid request"}

    category = (data.get("category") or "").strip()
    folder = (data.get("folder") or "").strip()

    if not category or not folder:
        return {"ok": False, "error": "missing category or folder"}

    base = get_base_dir()
    clients_dir = os.path.join(base, "clients")
    version_dir = os.path.join(clients_dir, category.lower(), folder)

    if not os.path.isdir(version_dir):
        return {"ok": False, "error": "version directory does not exist"}

    try:
        shutil.rmtree(version_dir)
        version_key = f"{category.lower()}/{folder}"
        core_downloader.delete_progress(version_key)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
