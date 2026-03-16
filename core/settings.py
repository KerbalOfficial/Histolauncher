# core/settings.py

import configparser
import json
import logging
import os
import re
import shutil

from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


DEFAULTS = {
    "account": {
        "username": "Player" + str(os.getpid() % 10000),
        "account_type": "Local",
    },
    "client": {
        "min_ram": "2048M",
        "max_ram": "4096M",
        "extra_jvm_args": "",
        "selected_version": "",
        "favorite_versions": "",
        "storage_directory": "global",
    },
    "launcher": {
        "java_path": "",
        "url_proxy": "",
        "low_data_mode": "0",
        "fast_download": "0",
        "ygg_port": "25565",
        "versions_view": "grid",  # or "list"
        "mods_view": "list",  # or "grid"
    },
}

# Deprecated settings to ignore when loading from old files
DEPRECATED_KEYS = {"signature_hash"}

_MAX_PROFILE_NAME_LEN = 32
_MAX_PROFILE_ID_LEN = 48
_PROFILE_ADD_SENTINEL = "__add_new_profile__"
_PROFILE_SCOPES = {"settings", "versions", "mods"}


def get_base_dir() -> str:
    user = os.path.expanduser("~")
    base = os.path.join(user, ".histolauncher")
    os.makedirs(base, exist_ok=True)
    return base


def _get_profiles_settings_dir() -> str:
    path = os.path.join(get_base_dir(), "profiles", "settings")
    os.makedirs(path, exist_ok=True)
    return path


def _get_profiles_meta_path() -> str:
    return os.path.join(_get_profiles_settings_dir(), "profiles.json")


def _safe_profile_id(name: str) -> str:
    raw = str(name or "").strip().lower()
    raw = raw.replace(" ", "-")
    raw = re.sub(r"[^a-z0-9_-]+", "", raw)
    raw = raw.strip("-_")
    if not raw:
        raw = "profile"
    return raw[:_MAX_PROFILE_ID_LEN]


def _default_meta() -> Dict[str, Any]:
    return {
        "active": "default",
        "profiles": [
            {"id": "default", "name": "Default"},
        ],
    }


def _write_default_settings_file(path: str) -> None:
    config = configparser.ConfigParser()
    for section, defaults in DEFAULTS.items():
        config[section] = {k: str(v) for k, v in defaults.items()}
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        config.write(f)
    os.replace(tmp_path, path)


def _load_profiles_meta() -> Dict[str, Any]:
    meta_path = _get_profiles_meta_path()
    if not os.path.exists(meta_path):
        return _default_meta()
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _default_meta()
        profiles = data.get("profiles")
        active = data.get("active")
        if not isinstance(profiles, list) or not isinstance(active, str):
            return _default_meta()
        return data
    except Exception:
        return _default_meta()


def _save_profiles_meta(meta: Dict[str, Any]) -> None:
    meta_path = _get_profiles_meta_path()
    tmp_path = meta_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    os.replace(tmp_path, meta_path)


def _profile_settings_file(profile_id: str) -> str:
    safe_id = _safe_profile_id(profile_id)
    return os.path.join(_get_profiles_settings_dir(), f"{safe_id}.ini")


def _profile_token_file(profile_id: str) -> str:
    safe_id = _safe_profile_id(profile_id)
    return os.path.join(_get_profiles_settings_dir(), f"{safe_id}.account.token")


def _normalize_scope(scope: str) -> str:
    s = str(scope or "").strip().lower()
    if s not in _PROFILE_SCOPES:
        raise ValueError(f"Unsupported profile scope: {scope}")
    return s


def _get_scope_base_dir(scope: str) -> str:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        return _get_profiles_settings_dir()
    path = os.path.join(get_base_dir(), "profiles", scope_norm)
    os.makedirs(path, exist_ok=True)
    return path


def _get_scope_meta_path(scope: str) -> str:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        return _get_profiles_meta_path()
    return os.path.join(_get_scope_base_dir(scope_norm), "profiles.json")


