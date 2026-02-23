# core/settings.py
import os

def get_base_dir():
    user = os.path.expanduser("~")
    base = os.path.join(user, ".histolauncher")
    os.makedirs(base, exist_ok=True)
    return base

def get_settings_path():
    return os.path.join(get_base_dir(), "settings.ini")

DEFAULTS = {
    "username": "Player",
    "account_type": "Local",
    "min_ram": "64M",
    "max_ram": "2048M",
    "selected_version": "",
    "url_proxy": "",
    "favorite_versions": "",
    "storage_directory": "global",
    "low_data_mode": "0",
    "signature_hash": "SHA256",
}

def load_global_settings():
    path = get_settings_path()
    data = {}

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    data[key.strip()] = value.strip()

    merged = dict(DEFAULTS)
    merged.update(data)
    return merged


def get_token_path():
    return os.path.join(get_base_dir(), "account.token")


def save_account_token(token):
    path = get_token_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        # Write security warning
        warning = b"# WARNING: DO NOT SHARE THIS TOKEN!\n# ANYONE THAT HAS HOLD OF IT CAN TAKE YOUR HISTOLAUNCHER ACCOUNT!\n# Keep this file secure and never share it with anyone.\n\n"
        f.write(warning)
        # Write the token
        if isinstance(token, str):
            token_bytes = token.encode("utf-8")
        else:
            token_bytes = bytes(token)
        f.write(token_bytes)
    try:
        os.replace(tmp, path)
    except Exception:
        os.remove(tmp)
        raise
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def load_account_token():
    path = get_token_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
            try:
                text = data.decode("utf-8")
                # Skip warning comment lines at the beginning
                lines = text.split('\n')
                token_line = None
                for line in lines:
                    stripped = line.strip()
                    # Skip empty lines and comment lines (warnings)
                    if stripped and not stripped.startswith('#'):
                        token_line = stripped
                        break
                return token_line if token_line else text
            except Exception:
                return data
    except Exception:
        return None


def clear_account_token():
    path = get_token_path()
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


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
    path = get_settings_path()
    current = load_global_settings()
    current.update(settings_dict)

    keys = list(DEFAULTS.keys())
    extra_keys = sorted(k for k in current.keys() if k not in DEFAULTS)
    all_keys = keys + extra_keys

    lines = []
    for k in all_keys:
        v = current.get(k, "")
        lines.append(f"{k} = {v}")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
def save_session_token(token: str):
    """Save Cloudflare session token for authenticated accounts."""
    save_account_token(token)


def load_session_token() -> str | None:
    """Load Cloudflare session token for authenticated accounts."""
    return load_account_token()


def clear_session_token():
    """Clear Cloudflare session token when logging out."""
    clear_account_token()

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
