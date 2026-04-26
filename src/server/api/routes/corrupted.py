from __future__ import annotations

import os
import shutil

from core.logger import colorize_log
from core.version_manager import get_clients_dir, scan_categories

from server.api._helpers import _is_path_within
from server.api._state import STATE
from server.api._validation import _validate_category_string, _validate_version_string


__all__ = ["api_corrupted_versions", "api_delete_corrupted_versions"]


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

            if not _validate_category_string(category) or not _validate_version_string(folder):
                failed.append({
                    "error": "invalid category or folder",
                    "category": category,
                    "folder": folder,
                })
                continue

            version_path = os.path.join(clients_dir, category, folder)

            if not _is_path_within(clients_dir, version_path):
                failed.append({
                    "error": "invalid path",
                    "category": category,
                    "folder": folder,
                })
                continue

            if not os.path.isdir(version_path):
                failed.append({
                    "error": "directory not found",
                    "category": category,
                    "folder": folder,
                })
                continue

            try:
                shutil.rmtree(version_path)
                deleted.append({"category": category, "folder": folder})
                print(colorize_log(f"[api] Deleted corrupted version: {category}/{folder}"))
            except Exception as e:
                failed.append({"error": str(e), "category": category, "folder": folder})

        try:
            scan_categories(force_refresh=True)
        except Exception:
            pass

        return {"ok": True, "deleted": deleted, "failed": failed}

    except Exception as e:
        import traceback

        traceback.print_exc()
        return {"ok": False, "error": str(e)}
