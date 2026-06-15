from __future__ import annotations

import os
from typing import Final

from core.settings import get_base_dir

BASE_DIR: Final[str] = get_base_dir()

PROGRESS_DIR: Final[str] = os.path.join(BASE_DIR, "cache", "progress")
CACHE_LIBRARIES_DIR: Final[str] = os.path.join(BASE_DIR, "cache", "libraries")
ASSETS_DIR: Final[str] = os.path.join(BASE_DIR, "assets")
ASSETS_INDEXES_DIR: Final[str] = os.path.join(ASSETS_DIR, "indexes")
ASSETS_OBJECTS_DIR: Final[str] = os.path.join(ASSETS_DIR, "objects")

DOWNLOAD_CHUNK_SIZE: Final[int] = 64 * 1024

ASSET_THREADS_HIGH: Final[int] = 16
ASSET_THREADS_MED: Final[int] = 8
ASSET_THREADS_LOW: Final[int] = 4

STAGE_WEIGHTS: Final[dict[str, int]] = {
    "version_json": 5,
    "client": 20,
    "libraries": 25,
    "natives": 15,
    "assets": 25,
    "finalize": 10,
    "download": 20,
    "extracting_loader": 30,
    "downloading_libs": 40,
    "error": 0,
}

BLOCKED_FORGE_VERSIONS: Final[frozenset[str]] = frozenset()

SUPPORTED_LOADER_TYPES: Final[frozenset[str]] = frozenset(
    {
        "fabric",
        "legacyfabric",
        "babric",
        "ornithe",
        "forge",
        "liteloader",
        "modloader",
        "neoforge",
        "quilt",
    }
)

__all__ = [
    "ASSETS_DIR",
    "ASSETS_INDEXES_DIR",
    "ASSETS_OBJECTS_DIR",
    "ASSET_THREADS_HIGH",
    "ASSET_THREADS_LOW",
    "ASSET_THREADS_MED",
    "BASE_DIR",
    "BLOCKED_FORGE_VERSIONS",
    "CACHE_LIBRARIES_DIR",
    "DOWNLOAD_CHUNK_SIZE",
    "PROGRESS_DIR",
    "STAGE_WEIGHTS",
    "SUPPORTED_LOADER_TYPES",
]