def _load_scope_meta(scope: str) -> Dict[str, Any]:
    meta_path = _get_scope_meta_path(scope)
    if not os.path.exists(meta_path):
        return _default_meta()
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _default_meta()
        profiles = data.get("profiles")
        active = data.get("active")
        if not isinstance(profiles, list) or not isinstance(active, str):
            return _default_meta()
        return data
    except Exception:
        return _default_meta()


def _save_scope_meta(scope: str, meta: Dict[str, Any]) -> None:
    meta_path = _get_scope_meta_path(scope)
    tmp_path = meta_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    os.replace(tmp_path, meta_path)


def _ensure_scope_profile_dirs(scope: str, profile_id: str) -> None:
    scope_norm = _normalize_scope(scope)
    pid = _safe_profile_id(profile_id)
    if scope_norm == "versions":
        os.makedirs(os.path.join(_get_scope_base_dir(scope_norm), pid), exist_ok=True)
        return
    if scope_norm == "mods":
        root = os.path.join(_get_scope_base_dir(scope_norm), pid)
        os.makedirs(os.path.join(root, "mods"), exist_ok=True)
        os.makedirs(os.path.join(root, "modpacks"), exist_ok=True)
        return


def _migrate_scope_from_legacy(scope: str) -> None:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "versions":
        legacy_clients = os.path.join(get_base_dir(), "clients")
        default_root = os.path.join(_get_scope_base_dir(scope_norm), "default")
        if os.path.isdir(legacy_clients) and not os.path.exists(default_root):
            try:
                shutil.move(legacy_clients, default_root)
                logger.info("Migrated legacy clients/ to profiles/versions/default/")
            except Exception as e:
                logger.warning(f"Failed migrating legacy clients directory: {e}")
        return

    if scope_norm == "mods":
        legacy_mods = os.path.join(get_base_dir(), "mods")
        legacy_modpacks = os.path.join(get_base_dir(), "modpacks")
        default_root = os.path.join(_get_scope_base_dir(scope_norm), "default")
        default_mods = os.path.join(default_root, "mods")
        default_modpacks = os.path.join(default_root, "modpacks")

        if os.path.isdir(legacy_mods) and not os.path.exists(default_mods):
            try:
                os.makedirs(default_root, exist_ok=True)
                shutil.move(legacy_mods, default_mods)
                logger.info("Migrated legacy mods/ to profiles/mods/default/mods/")
            except Exception as e:
                logger.warning(f"Failed migrating legacy mods directory: {e}")

        if os.path.isdir(legacy_modpacks) and not os.path.exists(default_modpacks):
            try:
                os.makedirs(default_root, exist_ok=True)
                shutil.move(legacy_modpacks, default_modpacks)
                logger.info("Migrated legacy modpacks/ to profiles/mods/default/modpacks/")
            except Exception as e:
                logger.warning(f"Failed migrating legacy modpacks directory: {e}")
        return


def _ensure_scope_initialized(scope: str) -> None:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        _ensure_profile_system_initialized()
        return

    _get_scope_base_dir(scope_norm)
    meta = _load_scope_meta(scope_norm)

    if not any(str(p.get("id", "")) == "default" for p in meta.get("profiles", [])):
        meta.setdefault("profiles", []).insert(0, {"id": "default", "name": "Default"})

    _migrate_scope_from_legacy(scope_norm)

    profile_ids = {str(p.get("id", "")) for p in meta.get("profiles", [])}
    active = str(meta.get("active") or "default")
    if active not in profile_ids:
        meta["active"] = "default"

    for p in meta.get("profiles", []):
        pid = str(p.get("id", "")).strip()
        if not pid:
            continue
        _ensure_scope_profile_dirs(scope_norm, pid)

    _save_scope_meta(scope_norm, meta)


