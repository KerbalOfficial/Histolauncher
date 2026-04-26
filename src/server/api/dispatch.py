from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from server.api._helpers import _extract_category
from server.api.routes.account import (
    api_account_current,
    api_account_disconnect,
    api_account_launcher_message,
    api_account_login,
    api_account_refresh_assets,
    api_account_settings_iframe,
    api_account_status,
    api_account_verify_session,
)
from server.api.routes.corrupted import (
    api_corrupted_versions,
    api_delete_corrupted_versions,
)
from server.api.routes.initial import api_initial
from server.api.routes.installer import (
    api_cancel,
    api_delete_version,
    api_install,
    api_installed,
    api_open_data_folder,
    api_operations_cancel,
    api_pause,
    api_resume,
    api_status,
)
from server.api.routes.java import (
    api_java_download,
    api_java_install_options,
    api_java_runtimes,
    api_java_runtimes_refresh,
)
from server.api.routes.launch import (
    api_clear_logs,
    api_crash_log,
    api_game_window_visible,
    api_launch,
    api_launch_status,
    api_open_crash_log,
)
from server.api.routes.loaders import (
    api_delete_loader,
    api_install_loader,
    api_loaders,
    api_loaders_installed,
)
from server.api.routes.modpacks import (
    api_modpacks_delete,
    api_modpacks_export,
    api_modpacks_import,
    api_modpacks_import_progress,
    api_modpacks_installed,
    api_modpacks_set_mod_overwrite,
    api_modpacks_toggle,
    api_modpacks_toggle_mod,
)
from server.api.routes.mods import (
    api_mods_archive_subfolders,
    api_mods_delete,
    api_mods_detail,
    api_mods_import,
    api_mods_install,
    api_mods_installed,
    api_mods_move,
    api_mods_search,
    api_mods_set_active_version,
    api_mods_toggle,
    api_mods_update_version_settings,
    api_mods_version_options,
    api_mods_versions,
)
from server.api.routes.profiles import (
    api_profiles,
    api_profiles_create,
    api_profiles_delete,
    api_profiles_mods,
    api_profiles_mods_create,
    api_profiles_mods_delete,
    api_profiles_mods_rename,
    api_profiles_mods_switch,
    api_profiles_rename,
    api_profiles_switch,
    api_profiles_versions,
    api_profiles_versions_create,
    api_profiles_versions_delete,
    api_profiles_versions_rename,
    api_profiles_versions_switch,
)
from server.api.routes.settings import (
    api_settings,
    api_storage_directory_select,
    api_storage_directory_validate,
    api_version_edit,
)
from server.api.routes.versions import api_search, api_versions
from server.api.routes.versions_io import api_export_versions, api_import_versions
from server.api.routes.worlds import (
    api_worlds_delete,
    api_worlds_detail,
    api_worlds_export,
    api_worlds_import,
    api_worlds_import_scan,
    api_worlds_install,
    api_worlds_installed,
    api_worlds_icon_update,
    api_worlds_nbt,
    api_worlds_nbt_advanced_update,
    api_worlds_nbt_simple_update,
    api_worlds_open,
    api_worlds_search,
    api_worlds_storage_options,
    api_worlds_update,
    api_worlds_version_options,
    api_worlds_versions,
)
from server.api.version_check import is_launcher_outdated


__all__ = ["handle_api_request"]


def _query_flag(path: str, name: str) -> bool:
    try:
        values = parse_qs(urlparse(path).query or "").get(name) or []
    except Exception:
        return False
    if not values:
        return False
    return str(values[-1]).strip().lower() in {"1", "true", "yes", "on"}


