# server/api_handler.py

import os
import sys
import shutil
import time
import json
import re
import urllib.request
import urllib.parse
import urllib.error

from typing                 import Any, Dict

from core.discord_rpc       import set_game_presence, set_install_presence, set_launcher_presence
from core.logger            import colorize_log
from core.version_manager   import scan_categories, get_version_loaders, get_clients_dir
from core.java_launcher     import launch_version, consume_last_launch_error
from core.settings          import (
                                        load_global_settings,
                                        save_global_settings,
                                        get_base_dir,
                                        clear_account_token,
                                        _apply_url_proxy,
                                        list_profiles,
                                        create_profile,
                                        set_active_profile,
                                        delete_profile,
                                        rename_profile,
                                        get_active_profile_id,
                                        list_scope_profiles,
                                        create_scope_profile,
                                        set_active_scope_profile,
                                        delete_scope_profile,
                                        rename_scope_profile,
                                        get_active_scope_profile_id,
                                    )
from core.java_runtime      import detect_java_runtimes
from core.downloader        import _wiki_image_url
from core                   import modloaders       as core_modloaders
from core                   import manifest         as core_manifest
from core                   import downloader       as core_downloader
from core.zip_utils         import safe_extract_zip, ZipSecurityError

GITHUB_RAW_VERSION_URL = "https://raw.githubusercontent.com/KerbalOfficial/Histolauncher/main/version.dat"
REMOTE_TIMEOUT = 5.0

_corrupted_versions_checked = False

MAX_VERSION_ID_LENGTH = 64
MAX_CATEGORY_LENGTH = 64
MAX_USERNAME_LENGTH = 16
MAX_LOADER_VERSION_LENGTH = 64
MAX_VERSIONS_IMPORT_PAYLOAD = 1024 * 1024 * 1024
MAX_MODS_IMPORT_PAYLOAD = 64 * 1024 * 1024
MAX_MODPACKS_IMPORT_PAYLOAD = 256 * 1024 * 1024
MAX_PAYLOAD_SIZE = MAX_VERSIONS_IMPORT_PAYLOAD
MAX_MOD_SLUG_LENGTH = 128
MAX_MODPACK_SLUG_LENGTH = 128
MAX_VERSION_LABEL_LENGTH = 128
MAX_FILENAME_LENGTH = 255

CURRENT_MD_VERSION = "1.0"

FORGE_INSTALL_BLOCKED_VERSIONS = {"1.2.4", "1.2.3", "1.1"}
_rpc_install_started_at: Dict[str, float] = {}


def _parse_install_key(version_key: str) -> Dict[str, Any]:
    parts = (version_key or "").split("/")
    if len(parts) >= 3 and parts[2].startswith("modloader-"):
        tail = parts[2][len("modloader-"):]
        loader_type = ""
        loader_version = ""
        if "-" in tail:
            loader_type, loader_version = tail.split("-", 1)
        else:
            loader_type = tail
        return {
            "category": parts[0],
            "folder": parts[1],
            "is_modloader": True,
            "loader_type": loader_type,
            "loader_version": loader_version,
        }

    if len(parts) >= 2:
        return {
            "category": parts[0],
            "folder": parts[1],
            "is_modloader": False,
            "loader_type": None,
            "loader_version": None,
        }

    return {
        "category": None,
        "folder": None,
        "is_modloader": False,
        "loader_type": None,
        "loader_version": None,
    }


def _update_rpc_install_presence(version_key: str, status: Dict[str, Any]) -> None:
    info = _parse_install_key(version_key)
    if not info.get("category") or not info.get("folder"):
        return

    state = str((status or {}).get("status") or "").lower()
    start_time = _rpc_install_started_at.get(version_key)
    version_identifier = f"{info['category']}/{info['folder']}"

    if state in ("downloading", "installing", "starting", "paused"):
        set_install_presence(
            version_identifier,
            progress_percent=(status or {}).get("overall_percent"),
            start_time=start_time,
            loader_type=info.get("loader_type"),
            loader_version=info.get("loader_version"),
        )
        return

    if state in ("installed", "failed", "error", "cancelled"):
        _rpc_install_started_at.pop(version_key, None)
        set_launcher_presence()


def _validate_version_string(version_id: str, max_length: int = MAX_VERSION_ID_LENGTH) -> bool:
    if not isinstance(version_id, str):
        return False
    version_id = version_id.strip()
    if not version_id or len(version_id) > max_length:
        return False
    # Allow alphanumeric, dots, dashes, underscores, and forward slashes
    import re
    return bool(re.match(r'^[a-zA-Z0-9._\-/]+$', version_id))


def _validate_category_string(category: str, max_length: int = MAX_CATEGORY_LENGTH) -> bool:
    """Validate category string format and length."""
    if not isinstance(category, str):
        return False
    category = category.strip()
    if not category or len(category) > max_length:
        return False
    # Allow alphanumeric, spaces, hyphen, and underscore.
    import re
    return bool(re.match(r'^[a-zA-Z0-9 _-]+$', category))


def _validate_loader_type(loader_type: str) -> bool:
    """Validate loader type is one of the allowed values."""
    return loader_type in ["fabric", "forge"]


def _is_enabled_setting(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_legacy_family_category(category: str) -> bool:
    c = str(category or "").strip().lower()
    if not c:
        return False

    legacy_tags = {"alpha", "beta", "classic", "indev", "infdev", "pre-classic", "preclassic"}
    return c in legacy_tags or (c.startswith("oa-") and any(tag in c for tag in legacy_tags))


def _is_non_crash_exit(version_id: str, exit_code: int) -> bool:
    if exit_code == 0:
        return True

    category = version_id.split("/", 1)[0].lower() if "/" in version_id else version_id.lower()

    if _is_legacy_family_category(category) and exit_code == 1:
        return True
    
    if exit_code in (-1073741510, 130):
        return True

    return False


def _looks_like_path_traversal(value: str) -> bool:
    if not isinstance(value, str):
        return True
    if "\x00" in value:
        return True
    normalized = value.replace("\\", "/")
    if "/" in normalized:
        return True
    if ".." in normalized:
        return True
    if os.path.isabs(value):
        return True
    # Block Windows drive-letter patterns like C:foo and C:\foo
    if len(value) >= 2 and value[1] == ":":
        return True
    return False


def _validate_mod_slug(mod_slug: str, max_length: int = MAX_MOD_SLUG_LENGTH) -> bool:
    if not isinstance(mod_slug, str):
        return False
    mod_slug = mod_slug.strip().lower()
    if not mod_slug or len(mod_slug) > max_length:
        return False
    if _looks_like_path_traversal(mod_slug):
        return False
    return bool(re.match(r"^[a-z0-9][a-z0-9._-]*$", mod_slug))


def _validate_modpack_slug(slug: str, max_length: int = MAX_MODPACK_SLUG_LENGTH) -> bool:
    if not isinstance(slug, str):
        return False
    slug = slug.strip().lower()
    if not slug or len(slug) > max_length:
        return False
    if _looks_like_path_traversal(slug):
        return False
    return bool(re.match(r"^[a-z0-9][a-z0-9-]*$", slug))


def _validate_version_label(version_label: str, max_length: int = MAX_VERSION_LABEL_LENGTH) -> bool:
    if not isinstance(version_label, str):
        return False
    version_label = version_label.strip()
    if not version_label or len(version_label) > max_length:
        return False
    return not _looks_like_path_traversal(version_label)


def _validate_jar_filename(file_name: str, max_length: int = MAX_FILENAME_LENGTH) -> bool:
    if not isinstance(file_name, str):
        return False
    file_name = file_name.strip()
    if not file_name or len(file_name) > max_length:
        return False
    if _looks_like_path_traversal(file_name):
        return False
    if os.path.basename(file_name) != file_name:
        return False
    if any(c in file_name for c in '<>:"|?*'):
        return False
    return file_name.lower().endswith('.jar')


def _version_identity_key(category: Any, folder: Any) -> str:
    cat = str(category or "").strip().lower()
    fol = str(folder or "").strip().lower()
    return f"{cat}/{fol}"


def _format_bytes(bytes_size: int) -> str:
    """Format bytes to human-readable string (B, KB, MB, GB)."""
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} KB"
    elif bytes_size < 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_size / (1024 * 1024 * 1024):.2f} GB"


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


def _map_manifest_entry_to_category(version_id: str, version_type: str, source: str) -> str:
    src = (source or "").strip().lower()
    vid = (version_id or "").strip()
    vtype = (version_type or "").strip().lower()

    if src != "omniarchive":
        return _map_mojang_type_to_category(vtype)

    vid_lower = vid.lower()
    
    if vid_lower.startswith("inf-"):
        return "OA-infdev"
    if vid_lower.startswith("in-"):
        return "OA-indev"
    if vid_lower.startswith("c0"):
        return "OA-classic"
    if vid_lower.startswith("a1"):
        return "OA-alpha"
    if vid_lower.startswith("b1"):
        return "OA-beta"
    if vtype == "special":
        return "OA-special"

    return "OA-other"


def _format_mojang_version_entry(manifest_entry: Dict[str, Any], source: str) -> Dict[str, Any]:
    vid = manifest_entry.get("id")
    vtype = manifest_entry.get("type", "")
    resolved_source = manifest_entry.get("source") or source or "mojang"
    category = _map_manifest_entry_to_category(vid, vtype, resolved_source)
    display = vid
    
    return {
        "display": display,
        "category": category,
        "folder": vid,
        "launch_disabled": False,
        "launch_disabled_message": "",
        "is_remote": True,
        "source": resolved_source,
    }


def _get_installing_map_from_progress() -> Dict[str, Dict[str, Any]]:
    installing: Dict[str, Dict[str, Any]] = {}
    try:
        for vkey, prog in core_downloader.list_progress_files():
            if not isinstance(prog, dict): continue
            status = (prog.get("status") or "").lower()
            if status in ("downloading", "paused"): installing[vkey] = prog
    except (IOError, OSError, ValueError, KeyError):
        pass
    return installing


def handle_api_request(path: str, data: Any):
    p = path.split("?", 1)[0].rstrip("/")
    
    EXACT_NO_PARAMS = {
        "/api/account/status": api_account_status,
        "/api/account/current": api_account_current,
        "/api/account/settings-iframe": api_account_settings_iframe,
        "/api/account/launcher-message": api_account_launcher_message,
        "/api/account/disconnect": api_account_disconnect,
        "/api/profiles": api_profiles,
        "/api/profiles/versions": api_profiles_versions,
        "/api/profiles/mods": api_profiles_mods,
        "/api/is-launcher-outdated": is_launcher_outdated,
        "/api/initial": api_initial,
        "/api/clear-logs": api_clear_logs,
        "/api/installed": api_installed,
        "/api/open_data_folder": api_open_data_folder,
        "/api/corrupted-versions": api_corrupted_versions,
        "/api/java-runtimes": api_java_runtimes,
        "/api/java-runtimes-refresh": api_java_runtimes_refresh,
        "/api/mods/installed": api_mods_installed,
        "/api/mods/version-options": api_mods_version_options,
        "/api/modpacks/installed": api_modpacks_installed,
    }
    
    EXACT_WITH_DATA = {
        "/api/account/login": api_account_login,
        "/api/account/verify-session": api_account_verify_session,
        "/api/profiles/create": api_profiles_create,
        "/api/profiles/switch": api_profiles_switch,
        "/api/profiles/delete": api_profiles_delete,
        "/api/profiles/rename": api_profiles_rename,
        "/api/profiles/versions/create": api_profiles_versions_create,
        "/api/profiles/versions/switch": api_profiles_versions_switch,
        "/api/profiles/versions/delete": api_profiles_versions_delete,
        "/api/profiles/versions/rename": api_profiles_versions_rename,
        "/api/profiles/mods/create": api_profiles_mods_create,
        "/api/profiles/mods/switch": api_profiles_mods_switch,
        "/api/profiles/mods/delete": api_profiles_mods_delete,
        "/api/profiles/mods/rename": api_profiles_mods_rename,
        "/api/search": api_search,
        "/api/launch": api_launch,
        "/api/crash-log": api_crash_log,
        "/api/open-crash-log": api_open_crash_log,
        "/api/settings": api_settings,
        "/api/install": api_install,
        "/api/delete": api_delete_version,
        "/api/install-loader": api_install_loader,
        "/api/delete-loader": api_delete_loader,
        "/api/delete-corrupted-versions": api_delete_corrupted_versions,
        "/api/versions/export": api_export_versions,
        "/api/versions/import": api_import_versions,
        "/api/mods/search": api_mods_search,
        "/api/mods/versions": api_mods_versions,
        "/api/mods/install": api_mods_install,
        "/api/mods/import": api_mods_import,
        "/api/mods/delete": api_mods_delete,
        "/api/mods/toggle": api_mods_toggle,
        "/api/mods/set-active-version": api_mods_set_active_version,
        "/api/mods/detail": api_mods_detail,
        "/api/modpacks/export": api_modpacks_export,
        "/api/modpacks/import": api_modpacks_import,
        "/api/modpacks/toggle": api_modpacks_toggle,
        "/api/modpacks/toggle-mod": api_modpacks_toggle_mod,
        "/api/modpacks/delete": api_modpacks_delete,
    }
    
    PREFIX_HANDLERS = [
        ("/api/versions", lambda path: api_versions(_extract_category(path))),
        ("/api/launch_status/", lambda path: api_launch_status(path[len("/api/launch_status/"):])),
        ("/api/game_window_visible/", lambda path: api_game_window_visible(path[len("/api/game_window_visible/"):])),
        ("/api/status/", lambda path: api_status(path[len("/api/status/"):])),
        ("/api/cancel/", lambda path: api_cancel(path[len("/api/cancel/"):])),
        ("/api/pause/", lambda path: api_pause(path[len("/api/pause/"):])),
        ("/api/resume/", lambda path: api_resume(path[len("/api/resume/"):])),
        ("/api/loaders/", lambda path: api_loaders(path[len("/api/loaders/"):])),
    ]
    
    if p in EXACT_NO_PARAMS:
        return EXACT_NO_PARAMS[p]()
    
    if p in EXACT_WITH_DATA:
        return EXACT_WITH_DATA[p](data)
    
    for prefix, handler in PREFIX_HANDLERS:
        if p.startswith(prefix):
            return handler(p)
    
    return {"error": "Unknown endpoint"}


