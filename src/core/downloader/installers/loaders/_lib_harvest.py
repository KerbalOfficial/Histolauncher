from __future__ import annotations

import os
import shutil
from typing import Callable, List, Optional, Set, Tuple

from core.downloader.library_store import link_into_version, store_path_for
from core.logger import colorize_log


CancelCheck = Callable[[], None]
ProgressCb = Callable[[int, int], None]


def _walk_jars(root: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    if not os.path.isdir(root):
        return out
    for dirpath, _, files in os.walk(root):
        for fn in files:
            if not fn.lower().endswith(".jar"):
                continue
            src = os.path.join(dirpath, fn)
            rel = os.path.relpath(src, root).replace("\\", "/")
            if rel.upper().startswith("META-INF/"):
                continue
            out.append((src, rel))
    return out


def harvest_libraries(
    *,
    source_libraries_dir: str,
    dest_libraries_dir: str,
    overwrite_predicate: Optional[Callable[[str, str, str], bool]] = None,
    cancel_check: Optional[CancelCheck] = None,
    progress_cb: Optional[ProgressCb] = None,
) -> Tuple[int, int]:
    if not os.path.isdir(source_libraries_dir):
        return (0, 0)

    plan = _walk_jars(source_libraries_dir)
    total = len(plan)
    if total == 0:
        return (0, 0)

    seen_store_paths: Set[str] = set()
    new_count = 0
    replaced_count = 0

    for index, (src, rel) in enumerate(plan, 1):
        if cancel_check is not None:
            cancel_check()

        dest = os.path.join(dest_libraries_dir, rel.replace("/", os.sep))
        store_path = store_path_for(rel)

        if not os.path.isfile(store_path):
            os.makedirs(os.path.dirname(store_path), exist_ok=True)
            try:
                _atomic_ingest(src, store_path)
            except OSError as exc:
                print(colorize_log(
                    f"[lib-harvest] could not ingest {rel}: {exc}; copying inline"
                ))
                shutil.copy2(src, store_path)

        if store_path in seen_store_paths:
            if progress_cb is not None:
                try:
                    progress_cb(index, total)
                except Exception:
                    pass
            continue
        seen_store_paths.add(store_path)

        place = True
        if os.path.exists(dest):
            try:
                if os.path.samefile(store_path, dest):
                    place = False
            except OSError:
                pass
            if place and overwrite_predicate is None:
                try:
                    place = os.path.getsize(store_path) != os.path.getsize(dest)
                except OSError:
                    place = True
            elif place:
                try:
                    place = bool(overwrite_predicate(rel, store_path, dest))
                except Exception:
                    place = True

        existed = os.path.exists(dest)
        if place:
            link_into_version(store_file=store_path, version_dest=dest)
            if existed:
                replaced_count += 1
            else:
                new_count += 1

        if progress_cb is not None:
            try:
                progress_cb(index, total)
            except Exception:
                pass

    return (new_count, replaced_count)


def _atomic_ingest(src: str, store_dest: str) -> None:
    try:
        os.replace(src, store_dest)
    except OSError:
        shutil.copy2(src, store_dest)
        try:
            os.remove(src)
        except OSError:
            pass


__all__ = ["harvest_libraries"]