def _ensure_profile_system_initialized() -> None:
    _get_profiles_settings_dir()
    meta = _load_profiles_meta()

    # Ensure required default profile entry exists.
    if not any(str(p.get("id", "")) == "default" for p in meta.get("profiles", [])):
        meta.setdefault("profiles", []).insert(0, {"id": "default", "name": "Default"})

    # Migrate legacy single-profile files.
    legacy_settings = os.path.join(get_base_dir(), "settings.ini")
    legacy_token = os.path.join(get_base_dir(), "account.token")

    default_settings = _profile_settings_file("default")
    default_token = _profile_token_file("default")

    if os.path.isfile(legacy_settings) and not os.path.isfile(default_settings):
        try:
            shutil.copy2(legacy_settings, default_settings)
            os.remove(legacy_settings)
            logger.info("Migrated legacy settings.ini to profiles/settings/default.ini")
        except Exception as e:
            logger.warning(f"Failed migrating legacy settings.ini: {e}")

    if os.path.isfile(legacy_token) and not os.path.isfile(default_token):
        try:
            shutil.copy2(legacy_token, default_token)
            os.remove(legacy_token)
            logger.info("Migrated legacy account.token to profiles/settings/default.account.token")
        except Exception as e:
            logger.warning(f"Failed migrating legacy account.token: {e}")

    # Ensure default settings exists.
    if not os.path.isfile(default_settings):
        _write_default_settings_file(default_settings)

    # Ensure active profile is valid.
    profile_ids = {str(p.get("id", "")) for p in meta.get("profiles", [])}
    active = str(meta.get("active") or "default")
    if active not in profile_ids:
        meta["active"] = "default"

    # Ensure each profile has a settings file.
    for p in meta.get("profiles", []):
        pid = str(p.get("id", "")).strip()
        if not pid:
            continue
        pfile = _profile_settings_file(pid)
        if not os.path.isfile(pfile):
            _write_default_settings_file(pfile)

    _save_profiles_meta(meta)


def get_active_profile_id() -> str:
    _ensure_profile_system_initialized()
    meta = _load_profiles_meta()
    return str(meta.get("active") or "default")


def list_profiles() -> List[Dict[str, str]]:
    _ensure_profile_system_initialized()
    meta = _load_profiles_meta()
    out: List[Dict[str, str]] = []
    for p in meta.get("profiles", []):
        pid = str(p.get("id", "")).strip()
        name = str(p.get("name", "")).strip()
        if not pid or pid == _PROFILE_ADD_SENTINEL:
            continue
        if not name:
            name = pid
        out.append({"id": pid, "name": name})
    if not out:
        out.append({"id": "default", "name": "Default"})
    return out


def _is_valid_profile_name(name: str) -> bool:
    if not isinstance(name, str):
        return False
    n = name.strip()
    return 1 <= len(n) <= _MAX_PROFILE_NAME_LEN


def create_profile(name: str) -> Dict[str, str]:
    _ensure_profile_system_initialized()
    if not _is_valid_profile_name(name):
        raise ValueError("Profile name must be 1-32 characters")

    clean_name = str(name).strip()
    meta = _load_profiles_meta()
    existing = meta.get("profiles", [])
    existing_names = {str(p.get("name", "")).strip().lower() for p in existing}
    if clean_name.lower() in existing_names:
        raise ValueError("A profile with this name already exists")

    base_id = _safe_profile_id(clean_name)
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
    _ensure_profile_system_initialized()
    pid = _safe_profile_id(profile_id)
    if not pid:
        return False
    meta = _load_profiles_meta()
    profile_ids = {str(p.get("id", "")) for p in meta.get("profiles", [])}
    if pid not in profile_ids:
        return False
    meta["active"] = pid
    _save_profiles_meta(meta)

    # Ensure settings file exists for selected profile.
    settings_path = _profile_settings_file(pid)
    if not os.path.isfile(settings_path):
        _write_default_settings_file(settings_path)
    return True


