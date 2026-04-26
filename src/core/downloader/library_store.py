from __future__ import annotations

import os
import shutil
from typing import Optional

from core.downloader._paths import LIBRARY_STORE_DIR
from core.logger import colorize_log


def store_path_for(artifact_path: str) -> str:
    safe = artifact_path.replace("\\", "/").lstrip("/")
    return os.path.join(LIBRARY_STORE_DIR, safe.replace("/", os.sep))


def link_into_version(
    *,
    store_file: str,
    version_dest: str,
    chunk_size: int = 64 * 1024,
) -> None:
    if not os.path.isfile(store_file):
        raise FileNotFoundError(store_file)

    os.makedirs(os.path.dirname(version_dest) or ".", exist_ok=True)

    if os.path.exists(version_dest):
        try:
            if os.path.samefile(store_file, version_dest):
                return
        except OSError:
            pass
        try:
            os.remove(version_dest)
        except OSError as exc:
            print(colorize_log(
                f"[lib-store] could not replace {version_dest}: {exc}; copying"
            ))
            _copy(store_file, version_dest, chunk_size)
            return

    try:
        os.link(store_file, version_dest)
        return
    except (OSError, NotImplementedError) as exc:
        print(colorize_log(
            f"[lib-store] hardlink failed ({exc}); copying {os.path.basename(version_dest)}"
        ))
        _copy(store_file, version_dest, chunk_size)


def _copy(src: str, dest: str, chunk_size: int) -> None:
    with open(src, "rb") as s, open(dest, "wb") as d:
        shutil.copyfileobj(s, d, length=chunk_size)


__all__ = [
    "link_into_version",
    "store_path_for",
]
