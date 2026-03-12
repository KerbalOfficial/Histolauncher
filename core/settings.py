# core/settings.py

import os
import configparser
import logging

logger = logging.getLogger(__name__)

def get_base_dir():
    user = os.path.expanduser("~")
    base = os.path.join(user, ".histolauncher")
    os.makedirs(base, exist_ok=True)
    return base

def get_settings_path():
    return os.path.join(get_base_dir(), "settings.ini")

DEFAULTS = {
    "account": {
        "username": "Player" + str(os.getpid()%10000),
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

def load_global_settings():
    path = get_settings_path()
    data = {}

    if os.path.exists(path):
        try:
            config = configparser.ConfigParser()
            config.read(path, encoding="utf-8")
            
            # Try new format: read from all sections
            for section in config.sections():
                data.update(dict(config[section]))
                
        except (configparser.MissingSectionHeaderError, configparser.ParsingError):
            # Old format without section headers - parse manually as flat key-value
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

    # Remove deprecated keys
    for deprecated_key in DEPRECATED_KEYS:
        data.pop(deprecated_key, None)

    # Flatten defaults and merge with loaded data
    merged = {}
    for section, defaults in DEFAULTS.items():
        merged.update(defaults)
    merged.update(data)
    
    return merged


def get_token_path():
    return os.path.join(get_base_dir(), "account.token")


def save_account_token(token):
    """Save account token securely with atomic write and proper error handling."""
    try:
        path = get_token_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        
        with open(tmp, "wb") as f:
            f.write(b"# WARNING: DO NOT SHARE THIS TOKEN!\n# ANYONE THAT HAS HOLD OF IT CAN TAKE YOUR HISTOLAUNCHER ACCOUNT!\n\n# Keep this file secure and never share it with anyone!!!\n")
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
            # File permissions may not be supported on all systems
            logger.debug(f"Could not set file permissions for token file: {path}")
    except IOError as e:
        logger.error(f"Failed to save account token: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error saving account token: {e}")
        raise


def load_account_token():
    """Load account token from file with proper error handling."""
    path = get_token_path()
    if not os.path.exists(path):
        return None
    
    try:
        with open(path, "rb") as f:
            data = f.read()
            try:
                text = data.decode("utf-8")
                lines = text.split('\n')
                token_line = None
                for line in lines:
                    stripped = line.strip()
                    if stripped and not stripped.startswith('#'):
                        token_line = stripped
                        break
                return token_line if token_line else None
            except UnicodeDecodeError:
                # Token file may be binary or corrupted
                logger.warning("Account token file appears to be corrupted")
                return None
    except IOError as e:
        logger.error(f"Failed to read account token: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error loading account token: {e}")
        return None


def clear_account_token():
    """Remove account token file with proper error handling."""
    path = get_token_path()
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.debug(f"Account token cleared: {path}")
    except IOError as e:
        logger.error(f"Failed to clear account token: {e}")
    except Exception as e:
        logger.error(f"Unexpected error clearing account token: {e}")


def get_account_type():
    path = get_settings_path()
    cfg = load_global_settings() or {}
    return (cfg.get("account_type") or "Local").strip()


def set_account_type(value: str):
    if not isinstance(value, str):
        raise TypeError("account type must be a string")
    v = value.strip() or "Local"
    save_global_settings({"account_type": v})


def save_global_settings(settings_dict):
    """Save settings to organized ini sections for clarity and maintainability."""
    path = get_settings_path()
    current = load_global_settings()
    current.update(settings_dict)

    config = configparser.ConfigParser()
    
    # Save to organized sections
    for section, defaults in DEFAULTS.items():
        config[section] = {}
        for key in defaults:
            v = str(current.get(key, defaults[key]))
            config[section][key] = v
    
    # Add any extra keys that aren't in DEFAULTS (for future extensibility)
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
    
    # Write to a temporary file first (atomic write)
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


def load_version_data(version_dir):
    data_path = os.path.join(version_dir, "data.ini")
    if not os.path.exists(data_path):
        return None

    data = {}
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