def delete_profile(profile_id: str) -> bool:
    _ensure_profile_system_initialized()
    pid = _safe_profile_id(profile_id)
    if not pid:
        return False

    meta = _load_profiles_meta()
    profiles = meta.get("profiles", [])
    if len(profiles) <= 1:
        # Must always keep at least one profile.
        return False

    # Keep Default undeletable as an always-safe fallback profile.
    if pid == "default":
        return False

    exists = any(str(p.get("id", "")) == pid for p in profiles)
    if not exists:
        return False

    meta["profiles"] = [p for p in profiles if str(p.get("id", "")) != pid]

    if str(meta.get("active") or "") == pid:
        meta["active"] = "default"

    _save_profiles_meta(meta)

    try:
        p_settings = _profile_settings_file(pid)
        if os.path.isfile(p_settings):
            os.remove(p_settings)
    except Exception:
        pass

    try:
        p_token = _profile_token_file(pid)
        if os.path.isfile(p_token):
            os.remove(p_token)
    except Exception:
        pass

    return True


def rename_profile(profile_id: str, new_name: str) -> bool:
    _ensure_profile_system_initialized()
    pid = _safe_profile_id(profile_id)
    if not pid:
        return False

    if pid == 'default':
        raise ValueError("The Default profile cannot be renamed")

    if not _is_valid_profile_name(new_name):
        raise ValueError("Profile name must be 1-32 characters")

    clean_name = str(new_name).strip()
    meta = _load_profiles_meta()
    profiles = meta.get("profiles", [])

    target = None
    for p in profiles:
                if str(p.get("id", "")).strip() == pid:
                        target = p
                        break
    if target is None:
        return False

    existing_names = {
        str(p.get("name", "")).strip().lower()
        for p in profiles
        if str(p.get("id", "")).strip() != pid
    }
    if clean_name.lower() in existing_names:
        raise ValueError("A profile with this name already exists")

    target["name"] = clean_name
    _save_profiles_meta(meta)
    return True


def get_settings_path(profile_id: Optional[str] = None) -> str:
    _ensure_profile_system_initialized()
    pid = _safe_profile_id(profile_id or get_active_profile_id())
    return _profile_settings_file(pid)


def get_token_path(profile_id: Optional[str] = None) -> str:
    _ensure_profile_system_initialized()
    pid = _safe_profile_id(profile_id or get_active_profile_id())
    return _profile_token_file(pid)


def list_scope_profiles(scope: str) -> List[Dict[str, str]]:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        return list_profiles()

    _ensure_scope_initialized(scope_norm)
    meta = _load_scope_meta(scope_norm)
    out: List[Dict[str, str]] = []
    for p in meta.get("profiles", []):
        pid = str(p.get("id", "")).strip()
        name = str(p.get("name", "")).strip()
        if not pid or pid == _PROFILE_ADD_SENTINEL:
            continue
        out.append({"id": pid, "name": name or pid})
    if not out:
        out.append({"id": "default", "name": "Default"})
    return out


def get_active_scope_profile_id(scope: str) -> str:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        return get_active_profile_id()

    _ensure_scope_initialized(scope_norm)
    meta = _load_scope_meta(scope_norm)
    return str(meta.get("active") or "default")


def create_scope_profile(scope: str, name: str) -> Dict[str, str]:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        return create_profile(name)

    _ensure_scope_initialized(scope_norm)
    if not _is_valid_profile_name(name):
        raise ValueError("Profile name must be 1-32 characters")

    clean_name = str(name).strip()
    meta = _load_scope_meta(scope_norm)
    existing = meta.get("profiles", [])
    existing_names = {str(p.get("name", "")).strip().lower() for p in existing}
    if clean_name.lower() in existing_names:
        raise ValueError("A profile with this name already exists")

    base_id = _safe_profile_id(clean_name)
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

    _ensure_scope_initialized(scope_norm)
    pid = _safe_profile_id(profile_id)
    if not pid:
        return False
    meta = _load_scope_meta(scope_norm)
    profile_ids = {str(p.get("id", "")) for p in meta.get("profiles", [])}
    if pid not in profile_ids:
        return False

    meta["active"] = pid
    _save_scope_meta(scope_norm, meta)
    _ensure_scope_profile_dirs(scope_norm, pid)
    return True


