from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

API_BASE = "https://discovery.histolauncher.org"

CURSEFORGE_API_BASE = f"{API_BASE}/curseforge"
MODRINTH_API_BASE = f"{API_BASE}/modrinth"
DIRECT_MODRINTH_API_BASE = "https://api.modrinth.com/v2"

CURSEFORGE_MINECRAFT_GAME_ID = 432

CURSEFORGE_MODLOADER_TYPE_FORGE = 1
CURSEFORGE_MODLOADER_TYPE_FABRIC = 4
CURSEFORGE_MODLOADER_TYPE_QUILT = 5
CURSEFORGE_MODLOADER_TYPE_NEOFORGE = 6

REQUEST_TIMEOUT = 30.0
REQUEST_RETRY_ATTEMPTS = 3
REQUEST_RETRY_DELAY = 0.5
IMPORT_RETRY_ATTEMPTS = 10
IMPORT_RETRY_DELAY = 1.0

_MODRINTH_CACHE: Dict[str, dict] = {}
_MODRINTH_SEARCH_TTL = 120
_MODRINTH_DETAIL_TTL = 300

SUPPORTED_MOD_LOADERS = ("fabric", "babric", "forge", "modloader", "neoforge", "quilt")
SUPPORTED_SHADER_TYPES = ("optifine", "iris")
SUPPORTED_ADDON_TYPES = ("mods", "resourcepacks", "shaderpacks", "modpacks")

ADDON_STORAGE_DIRS = {
    "mods": "mods",
    "resourcepacks": "resourcepacks",
    "shaderpacks": "shaderpacks",
    "modpacks": "modpacks",
}

ADDON_IMPORT_EXTENSIONS = {
    "mods": {".jar", ".zip"},
    "resourcepacks": {".zip"},
    "shaderpacks": {".zip"},
    "modpacks": {".hlmp", ".mrpack", ".zip"},
}

MODRINTH_PROJECT_TYPES = {
    "mods": "mod",
    "resourcepacks": "resourcepack",
    "shaderpacks": "shader",
    "modpacks": "modpack",
}

_CURSEFORGE_CLASS_ID_CACHE: Dict[str, Optional[int]] = {}

_MAX_SAFE_COMPONENT_LENGTH = 128
_SUPPORTED_MOD_ARCHIVE_EXTENSIONS = {".jar", ".zip"}


class ExternalModpackImportError(RuntimeError):
    pass