def handle_api_request(path: str, data: Any):
    p = path.split("?", 1)[0].rstrip("/")

    EXACT_NO_PARAMS = {
        "/api/account/status": api_account_status,
        "/api/account/current": api_account_current,
        "/api/account/settings-iframe": api_account_settings_iframe,
        "/api/account/launcher-message": api_account_launcher_message,
        "/api/account/disconnect": api_account_disconnect,
        "/api/profiles": api_profiles,
        "/api/profiles/versions": api_profiles_versions,
        "/api/profiles/mods": api_profiles_mods,
        "/api/is-launcher-outdated": is_launcher_outdated,
        "/api/initial": api_initial,
        "/api/clear-logs": api_clear_logs,
        "/api/installed": api_installed,
        "/api/open_data_folder": api_open_data_folder,
        "/api/corrupted-versions": api_corrupted_versions,
        "/api/java-install-options": api_java_install_options,
        "/api/java-runtimes": api_java_runtimes,
        "/api/java-runtimes-refresh": api_java_runtimes_refresh,
        "/api/mods/installed": api_mods_installed,
        "/api/mods/version-options": api_mods_version_options,
        "/api/modpacks/installed": api_modpacks_installed,
    }

    EXACT_WITH_DATA = {
        "/api/account/login": api_account_login,
        "/api/account/verify-session": api_account_verify_session,
        "/api/account/refresh-assets": api_account_refresh_assets,
        "/api/profiles/create": api_profiles_create,
        "/api/profiles/switch": api_profiles_switch,
        "/api/profiles/delete": api_profiles_delete,
        "/api/profiles/rename": api_profiles_rename,
        "/api/profiles/versions/create": api_profiles_versions_create,
        "/api/profiles/versions/switch": api_profiles_versions_switch,
        "/api/profiles/versions/delete": api_profiles_versions_delete,
        "/api/profiles/versions/rename": api_profiles_versions_rename,
        "/api/profiles/mods/create": api_profiles_mods_create,
        "/api/profiles/mods/switch": api_profiles_mods_switch,
        "/api/profiles/mods/delete": api_profiles_mods_delete,
        "/api/profiles/mods/rename": api_profiles_mods_rename,
        "/api/search": api_search,
        "/api/launch": api_launch,
        "/api/crash-log": api_crash_log,
        "/api/open-crash-log": api_open_crash_log,
        "/api/settings": api_settings,
        "/api/version/edit": api_version_edit,
        "/api/storage-directory/select": api_storage_directory_select,
        "/api/storage-directory/validate": api_storage_directory_validate,
        "/api/worlds/storage-options": api_worlds_storage_options,
        "/api/worlds/version-options": api_worlds_version_options,
        "/api/worlds/installed": api_worlds_installed,
        "/api/worlds/detail": api_worlds_detail,
        "/api/worlds/nbt": api_worlds_nbt,
        "/api/worlds/nbt/simple-update": api_worlds_nbt_simple_update,
        "/api/worlds/nbt/advanced-update": api_worlds_nbt_advanced_update,
        "/api/worlds/update": api_worlds_update,
        "/api/worlds/icon-update": api_worlds_icon_update,
        "/api/worlds/delete": api_worlds_delete,
        "/api/worlds/open": api_worlds_open,
        "/api/worlds/search": api_worlds_search,
        "/api/worlds/versions": api_worlds_versions,
        "/api/worlds/install": api_worlds_install,
        "/api/worlds/export": api_worlds_export,
        "/api/worlds/import-scan": api_worlds_import_scan,
        "/api/worlds/import": api_worlds_import,
        "/api/install": api_install,
        "/api/delete": api_delete_version,
        "/api/install-loader": api_install_loader,
        "/api/delete-loader": api_delete_loader,
        "/api/delete-corrupted-versions": api_delete_corrupted_versions,
        "/api/java-download": api_java_download,
        "/api/versions/export": api_export_versions,
        "/api/versions/import": api_import_versions,
        "/api/addons/installed": api_mods_installed,
        "/api/addons/version-options": api_mods_version_options,
        "/api/mods/search": api_mods_search,
        "/api/mods/versions": api_mods_versions,
        "/api/mods/install": api_mods_install,
        "/api/mods/import": api_mods_import,
        "/api/mods/delete": api_mods_delete,
        "/api/mods/toggle": api_mods_toggle,
        "/api/mods/move": api_mods_move,
        "/api/mods/set-active-version": api_mods_set_active_version,
        "/api/mods/archive-subfolders": api_mods_archive_subfolders,
        "/api/mods/update-version-settings": api_mods_update_version_settings,
        "/api/mods/detail": api_mods_detail,
        "/api/modpacks/export": api_modpacks_export,
        "/api/modpacks/import": api_modpacks_import,
        "/api/modpacks/toggle": api_modpacks_toggle,
        "/api/modpacks/toggle-mod": api_modpacks_toggle_mod,
        "/api/modpacks/set-mod-overwrite": api_modpacks_set_mod_overwrite,
        "/api/modpacks/delete": api_modpacks_delete,
        "/api/operations/cancel": api_operations_cancel,
    }

    PREFIX_HANDLERS = [
        (
            "/api/versions",
            lambda _p: api_versions(
                _extract_category(_p),
                force_refresh=_query_flag(path, "refresh") or _query_flag(path, "force"),
            ),
        ),
        ("/api/launch_status/", lambda _p: api_launch_status(_p[len("/api/launch_status/"):])),
        (
            "/api/modpacks/import/progress",
            lambda _p: api_modpacks_import_progress(
                path.split("id=")[1].split("&")[0] if "id=" in path else ""
            ),
        ),
        (
            "/api/game_window_visible/",
            lambda _p: api_game_window_visible(_p[len("/api/game_window_visible/"):]),
        ),
        ("/api/status/", lambda _p: api_status(_p[len("/api/status/"):])),
        ("/api/cancel/", lambda _p: api_cancel(_p[len("/api/cancel/"):])),
        ("/api/pause/", lambda _p: api_pause(_p[len("/api/pause/"):])),
        ("/api/resume/", lambda _p: api_resume(_p[len("/api/resume/"):])),
        (
            "/api/loaders-installed/",
            lambda _p: api_loaders_installed(_p[len("/api/loaders-installed/"):]),
        ),
        ("/api/loaders/", lambda _p: api_loaders(_p[len("/api/loaders/"):])),
    ]

    if p in EXACT_NO_PARAMS:
        return EXACT_NO_PARAMS[p]()

    if p in EXACT_WITH_DATA:
        return EXACT_WITH_DATA[p](data)

    for prefix, handler in PREFIX_HANDLERS:
        if p.startswith(prefix):
            return handler(p)

    return {"error": "Unknown endpoint"}
