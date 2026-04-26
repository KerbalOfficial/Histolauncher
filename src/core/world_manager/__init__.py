from __future__ import annotations

from core.world_manager._constants import (
    CURSEFORGE_WORLD_CLASS_ID,
    DIFFICULTY_ID_TO_NAME,
    DIFFICULTY_NAME_TO_ID,
    EMBEDDED_WORLD_PLAYER_ID,
    MAX_WORLD_ID_LENGTH,
    MAX_WORLD_TITLE_LENGTH,
    MINECRAFT_USERCACHE_PATH,
    OVERWORLD_CLOCK_ID,
)
from core.world_manager.archive import (
    export_world_zip,
    import_world_zip_bytes,
    install_world_archive,
    scan_world_zip_bytes,
)
from core.world_manager.curseforge import (
    get_world_detail_curseforge,
    get_world_files_curseforge,
    list_world_categories_curseforge,
    search_worlds_curseforge,
)
from core.world_manager.metadata import get_world_detail, list_worlds
from core.world_manager.nbt_editor import (
    get_world_nbt_editor,
    update_world_advanced_nbt,
    update_world_simple_nbt,
)
from core.world_manager.operations import (
    delete_world,
    open_world_folder,
    replace_world_icon,
    update_world,
)
from core.world_manager.storage import (
    list_storage_options,
    list_version_options,
    resolve_storage_target,
)


__all__ = [
    "CURSEFORGE_WORLD_CLASS_ID",
    "DIFFICULTY_ID_TO_NAME",
    "DIFFICULTY_NAME_TO_ID",
    "EMBEDDED_WORLD_PLAYER_ID",
    "MAX_WORLD_ID_LENGTH",
    "MAX_WORLD_TITLE_LENGTH",
    "MINECRAFT_USERCACHE_PATH",
    "OVERWORLD_CLOCK_ID",
    "delete_world",
    "export_world_zip",
    "get_world_detail",
    "get_world_detail_curseforge",
    "get_world_files_curseforge",
    "get_world_nbt_editor",
    "import_world_zip_bytes",
    "install_world_archive",
    "list_storage_options",
    "list_world_categories_curseforge",
    "list_version_options",
    "list_worlds",
    "open_world_folder",
    "replace_world_icon",
    "resolve_storage_target",
    "scan_world_zip_bytes",
    "search_worlds_curseforge",
    "update_world",
    "update_world_advanced_nbt",
    "update_world_simple_nbt",
]
