from __future__ import annotations

import os
from urllib.parse import unquote

from core.settings import (
    get_default_minecraft_dir,
    normalize_storage_directory_mode,
    validate_custom_storage_directory,
)
from core.version_manager import get_clients_dir

from server.http._constants import UI_DIR


__all__ = ["StaticPathsMixin"]


def _safe_static_join(root: str, relative_path: str, invalid_name: str) -> str:
    root_real = os.path.normcase(os.path.realpath(root))
    target_path = os.path.normpath(os.path.join(root, relative_path))
    target_real = os.path.normcase(os.path.realpath(target_path))

    try:
        if os.path.commonpath([root_real, target_real]) != root_real:
            return os.path.join(UI_DIR, invalid_name)
    except ValueError:
        return os.path.join(UI_DIR, invalid_name)

    return target_path


class StaticPathsMixin:
    def translate_path(self, path):
        path = path.split("?", 1)[0]
        path = path.split("#", 1)[0]

        if path.startswith("/clients/"):
            client_rel = unquote(path[len("/clients/"):]).replace("/", os.sep)
            return _safe_static_join(
                get_clients_dir(), client_rel, "__invalid_clients_path__"
            )

        from core import mod_manager

        if path.startswith("/mods-cache/"):
            rel_path = unquote(path[len("/mods-cache/"):]).replace("/", os.sep)
            return _safe_static_join(
                mod_manager.get_mods_storage_dir(), rel_path, "__invalid_mod_cache_path__"
            )

        if path.startswith("/addons-cache/"):
            rel_path = unquote(path[len("/addons-cache/"):]).replace("/", os.sep)
            return _safe_static_join(
                mod_manager.get_addons_profile_root(),
                rel_path,
                "__invalid_addons_cache_path__",
            )

        if path.startswith("/modpacks-cache/"):
            rel_path = unquote(path[len("/modpacks-cache/"):]).replace("/", os.sep)
            return _safe_static_join(
                mod_manager.get_modpacks_storage_dir(),
                rel_path,
                "__invalid_modpack_cache_path__",
            )

        ui_rel = unquote(path.lstrip("/")).replace("/", os.sep)
        return _safe_static_join(UI_DIR, ui_rel, "__invalid_ui_path__")

    def _get_worlds_directory(self) -> str:
        try:
            from core.settings import load_global_settings, get_versions_profile_dir
        except Exception:
            load_global_settings = None
            get_versions_profile_dir = None  # type: ignore[assignment]

        game_dir = get_default_minecraft_dir()

        try:
            if load_global_settings:
                gs = load_global_settings() or {}
                storage_mode = normalize_storage_directory_mode(
                    gs.get("storage_directory")
                )
                if storage_mode == "version":
                    sel = str(gs.get("selected_version") or "").strip()
                    if sel:
                        base_versions = get_versions_profile_dir()
                        cand = os.path.join(base_versions, sel)
                        if os.path.isdir(cand):
                            game_dir = os.path.join(cand, "data")
                        else:
                            game_dir = (
                                os.path.join(base_versions, "data")
                                if os.path.isdir(os.path.join(base_versions, "data"))
                                else base_versions
                            )
                    else:
                        game_dir = get_default_minecraft_dir()
                elif storage_mode == "custom":
                    validation = validate_custom_storage_directory(
                        gs.get("custom_storage_directory")
                    )
                    if validation.get("ok"):
                        game_dir = validation.get("path") or game_dir
                else:
                    game_dir = get_default_minecraft_dir()
        except Exception:
            pass

        worlds_dir = os.path.join(game_dir, "legacy_worlds")
        os.makedirs(worlds_dir, exist_ok=True)
        return worlds_dir
