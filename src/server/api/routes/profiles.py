from __future__ import annotations

from core.settings import (
    create_profile,
    create_scope_profile,
    delete_profile,
    delete_scope_profile,
    get_active_profile_id,
    get_active_scope_profile_id,
    list_profiles,
    list_scope_profiles,
    load_global_settings,
    rename_profile,
    rename_scope_profile,
    set_active_profile,
    set_active_scope_profile,
)


__all__ = [
    "api_profiles",
    "api_profiles_create",
    "api_profiles_switch",
    "api_profiles_delete",
    "api_profiles_rename",
    "api_profiles_versions",
    "api_profiles_versions_create",
    "api_profiles_versions_switch",
    "api_profiles_versions_delete",
    "api_profiles_versions_rename",
    "api_profiles_mods",
    "api_profiles_mods_create",
    "api_profiles_mods_switch",
    "api_profiles_mods_delete",
    "api_profiles_mods_rename",
]


def api_profiles(data=None):
    try:
        return {
            "ok": True,
            "profiles": list_profiles(),
            "active_profile": get_active_profile_id(),
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
        return {
            "ok": True,
            "profile": profile,
            "profiles": list_profiles(),
            "active_profile": get_active_profile_id(),
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

        return {
            "ok": True,
            "active_profile": get_active_profile_id(),
            "settings": load_global_settings(),
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


def _scope_list(scope: str):
    return {
        "ok": True,
        "profiles": list_scope_profiles(scope),
        "active_profile": get_active_scope_profile_id(scope),
    }


def _scope_create(scope: str, data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        name = str(data.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "Profile name is required"}
        if len(name) > 32:
            return {"ok": False, "error": "Profile name must be 1-32 characters"}

        profile = create_scope_profile(scope, name)
        return {
            "ok": True,
            "profile": profile,
            "profiles": list_scope_profiles(scope),
            "active_profile": get_active_scope_profile_id(scope),
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _scope_switch(scope: str, data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        profile_id = str(data.get("profile_id") or "").strip()
        if not profile_id:
            return {"ok": False, "error": "profile_id is required"}
        if not set_active_scope_profile(scope, profile_id):
            return {"ok": False, "error": "Profile not found"}
        return {"ok": True, "active_profile": get_active_scope_profile_id(scope)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _scope_delete(scope: str, data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "Invalid request"}
        profile_id = str(data.get("profile_id") or "").strip()
        if not profile_id:
            return {"ok": False, "error": "profile_id is required"}
        if not delete_scope_profile(scope, profile_id):
            return {
                "ok": False,
                "error": "Failed to delete profile (cannot delete Default or last profile)",
            }
        return {
            "ok": True,
            "profiles": list_scope_profiles(scope),
            "active_profile": get_active_scope_profile_id(scope),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _scope_rename(scope: str, data):
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

        if not rename_scope_profile(scope, profile_id, name):
            return {"ok": False, "error": "Profile not found"}

        return {
            "ok": True,
            "profiles": list_scope_profiles(scope),
            "active_profile": get_active_scope_profile_id(scope),
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_versions(data=None):
    try:
        return _scope_list("versions")
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_versions_create(data):
    return _scope_create("versions", data)


def api_profiles_versions_switch(data):
    return _scope_switch("versions", data)


def api_profiles_versions_delete(data):
    return _scope_delete("versions", data)


def api_profiles_versions_rename(data):
    return _scope_rename("versions", data)


def api_profiles_mods(data=None):
    try:
        return _scope_list("mods")
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_profiles_mods_create(data):
    return _scope_create("mods", data)


def api_profiles_mods_switch(data):
    return _scope_switch("mods", data)


def api_profiles_mods_delete(data):
    return _scope_delete("mods", data)


def api_profiles_mods_rename(data):
    return _scope_rename("mods", data)
