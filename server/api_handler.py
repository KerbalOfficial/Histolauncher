# server/api_handler.py
from core.version_manager import scan_categories
from core.java_launcher import launch_version
from core.settings import load_global_settings, save_global_settings

import os
import urllib.request
import urllib.error

GITHUB_RAW_VERSION_URL = "https://raw.githubusercontent.com/KerbalOfficial/Histolauncher/main/version.dat"
REMOTE_TIMEOUT = 5.0

def read_local_version(project_root=None):
    try:
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(project_root, "version.dat")
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None

def fetch_remote_version(timeout=REMOTE_TIMEOUT):
    try:
        req = urllib.request.Request(GITHUB_RAW_VERSION_URL, headers={"User-Agent": "Histolauncher-Updater/1.0"})
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
    local = read_local_version(project_root)
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

def handle_api_request(path, data):
    if path.rstrip("/") == "/api/is-launcher-outdated":
        return is_launcher_outdated()

    if path == "/api/initial":
        return api_initial()

    if path.startswith("/api/versions/"):
        category = path.split("/api/versions/")[1]
        return api_versions(category)

    if path == "/api/search":
        return api_search(data)

    if path == "/api/launch":
        return api_launch(data)

    if path == "/api/settings":
        return api_settings(data)

    return {"error": "Unknown endpoint"}

def api_initial():
    categories = scan_categories()
    settings = load_global_settings()

    cats = sorted(categories.keys(), key=lambda x: (x != "* All", x))
    if "* All" in cats:
        cats = [c for c in cats if c != "* All"]
    default_cat = "* All" if "* All" in categories else (cats[0] if cats else None)

    return {
        "categories": cats,
        "default_category": default_cat,
        "versions": api_versions(default_cat)["versions"] if default_cat else [],
        "settings": settings,
        "selected_version": settings.get("selected_version", "") or None,
    }

def api_versions(category):
    categories = scan_categories()
    if category not in categories:
        return {"versions": []}

    versions = categories[category]

    if category == "* All":
        formatted = [
            {
                "display": f"{v['display_name']}  [{v['category']}/{v['folder']}]",
                "category": v["category"],
                "folder": v["folder"],
                "launch_disabled": v.get("launch_disabled", False),
                "launch_disabled_message": v.get("launch_disabled_message", "")
            }
            for v in versions
        ]
    else:
        formatted = [
            {
                "display": f"{v['display_name']}  [{v['folder']}]",
                "category": category,
                "folder": v["folder"],
                "launch_disabled": v.get("launch_disabled", False),
                "launch_disabled_message": v.get("launch_disabled_message", "")
            }
            for v in versions
        ]

    return {"versions": formatted}

def api_search(data):
    if not isinstance(data, dict):
        return {"results": []}

    q = (data.get("q") or "").strip().lower()
    category = data.get("category") or None

    categories = scan_categories()
    results = []
    source = []

    if category and category in categories:
        source = categories[category]
    else:
        source = categories.get("* All", [])

    if not q:
        return {"results": []}

    for v in source:
        if q in (v.get("display_name") or "").lower() or q in (v.get("folder") or "").lower() or q in (v.get("category") or "").lower():
            results.append({
                "display": f"{v['display_name']}  [{v['category']}/{v['folder']}]",
                "category": v["category"],
                "folder": v["folder"],
                "launch_disabled": v.get("launch_disabled", False),
                "launch_disabled_message": v.get("launch_disabled_message", "")
            })

    return {"results": results}

def api_launch(data):
    category = data["category"]
    folder = data["folder"]
    username = data["username"]

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
