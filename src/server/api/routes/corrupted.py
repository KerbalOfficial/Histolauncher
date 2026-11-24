from __future__ import annotations

import os
import shutil
from concurrent.futures import ThreadPoolExecutor

from core import manifest
from core.logger import safe_print
from core.version_manager import _read_data_ini, get_clients_dir, scan_categories

from server.api._helpers import _resolve_version_dir_secure
from server.api._state import STATE
from server.api._validation import _validate_category_string, _validate_version_string
from server.api.routes.versions import invalidate_available_versions_cache


__all__ = ["api_corrupted_versions", "api_delete_corrupted_versions", "api_vulnerable_versions"]


def _freetype_jars(names) -> set:
    return {n for n in names if n.startswith("lwjgl-freetype-") and "-natives-" not in n}


def _is_outdated_install(version_id: str, classpath: list) -> bool:
    installed = _freetype_jars(classpath)
    try:
        entry = manifest.get_version_entry(version_id)
        vjson = manifest.fetch_version_json(entry["url"])
    except Exception:
        return False
    official = _freetype_jars(
        os.path.basename(((lib.get("downloads") or {}).get("artifact") or {}).get("path") or "")
        for lib in vjson.get("libraries") or []
        if isinstance(lib, dict) and str(lib.get("name") or "").count(":") == 2
    )
    has_core = any(
        n.startswith("lwjgl-") and n[6:7].isdigit() and "-natives-" not in n for n in classpath
    )
    return installed != official or not has_core


def api_vulnerable_versions():
    if STATE.vulnerable_versions_checked:
        return {"ok": True, "vulnerable": []}
    STATE.vulnerable_versions_checked = True

    candidates = []
    clients_dir = get_clients_dir()
    for category_name in os.listdir(clients_dir) if os.path.isdir(clients_dir) else []:
        category_path = os.path.join(clients_dir, category_name)
        if not os.path.isdir(category_path):
            continue
        for version_folder in os.listdir(category_path):
            meta = _read_data_ini(os.path.join(category_path, version_folder, "data.ini"))
            classpath = [c.strip() for c in (meta.get("classpath") or "").split(",") if c.strip()]
            if _freetype_jars(classpath):
                candidates.append((category_name, version_folder, meta, classpath))

    with ThreadPoolExecutor(max_workers=8) as pool:
        flags = list(pool.map(lambda c: _is_outdated_install(c[1], c[3]), candidates))

    vulnerable = [
        {
            "category": category,
            "folder": folder,
            "full_assets": str(meta.get("full_assets", "true")).lower() == "true",
        }
        for (category, folder, meta, _), flagged in zip(candidates, flags)
        if flagged
    ]
    return {"ok": True, "vulnerable": vulnerable}


def api_corrupted_versions():
    if STATE.corrupted_versions_checked:
        return {"ok": True, "corrupted": []}

    try:
        corrupted = []

        clients_dir = get_clients_dir()

        if not os.path.isdir(clients_dir):
            STATE.corrupted_versions_checked = True
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
                        "full_path": version_path,
                    })

        STATE.corrupted_versions_checked = True
        return {"ok": True, "corrupted": corrupted}

    except Exception as e:
        import traceback

        traceback.print_exc()
        STATE.corrupted_versions_checked = True
        return {"ok": False, "error": str(e), "corrupted": []}


def api_delete_corrupted_versions(data):
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid request"}

    versions_to_delete = data.get("versions", [])
    if not isinstance(versions_to_delete, list):
        return {"ok": False, "error": "versions must be an array"}

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

            if not _validate_category_string(category) or not _validate_version_string(folder):
                failed.append({
                    "error": "invalid category or folder",
                    "category": category,
                    "folder": folder,
                })
                continue

            resolved = _resolve_version_dir_secure(category, folder)
            if not resolved.get("ok"):
                failed.append({
                    "error": resolved.get("error") or "directory not found",
                    "category": category,
                    "folder": folder,
                })
                continue

            version_path = resolved.get("path") or ""

            try:
                shutil.rmtree(version_path)
                deleted.append({"category": category, "folder": folder})
                safe_print(f"[api] Deleted corrupted version: {category}/{folder}")
            except Exception as e:
                failed.append({"error": str(e), "category": category, "folder": folder})

        try:
            scan_categories(force_refresh=True)
            invalidate_available_versions_cache()
        except Exception:
            pass

        return {"ok": True, "deleted": deleted, "failed": failed}

    except Exception as e:
        import traceback

        traceback.print_exc()
        return {"ok": False, "error": str(e)}