def _extract_category(path: str) -> str:
    parts = path.split("/api/versions", 1)[1].lstrip("/").split("/")
    return parts[0] if parts and parts[0] else None


def api_initial():
    settings_dict = load_global_settings()
    show_third_party = _is_enabled_setting(settings_dict.get("show_third_party_versions", "0"))

    mf = core_manifest.fetch_manifest(include_third_party=show_third_party)
    manifest = mf.get("data")

    manifest_error = False
    remote_versions = []
    categories = set()

    if manifest is None:
        manifest_error = True
    else:
        for m in manifest.get("versions", []):
            vid = m.get("id")
            vtype = m.get("type", "")
            source = m.get("source") or "mojang"
            category = _map_manifest_entry_to_category(vid, vtype, source)

            img = _wiki_image_url(vid, vtype)

            remote_versions.append({
                "display": vid,
                "category": category,
                "folder": vid,
                "installed": False,
                "is_remote": True,
                "source": source,
                "image_url": img,
            })
            categories.add(category)

    try:
        categories_map = scan_categories()
        local_versions = categories_map.get("* All", [])
    except Exception:
        local_versions = []

    installing_map = _get_installing_map_from_progress()
    installing_list = []
    installing_keys = set()

    for vkey, prog in installing_map.items():
        if "/" in vkey:
            cat, folder = vkey.split("/", 1)
        else:
            cat, folder = "Unknown", vkey

        installing_keys.add(_version_identity_key(cat, folder))

        display = folder
        for v in remote_versions:
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

    installed_set = {_version_identity_key(lv.get("category"), lv.get("folder")) for lv in local_versions}

    filtered_remote = []
    for v in remote_versions:
        key_str = _version_identity_key(v.get("category"), v.get("folder"))
        if key_str in installed_set:
            continue
        if key_str in installing_keys:
            continue
        filtered_remote.append(v)

    profiles = list_profiles()
    active_profile = get_active_profile_id()
    versions_profiles = list_scope_profiles("versions")
    active_versions_profile = get_active_scope_profile_id("versions")
    mods_profiles = list_scope_profiles("mods")
    active_mods_profile = get_active_scope_profile_id("mods")

    return {
        "versions": filtered_remote,
        "installed": local_versions,
        "installing": installing_list,
        "categories": sorted(list(categories)),
        "selected_version": settings_dict.get("selected_version", ""),
        "settings": settings_dict,
        "profiles": profiles,
        "active_profile": active_profile,
        "versions_profiles": versions_profiles,
        "active_versions_profile": active_versions_profile,
        "mods_profiles": mods_profiles,
        "active_mods_profile": active_mods_profile,
        "manifest_error": manifest_error,
    }


