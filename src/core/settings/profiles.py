from __future__ import annotations

import configparser
import json
import logging
import os
import re
import shutil
import threading
import time
from typing import Any

from core.settings.defaults import (
    DEFAULTS,
    MAX_PROFILE_ID_LEN,
    MAX_PROFILE_NAME_LEN,
    META_WRITE_LOCK,
    PROFILE_ADD_SENTINEL,
    PROFILE_SCOPES,
)
from core.settings.paths import (
    get_base_dir,
    get_profiles_meta_path,
    get_profiles_root_dir,
    get_profiles_settings_dir,
)

logger = logging.getLogger(__name__)

__all__ = [
    "create_profile",
    "create_scope_profile",
    "delete_profile",
    "delete_scope_profile",
    "ensure_profile_system_initialized",
    "ensure_scope_initialized",
    "get_account_cache_path",
    "get_active_profile_id",
    "get_active_scope_profile_id",
    "get_mods_profile_dir",
    "get_settings_path",
    "get_token_path",
    "get_versions_profile_dir",
    "list_profiles",
    "list_scope_profiles",
    "rename_profile",
    "rename_scope_profile",
    "safe_profile_id",
    "set_active_profile",
    "set_active_scope_profile",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def safe_profile_id(name: str | None) -> str:
    raw = str(name or "").strip().lower()
    raw = raw.replace(" ", "-")
    raw = re.sub(r"[^a-z0-9_-]+", "", raw)
    raw = raw.strip("-_")
    if not raw:
        raw = "profile"
    return raw[:MAX_PROFILE_ID_LEN]


def _default_meta() -> dict[str, Any]:
    return {
        "active": "default",
        "profiles": [{"id": "default", "name": "Default"}],
    }


def _write_default_settings_file(path: str) -> None:
    config = configparser.ConfigParser()
    for section, defaults in DEFAULTS.items():
        config[section] = {k: str(v) for k, v in defaults.items()}
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        config.write(f)
    os.replace(tmp_path, path)


def _atomic_save_meta(meta_path: str, meta: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)

    with META_WRITE_LOCK:
        last_error: Exception | None = None
        for attempt in range(6):
            tmp_path = f"{meta_path}.{os.getpid()}.{threading.get_ident()}.tmp"
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)
                os.replace(tmp_path, meta_path)
                return
            except PermissionError as e:
                last_error = e
                time.sleep(0.04 * (attempt + 1))
            finally:
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except OSError:
                    pass

    if last_error is not None:
        raise last_error
    raise RuntimeError("Failed to save profiles metadata")


def _load_meta_from_path(meta_path: str) -> dict[str, Any]:
    if not os.path.exists(meta_path):
        return _default_meta()
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _default_meta()
    if not isinstance(data, dict):
        return _default_meta()
    if not isinstance(data.get("profiles"), list) or not isinstance(data.get("active"), str):
        return _default_meta()
    return data


def _profile_settings_file(profile_id: str) -> str:
    return os.path.join(get_profiles_settings_dir(), f"{safe_profile_id(profile_id)}.ini")


def _profile_token_file(profile_id: str) -> str:
    return os.path.join(
        get_profiles_settings_dir(), f"{safe_profile_id(profile_id)}.account.token"
    )


def _is_valid_profile_name(name: object) -> bool:
    if not isinstance(name, str):
        return False
    n = name.strip()
    return 1 <= len(n) <= MAX_PROFILE_NAME_LEN


# ---------------------------------------------------------------------------
# Scope handling
# ---------------------------------------------------------------------------


def _normalize_scope(scope: str) -> str:
    s = str(scope or "").strip().lower()
    if s == "mods":
        s = "addons"
    if s not in PROFILE_SCOPES:
        raise ValueError(f"Unsupported profile scope: {scope}")
    return s


