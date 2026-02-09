# core/version_manager.py
import os
import time

from core.settings import get_base_dir

_CACHE = None
_CACHE_TS = 0
_CACHE_TTL = 2.0


def get_clients_dir():
    return os.path.join(get_base_dir(), "clients")


def _read_data_ini(path):
    if not os.path.exists(path):
        return {}
    cfg = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def _normalize_category_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return ""
    # Simple rule: first letter uppercase, rest lowercase
    return n[0].upper() + n[1:].lower()


def _scan_once():
    clients_dir = get_clients_dir()
    results = {}
    if not os.path.isdir(clients_dir):
        return results

    base_dir = get_base_dir()

    for raw_category in sorted(os.listdir(clients_dir)):
        cat_path = os.path.join(clients_dir, raw_category)
        if not os.path.isdir(cat_path):
            continue

        category = _normalize_category_name(raw_category)
        versions = results.setdefault(category, [])

        for version in sorted(os.listdir(cat_path)):
            vpath = os.path.join(cat_path, version)
            if not os.path.isdir(vpath):
                continue
            meta = _read_data_ini(os.path.join(vpath, "data.ini"))
            display_name = meta.get("display_name") or version
            main_class = meta.get("main_class") or "net.minecraft.client.Minecraft"
            classpath = meta.get("classpath") or "client.jar"
            native_subfolder = meta.get("native_subfolder") or ""

            raw_disabled = meta.get("launch_disabled", "").strip()
            launch_disabled = False
            launch_disabled_message = ""
            if raw_disabled:
                parts = raw_disabled.split(",", 1)
                flag = parts[0].strip().lower()
                launch_disabled = flag in ("1", "true", "yes")
                if len(parts) > 1:
                    msg = parts[1].strip()
                    if (msg.startswith('"') and msg.endswith('"')) or (msg.startswith("'") and msg.endswith("'")):
                        msg = msg[1:-1]
                    launch_disabled_message = msg

            versions.append({
                "folder": version,
                "display_name": display_name,
                "main_class": main_class,
                "classpath": [p.strip() for p in classpath.split(",") if p.strip()],
                "native_subfolder": native_subfolder,
                "path": os.path.relpath(vpath, base_dir),
                "category": category,
                "launch_disabled": launch_disabled,
                "launch_disabled_message": launch_disabled_message
            })

    all_versions = []
    for cat, vers in results.items():
        all_versions.extend(vers)
    all_versions = sorted(all_versions, key=lambda v: (v.get("category", ""), v.get("folder", "")))
    results["* All"] = all_versions
    return results


def scan_categories(force_refresh=False):
    global _CACHE, _CACHE_TS
    now = time.time()
    if force_refresh or _CACHE is None or (now - _CACHE_TTL) > _CACHE_TTL:
        _CACHE = _scan_once()
        _CACHE_TS = now
    return _CACHE or {}
