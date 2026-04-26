from __future__ import annotations

import os
from typing import Final

from core.settings import get_base_dir

BASE_DIR: Final[str] = get_base_dir()

#: Where on-disk progress JSON files live.
PROGRESS_DIR: Final[str] = os.path.join(BASE_DIR, "cache", "progress")

#: Canonical store of downloaded library jars (deduplicated across versions).
LIBRARY_STORE_DIR: Final[str] = os.path.join(BASE_DIR, "cache", "libraries")

ASSETS_DIR: Final[str] = os.path.join(BASE_DIR, "assets")
ASSETS_INDEXES_DIR: Final[str] = os.path.join(ASSETS_DIR, "indexes")
ASSETS_OBJECTS_DIR: Final[str] = os.path.join(ASSETS_DIR, "objects")


def ensure_progress_dir() -> None:
    os.makedirs(PROGRESS_DIR, exist_ok=True)


def ensure_install_dirs() -> None:
    from core.settings import get_versions_profile_dir

    os.makedirs(get_versions_profile_dir(), exist_ok=True)
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    os.makedirs(LIBRARY_STORE_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(ASSETS_INDEXES_DIR, exist_ok=True)
    os.makedirs(ASSETS_OBJECTS_DIR, exist_ok=True)


__all__ = [
    "ASSETS_DIR",
    "ASSETS_INDEXES_DIR",
    "ASSETS_OBJECTS_DIR",
    "BASE_DIR",
    "LIBRARY_STORE_DIR",
    "PROGRESS_DIR",
    "ensure_install_dirs",
    "ensure_progress_dir",
]