def _get_scope_base_dir(scope: str) -> str:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        return get_profiles_settings_dir()

    profiles_root = get_profiles_root_dir()

    if scope_norm == "addons":
        legacy_mods_profiles = os.path.join(profiles_root, "mods")
        addons_profiles = os.path.join(profiles_root, "addons")
        if os.path.isdir(legacy_mods_profiles) and not os.path.exists(addons_profiles):
            try:
                shutil.move(legacy_mods_profiles, addons_profiles)
                logger.info("Migrated legacy profiles/mods/ to profiles/addons/")
            except OSError as e:
                logger.warning(f"Failed migrating legacy profiles/mods directory: {e}")

    path = os.path.join(profiles_root, scope_norm)
    os.makedirs(path, exist_ok=True)
    return path


def _get_scope_meta_path(scope: str) -> str:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        return get_profiles_meta_path()
    return os.path.join(_get_scope_base_dir(scope_norm), "profiles.json")


def _load_scope_meta(scope: str) -> dict[str, Any]:
    return _load_meta_from_path(_get_scope_meta_path(scope))


def _save_scope_meta(scope: str, meta: dict[str, Any]) -> None:
    _atomic_save_meta(_get_scope_meta_path(scope), meta)


def _ensure_scope_profile_dirs(scope: str, profile_id: str) -> None:
    scope_norm = _normalize_scope(scope)
    pid = safe_profile_id(profile_id)
    if scope_norm == "versions":
        os.makedirs(os.path.join(_get_scope_base_dir(scope_norm), pid), exist_ok=True)
        return
    if scope_norm == "addons":
        root = os.path.join(_get_scope_base_dir(scope_norm), pid)
        os.makedirs(os.path.join(root, "mods"), exist_ok=True)
        os.makedirs(os.path.join(root, "modpacks"), exist_ok=True)


def _migrate_scope_from_legacy(scope: str) -> None:
    scope_norm = _normalize_scope(scope)
    base_dir = get_base_dir()

    if scope_norm == "versions":
        legacy_clients = os.path.join(base_dir, "clients")
        default_root = os.path.join(_get_scope_base_dir(scope_norm), "default")
        if os.path.isdir(legacy_clients) and not os.path.exists(default_root):
            try:
                shutil.move(legacy_clients, default_root)
                logger.info("Migrated legacy clients/ to profiles/versions/default/")
            except OSError as e:
                logger.warning(f"Failed migrating legacy clients directory: {e}")
        return

    if scope_norm == "addons":
        legacy_mods = os.path.join(base_dir, "mods")
        legacy_modpacks = os.path.join(base_dir, "modpacks")
        default_root = os.path.join(_get_scope_base_dir(scope_norm), "default")
        default_mods = os.path.join(default_root, "mods")
        default_modpacks = os.path.join(default_root, "modpacks")

        if os.path.isdir(legacy_mods) and not os.path.exists(default_mods):
            try:
                os.makedirs(default_root, exist_ok=True)
                shutil.move(legacy_mods, default_mods)
                logger.info("Migrated legacy mods/ to profiles/addons/default/mods/")
            except OSError as e:
                logger.warning(f"Failed migrating legacy mods directory: {e}")

        if os.path.isdir(legacy_modpacks) and not os.path.exists(default_modpacks):
            try:
                os.makedirs(default_root, exist_ok=True)
                shutil.move(legacy_modpacks, default_modpacks)
                logger.info("Migrated legacy modpacks/ to profiles/addons/default/modpacks/")
            except OSError as e:
                logger.warning(f"Failed migrating legacy modpacks directory: {e}")


def ensure_scope_initialized(scope: str) -> None:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        ensure_profile_system_initialized()
        return

    _get_scope_base_dir(scope_norm)
    meta_path = _get_scope_meta_path(scope_norm)
    meta_changed = not os.path.exists(meta_path)
    meta = _load_scope_meta(scope_norm)

    if not any(str(p.get("id", "")) == "default" for p in meta.get("profiles", [])):
        meta.setdefault("profiles", []).insert(0, {"id": "default", "name": "Default"})
        meta_changed = True

    _migrate_scope_from_legacy(scope_norm)

    profile_ids = {str(p.get("id", "")) for p in meta.get("profiles", [])}
    active = str(meta.get("active") or "default")
    if active not in profile_ids:
        meta["active"] = "default"
        meta_changed = True

    for p in meta.get("profiles", []):
        pid = str(p.get("id", "")).strip()
        if pid:
            _ensure_scope_profile_dirs(scope_norm, pid)

    if meta_changed:
        _save_scope_meta(scope_norm, meta)


