from __future__ import annotations

import os
import shutil
from typing import Optional

from core.downloader._paths import LIBRARY_STORE_DIR
from core.logger import safe_print


def store_path_for(artifact_path: str) -> str:
    raw = str(artifact_path or "").replace("\\", "/").strip().lstrip("/")
    parts = []
    for part in raw.split("/"):
        if not part or part == ".":
            continue
        if part == ".." or "\x00" in part or (len(part) >= 2 and part[1] == ":"):
            raise ValueError(f"invalid library artifact path: {artifact_path!r}")
        parts.append(part)

    if not parts:
        raise ValueError("library artifact path is empty")

    path = os.path.join(LIBRARY_STORE_DIR, *parts)
    root_real = os.path.normcase(os.path.realpath(LIBRARY_STORE_DIR))
    path_real = os.path.normcase(os.path.realpath(path))
    try:
        if os.path.commonpath([root_real, path_real]) != root_real:
            raise ValueError(f"invalid library artifact path: {artifact_path!r}")
    except ValueError:
        raise ValueError(f"invalid library artifact path: {artifact_path!r}")
    return path


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
            safe_print(
                f"[lib-store] could not replace {version_dest}: {exc}; copying"
            )
            _copy(store_file, version_dest, chunk_size)
            return

    try:
        os.link(store_file, version_dest)
        return
    except (OSError, NotImplementedError) as exc:
        safe_print(
            f"[lib-store] hardlink failed ({exc}); copying {os.path.basename(version_dest)}"
        )
        _copy(store_file, version_dest, chunk_size)


def _copy(src: str, dest: str, chunk_size: int) -> None:
    with open(src, "rb") as s, open(dest, "wb") as d:
        shutil.copyfileobj(s, d, length=chunk_size)


__all__ = [
    "link_into_version",
    "store_path_for",
]