def delete_scope_profile(scope: str, profile_id: str) -> bool:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        return delete_profile(profile_id)

    _ensure_scope_initialized(scope_norm)
    pid = _safe_profile_id(profile_id)
    if not pid:
        return False
    meta = _load_scope_meta(scope_norm)
    profiles = meta.get("profiles", [])
    if len(profiles) <= 1:
        return False
    if pid == "default":
        return False

    exists = any(str(p.get("id", "")) == pid for p in profiles)
    if not exists:
        return False

    meta["profiles"] = [p for p in profiles if str(p.get("id", "")) != pid]
    if str(meta.get("active") or "") == pid:
        meta["active"] = "default"
    _save_scope_meta(scope_norm, meta)

    try:
        scope_root = os.path.join(_get_scope_base_dir(scope_norm), pid)
        if os.path.isdir(scope_root):
            shutil.rmtree(scope_root)
    except Exception:
        pass

    return True


def rename_scope_profile(scope: str, profile_id: str, new_name: str) -> bool:
    scope_norm = _normalize_scope(scope)
    if scope_norm == "settings":
        return rename_profile(profile_id, new_name)

    _ensure_scope_initialized(scope_norm)
    pid = _safe_profile_id(profile_id)
    if not pid:
        return False

    if pid == 'default':
        raise ValueError("The Default profile cannot be renamed")

    if not _is_valid_profile_name(new_name):
        raise ValueError("Profile name must be 1-32 characters")

    clean_name = str(new_name).strip()
    meta = _load_scope_meta(scope_norm)
    profiles = meta.get("profiles", [])

    target = None
    for p in profiles:
        if str(p.get("id", "")).strip() == pid:
            target = p
            break
    if target is None:
        return False

    existing_names = {
        str(p.get("name", "")).strip().lower()
        for p in profiles
        if str(p.get("id", "")).strip() != pid
    }
    if clean_name.lower() in existing_names:
        raise ValueError("A profile with this name already exists")

    target["name"] = clean_name
    _save_scope_meta(scope_norm, meta)
    return True


def get_versions_profile_dir(profile_id: Optional[str] = None) -> str:
    _ensure_scope_initialized("versions")
    pid = _safe_profile_id(profile_id or get_active_scope_profile_id("versions"))
    path = os.path.join(_get_scope_base_dir("versions"), pid)
    os.makedirs(path, exist_ok=True)
    return path


def get_mods_profile_dir(profile_id: Optional[str] = None) -> str:
    _ensure_scope_initialized("mods")
    pid = _safe_profile_id(profile_id or get_active_scope_profile_id("mods"))
    path = os.path.join(_get_scope_base_dir("mods"), pid)
    os.makedirs(path, exist_ok=True)
    return path


def load_global_settings(profile_id: Optional[str] = None) -> Dict[str, Any]:
    path = get_settings_path(profile_id)
    data: Dict[str, Any] = {}

    if os.path.exists(path):
        try:
            config = configparser.ConfigParser()
            config.read(path, encoding="utf-8")

            # New format: read from all sections.
            for section in config.sections():
                data.update(dict(config[section]))

        except (configparser.MissingSectionHeaderError, configparser.ParsingError):
            # Legacy format without section headers.
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, value = line.split("=", 1)
                            data[key.strip()] = value.strip()
                logger.info(f"Migrated legacy settings format from {path}")
            except Exception as e:
                logger.warning(f"Failed to parse legacy settings file: {e}")
                data = {}
        except Exception as e:
            logger.warning(f"Failed to parse settings file, using defaults: {e}")
            data = {}

    for deprecated_key in DEPRECATED_KEYS:
        data.pop(deprecated_key, None)

    merged: Dict[str, Any] = {}
    for _, defaults in DEFAULTS.items():
        merged.update(defaults)
    merged.update(data)

    return merged