# ---------------------------------------------------------------------------
# Settings-scope (default) initialisation + CRUD
# ---------------------------------------------------------------------------


def _load_profiles_meta() -> dict[str, Any]:
    return _load_meta_from_path(get_profiles_meta_path())


def _save_profiles_meta(meta: dict[str, Any]) -> None:
    _atomic_save_meta(get_profiles_meta_path(), meta)


def ensure_profile_system_initialized() -> None:
    get_profiles_settings_dir()
    meta_path = get_profiles_meta_path()
    meta_changed = not os.path.exists(meta_path)
    meta = _load_profiles_meta()

    if not any(str(p.get("id", "")) == "default" for p in meta.get("profiles", [])):
        meta.setdefault("profiles", []).insert(0, {"id": "default", "name": "Default"})
        meta_changed = True

    base_dir = get_base_dir()
    legacy_settings = os.path.join(base_dir, "settings.ini")
    legacy_token = os.path.join(base_dir, "account.token")
    default_settings = _profile_settings_file("default")
    default_token = _profile_token_file("default")

    if os.path.isfile(legacy_settings) and not os.path.isfile(default_settings):
        try:
            shutil.copy2(legacy_settings, default_settings)
            os.remove(legacy_settings)
            logger.info("Migrated legacy settings.ini to profiles/settings/default.ini")
        except OSError as e:
            logger.warning(f"Failed migrating legacy settings.ini: {e}")

    if os.path.isfile(legacy_token) and not os.path.isfile(default_token):
        try:
            shutil.copy2(legacy_token, default_token)
            os.remove(legacy_token)
            logger.info("Migrated legacy account.token to profiles/settings/default.account.token")
        except OSError as e:
            logger.warning(f"Failed migrating legacy account.token: {e}")

    if not os.path.isfile(default_settings):
        _write_default_settings_file(default_settings)

    profile_ids = {str(p.get("id", "")) for p in meta.get("profiles", [])}
    active = str(meta.get("active") or "default")
    if active not in profile_ids:
        meta["active"] = "default"
        meta_changed = True

    for p in meta.get("profiles", []):
        pid = str(p.get("id", "")).strip()
        if not pid:
            continue
        pfile = _profile_settings_file(pid)
        if not os.path.isfile(pfile):
            _write_default_settings_file(pfile)

    if meta_changed:
        _save_profiles_meta(meta)


def get_active_profile_id() -> str:
    ensure_profile_system_initialized()
    meta = _load_profiles_meta()
    return str(meta.get("active") or "default")


def list_profiles() -> list[dict[str, str]]:
    ensure_profile_system_initialized()
    meta = _load_profiles_meta()
    out: list[dict[str, str]] = []
    for p in meta.get("profiles", []):
        pid = str(p.get("id", "")).strip()
        name = str(p.get("name", "")).strip()
        if not pid or pid == PROFILE_ADD_SENTINEL:
            continue
        out.append({"id": pid, "name": name or pid})
    if not out:
        out.append({"id": "default", "name": "Default"})
    return out


def create_profile(name: str) -> dict[str, str]:
    ensure_profile_system_initialized()
    if not _is_valid_profile_name(name):
        raise ValueError("Profile name must be 1-32 characters")

    clean_name = str(name).strip()
    meta = _load_profiles_meta()
    existing = meta.get("profiles", [])
    if clean_name.lower() in {str(p.get("name", "")).strip().lower() for p in existing}:
        raise ValueError("A profile with this name already exists")

    base_id = safe_profile_id(clean_name)
    if not base_id:
        raise ValueError("Invalid profile name")

    existing_ids = {str(p.get("id", "")).strip() for p in existing}
    candidate = base_id
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base_id}-{suffix}"
        suffix += 1

    profile = {"id": candidate, "name": clean_name}
    meta.setdefault("profiles", []).append(profile)
    meta["active"] = candidate
    _save_profiles_meta(meta)

    settings_path = _profile_settings_file(candidate)
    if not os.path.isfile(settings_path):
        _write_default_settings_file(settings_path)
    return profile