def api_profiles(data=None):
    try:
        profiles = list_profiles()
        active_profile = get_active_profile_id()
        return {
            "ok": True,
            "profiles": profiles,
            "active_profile": active_profile,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_create(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        name = str(data.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "Profile name is required"}
        if len(name) > 32:
            return {"ok": False, "error": "Profile name must be 1-32 characters"}

        profile = create_profile(name)
        profiles = list_profiles()
        active_profile = get_active_profile_id()
        return {
            "ok": True,
            "profile": profile,
            "profiles": profiles,
            "active_profile": active_profile,
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_switch(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        profile_id = str(data.get("profile_id") or "").strip()
        if not profile_id:
            return {"ok": False, "error": "profile_id is required"}

        if not set_active_profile(profile_id):
            return {"ok": False, "error": "Profile not found"}

        settings_dict = load_global_settings()
        return {
            "ok": True,
            "active_profile": get_active_profile_id(),
            "settings": settings_dict,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_delete(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        profile_id = str(data.get("profile_id") or "").strip()
        if not profile_id:
            return {"ok": False, "error": "profile_id is required"}

        if not delete_profile(profile_id):
            return {
                "ok": False,
                "error": "Failed to delete profile (cannot delete Default or last profile)",
            }

        return {
            "ok": True,
            "profiles": list_profiles(),
            "active_profile": get_active_profile_id(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_rename(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        profile_id = str(data.get("profile_id") or "").strip()
        name = str(data.get("name") or "").strip()
        if not profile_id:
            return {"ok": False, "error": "profile_id is required"}
        if not name:
            return {"ok": False, "error": "Profile name is required"}
        if len(name) > 32:
            return {"ok": False, "error": "Profile name must be 1-32 characters"}

        if not rename_profile(profile_id, name):
            return {"ok": False, "error": "Profile not found"}

        return {
            "ok": True,
            "profiles": list_profiles(),
            "active_profile": get_active_profile_id(),
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_versions(data=None):
    try:
        return {
            "ok": True,
            "profiles": list_scope_profiles("versions"),
            "active_profile": get_active_scope_profile_id("versions"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_versions_create(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        name = str(data.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "Profile name is required"}
        if len(name) > 32:
            return {"ok": False, "error": "Profile name must be 1-32 characters"}

        profile = create_scope_profile("versions", name)
        return {
            "ok": True,
            "profile": profile,
            "profiles": list_scope_profiles("versions"),
            "active_profile": get_active_scope_profile_id("versions"),
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_versions_switch(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        profile_id = str(data.get("profile_id") or "").strip()
        if not profile_id:
            return {"ok": False, "error": "profile_id is required"}
        if not set_active_scope_profile("versions", profile_id):
            return {"ok": False, "error": "Profile not found"}
        return {"ok": True, "active_profile": get_active_scope_profile_id("versions")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_versions_delete(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        profile_id = str(data.get("profile_id") or "").strip()
        if not profile_id:
            return {"ok": False, "error": "profile_id is required"}
        if not delete_scope_profile("versions", profile_id):
            return {"ok": False, "error": "Failed to delete profile (cannot delete Default or last profile)"}
        return {
            "ok": True,
            "profiles": list_scope_profiles("versions"),
            "active_profile": get_active_scope_profile_id("versions"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_versions_rename(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        profile_id = str(data.get("profile_id") or "").strip()
        name = str(data.get("name") or "").strip()
        if not profile_id:
            return {"ok": False, "error": "profile_id is required"}
        if not name:
            return {"ok": False, "error": "Profile name is required"}
        if len(name) > 32:
            return {"ok": False, "error": "Profile name must be 1-32 characters"}

        if not rename_scope_profile("versions", profile_id, name):
            return {"ok": False, "error": "Profile not found"}

        return {
            "ok": True,
            "profiles": list_scope_profiles("versions"),
            "active_profile": get_active_scope_profile_id("versions"),
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_mods(data=None):
    try:
        return {
            "ok": True,
            "profiles": list_scope_profiles("mods"),
            "active_profile": get_active_scope_profile_id("mods"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_mods_create(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        name = str(data.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "Profile name is required"}
        if len(name) > 32:
            return {"ok": False, "error": "Profile name must be 1-32 characters"}

        profile = create_scope_profile("mods", name)
        return {
            "ok": True,
            "profile": profile,
            "profiles": list_scope_profiles("mods"),
            "active_profile": get_active_scope_profile_id("mods"),
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_mods_switch(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        profile_id = str(data.get("profile_id") or "").strip()
        if not profile_id:
            return {"ok": False, "error": "profile_id is required"}
        if not set_active_scope_profile("mods", profile_id):
            return {"ok": False, "error": "Profile not found"}
        return {"ok": True, "active_profile": get_active_scope_profile_id("mods")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_mods_delete(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        profile_id = str(data.get("profile_id") or "").strip()
        if not profile_id:
            return {"ok": False, "error": "profile_id is required"}
        if not delete_scope_profile("mods", profile_id):
            return {"ok": False, "error": "Failed to delete profile (cannot delete Default or last profile)"}
        return {
            "ok": True,
            "profiles": list_scope_profiles("mods"),
            "active_profile": get_active_scope_profile_id("mods"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_mods_rename(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        profile_id = str(data.get("profile_id") or "").strip()
        name = str(data.get("name") or "").strip()
        if not profile_id:
            return {"ok": False, "error": "profile_id is required"}
        if not name:
            return {"ok": False, "error": "Profile name is required"}
        if len(name) > 32:
            return {"ok": False, "error": "Profile name must be 1-32 characters"}

        if not rename_scope_profile("mods", profile_id, name):
            return {"ok": False, "error": "Profile not found"}

        return {
            "ok": True,
            "profiles": list_scope_profiles("mods"),
            "active_profile": get_active_scope_profile_id("mods"),
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _build_java_runtime_response(force_refresh: bool = False):
    settings = load_global_settings() or {}
    selected_java_path = (settings.get("java_path") or "").strip()

    runtimes = detect_java_runtimes(force_refresh=force_refresh)
    options = []
    for rt in runtimes:
        path = str(rt.get("path") or "")
        label = str(rt.get("label") or "Java")
        version = str(rt.get("version") or "unknown")
        major = int(rt.get("major") or 0)
        options.append(
            {
                "path": path,
                "label": label,
                "version": version,
                "major": major,
                "display": f"{label} ({version}) - {path}",
            }
        )

    return {
        "ok": True,
        "selected_java_path": selected_java_path,
        "runtimes": options,
    }


def api_java_runtimes():
    try:
        return _build_java_runtime_response(force_refresh=False)
    except Exception as e:
        return {"ok": False, "error": str(e), "runtimes": []}


def api_java_runtimes_refresh():
    try:
        return _build_java_runtime_response(force_refresh=True)
    except Exception as e:
        return {"ok": False, "error": str(e), "runtimes": []}


def api_versions(category):
    categories = scan_categories()
    local_versions = categories.get("* All", [])

    settings_dict = load_global_settings()
    show_third_party = _is_enabled_setting(settings_dict.get("show_third_party_versions", "0"))

    try:
        mf = core_manifest.fetch_manifest(include_third_party=show_third_party)
        manifest = mf.get("data") or {}
        manifest_versions = manifest.get("versions", [])
    except Exception:
        manifest_versions = []

    remote_list = []
    for m in manifest_versions:
        vid = m.get("id")
        vtype = m.get("type", "")
        source = m.get("source") or "mojang"
        mapped_cat = _map_manifest_entry_to_category(vid, vtype, source)
        remote_list.append({
            "display": vid,
            "category": mapped_cat,
            "folder": vid,
            "installed": False,
            "is_remote": True,
            "source": source,
        })

    installed_set = {_version_identity_key(lv.get("category"), lv.get("folder")) for lv in local_versions}

    installing_map = _get_installing_map_from_progress()
    installing_keys = set()
    for vkey in installing_map.keys():
        if "/" in vkey:
            cat, folder = vkey.split("/", 1)
        else:
            cat, folder = "Unknown", vkey
        installing_keys.add(_version_identity_key(cat, folder))

    def allowed_remote(entry):
        key_str = _version_identity_key(entry.get("category"), entry.get("folder"))
        return key_str not in installed_set and key_str not in installing_keys

    installed_out = []
    remote_out = []

    if not category or category == "* All":
        installed_out = local_versions
        remote_out = [m for m in remote_list if allowed_remote(m)]
    else:
        installed_out = [lv for lv in local_versions if lv["category"] == category]
        remote_out = [m for m in remote_list if m["category"] == category and allowed_remote(m)]

    return {
        "installed": installed_out,
        "available": remote_out,
    }


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
        settings_dict = load_global_settings()
        show_third_party = _is_enabled_setting(settings_dict.get("show_third_party_versions", "0"))

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


def api_launch(data):
    category = data.get("category")
    folder = data.get("folder")
    username = data.get("username")
    loader = data.get("loader")  # Optional loader type: "fabric", "forge", etc.
    loader_version = data.get("loader_version")  # Optional specific loader version

    if not category or not folder:
        return {"ok": False, "message": "Missing category or folder"}
    
    # Validate input strings
    if not _validate_category_string(category):
        return {"ok": False, "message": "Invalid category format"}
    
    if not _validate_version_string(folder):
        return {"ok": False, "message": "Invalid folder format"}
    
    if username and len(str(username)) > MAX_USERNAME_LENGTH:
        return {"ok": False, "message": "Username is too long"}
    
    if loader and not _validate_loader_type(loader):
        return {"ok": False, "message": "Invalid loader type"}
    
    if loader_version and not _validate_version_string(loader_version, MAX_LOADER_VERSION_LENGTH):
        return {"ok": False, "message": "Invalid loader version format"}

    clients_dir = get_clients_dir()

    storage_cat = category.lower()
    version_dir = os.path.join(clients_dir, storage_cat, folder)
    jar_path = os.path.join(version_dir, "client.jar")

    if not os.path.exists(jar_path):
        return {"ok": False, "message": "Client not installed. Please download it from Versions first."}

    # If a loader was requested, make sure installed mods are compatible with
    # the loader version.  This prevents users from launching the game only to
    # have Fabric log a mixin failure seconds later (e.g. due to a newer mod
    # downloaded from CurseForge).
    if loader:
        from core.java_launcher import (
            check_mod_loader_compatibility,
            _get_loader_version,
            _legacy_forge_requires_modloader,
            _has_modloader_runtime,
        )
        current_loader = _get_loader_version(version_dir, loader)

        if not current_loader:
            return {
                "ok": False,
                "message": (
                    f"{loader.capitalize()} is not installed for {folder}. "
                    "Install the loader first from Versions -> Modloaders."
                ),
            }

        if loader.lower() == "forge":
            if _legacy_forge_requires_modloader(version_dir, current_loader) and not _has_modloader_runtime(version_dir):
                return {
                    "ok": False,
                    "message": (
                        f"Forge {current_loader} for Minecraft {folder} is a ModLoader-era build. "
                        "It requires ModLoader runtime classes (BaseMod/ModLoader), which are not present in this client. "
                        "Place a matching modloader jar in this version folder (for example: modloader-<mc>.jar), then relaunch Forge."
                    ),
                }

        issues = check_mod_loader_compatibility(version_dir, loader)
        if issues:
            # build a human‑readable message with one line per problematic mod
            lines = []
            for mod_id, jar_name, req in issues:
                lines.append(f"{mod_id} ({jar_name}) requires loader {req} (current {current_loader})")
            return {"ok": False, "message": "Mod compatibility issue:\n" + "\n".join(lines)}

    version_identifier = f"{category}/{folder}"
    process_id = launch_version(version_identifier, username_override=username, loader=loader, loader_version=loader_version)

    if process_id:
        set_game_presence(
            version_identifier,
            start_time=time.time(),
            phase="Launching",
            loader_type=loader,
            loader_version=loader_version,
        )
        return {
            "ok": True,
            "process_id": process_id,
            "message": f"Launching {folder} as {username}"
        }
    else:
        set_launcher_presence()
        launch_error = consume_last_launch_error(version_identifier)
        return {
            "ok": False,
            "message": launch_error or f"Failed to launch {folder}"
        }


def api_launch_status(process_id):
    from core.java_launcher import _get_process_status
    
    if not process_id:
        set_launcher_presence()
        return {"ok": False, "error": "Invalid process ID"}
    
    status_info = _get_process_status(process_id)
    
    if status_info is None:
        set_launcher_presence()
        return {
            "ok": False,
            "error": "Process not found",
            "status": "unknown"
        }
    
    if status_info["status"] == "running":
        return {
            "ok": True,
            "status": "running",
            "elapsed": status_info.get("elapsed", 0)
        }
    else:
        exit_code = status_info.get("exit_code", -1)
        version_id = status_info.get("version", "")
        category = version_id.split("/", 1)[0].lower() if "/" in version_id else version_id.lower()

        is_crash = not _is_non_crash_exit(version_id, exit_code)
        
        log_path = status_info.get("log_path")
        
        print(colorize_log(f"[api_launch_status] exit_code={exit_code}, category={category}, is_crash={is_crash}, log_path={log_path}"))
        set_launcher_presence()
        
        return {
            "ok": not is_crash,
            "status": "crashed" if is_crash else "exited",
            "exit_code": exit_code,
            "log_path": log_path
        }


def api_game_window_visible(process_id):
    from core.java_launcher import _get_game_window_visible
    
    if not process_id:
        set_launcher_presence()
        return {"ok": False, "error": "Invalid process ID"}

    result = _get_game_window_visible(process_id)

    if result.get("ok"):
        set_game_presence(
            result.get("version"),
            start_time=result.get("start_time"),
            phase="Playing" if result.get("visible") else "Launching",
        )
    else:
        set_launcher_presence()

    return result


def _analyze_crash_log(log_content: str) -> dict:
    import re
    
    class_file_versions = {
        52: "Java 8",
        55: "Java 11",
        56: "Java 12",
        57: "Java 13",
        58: "Java 14",
        59: "Java 15",
        60: "Java 16",
        61: "Java 17",
        62: "Java 18",
        63: "Java 19",
        64: "Java 20",
        65: "Java 21",
        66: "Java 22",
        67: "Java 23",
        68: "Java 24",
        69: "Java 25",
    }
    
    match = re.search(r"UnsupportedClassVersionError:.*?class file version (\d+\.0).*?version of the Java Runtime only recognizes class file versions up to (\d+\.0)", log_content, re.DOTALL)
    if match:
        required_version_str = match.group(1).split('.')[0]
        current_version_str = match.group(2).split('.')[0]
        
        try:
            required_major = int(required_version_str)
            current_major = int(current_version_str)
            
            required_java = class_file_versions.get(required_major, f"Java with class version {required_major}")
            current_java = class_file_versions.get(current_major, f"Java with class version {current_major}")
            
            return {
                "has_error": True,
                "error_type": "JavaVersionMismatch",
                "message": f"Java version mismatch detected!",
                "details": f"You are using an older version of Java! ({current_java}). This version requires {required_java}.",
                "suggestion": f"Please install {required_java} and try launching again."
            }
        except (ValueError, IndexError):
            pass
    
    if "OutOfMemoryError" in log_content:
        return {
            "has_error": True,
            "error_type": "OutOfMemory",
            "message": "Out of Memory Error",
            "details": "The game ran out of allocated RAM.",
            "suggestion": "Try increasing the maximum RAM allocation in the launcher settings."
        }

    if "Could not reserve enough space for object heap" in log_content:
        return {
            "has_error": True,
            "error_type": "HeapAllocationFailure",
            "message": "Heap Allocation Failure",
            "details": "The Java Virtual Machine could not reserve enough memory for the heap.",
            "suggestion": "Try reducing the maximum RAM allocation in the launcher settings or closing other applications to free up memory."
        }
    
    if "ModNotFoundException" in log_content or "net.minecraftforge.fml.ModLoadingException" in log_content:
        return {
            "has_error": True,
            "error_type": "ModError",
            "message": "Mod Loading Error",
            "details": "A required mod could not be found or loaded.",
            "suggestion": "Check that all required mods are installed correctly."
        }
    
    if re.search(r"(missing texture|Unable to load resource)", log_content, re.IGNORECASE):
        return {
            "has_error": True,
            "error_type": "ResourceError",
            "message": "Missing Resource",
            "details": "The game encountered missing textures or resources.",
            "suggestion": "Try verifying game files or reinstalling the version."
        }
    
    return {
        "has_error": False,
        "error_type": None,
        "message": None,
        "details": None,
        "suggestion": None
    }


def api_crash_log(data: Any):
    if not isinstance(data, dict):
        return {"ok": False, "error": "Invalid request", "content": ""}
    
    log_path = (data.get("log_path") or "").strip()
    
    if not log_path:
        return {"ok": False, "error": "Missing log_path", "content": ""}
    
    try:
        if not os.path.isfile(log_path):
            return {
                "ok": False,
                "error": f"Log file not found: {log_path}",
                "content": ""
            }
        
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        
        error_analysis = _analyze_crash_log(content)
        
        if len(content) > 102400:
            content = "... (content truncated) ...\n" + content[-102400:]
        
        return {
            "ok": True,
            "filename": os.path.basename(log_path),
            "filepath": log_path,
            "content": content,
            "error_analysis": error_analysis
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"Could not read log file: {str(e)}",
            "content": ""
        }


def api_open_crash_log(data: Any):
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid request"}
    
    log_path = (data.get("log_path") or "").strip()
    
    if not log_path:
        return {"ok": False, "error": "missing log_path"}
    
    if not os.path.exists(log_path):
        return {"ok": False, "error": f"Log file not found: {log_path}"}
    
    try:
        import platform
        import subprocess
        
        print(colorize_log(f"[api_open_crash_log] Opening file: {log_path}"))
        print(colorize_log(f"[api_open_crash_log] File exists: {os.path.isfile(log_path)}"))
        if os.path.isfile(log_path):
            file_size = os.path.getsize(log_path)
            print(colorize_log(f"[api_open_crash_log] File size: {file_size} bytes"))
        
        system = platform.system()
        
        if system == "Windows":
            os.startfile(log_path)
        elif system == "Darwin":
            subprocess.run(["open", log_path])
        else:
            subprocess.run(["xdg-open", log_path])
        
        return {
            "ok": True,
            "message": f"Opening {os.path.basename(log_path)}..."
        }
    
    except Exception as e:
        print(colorize_log(f"[api] Error opening crash log: {e}"))
        return {"ok": False, "error": f"Failed to open log file: {str(e)}"}


def api_clear_logs():
    try:
        base_dir = get_base_dir()
        logs_dir = os.path.join(base_dir, "logs")
        
        if not os.path.exists(logs_dir):
            return {"ok": True, "message": "No logs directory found"}
        
        skipped_files = []
        deleted_count = 0
        
        for root, dirs, files in os.walk(logs_dir, topdown=False):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except (OSError, PermissionError) as e:
                    skipped_files.append(os.path.basename(file_path))
                    print(colorize_log(f"[api_clear_logs] Skipped (in use): {file_path}"))
            
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                try:
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                except (OSError, PermissionError):
                    pass
        
        # Try to remove the main logs directory if empty
        try:
            if os.path.exists(logs_dir) and not os.listdir(logs_dir):
                os.rmdir(logs_dir)
        except (OSError, PermissionError):
            pass
        
        print(colorize_log(f"[api_clear_logs] Cleared logs: {deleted_count} files deleted, {len(skipped_files)} files skipped"))
        
        message = f"Deleted {deleted_count} log files."
        if skipped_files:
            message += f" {len(skipped_files)} active log file(s) are still in use and will be cleared next time."
        
        return {
            "ok": True,
            "message": message,
            "deleted": deleted_count,
            "skipped": len(skipped_files)
        }
    except Exception as e:
        print(colorize_log(f"[api_clear_logs] Error clearing logs: {e}"))
        return {"ok": False, "error": f"Failed to clear logs: {str(e)}"}


def api_settings(data):
    if not isinstance(data, dict):
        data = {}

    current = load_global_settings()
    prev_type = (current.get("account_type") or "Local").strip()

    current.update(data)
    save_global_settings(current)

    new_type = (current.get("account_type") or "Local").strip()
    if prev_type.lower() != new_type.lower() and new_type.lower() == "local":
        try:
            clear_account_token()
        except Exception:
            pass

    if current.get("account_type") == "Histolauncher":
        username = data.get('username') or current.get('username') or '(from session token)'
        uuid = data.get('uuid') or current.get('uuid') or '(from session token)'
        print(colorize_log(f"[api_settings] Histolauncher account configured: username={username}, uuid={uuid}"))

    return {"ok": True, "message": "Settings saved.", "settings": current}


def _verify_and_store_session_token(session_token: str):
    from .auth import get_user_info
    from core.settings import save_account_token

    session_value = str(session_token or "").strip()
    if not session_value:
        return {"ok": False, "error": "missing sessionToken"}

    success, user_data, error = get_user_info(session_value)
    if not success:
        return {"ok": False, "error": error or "Failed to verify session"}

    save_account_token(session_value)

    try:
        s = load_global_settings() or {}
        s["account_type"] = "Histolauncher"
        s.pop("uuid", None)
        s.pop("username", None)
        save_global_settings(s)
    except Exception as e:
        return {"ok": False, "error": f"Failed to save settings: {str(e)}"}

    username = user_data.get("username", "")
    account_uuid = user_data.get("uuid", "")
    print(colorize_log(f"[api_account_verify_session] Account verified: username={username}, uuid={account_uuid}"))

    return {
        "ok": True,
        "message": "Session verified and stored",
        "username": username,
        "uuid": account_uuid,
    }


def api_account_login(data):
    """Proxy-aware backend login endpoint for Histolauncher accounts."""
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid request"}

        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "").strip()
        if not username or not password:
            return {"ok": False, "error": "missing username or password"}

        from .auth import login_with_session

        success, session_token, error = login_with_session(username, password)
        if not success or not session_token:
            return {"ok": False, "error": error or "Invalid credentials"}

        return _verify_and_store_session_token(session_token)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_account_verify_session(data):
    """Verify and store a Cloudflare session token from the frontend.
    
    This is needed for pywebview because the browser/webview doesn't automatically
    manage cookies from cross-origin requests. The frontend logs in at Cloudflare,
    receives a session token in the response, and sends it here to the Python backend.
    The backend stores it and can use it to verify the account with Cloudflare.
    
    SECURITY: We only store the session token, NOT the UUID/username in settings.ini.
    The frontend should call /api/account/current to get verified account info.
    """
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid request"}
        return _verify_and_store_session_token(data.get("sessionToken", ""))
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


def api_account_current():
    try:
        settings = load_global_settings() or {}
        if str(settings.get("account_type") or "Local").strip().lower() != "histolauncher":
            return {
                "ok": False,
                "error": "Histolauncher account not enabled",
                "authenticated": False,
                "unauthorized": False,
                "local_account": True,
            }

        from .auth import get_verified_account
        
        success, user_data, error = get_verified_account()
        if not success:
            err_msg = (error or "").lower()
            unauthorized = False
            if "not logged in" in err_msg or "session expired" in err_msg:
                unauthorized = True
            return {
                "ok": False,
                "error": error or "Not authenticated",
                "authenticated": False,
                "unauthorized": unauthorized
            }
        
        return {
            "ok": True,
            "authenticated": True,
            "uuid": user_data.get("uuid", ""),
            "username": user_data.get("username", "")
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "authenticated": False,
            "network_error": True
        }


def _get_histolauncher_settings_proxy_config_script() -> str:
    return """<script>
const IS_DEV = false;
const LOCAL_PROXY_ORIGIN = window.location.origin;
const ACCOUNTS_BASE = `${LOCAL_PROXY_ORIGIN}/histolauncher-proxy/accounts`;
const TEXTURE_BASE = `${LOCAL_PROXY_ORIGIN}/histolauncher-proxy/textures`;

const CONFIG = {
  API: {
    BASE: `${ACCOUNTS_BASE}/api`,
    LOGIN: `${ACCOUNTS_BASE}/api/login`,
    SIGNUP: `${ACCOUNTS_BASE}/api/signup`,
    ADMIN_ME: `${ACCOUNTS_BASE}/api/admin/me`,
    ADMIN_PANEL_CONTENT: `${ACCOUNTS_BASE}/api/admin/panel-content`,
    ADMIN_PANEL_SCRIPT: `${ACCOUNTS_BASE}/api/admin/panel-script`,
    ADMIN_GLOBAL_MESSAGE: `${ACCOUNTS_BASE}/api/admin/global-message`,
    GLOBAL_MESSAGE: `${ACCOUNTS_BASE}/api/global-message`,
    UPLOAD_SKIN: `${ACCOUNTS_BASE}/api/settings/uploadSkin`,
    CAPE_OPTIONS: `${ACCOUNTS_BASE}/api/settings/capes`,
    TEXTURES_BASE: `${TEXTURE_BASE}`
  },
  GITHUB: {
    OWNER: 'KerbalOfficial',
    REPO: 'Histolauncher'
  },
  STORAGE_KEYS: {
    UUID: 'uuid',
    USERNAME: 'username'
  }
};

function getGitHubReleasesUrl(owner = CONFIG.GITHUB.OWNER, repo = CONFIG.GITHUB.REPO) {
  return `https://api.github.com/repos/${owner}/${repo}/releases`;
}
</script>"""


def _get_histolauncher_iframe_navigation_guard_script() -> str:
    return """<script>
(function () {
  const logBlocked = (reason, target) => {
    try {
      console.warn('[Histolauncher iframe] Blocked navigation:', reason, target || '');
    } catch (_) {}
  };

  try {
    window.open = function (targetUrl) {
      logBlocked('window.open', targetUrl);
      return null;
    };
  } catch (_) {}

  try {
    if (window.history) {
      window.history.pushState = function () {
        logBlocked('history.pushState', '');
      };
      window.history.replaceState = function () {
        logBlocked('history.replaceState', '');
      };
    }
  } catch (_) {}

  document.addEventListener('click', function (event) {
    const link = event.target && event.target.closest ? event.target.closest('a[href]') : null;
    if (!link) return;

    const href = link.getAttribute('href') || '';
    if (!href || href.startsWith('#')) return;

    event.preventDefault();
    event.stopPropagation();
    logBlocked('link-click', href);
  }, true);

  document.addEventListener('submit', function (event) {
    event.preventDefault();
    event.stopPropagation();
    const action = event.target && event.target.getAttribute ? (event.target.getAttribute('action') || '') : '';
    logBlocked('form-submit', action);
  }, true);
})();
</script>"""


def _fetch_histolauncher_text(url: str, *, include_auth_cookie: bool = False, timeout_seconds: float = 15.0) -> str:
    from .auth import load_histolauncher_cookie_header

    candidate_urls = []
    proxied = _apply_url_proxy(url)
    if proxied:
        candidate_urls.append(proxied)
    if url not in candidate_urls:
        candidate_urls.append(url)

    last_error = "Failed to load remote resource"
    for candidate in candidate_urls:
        try:
            headers = {"User-Agent": "Histolauncher/1.0"}
            if include_auth_cookie:
                cookie_header = load_histolauncher_cookie_header()
                if cookie_header:
                    headers["Cookie"] = cookie_header

            req = urllib.request.Request(candidate, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", errors="replace").strip()
            except Exception:
                detail = ""
            last_error = detail or f"Remote request failed ({e.code})"
        except Exception as e:
            last_error = str(e)

    raise RuntimeError(last_error)


def _patch_histolauncher_loader_script(script_path: str, script_body: str) -> str:
    patched = str(script_body or "")

    if script_path.endswith("/loaders/topbar.js"):
        patched = re.sub(
            r"const topbarDisabled = .*?;",
            "const topbarDisabled = true;",
            patched,
            count=1,
        )
        patched = re.sub(
            r"const globalMessageDisabled = .*?;",
            "const globalMessageDisabled = true;",
            patched,
            count=1,
        )

    # Prevent the embedded settings page from navigating away from the iframe.
    patched = re.sub(
        r"(?:window\.)?location\.href\s*=\s*(['\"]).*?\1\s*;",
        "console.warn('[Histolauncher iframe] Blocked redirect via location.href');",
        patched,
        flags=re.IGNORECASE,
    )
    patched = re.sub(
        r"(?:window\.)?location\.(?:assign|replace)\s*\([^)]*\)\s*;",
        "console.warn('[Histolauncher iframe] Blocked redirect via location method');",
        patched,
        flags=re.IGNORECASE,
    )

    if script_path.endswith("/loaders/settings.js"):
        patched = patched.replace(
            'document.body.innerHTML = "<main><p>Please <a href=\'/login\'>log in</a> first</p></main>";',
            'document.body.innerHTML = "<main><p>Please log in first.</p></main>";'
        )

    return patched.replace("</script>", "<\\/script>")


def _inline_histolauncher_loader_script(html: str, script_path: str, script_body: str) -> str:
    inline_script = f"<script>\n{script_body}\n</script>"
    pattern = rf"<script[^>]+src=[\"']{re.escape(script_path)}[\"'][^>]*></script>"
    return re.sub(pattern, lambda _: inline_script, html, count=1, flags=re.IGNORECASE)


def _transform_histolauncher_settings_html(raw_html: str) -> str:
    html = str(raw_html or "")
    config_script = _get_histolauncher_settings_proxy_config_script()
    navigation_guard_script = _get_histolauncher_iframe_navigation_guard_script()

    config_pattern = r"<script[^>]+src=[\"']/loaders/config\.js[\"'][^>]*>\s*</script>"
    html = re.sub(config_pattern, "", html, flags=re.IGNORECASE)
    html = html.replace("</head>", f"{config_script}\n</head>", 1)

    if "Blocked navigation" not in html:
        html = html.replace("</head>", f"{navigation_guard_script}\n</head>", 1)

    if "<base " not in html.lower():
        html = re.sub(
            r"<head([^>]*)>",
            '<head\\1>\n<base href="https://histolauncher.org/">',
            html,
            count=1,
            flags=re.IGNORECASE,
        )

    html = re.sub(
        r"<script[^>]*>[^<]*__CF\\$cv\\$params.*?</script>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html = re.sub(
        r"<script[^>]+src=[\"'][^\"']*cdn-cgi/challenge-platform[^\"']*[\"'][^>]*></script>",
        "",
        html,
        flags=re.IGNORECASE,
    )
    html = re.sub(
        r"<script[^>]+src=[\"'][^\"']*static\\.cloudflareinsights\\.com[^\"']*[\"'][^>]*></script>",
        "",
        html,
        flags=re.IGNORECASE,
    )

    for script_path in ("/loaders/auth.js", "/loaders/topbar.js", "/loaders/settings.js"):
        remote_script = _fetch_histolauncher_text(
            f"https://histolauncher.org{script_path}",
            include_auth_cookie=False,
            timeout_seconds=15.0,
        )
        html = _inline_histolauncher_loader_script(
            html,
            script_path,
            _patch_histolauncher_loader_script(script_path, remote_script),
        )

    return html


def api_account_settings_iframe():
    from .auth import load_histolauncher_cookie_header

    cookie_header = load_histolauncher_cookie_header()
    if not cookie_header:
        return {"ok": False, "error": "Not authenticated"}

    base_url = "https://histolauncher.org/settings?disable-topbar=1&disable-global-message=1"
    candidate_urls = []
    proxied = _apply_url_proxy(base_url)
    if proxied:
        candidate_urls.append(proxied)
    if base_url not in candidate_urls:
        candidate_urls.append(base_url)

    last_error = "Failed to load account settings"
    for url in candidate_urls:
        try:
            payload = _fetch_histolauncher_text(
                url,
                include_auth_cookie=True,
                timeout_seconds=15.0,
            )
            return {
                "ok": True,
                "html": _transform_histolauncher_settings_html(payload),
            }
        except Exception as e:
            last_error = str(e)

    return {"ok": False, "error": last_error}


def api_account_launcher_message():
    try:
        from .auth import get_launcher_message

        success, payload, error = get_launcher_message()
        if not success:
            return {
                "ok": False,
                "active": False,
                "error": error or "Failed to load launcher message",
            }

        if not isinstance(payload, dict):
            return {"ok": False, "active": False, "error": "Invalid launcher message response"}

        active = bool(payload.get("active"))
        message = str(payload.get("message") or "")
        msg_type = str(payload.get("type") or "message").strip().lower()
        if msg_type not in {"message", "warning", "important"}:
            msg_type = "message"

        return {
            "ok": True,
            "active": active,
            "message": message,
            "type": msg_type,
            "updatedAt": payload.get("updatedAt"),
            "updatedBy": payload.get("updatedBy"),
        }
    except Exception as e:
        return {"ok": False, "active": False, "error": str(e)}


def api_account_status():
    try:
        s = load_global_settings() or {}
        account_type = s.get("account_type", "Local")
        is_connected = account_type == "Histolauncher"
        return {"ok": True, "connected": is_connected}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_account_disconnect():
    try:
        s = load_global_settings() or {}
        s["account_type"] = "Local"
        save_global_settings(s)
        return {"ok": True, "message": "Account disconnected."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_install(data):
    if not isinstance(data, dict):
        return {"error": "invalid request"}

    version_id = data.get("version") or data.get("folder")
    category = data.get("category")
    full_assets = bool(data.get("full_assets", False))

    if not version_id or not category:
        return {"error": "missing version or category"}
    
    # Validate input strings
    if not _validate_version_string(version_id):
        return {"error": "invalid version format"}
    
    if not _validate_category_string(category):
        return {"error": "invalid category format"}

    storage_type = category.lower()
    settings_dict = load_global_settings() or {}
    show_third_party = _is_enabled_setting(settings_dict.get("show_third_party_versions", "0"))

    core_downloader.install_version(
        version_id,
        storage_category=storage_type,
        full_assets=full_assets,
        background=True,
        include_third_party=show_third_party,
    )

    version_key = f"{storage_type}/{version_id}"
    _rpc_install_started_at[version_key] = time.time()
    set_install_presence(f"{category}/{version_id}", start_time=_rpc_install_started_at[version_key])
    return {"started": True, "version": version_key}


def api_status(version_key):
    try:
        decoded = urllib.parse.unquote(version_key)
        if "/" not in decoded: return {"status": "unknown"}
        category, version_id = decoded.split("/", 1)
        status = core_downloader.get_install_status(version_id, category)
        if not status:
            if decoded in _rpc_install_started_at:
                _rpc_install_started_at.pop(decoded, None)
                set_launcher_presence()
            return {"status": "unknown"}

        _update_rpc_install_presence(decoded, status)
        return status
    except Exception as e: return {"error": str(e)}




def api_cancel(version_key):
    try:
        decoded = urllib.parse.unquote(version_key)
        if "/" not in decoded:
            return {"ok": False, "error": "invalid key"}

        category, version_id = decoded.split("/", 1)

        core_downloader.cancel_install(version_id, category)
        _rpc_install_started_at.pop(decoded, None)
        set_launcher_presence()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_pause(version_key):
    try:
        decoded = urllib.parse.unquote(version_key)
        if "/" not in decoded:
            return {"ok": False, "error": "invalid key"}

        category, version_id = decoded.split("/", 1)
        core_downloader.pause_install(version_id, category)
        prog = core_downloader.get_install_status(version_id, category) or {"status": "paused"}
        _update_rpc_install_presence(decoded, prog)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_resume(version_key):
    try:
        decoded = urllib.parse.unquote(version_key)
        if "/" not in decoded:
            return {"ok": False, "error": "invalid key"}

        category, version_id = decoded.split("/", 1)
        core_downloader.resume_install(version_id, category)
        prog = core_downloader.get_install_status(version_id, category) or {"status": "downloading"}
        _update_rpc_install_presence(decoded, prog)
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
                import subprocess
                subprocess.Popen(["open", base])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", base])

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
    
    # Validate input strings
    if not _validate_category_string(category):
        return {"ok": False, "error": "invalid category format"}
    
    if not _validate_version_string(folder):
        return {"ok": False, "error": "invalid folder format"}

    clients_dir = get_clients_dir()
    version_dir = os.path.join(clients_dir, category.lower(), folder)
    
    # Security: Verify that the resolved path is within clients_dir (prevent path traversal)
    try:
        real_version_dir = os.path.realpath(version_dir)
        real_clients_dir = os.path.realpath(clients_dir)
        if not real_version_dir.startswith(real_clients_dir):
            return {"ok": False, "error": "invalid version path"}
    except (OSError, ValueError):
        return {"ok": False, "error": "invalid version path"}

    if not os.path.isdir(version_dir):
        return {"ok": False, "error": "version directory does not exist"}

    try:
        shutil.rmtree(version_dir)
        version_key = f"{category.lower()}/{folder}"
        core_downloader.delete_progress(version_key)
        scan_categories(force_refresh=True)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_loaders(version_key: str):
    """
    GET /api/loaders/{category}/{folder}
    Returns available and installed loaders for a version.
    """
    if not version_key or "/" not in version_key:
        return {"ok": False, "error": "invalid version key"}
    
    parts = version_key.split("/", 1)
    category_input, folder = parts[0], parts[1]
    
    # Force cache refresh to get latest loader data
    categories_data = scan_categories(force_refresh=True)
    
    # Find the actual category name (case-insensitive match)
    category = None
    for cat_name in categories_data.keys():
        if cat_name.lower() == category_input.lower():
            category = cat_name
            break
    
    if not category:
        return {"ok": False, "error": f"category not found: {category_input}"}
    
    # Get installed loaders
    installed = get_version_loaders(category, folder)
    
    # Calculate sizes for installed loaders
    loaders_base = os.path.join(get_clients_dir(), category, folder, "loaders")
    
    for loader_type in installed:
        for loader in installed[loader_type]:
            loader_path = os.path.join(loaders_base, loader_type, loader["version"])
            total_size = 0
            if os.path.isdir(loader_path):
                # walk the entire directory tree instead of only top level
                for root, dirs, files in os.walk(loader_path):
                    for fname in files:
                        try:
                            total_size += os.path.getsize(os.path.join(root, fname))
                        except Exception:
                            pass
            loader["size"] = total_size
            loader["size_display"] = _format_bytes(total_size)
    
    # Get available loaders from APIs
    fabric_loaders = core_modloaders.get_fabric_loaders_for_version(folder, stable_only=False)
    forge_versions = core_modloaders.get_forge_versions_for_mc(folder)
    if folder in FORGE_INSTALL_BLOCKED_VERSIONS:
        forge_versions = []
    
    return {
        "ok": True,
        "version_key": version_key,
        "installed": installed,
        "available": {
            "fabric": [{"version": loader.get("version"), "stable": loader.get("stable", False)} for loader in fabric_loaders],
            "forge": [{"version": fv.get("forge_version")} for fv in forge_versions],
        },
        "total_available": {
            "fabric": len(fabric_loaders),
            "forge": len(forge_versions)
        }
    }


def api_install_loader(data: Any):
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid request"}
    
    category = (data.get("category") or "").strip()
    folder = (data.get("folder") or "").strip()
    loader_type = (data.get("loader_type") or "").lower().strip()
    loader_version = (data.get("loader_version") or "").strip()
    
    if not all([category, folder, loader_type, loader_version]):
        return {"ok": False, "error": "missing required fields"}
    
    # Validate input strings
    if not _validate_category_string(category):
        return {"ok": False, "error": "invalid category format"}
    
    if not _validate_version_string(folder):
        return {"ok": False, "error": "invalid folder format"}
    
    if not _validate_loader_type(loader_type):
        return {"ok": False, "error": "invalid loader type"}
    
    if not _validate_version_string(loader_version, MAX_LOADER_VERSION_LENGTH):
        return {"ok": False, "error": "invalid loader version format"}

    if loader_type == "forge" and folder in FORGE_INSTALL_BLOCKED_VERSIONS:
        return {
            "ok": False,
            "error": (
                f"Forge installation is disabled for Minecraft {folder}. "
                "These legacy Forge builds are ModLoader addons and are not supported by automatic Forge installation."
            ),
        }
    
    # Create a unique install key for progress tracking
    # Format: {category}/{folder}/modloader-{loader_type}-{loader_version}
    install_key = f"{category.lower()}/{folder}/modloader-{loader_type}-{loader_version}"
    _rpc_install_started_at[install_key] = time.time()
    set_install_presence(
        f"{category}/{folder}",
        start_time=_rpc_install_started_at[install_key],
        loader_type=loader_type,
        loader_version=loader_version,
    )
    
    # Start async installation (same pattern as install_version)
    import threading
    
    def install_loader_background():
        try:
            result = core_downloader.download_loader(
                loader_type=loader_type,
                mc_version=folder,
                loader_version=loader_version,
                category=category,
                folder=folder,
            )
            
            if result.get("ok"):
                # Refresh version cache to include the newly installed loader
                scan_categories(force_refresh=True)
                
                # Send notification
                try:
                    from core.libraries.plyer import notification
                    loader_name = "Fabric" if loader_type == "fabric" else "Forge"
                    notification.notify(
                        title=f"[{loader_name} {loader_version}] Mod Loader Installation complete!",
                        message=f"{loader_name} {loader_version} for {category} {folder} has installed successfully!",
                        app_icon=os.path.join(
                            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "ui",
                            "assets",
                            "images",
                            "histolauncher_256x256.ico",
                        ),
                    )
                except Exception as e:
                    print(colorize_log(f"[api] Could not send notification: {e}"))
                
                print(colorize_log(f"[api] {loader_type.capitalize()} {loader_version} installed successfully for {install_key}"))
            else:
                error_msg = result.get("error", "Unknown error")
                print(colorize_log(f"[api] Failed to install {loader_type} loader: {error_msg}"))
        except Exception as e:
            print(colorize_log(f"[api] Exception during loader installation: {e}"))
    
    # Start the installation in a background thread
    thread = threading.Thread(target=install_loader_background, daemon=True)
    thread.start()
    
    # Return immediately with the install key for progress tracking
    return {
        "ok": True,
        "install_key": install_key,
        "loader_type": loader_type,
        "loader_version": loader_version,
        "message": f"Installing {loader_type.capitalize()} {loader_version}..."
    }


def api_delete_loader(data: Any):
    """
    DELETE /api/delete-loader
    Deletes a mod loader for a version.
    
    Request body:
    {
        "category": "Release",
        "folder": "1.20.2",
        "loader_type": "fabric" or "forge",
        "loader_version": "0.14.22" (fabric) or "49.0.0" (forge)
    }
    """
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid request"}
    
    category = (data.get("category") or "").strip()
    folder = (data.get("folder") or "").strip()
    loader_type = (data.get("loader_type") or "").lower().strip()
    loader_version = (data.get("loader_version") or "").strip()
    
    if not all([category, folder, loader_type, loader_version]):
        return {"ok": False, "error": "missing required fields"}
    
    # Validate input strings
    if not _validate_category_string(category):
        return {"ok": False, "error": "invalid category format"}
    
    if not _validate_version_string(folder):
        return {"ok": False, "error": "invalid folder format"}
    
    if not _validate_loader_type(loader_type):
        return {"ok": False, "error": "invalid loader type"}
    
    if not _validate_version_string(loader_version, MAX_LOADER_VERSION_LENGTH):
        return {"ok": False, "error": "invalid loader version format"}
    
    try:
        # Get the loader directory path
        loader_path = os.path.join(get_clients_dir(), category, folder, "loaders", loader_type, loader_version)
        
        if not os.path.isdir(loader_path):
            return {"ok": False, "error": f"Loader directory not found: {loader_path}"}
        
        # Delete the loader directory
        shutil.rmtree(loader_path)
        print(colorize_log(f"[api] Deleted {loader_type} loader {loader_version} for {category}/{folder}"))
        
        # Refresh cache to reflect the deletion
        scan_categories(force_refresh=True)
        
        return {
            "ok": True,
            "loader_type": loader_type,
            "loader_version": loader_version,
            "message": f"{loader_type.capitalize()} {loader_version} deleted successfully"
        }
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": f"Failed to delete loader: {str(e)}"}


def api_corrupted_versions():
    global _corrupted_versions_checked
    
    # If already checked in this session, return empty list
    if _corrupted_versions_checked:
        return {"ok": True, "corrupted": []}
    
    try:
        corrupted = []
        
        clients_dir = get_clients_dir()
        
        if not os.path.isdir(clients_dir):
            _corrupted_versions_checked = True
            return {"ok": True, "corrupted": []}
        
        for category_name in os.listdir(clients_dir):
            category_path = os.path.join(clients_dir, category_name)
            if not os.path.isdir(category_path):
                continue
            
            for version_folder in os.listdir(category_path):
                version_path = os.path.join(category_path, version_folder)
                if not os.path.isdir(version_path):
                    continue
                
                data_ini_path = os.path.join(version_path, "data.ini")
                if not os.path.exists(data_ini_path):
                    corrupted.append({
                        "category": category_name,
                        "folder": version_folder,
                        "display": version_folder,
                        "full_path": version_path
                    })
        
        _corrupted_versions_checked = True
        return {"ok": True, "corrupted": corrupted}
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        _corrupted_versions_checked = True
        return {"ok": False, "error": str(e), "corrupted": []}


def api_delete_corrupted_versions(data):
    """
    Delete multiple corrupted versions at once.
    
    Request body:
    {
        "versions": [
            {"category": "Release", "folder": "1.20.2"},
            ...
        ]
    }
    """
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid request"}
    
    versions_to_delete = data.get("versions", [])
    if not isinstance(versions_to_delete, list):
        return {"ok": False, "error": "versions must be an array"}
    
    clients_dir = get_clients_dir()
    deleted = []
    failed = []
    
    try:
        for v in versions_to_delete:
            if not isinstance(v, dict):
                failed.append({"error": "invalid item", "item": v})
                continue
            
            category = (v.get("category") or "").strip()
            folder = (v.get("folder") or "").strip()
            
            if not category or not folder:
                failed.append({"error": "missing category or folder", "item": v})
                continue
            
            version_path = os.path.join(clients_dir, category, folder)
            
            # Security: verify path is within clients_dir
            try:
                real_version_path = os.path.realpath(version_path)
                real_clients_dir = os.path.realpath(clients_dir)
                if not real_version_path.startswith(real_clients_dir):
                    failed.append({"error": "invalid path", "category": category, "folder": folder})
                    continue
            except (OSError, ValueError):
                failed.append({"error": "invalid path", "category": category, "folder": folder})
                continue
            
            if not os.path.isdir(version_path):
                failed.append({"error": "directory not found", "category": category, "folder": folder})
                continue
            
            try:
                shutil.rmtree(version_path)
                deleted.append({"category": category, "folder": folder})
                print(colorize_log(f"[api] Deleted corrupted version: {category}/{folder}"))
            except Exception as e:
                failed.append({"error": str(e), "category": category, "folder": folder})
        
        # Refresh version cache
        try:
            scan_categories(force_refresh=True)
        except Exception:
            pass
        
        return {
            "ok": True,
            "deleted": deleted,
            "failed": failed
        }
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


def api_export_versions(data):
    """
    Export a single selected version as a ZIP file (.hlvdf format).
    
    Request body:
    {
        "category": "Release",
        "folder": "1.20.2",
        "export_options": {
            "include_loaders": true,
            "include_assets": true,
            "include_logs": false,
            "include_config": false,
            "compression": "standard"
        }
    }
    
    Returns: Path to the saved .hlvdf file and opens file explorer
    """
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid request"}
        
        category = (data.get("category") or "").strip()
        folder = (data.get("folder") or "").strip()
        
        if not category or not folder:
            return {"ok": False, "error": "missing category or folder"}
        
        # Validate strings
        if not _validate_category_string(category):
            return {"ok": False, "error": "invalid category format"}
        
        if not _validate_version_string(folder):
            return {"ok": False, "error": "invalid folder format"}
        
        # Import required modules
        import io
        import zipfile
        import tempfile
        
        # Parse export options
        export_options = data.get("export_options", {})
        include_loaders = export_options.get("include_loaders", True)
        include_assets = export_options.get("include_assets", True)
        include_config = export_options.get("include_config", False)
        compression = export_options.get("compression", "standard")
        
        # Validate compression level
        if compression not in ["quick", "standard", "full"]:
            compression = "standard"
        
        # Map compression to zipfile compression level
        if compression == "quick":
            compress_type = zipfile.ZIP_STORED
        elif compression == "full":
            compress_type = zipfile.ZIP_DEFLATED
        else:
            compress_type = zipfile.ZIP_DEFLATED
        
        print(colorize_log(f"[api] Starting export of {category}/{folder}..."))
        print(colorize_log(f"[api] Export options: loaders={include_loaders}, assets={include_assets}, config={include_config}, compression={compression}"))
        
        clients_dir = get_clients_dir()
        version_path = os.path.join(clients_dir, category, folder)
        
        # Security: verify path is within clients_dir
        try:
            real_version_path = os.path.realpath(version_path)
            real_clients_dir = os.path.realpath(clients_dir)
            if not real_version_path.startswith(real_clients_dir):
                return {"ok": False, "error": "invalid version path"}
        except (OSError, ValueError):
            return {"ok": False, "error": "invalid version path"}
        
        if not os.path.isdir(version_path):
            return {"ok": False, "error": "version not found"}
        
        temp_dir = tempfile.gettempdir()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".hlvdf", prefix=f"{folder}_", dir=temp_dir) as tmp_file:
            temp_path = tmp_file.name
        
        try:
            print(colorize_log(f"[api] Scanning files in {version_path}..."))
            file_count = 0
            
            with zipfile.ZipFile(temp_path, 'w', compress_type) as zipf:
                # Helper function to check if a path should be excluded
                def should_skip_file(relative_path, base_root):
                    # Skip mod loaders if not included
                    if not include_loaders:
                        if 'fabric-' in relative_path or 'forge-' in relative_path:
                            return True
                    # Always skip logs folder
                    if relative_path.startswith('logs') or relative_path.startswith('crash-reports'):
                        return True
                    # Skip config/saves unless explicitly included
                    if not include_config:
                        if relative_path.startswith('config') or relative_path.startswith('saves'):
                            return True
                    return False
                
                # First, add all files from the version directory
                for root, dirs, files in os.walk(version_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, version_path)
                        
                        # Check if file should be skipped
                        if should_skip_file(arcname, version_path):
                            continue
                        
                        if arcname == "data.ini":
                            existing_data = {}
                            try:
                                with open(file_path, "r", encoding="utf-8") as f:
                                    for line in f:
                                        line = line.strip()
                                        if "=" in line and not line.startswith("#"):
                                            k, v = line.split("=", 1)
                                            existing_data[k.strip()] = v.strip()
                            except Exception:
                                pass
                            
                            # Ensure metadata fields exist
                            if "md_version" not in existing_data:
                                existing_data["md_version"] = CURRENT_MD_VERSION
                            if "category" not in existing_data:
                                existing_data["category"] = category
                            
                            modified_data = "\n".join(f"{k}={v}" for k, v in existing_data.items()) + "\n"
                            zipf.writestr(arcname, modified_data)
                            
                            file_size_kb = len(modified_data) / 1024
                            print(colorize_log(f"[api]   Adding: {arcname} ({file_size_kb:.1f} KB)"))
                        else:
                            file_size_kb = os.path.getsize(file_path) / 1024
                            print(colorize_log(f"[api]   Adding: {arcname} ({file_size_kb:.1f} KB)"))
                            zipf.write(file_path, arcname)
                        
                        file_count += 1
                
                if include_assets:
                    base_dir = get_base_dir()
                    assets_path = os.path.join(base_dir, "assets")
                    if os.path.isdir(assets_path):
                        print(colorize_log(f"[api] Including assets directory..."))
                        for root, dirs, files in os.walk(assets_path):
                            for file in files:
                                file_path = os.path.join(root, file)
                                arcname = os.path.join("assets", os.path.relpath(file_path, assets_path))
                                
                                file_size_kb = os.path.getsize(file_path) / 1024
                                print(colorize_log(f"[api]   Adding: {arcname} ({file_size_kb:.1f} KB)"))
                                zipf.write(file_path, arcname)
                                file_count += 1
            
            zip_size_mb = os.path.getsize(temp_path) / 1024 / 1024
            
            print(colorize_log(f"[api] Successfully created ZIP: {file_count} files, {zip_size_mb:.2f} MB"))
            
            filename = f"{folder}.hlvdf"
            
            print(colorize_log(f"[api] Temporary file saved to {temp_path}..."))
            
            # Use tkinter to open file save dialog
            try:
                from tkinter import Tk
                from tkinter.filedialog import asksaveasfilename
                
                print(colorize_log(f"[api] Opening file save dialog..."))
                
                root = Tk()
                root.withdraw()  # Hide the window
                root.attributes('-topmost', True)  # Bring to front
                
                # Ask user where to save
                initial_name = filename
                default_dir = os.path.expanduser("~")
                
                save_path = asksaveasfilename(
                    initialfile=initial_name,
                    defaultextension=".hlvdf",
                    filetypes=[("Histolauncher Version", "*.hlvdf"), ("All Files", "*.*")],
                    initialdir=default_dir,
                    title=f"Save {category} {folder} Export"
                )
                
                root.destroy()
                
                if save_path:
                    # Copy from temp to user's selected location
                    print(colorize_log(f"[api] Copying file to {save_path}..."))
                    shutil.copy2(temp_path, save_path)
                    
                    # Clean up temp file
                    try:
                        os.remove(temp_path)
                        print(colorize_log(f"[api] Cleaned up temporary file"))
                    except Exception:
                        pass
                    
                    print(colorize_log(f"[api] [OK] Export completed successfully!"))
                    print(colorize_log(f"[api] File saved to: {save_path}"))
                    
                    return {
                        "ok": True,
                        "filename": os.path.basename(save_path),
                        "filepath": save_path,
                        "size_bytes": os.path.getsize(save_path),
                        "message": f"Successfully exported {category}/{folder}"
                    }
                else:
                    # User cancelled
                    print(colorize_log(f"[api] Export cancelled by user"))
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                    return {
                        "ok": False,
                        "error": "Export cancelled by user"
                    }
            
            except ImportError:
                # Fallback: save to Downloads folder
                print(colorize_log(f"[api] tkinter not available, using Downloads folder fallback"))
                
                downloads_dir = os.path.expanduser("~/Downloads")
                if not os.path.isdir(downloads_dir):
                    downloads_dir = os.path.expanduser("~")
                
                save_path = os.path.join(downloads_dir, filename)
                
                # If file exists, add number
                base_name, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(save_path):
                    save_path = os.path.join(downloads_dir, f"{base_name}_{counter}{ext}")
                    counter += 1
                
                print(colorize_log(f"[api] Copying file to {save_path}..."))
                shutil.copy2(temp_path, save_path)
                
                # Clean up temp file
                try:
                    os.remove(temp_path)
                    print(colorize_log(f"[api] Cleaned up temporary file"))
                except Exception:
                    pass
                
                print(colorize_log(f"[api] [OK] Export completed successfully!"))
                print(colorize_log(f"[api] File saved to: {save_path}"))
                
                # Open the Downloads folder
                try:
                    import platform
                    import subprocess
                    
                    if platform.system() == "Windows":
                        os.startfile(os.path.dirname(save_path))
                    elif platform.system() == "Darwin":
                        subprocess.run(["open", os.path.dirname(save_path)])
                    else:
                        subprocess.run(["xdg-open", os.path.dirname(save_path)])
                except Exception:
                    pass
                
                return {
                    "ok": True,
                    "filename": os.path.basename(save_path),
                    "filepath": save_path,
                    "size_bytes": os.path.getsize(save_path),
                    "message": f"Exported to {os.path.dirname(save_path)}"
                }
        
        except Exception as zip_err:
            # Clean up temp file
            print(colorize_log(f"[api] [FAILED] Export failed: {str(zip_err)}"))
            try:
                if 'temp_path' in locals():
                    os.remove(temp_path)
            except Exception:
                pass
            return {"ok": False, "error": f"Failed to create ZIP: {str(zip_err)}"}
    
    except Exception as e:
        import traceback
        print(colorize_log(f"[api] [FAILED] Export error: {str(e)}"))
        traceback.print_exc()
        return {"ok": False, "error": f"Failed to export version: {str(e)}"}


def api_import_versions(data):
    """
    Import a version from a .hlvdf ZIP file.
    
    Request body:
    {
        "version_name": "1.20.2",  # filename without extension
        "zip_data": "base64-encoded zip file data"
    }
    
    The category is extracted from data.ini inside the ZIP.
    Returns metadata version compatibility info
    """
    try:
        print(colorize_log(f"[api] api_import_versions called with data type: {type(data)}, data: {str(data)[:200] if data else 'None'}"))
        
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid request"}
        
        version_name = (data.get("version_name") or "").strip()
        zip_bytes_raw = data.get("zip_bytes")
        zip_data_base64 = (data.get("zip_data") or "").strip()

        zip_bytes = None
        if isinstance(zip_bytes_raw, (bytes, bytearray)):
            zip_bytes = bytes(zip_bytes_raw)
        elif zip_data_base64:
            import base64

            zip_bytes = base64.b64decode(zip_data_base64)

        zip_len = len(zip_bytes) if isinstance(zip_bytes, (bytes, bytearray)) else 0
        print(colorize_log(f"[api] version_name: '{version_name}', zip bytes length: {zip_len}"))

        if not version_name or not zip_bytes:
            return {"ok": False, "error": "missing version_name or zip data"}
        
        # Validate version name string
        if not _validate_version_string(version_name):
            return {"ok": False, "error": "invalid version_name format"}
        
        # Validate and extract ZIP
        import io
        import zipfile
        
        # Current metadata version - increment this when changing metadata handling
        CURRENT_MD_VERSION = "1.0"
        
        try:
            zip_buffer = io.BytesIO(zip_bytes)

            # First, read data.ini from the ZIP to get the category
            category = None
            existing_data = {}
            
            with zipfile.ZipFile(zip_buffer, 'r') as zipf:
                data_ini_entry = None
                for info in zipf.infolist():
                    normalized = str(info.filename or "").replace("\\", "/").lstrip("/")
                    if normalized == "data.ini":
                        data_ini_entry = info
                        break

                if data_ini_entry and int(data_ini_entry.file_size or 0) <= 1024 * 1024:
                    try:
                        with zipf.open(data_ini_entry, "r") as f:
                            content = f.read().decode('utf-8')
                            for line in content.split('\n'):
                                line = line.strip()
                                if "=" in line and not line.startswith("#"):
                                    k, v = line.split("=", 1)
                                    existing_data[k.strip()] = v.strip()
                    except Exception as read_err:
                        print(colorize_log(f"[api] Warning: Could not read data.ini from ZIP: {str(read_err)}"))
        
            # Get category from data.ini
            category = existing_data.get("category", "").strip()
            
            # Validate category from the extracted data
            if not category:
                # Default to Release if no category found
                print(colorize_log(f"[api] Warning: No category found in data.ini, defaulting to Release"))
                category = "Release"
            
            if not _validate_category_string(category):
                return {"ok": False, "error": f"invalid category in data.ini: {category}"}
            
            clients_dir = get_clients_dir()
            version_path = os.path.join(clients_dir, category, version_name)
            
            try:
                real_version_path = os.path.realpath(version_path)
                real_clients_dir = os.path.realpath(clients_dir)
                if not real_version_path.startswith(real_clients_dir):
                    return {"ok": False, "error": "invalid version path"}
            except (OSError, ValueError):
                return {"ok": False, "error": "invalid version path"}
            
            if os.path.isdir(version_path):
                return {"ok": False, "error": f"Version already exists at {category}/{version_name}.<br><i>Delete it and try again.</i>"}
            
            category_path = os.path.join(clients_dir, category)
            os.makedirs(category_path, exist_ok=True)
            
            try:
                zip_buffer.seek(0)
                with zipfile.ZipFile(zip_buffer, 'r') as zipf:
                    os.makedirs(version_path, exist_ok=True)

                    safe_extract_zip(
                        zipf,
                        version_path,
                        member_filter=lambda n, info: not n.startswith("assets/"),
                    )

                    base_dir = get_base_dir()
                    assets_path = os.path.join(base_dir, "assets")
                    os.makedirs(assets_path, exist_ok=True)

                    safe_extract_zip(
                        zipf,
                        assets_path,
                        member_filter=lambda n, info: n.startswith("assets/"),
                        name_transform=lambda n, info: n[len("assets/"):],
                    )
            except (zipfile.BadZipFile, ZipSecurityError):
                if version_path and os.path.isdir(version_path):
                    shutil.rmtree(version_path, ignore_errors=True)
                return {"ok": False, "error": "Invalid ZIP file"}
            
            old_md_version = existing_data.get("md_version", "missing").strip()
            if not old_md_version or old_md_version == "missing":
                print(colorize_log(f"[api] Auto-upgrading old version from no metadata version to {CURRENT_MD_VERSION}"))
            
            data_ini_path = os.path.join(version_path, "data.ini")
            if os.path.exists(data_ini_path):
                with open(data_ini_path, "r", encoding="utf-8") as f:
                    existing_data = {}
                    for line in f:
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            k, v = line.split("=", 1)
                            existing_data[k.strip()] = v.strip()
                
                existing_data["imported"] = "true"
                existing_data["md_version"] = CURRENT_MD_VERSION
                existing_data["category"] = category
                
                with open(data_ini_path, "w", encoding="utf-8") as f:
                    for k, v in existing_data.items():
                        f.write(f"{k}={v}\n")
            else:
                # Create data.ini with metadata if it doesn't exist
                with open(data_ini_path, "w", encoding="utf-8") as f:
                    f.write("imported=true\n")
                    f.write(f"md_version={CURRENT_MD_VERSION}\n")
                    f.write(f"category={category}\n")
            
            # Refresh cache
            scan_categories(force_refresh=True)
            
            print(colorize_log(f"[api] [OK] Imported version: {category}/{version_name}"))
            
            result = {
                "ok": True,
                "message": f"Successfully imported {category}/{version_name}",
                "category": category,
                "folder": version_name,
                "is_imported": True
            }
            
            return result
        
        except Exception as zip_err:
            # Clean up if extraction fails
            try:
                if 'version_path' in locals() and version_path and os.path.isdir(version_path):
                    shutil.rmtree(version_path, ignore_errors=True)
            except Exception:
                pass
            print(colorize_log(f"[api] [FAILED] Import failed: {str(zip_err)}"))
            return {"ok": False, "error": f"Failed to extract ZIP: {str(zip_err)}"}
    
    except Exception as e:
        import traceback
        print(colorize_log(f"[api] [FAILED] Import error: {str(e)}"))
        traceback.print_exc()
        return {"ok": False, "error": f"Failed to import version: {str(e)}"}


# ==================== MODS API ====================

def api_mods_installed(data=None):
    """Get list of installed mods."""
    try:
        from core import mod_manager

        mods = mod_manager.get_installed_mods()

        return {
            "ok": True,
            "mods": mods
        }
    except Exception as e:
        print(colorize_log(f"[api] Failed to get installed mods: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_search(data):
    """Search for mods from CurseForge or Modrinth."""
    try:
        from core import mod_manager
        
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        
        provider = (data.get("provider") or "modrinth").lower()
        search_query = data.get("search_query", "")
        game_version = data.get("game_version")
        mod_loader = data.get("mod_loader")
        page_size = data.get("page_size", 20)
        page_index = data.get("page_index", 0)
        api_key = data.get("api_key")  # For CurseForge
        
        if provider == "curseforge":
            result = mod_manager.search_mods_curseforge(
                search_query=search_query,
                game_version=game_version,
                mod_loader_type=mod_loader,
                page_size=page_size,
                index=page_index,
                api_key=api_key
            )
        elif provider == "modrinth":
            result = mod_manager.search_mods_modrinth(
                search_query=search_query,
                game_version=game_version,
                mod_loader=mod_loader,
                limit=page_size,
                offset=page_index * page_size
            )
        else:
            return {"ok": False, "error": f"Unknown provider: {provider}"}
        
        return {
            "ok": True,
            "total_count": result.get("total", 0),
            **result
        }
    except Exception as e:
        print(colorize_log(f"[api] Failed to search mods: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_version_options():
    """Return installed versions that have at least one Fabric/Forge loader installed."""
    try:
        categories = scan_categories(force_refresh=True)
        installed_versions = categories.get("* All", []) if isinstance(categories, dict) else []

        options = []
        seen_versions = set()
        for item in installed_versions:
            category = (item or {}).get("category")
            folder = (item or {}).get("folder")
            if not category or not folder:
                continue

            installed_loaders = get_version_loaders(category, folder)
            has_supported_loader = bool(installed_loaders.get("fabric") or installed_loaders.get("forge"))
            if not has_supported_loader:
                continue

            version_value = folder
            if version_value in seen_versions:
                continue
            seen_versions.add(version_value)

            options.append({
                "category": category,
                "folder": folder,
                "display": (item or {}).get("display_name") or folder,
                "version": version_value,
            })

        options.sort(key=lambda x: x.get("version", ""), reverse=True)

        return {
            "ok": True,
            "versions": options,
        }
    except Exception as e:
        print(colorize_log(f"[api] Failed to get mod version options: {e}"))
        return {"ok": False, "error": str(e), "versions": []}


def api_mods_versions(data):
    """Get available versions/files for a mod."""
    try:
        from core import mod_manager
        
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        
        provider = (data.get("provider") or "modrinth").lower()
        mod_id = data.get("mod_id")
        game_version = data.get("game_version")
        mod_loader = data.get("mod_loader")
        api_key = data.get("api_key")  # For CurseForge
        
        if not mod_id:
            return {"ok": False, "error": "mod_id is required"}
        
        if provider == "curseforge":
            versions = mod_manager.get_mod_files_curseforge(
                mod_id=mod_id,
                game_version=game_version,
                mod_loader_type=mod_loader,
                api_key=api_key
            )
        elif provider == "modrinth":
            versions = mod_manager.get_mod_versions_modrinth(
                mod_id=mod_id,
                game_version=game_version,
                mod_loader=mod_loader
            )
        else:
            return {"ok": False, "error": f"Unknown provider: {provider}"}
        
        return {
            "ok": True,
            "versions": versions
        }
    except Exception as e:
        print(colorize_log(f"[api] Failed to get mod versions: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_install(data):
    """Download and install a mod version."""
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        provider = (data.get("provider") or "modrinth").lower()
        mod_id = data.get("mod_id")
        mod_slug = (data.get("mod_slug") or "").strip().lower()
        mod_name = data.get("mod_name", mod_slug)
        mod_loader = data.get("mod_loader")
        download_url = data.get("download_url")
        file_name = (data.get("file_name") or "").strip()
        description = data.get("description", "")
        icon_url = data.get("icon_url", "")
        raw_version = str(data.get("version", "unknown") or "unknown").strip()

        if not mod_slug or not mod_loader or not download_url or not file_name:
            return {"ok": False, "error": "Missing required fields"}

        if mod_loader.lower() not in ["fabric", "forge"]:
            return {"ok": False, "error": "Invalid mod_loader (must be fabric or forge)"}

        if not _validate_mod_slug(mod_slug):
            return {"ok": False, "error": "Invalid mod_slug format"}

        if not _validate_jar_filename(file_name):
            return {"ok": False, "error": "Invalid file_name format"}

        # Normalize version label before using it as a filesystem path component.
        if len(raw_version) > MAX_VERSION_LABEL_LENGTH * 4:
            return {"ok": False, "error": "Invalid version label"}
        version_label = mod_manager.normalize_version_label(raw_version)
        if not _validate_version_label(version_label):
            return {"ok": False, "error": "Invalid version label"}

        # Download the mod file into mods/{loader}/{slug}/{version}/
        success = mod_manager.download_mod_file(
            download_url=download_url,
            mod_loader=mod_loader,
            mod_slug=mod_slug,
            version_label=version_label,
            file_name=file_name
        )

        if not success:
            return {"ok": False, "error": "Failed to download mod file"}

        # Save version-level metadata
        mod_manager.save_version_metadata(mod_loader, mod_slug, version_label, {
            "version": raw_version,
            "mod_loader": mod_loader,
            "file_name": file_name,
            "download_url": download_url,
            "provider": provider,
        })

        # Save / update mod-level metadata
        mod_dir = mod_manager.get_mod_dir(mod_loader, mod_slug)
        meta_file = os.path.join(mod_dir, "mod_meta.json")
        if os.path.isfile(meta_file):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = {}
        else:
            existing = {}

        existing.update({
            "mod_id": mod_id,
            "name": mod_name,
            "description": description,
            "icon_url": icon_url,
            "provider": provider,
            "mod_loader": mod_loader,
            "disabled": existing.get("disabled", False),
        })
        # If first version or no active version, set this as active
        if not existing.get("active_version"):
            existing["active_version"] = version_label
        mod_manager.save_mod_metadata(mod_loader, mod_slug, existing)

        # Download icon as display.png at mod root
        if icon_url:
            mod_manager.download_mod_icon(icon_url, mod_loader, mod_slug)

        print(colorize_log(f"[api] Installed mod version: {mod_name} v{raw_version} ({mod_loader})"))

        return {
            "ok": True,
            "message": f"Successfully installed {mod_name} v{raw_version}"
        }
    except Exception as e:
        print(colorize_log(f"[api] Failed to install mod: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_import(data):
    """Import a custom JAR mod from the user's filesystem."""
    try:
        from core import mod_manager
        import re as _re

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        mod_loader = (data.get("mod_loader") or "").strip().lower()
        jar_name = (data.get("jar_name") or "").strip()
        jar_data = data.get("jar_data")  # raw bytes from multipart

        if not mod_loader or mod_loader not in ("fabric", "forge"):
            return {"ok": False, "error": "mod_loader must be fabric or forge"}
        if not _validate_jar_filename(jar_name):
            return {"ok": False, "error": "A valid .jar filename is required"}
        if not isinstance(jar_data, (bytes, bytearray)):
            return {"ok": False, "error": "Invalid JAR file data"}
        if not jar_data or len(jar_data) == 0:
            return {"ok": False, "error": "JAR file data is empty"}

        # Derive slug from filename: strip .jar, lowercase, replace non-alnum with dashes
        base_name = jar_name[:-4]  # remove .jar
        mod_slug = _re.sub(r'[^a-z0-9]+', '-', base_name.lower()).strip('-') or "imported-mod"
        version_label = "imported"

        # Save the jar file directly
        ver_dir = mod_manager.get_mod_version_dir(mod_loader, mod_slug, version_label)
        jar_path = os.path.join(ver_dir, jar_name)
        with open(jar_path, "wb") as f:
            f.write(jar_data)

        # Save version metadata
        mod_manager.save_version_metadata(mod_loader, mod_slug, version_label, {
            "version": version_label,
            "mod_loader": mod_loader,
            "file_name": jar_name,
            "provider": "imported",
        })

        # Save / update mod-level metadata
        mod_dir = mod_manager.get_mod_dir(mod_loader, mod_slug)
        meta_file = os.path.join(mod_dir, "mod_meta.json")
        if os.path.isfile(meta_file):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = {}
        else:
            existing = {}

        existing.update({
            "name": base_name,
            "description": f"This mod was imported from an unknown source, no proper description is available.",
            "provider": "imported",
            "mod_loader": mod_loader,
            "is_imported": True,
            "disabled": existing.get("disabled", False),
        })
        if not existing.get("active_version"):
            existing["active_version"] = version_label
        mod_manager.save_mod_metadata(mod_loader, mod_slug, existing)

        print(colorize_log(f"[api] Imported custom mod: {jar_name} ({mod_loader})"))

        return {
            "ok": True,
            "message": f"Successfully imported {jar_name} ({mod_loader})"
        }
    except Exception as e:
        print(colorize_log(f"[api] Failed to import mod: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_delete(data):
    """Delete an installed mod or a specific version."""
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        mod_slug = (data.get("mod_slug") or "").strip().lower()
        mod_loader = (data.get("mod_loader") or "").strip().lower()
        version_label = data.get("version_label")  # optional

        if not mod_slug or not mod_loader:
            return {"ok": False, "error": "Missing mod_slug or mod_loader"}

        if mod_loader not in ["fabric", "forge"]:
            return {"ok": False, "error": "Invalid mod_loader"}

        if not _validate_mod_slug(mod_slug):
            return {"ok": False, "error": "Invalid mod_slug format"}

        if version_label is not None and not _validate_version_label(str(version_label)):
            return {"ok": False, "error": "Invalid version_label"}

        success = mod_manager.delete_mod(mod_loader, mod_slug, version_label)

        if success:
            what = f"{mod_slug}/{version_label}" if version_label else mod_slug
            return {"ok": True, "message": f"Deleted {what}"}
        return {"ok": False, "error": "Failed to delete mod"}
    except Exception as e:
        print(colorize_log(f"[api] Failed to delete mod: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_toggle(data):
    """Toggle a mod between enabled/disabled."""
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        mod_slug = (data.get("mod_slug") or "").strip().lower()
        mod_loader = (data.get("mod_loader") or "").strip().lower()
        disabled = bool(data.get("disabled", False))

        if not mod_slug or not mod_loader:
            return {"ok": False, "error": "Missing mod_slug or mod_loader"}

        if mod_loader not in ["fabric", "forge"]:
            return {"ok": False, "error": "Invalid mod_loader"}

        if not _validate_mod_slug(mod_slug):
            return {"ok": False, "error": "Invalid mod_slug format"}

        success = mod_manager.toggle_mod_disabled(mod_loader, mod_slug, disabled)
        if success:
            return {"ok": True, "disabled": disabled}
        return {"ok": False, "error": "Failed to toggle mod"}
    except Exception as e:
        print(colorize_log(f"[api] Failed to toggle mod: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_set_active_version(data):
    """Set the active version for an installed mod."""
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        mod_slug = (data.get("mod_slug") or "").strip().lower()
        mod_loader = (data.get("mod_loader") or "").strip().lower()
        version_label = data.get("version_label")

        if not mod_slug or not mod_loader or not version_label:
            return {"ok": False, "error": "Missing mod_slug, mod_loader or version_label"}

        if mod_loader not in ["fabric", "forge"]:
            return {"ok": False, "error": "Invalid mod_loader"}

        if not _validate_mod_slug(mod_slug):
            return {"ok": False, "error": "Invalid mod_slug format"}

        if not _validate_version_label(str(version_label)):
            return {"ok": False, "error": "Invalid version_label"}

        success = mod_manager.set_active_version(mod_loader, mod_slug, version_label)
        if success:
            return {"ok": True, "active_version": version_label}
        return {"ok": False, "error": "Failed to set active version"}
    except Exception as e:
        print(colorize_log(f"[api] Failed to set active version: {e}"))
        return {"ok": False, "error": str(e)}


def api_mods_detail(data):
    """Get detailed info about a mod (description, gallery, screenshots)."""
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        provider = (data.get("provider") or "modrinth").lower()
        mod_id = data.get("mod_id")

        if not mod_id:
            return {"ok": False, "error": "mod_id is required"}

        if provider == "modrinth":
            detail = mod_manager.get_mod_detail_modrinth(mod_id)
        elif provider == "curseforge":
            detail = mod_manager.get_mod_detail_curseforge(mod_id)
        else:
            return {"ok": False, "error": f"Unknown provider: {provider}"}

        if detail:
            return {"ok": True, **detail}
        return {"ok": False, "error": "Failed to fetch mod details"}
    except Exception as e:
        print(colorize_log(f"[api] Failed to get mod detail: {e}"))
        return {"ok": False, "error": str(e)}


# ==================== Modpack API ====================

def api_modpacks_installed(data=None):
    """Get list of installed modpacks."""
    try:
        from core import mod_manager
        packs = mod_manager.get_installed_modpacks()
        return {"ok": True, "modpacks": packs}
    except Exception as e:
        print(colorize_log(f"[api] Failed to get installed modpacks: {e}"))
        return {"ok": False, "error": str(e)}


def api_modpacks_export(data):
    """Export a modpack as .hlmp.

    Supports two output modes:
    - Browser mode (default): return base64 bytes in JSON.
    - Desktop mode (save_to_disk=true): open native save dialog in backend and
      return saved filepath metadata.
    """
    try:
        import base64
        import tempfile
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        name = (data.get("name") or "").strip()
        version = (data.get("version") or "").strip()
        description = (data.get("description") or "").strip()
        mod_loader = (data.get("mod_loader") or "").strip().lower()
        mods_list = data.get("mods") or []
        save_to_disk = bool(data.get("save_to_disk", False))

        if not name or len(name) > 64:
            return {"ok": False, "error": "Name must be 1-64 characters"}
        import re as _re
        if _re.search(r'[<>:"/\\|?*\x00-\x1f]', name):
            return {"ok": False, "error": "Name contains forbidden characters"}
        if not version or len(version) > 16:
            return {"ok": False, "error": "Version must be 1-16 characters"}
        if len(description) > 8192:
            return {"ok": False, "error": "Description too long (max 8192)"}
        if mod_loader not in ("fabric", "forge"):
            return {"ok": False, "error": "mod_loader must be fabric or forge"}
        if not mods_list:
            return {"ok": False, "error": "At least one mod is required"}

        normalized_mods = []
        for entry in mods_list:
            if not isinstance(entry, dict):
                continue
            mod_slug = (entry.get("mod_slug") or "").strip().lower()
            version_label = (entry.get("version_label") or "").strip()
            if not _validate_mod_slug(mod_slug):
                continue
            if not _validate_version_label(version_label):
                continue
            normalized_mods.append({
                "mod_slug": mod_slug,
                "version_label": version_label,
                "mod_name": (entry.get("mod_name") or mod_slug).strip(),
                "disabled": bool(entry.get("disabled", False)),
            })

        if not normalized_mods:
            return {"ok": False, "error": "No valid mods to export"}

        # Decode optional image
        image_data = None
        image_b64 = data.get("image_data")
        if image_b64:
            image_data = base64.b64decode(image_b64)

        hlmp_bytes = mod_manager.export_modpack(
            name=name, version=version, description=description,
            mod_loader=mod_loader, mods=normalized_mods, image_data=image_data,
        )

        file_name = f"{name}.hlmp"

        if save_to_disk:
            temp_fd = None
            temp_path = None
            try:
                temp_fd, temp_path = tempfile.mkstemp(prefix="histolauncher_modpack_", suffix=".hlmp")
                with os.fdopen(temp_fd, "wb") as tmpf:
                    tmpf.write(hlmp_bytes)
                temp_fd = None

                save_path = ""
                dialog_failed = False
                root = None

                # Preferred: native save dialog (desktop launcher UX).
                try:
                    from tkinter import Tk
                    from tkinter.filedialog import asksaveasfilename

                    root = Tk()
                    root.withdraw()
                    root.attributes("-topmost", True)
                    save_path = asksaveasfilename(
                        initialfile=file_name,
                        defaultextension=".hlmp",
                        filetypes=[("Histolauncher Modpack", "*.hlmp"), ("All Files", "*.*")],
                        initialdir=os.path.expanduser("~"),
                        title=f"Save {name} Modpack Export",
                    )
                except Exception as dialog_err:
                    dialog_failed = True
                    print(colorize_log(f"[api] Modpack save dialog unavailable, using fallback path: {dialog_err}"))
                finally:
                    try:
                        if root is not None:
                            root.destroy()
                    except Exception:
                        pass

                # User explicitly cancelled the native dialog.
                if save_path and str(save_path).strip():
                    final_path = save_path
                elif not dialog_failed:
                    return {
                        "ok": False,
                        "cancelled": True,
                        "error": "Export cancelled by user",
                    }
                else:
                    # Fallback for environments where native dialog is unavailable.
                    downloads_dir = os.path.expanduser("~/Downloads")
                    if not os.path.isdir(downloads_dir):
                        downloads_dir = os.path.expanduser("~")

                    base_name, ext = os.path.splitext(file_name)
                    final_path = os.path.join(downloads_dir, file_name)
                    counter = 1
                    while os.path.exists(final_path):
                        final_path = os.path.join(downloads_dir, f"{base_name}_{counter}{ext}")
                        counter += 1

                shutil.copy2(temp_path, final_path)
                return {
                    "ok": True,
                    "filename": os.path.basename(final_path),
                    "filepath": final_path,
                    "size_bytes": os.path.getsize(final_path),
                    "message": f"Exported to {os.path.dirname(final_path)}",
                }
            finally:
                try:
                    if temp_fd is not None:
                        os.close(temp_fd)
                except Exception:
                    pass
                try:
                    if temp_path and os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception:
                    pass

        return {
            "ok": True,
            "hlmp_data": base64.b64encode(hlmp_bytes).decode("ascii"),
            "filename": file_name,
            "size_bytes": len(hlmp_bytes),
        }
    except Exception as e:
        print(colorize_log(f"[api] Failed to export modpack: {e}"))
        return {"ok": False, "error": f"Failed to export modpack: {str(e)}"}


def api_modpacks_import(data):
    """Import a .hlmp (Histolauncher Modpack) file (raw bytes passed from multipart handler)."""
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        hlmp_data = data.get("hlmp_data")
        if not hlmp_data or len(hlmp_data) == 0:
            return {"ok": False, "error": "No .hlmp file data"}

        result = mod_manager.import_modpack(hlmp_data)
        return result
    except Exception as e:
        print(colorize_log(f"[api] Failed to import modpack: {e}"))
        return {"ok": False, "error": str(e)}


def api_modpacks_toggle_mod(data):
    """Toggle disabled state for a specific mod entry within an installed modpack."""
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        pack_slug = (data.get("pack_slug") or "").strip().lower()
        mod_slug = (data.get("mod_slug") or "").strip().lower()
        disabled = bool(data.get("disabled", False))

        if not pack_slug or not mod_slug:
            return {"ok": False, "error": "Missing pack_slug or mod_slug"}

        if not _validate_modpack_slug(pack_slug):
            return {"ok": False, "error": "Invalid pack_slug"}

        if not _validate_mod_slug(mod_slug):
            return {"ok": False, "error": "Invalid mod_slug"}

        success = mod_manager.toggle_mod_in_modpack(pack_slug, mod_slug, disabled)
        if success:
            return {"ok": True, "disabled": disabled}
        return {"ok": False, "error": "Mod not found in modpack"}
    except Exception as e:
        print(colorize_log(f"[api] Failed to toggle mod in modpack: {e}"))
        return {"ok": False, "error": str(e)}


def api_modpacks_toggle(data):
    """Toggle a modpack between enabled/disabled."""
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        slug = (data.get("slug") or "").strip().lower()
        disabled = bool(data.get("disabled", False))

        if not slug:
            return {"ok": False, "error": "Missing modpack slug"}

        if not _validate_modpack_slug(slug):
            return {"ok": False, "error": "Invalid modpack slug"}

        success = mod_manager.toggle_modpack(slug, disabled)
        if success:
            return {"ok": True, "disabled": disabled}
        return {"ok": False, "error": "Failed to toggle modpack"}
    except Exception as e:
        print(colorize_log(f"[api] Failed to toggle modpack: {e}"))
        return {"ok": False, "error": str(e)}


def api_modpacks_delete(data):
    """Delete an installed modpack."""
    try:
        from core import mod_manager

        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}

        slug = (data.get("slug") or "").strip().lower()
        if not slug:
            return {"ok": False, "error": "Missing modpack slug"}

        if not _validate_modpack_slug(slug):
            return {"ok": False, "error": "Invalid modpack slug"}

        success = mod_manager.delete_modpack(slug)
        if success:
            return {"ok": True, "message": f"Deleted modpack {slug}"}
        return {"ok": False, "error": "Failed to delete modpack"}
    except Exception as e:
        print(colorize_log(f"[api] Failed to delete modpack: {e}"))
        return {"ok": False, "error": str(e)}