def save_account_token(token: Any, profile_id: Optional[str] = None) -> None:
    """Save account token securely with atomic write and proper error handling."""
    try:
        path = get_token_path(profile_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"

        with open(tmp, "wb") as f:
            f.write(
                b"# WARNING: DO NOT SHARE THIS TOKEN!\n"
                b"# ANYONE THAT HAS HOLD OF IT CAN TAKE YOUR HISTOLAUNCHER ACCOUNT!\n\n"
                b"# Keep this file secure and never share it with anyone!!!\n"
            )
            if isinstance(token, str):
                token_bytes = token.encode("utf-8")
            else:
                token_bytes = bytes(token)
            f.write(token_bytes)

        try:
            os.replace(tmp, path)
        except OSError:
            os.remove(tmp)
            raise

        try:
            os.chmod(path, 0o600)
        except OSError:
            logger.debug(f"Could not set file permissions for token file: {path}")
    except IOError as e:
        logger.error(f"Failed to save account token: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error saving account token: {e}")
        raise


def load_account_token(profile_id: Optional[str] = None) -> Optional[str]:
    """Load account token from file with proper error handling."""
    path = get_token_path(profile_id)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "rb") as f:
            data = f.read()
            try:
                text = data.decode("utf-8")
                lines = text.split("\n")
                token_line = None
                for line in lines:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        token_line = stripped
                        break
                return token_line if token_line else None
            except UnicodeDecodeError:
                logger.warning("Account token file appears to be corrupted")
                return None
    except IOError as e:
        logger.error(f"Failed to read account token: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error loading account token: {e}")
        return None


def clear_account_token(profile_id: Optional[str] = None) -> None:
    """Remove account token file with proper error handling."""
    path = get_token_path(profile_id)
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.debug(f"Account token cleared: {path}")
    except IOError as e:
        logger.error(f"Failed to clear account token: {e}")
    except Exception as e:
        logger.error(f"Unexpected error clearing account token: {e}")


def get_account_type(profile_id: Optional[str] = None) -> str:
    cfg = load_global_settings(profile_id) or {}
    return (cfg.get("account_type") or "Local").strip()


def set_account_type(value: str, profile_id: Optional[str] = None) -> None:
    if not isinstance(value, str):
        raise TypeError("account type must be a string")
    v = value.strip() or "Local"
    save_global_settings({"account_type": v}, profile_id=profile_id)


def save_global_settings(settings_dict: Dict[str, Any], profile_id: Optional[str] = None) -> None:
    """Save settings to organized INI sections for clarity and maintainability."""
    path = get_settings_path(profile_id)
    current = load_global_settings(profile_id)
    current.update(settings_dict)

    config = configparser.ConfigParser()

    for section, defaults in DEFAULTS.items():
        config[section] = {}
        for key in defaults:
            v = str(current.get(key, defaults[key]))
            config[section][key] = v

    all_default_keys = set()
    for section_defaults in DEFAULTS.values():
        all_default_keys.update(section_defaults.keys())

    extra_keys = {k: v for k, v in current.items() if k not in all_default_keys}
    if extra_keys:
        if "launcher" not in config:
            config["launcher"] = {}
        for key, value in extra_keys.items():
            config["launcher"][key] = str(value)

    os.makedirs(os.path.dirname(path), exist_ok=True)

    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            config.write(f)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        raise


def load_version_data(version_dir: str) -> Optional[Dict[str, str]]:
    data_path = os.path.join(version_dir, "data.ini")
    if not os.path.exists(data_path):
        return None

    data: Dict[str, str] = {}
    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip()
    return data


def _get_url_proxy_prefix() -> str:
    """Get the configured URL proxy prefix from settings."""
    try:
        cfg = load_global_settings()
        return (cfg.get("url_proxy") or "").strip()
    except Exception:
        return ""


def _apply_url_proxy(url: str) -> str:
    """Apply URL proxy prefix if configured, otherwise return URL unchanged."""
    prefix = _get_url_proxy_prefix()
    if not prefix:
        return url
    return prefix + url