def set_active_profile(profile_id: str) -> bool:
    ensure_profile_system_initialized()
    pid = safe_profile_id(profile_id)
    if not pid:
        return False
    meta = _load_profiles_meta()
    if pid not in {str(p.get("id", "")) for p in meta.get("profiles", [])}:
        return False
    meta["active"] = pid
    _save_profiles_meta(meta)

    settings_path = _profile_settings_file(pid)
    if not os.path.isfile(settings_path):
        _write_default_settings_file(settings_path)
    return True


def delete_profile(profile_id: str) -> bool:
    ensure_profile_system_initialized()
    pid = safe_profile_id(profile_id)
    if not pid:
        return False

    meta = _load_profiles_meta()
    profiles = meta.get("profiles", [])
    if len(profiles) <= 1 or pid == "default":
        return False
    if not any(str(p.get("id", "")) == pid for p in profiles):
        return False

    meta["profiles"] = [p for p in profiles if str(p.get("id", "")) != pid]
    if str(meta.get("active") or "") == pid:
        meta["active"] = "default"
    _save_profiles_meta(meta)

    for path in (_profile_settings_file(pid), _profile_token_file(pid)):
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
    return True


def rename_profile(profile_id: str, new_name: str) -> bool:
    ensure_profile_system_initialized()
    pid = safe_profile_id(profile_id)
    if not pid:
        return False
    if pid == "default":
        raise ValueError("The Default profile cannot be renamed")
    if not _is_valid_profile_name(new_name):
        raise ValueError("Profile name must be 1-32 characters")

    clean_name = str(new_name).strip()
    meta = _load_profiles_meta()
    profiles = meta.get("profiles", [])

    target = next((p for p in profiles if str(p.get("id", "")).strip() == pid), None)
    if target is None:
        return False

    other_names = {
        str(p.get("name", "")).strip().lower()
        for p in profiles
        if str(p.get("id", "")).strip() != pid
    }
    if clean_name.lower() in other_names:
        raise ValueError("A profile with this name already exists")

    target["name"] = clean_name
    _save_profiles_meta(meta)
    return True


# ---------------------------------------------------------------------------
# Filesystem accessors
# ---------------------------------------------------------------------------


def get_settings_path(profile_id: str | None = None) -> str:
    ensure_profile_system_initialized()
    pid = safe_profile_id(profile_id or get_active_profile_id())
    return _profile_settings_file(pid)


def get_token_path(profile_id: str | None = None) -> str:
    ensure_profile_system_initialized()
    pid = safe_profile_id(profile_id or get_active_profile_id())
    return _profile_token_file(pid)


def get_account_cache_path(profile_id: str | None = None) -> str:
    ensure_profile_system_initialized()
    pid = safe_profile_id(profile_id or get_active_profile_id())
    return os.path.join(get_profiles_settings_dir(), f"{pid}.account.cache.json")


# ---------------------------------------------------------------------------
# Scoped profile CRUD (versions/addons)
# ---------------------------------------------------------------------------


def list_scope_profiles(scope: str) -> list[dict[str, str]]:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        return list_profiles()

    ensure_scope_initialized(scope_norm)
    meta = _load_scope_meta(scope_norm)
    out: list[dict[str, str]] = []
    for p in meta.get("profiles", []):
        pid = str(p.get("id", "")).strip()
        name = str(p.get("name", "")).strip()
        if not pid or pid == PROFILE_ADD_SENTINEL:
            continue
        out.append({"id": pid, "name": name or pid})
    if not out:
        out.append({"id": "default", "name": "Default"})
    return out


def get_active_scope_profile_id(scope: str) -> str:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        return get_active_profile_id()

    ensure_scope_initialized(scope_norm)
    meta = _load_scope_meta(scope_norm)
    return str(meta.get("active") or "default")


