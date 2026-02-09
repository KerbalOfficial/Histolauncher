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
    "min_ram": "64M",
    "max_ram": "2048M",
    "selected_version": "",
    "url_proxy": "",
    "favorite_versions": "",
    "storage_directory": "global",
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