def create_scope_profile(scope: str, name: str) -> dict[str, str]:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        return create_profile(name)

    ensure_scope_initialized(scope_norm)
    if not _is_valid_profile_name(name):
        raise ValueError("Profile name must be 1-32 characters")

    clean_name = str(name).strip()
    meta = _load_scope_meta(scope_norm)
    existing = meta.get("profiles", [])
    if clean_name.lower() in {str(p.get("name", "")).strip().lower() for p in existing}:
        raise ValueError("A profile with this name already exists")

    base_id = safe_profile_id(clean_name)
    if not base_id:
        raise ValueError("Invalid profile name")

    existing_ids = {str(p.get("id", "")).strip() for p in existing}
    candidate = base_id
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base_id}-{suffix}"
        suffix += 1

    profile = {"id": candidate, "name": clean_name}
    meta.setdefault("profiles", []).append(profile)
    meta["active"] = candidate
    _save_scope_meta(scope_norm, meta)
    _ensure_scope_profile_dirs(scope_norm, candidate)
    return profile


def set_active_scope_profile(scope: str, profile_id: str) -> bool:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        return set_active_profile(profile_id)

    ensure_scope_initialized(scope_norm)
    pid = safe_profile_id(profile_id)
    if not pid:
        return False
    meta = _load_scope_meta(scope_norm)
    if pid not in {str(p.get("id", "")) for p in meta.get("profiles", [])}:
        return False

    meta["active"] = pid
    _save_scope_meta(scope_norm, meta)
    _ensure_scope_profile_dirs(scope_norm, pid)
    return True


def delete_scope_profile(scope: str, profile_id: str) -> bool:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        return delete_profile(profile_id)

    ensure_scope_initialized(scope_norm)
    pid = safe_profile_id(profile_id)
    if not pid:
        return False
    meta = _load_scope_meta(scope_norm)
    profiles = meta.get("profiles", [])
    if len(profiles) <= 1 or pid == "default":
        return False
    if not any(str(p.get("id", "")) == pid for p in profiles):
        return False

    meta["profiles"] = [p for p in profiles if str(p.get("id", "")) != pid]
    if str(meta.get("active") or "") == pid:
        meta["active"] = "default"
    _save_scope_meta(scope_norm, meta)

    try:
        scope_root = os.path.join(_get_scope_base_dir(scope_norm), pid)
        if os.path.isdir(scope_root):
            shutil.rmtree(scope_root)
    except OSError:
        pass
    return True


def rename_scope_profile(scope: str, profile_id: str, new_name: str) -> bool:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        return rename_profile(profile_id, new_name)

    ensure_scope_initialized(scope_norm)
    pid = safe_profile_id(profile_id)
    if not pid:
        return False
    if pid == "default":
        raise ValueError("The Default profile cannot be renamed")
    if not _is_valid_profile_name(new_name):
        raise ValueError("Profile name must be 1-32 characters")

    clean_name = str(new_name).strip()
    meta = _load_scope_meta(scope_norm)
    profiles = meta.get("profiles", [])

    target = next((p for p in profiles if str(p.get("id", "")).strip() == pid), None)
    if target is None:
        return False

    other_names = {
        str(p.get("name", "")).strip().lower()
        for p in profiles
        if str(p.get("id", "")).strip() != pid
    }
    if clean_name.lower() in other_names:
        raise ValueError("A profile with this name already exists")

    target["name"] = clean_name
    _save_scope_meta(scope_norm, meta)
    return True


def get_versions_profile_dir(profile_id: str | None = None) -> str:
    ensure_scope_initialized("versions")
    pid = safe_profile_id(profile_id or get_active_scope_profile_id("versions"))
    path = os.path.join(_get_scope_base_dir("versions"), pid)
    os.makedirs(path, exist_ok=True)
    return path


def get_mods_profile_dir(profile_id: str | None = None) -> str:
    ensure_scope_initialized("addons")
    pid = safe_profile_id(profile_id or get_active_scope_profile_id("addons"))
    path = os.path.join(_get_scope_base_dir("addons"), pid)
    os.makedirs(path, exist_ok=True)
    return path
