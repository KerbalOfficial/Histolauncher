from __future__ import annotations

import os
import shutil
import zipfile
from typing import List

from core.mod_manager._constants import logger
from core.mod_manager._validation import (
    _is_safe_zip_entry_path,
    _is_within_dir,
    _normalize_archive_source_subfolder,
)
from core.mod_manager.storage import (
    _resolve_mod_archive_path,
    get_mod_version_dir,
)


def list_mod_archive_source_folders(
    mod_loader: str,
    mod_slug: str,
    version_label: str,
    preferred_file_name: str = "",
) -> List[str]:
    ver_dir = get_mod_version_dir(mod_loader, mod_slug, version_label)
    archive_path = _resolve_mod_archive_path(ver_dir, preferred_file_name=preferred_file_name)
    if not archive_path:
        return [""]

    folders = set()
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            for info in zf.infolist():
                raw_name = str(info.filename or "")
                if not raw_name:
                    continue

                normalized_name = raw_name.replace("\\", "/").lstrip("/")
                if not _is_safe_zip_entry_path(normalized_name):
                    continue

                parts = [p for p in normalized_name.split("/") if p]
                if not parts:
                    continue

                max_index = len(parts) if info.is_dir() else len(parts) - 1
                for idx in range(1, max_index + 1):
                    folder = "/".join(parts[:idx]).strip("/")
                    if folder:
                        folders.add(folder)
    except Exception as e:
        logger.warning(f"Failed to list archive source folders for {mod_loader}/{mod_slug}/{version_label}: {e}")
        return [""]

    ordered = sorted(folders, key=lambda x: (x.count("/"), x.lower()))
    return [""] + ordered


def extract_mod_archive_subfolder(
    mod_loader: str,
    mod_slug: str,
    version_label: str,
    source_subfolder: str,
    target_dir: str,
    preferred_file_name: str = "",
) -> int:
    normalized_source = _normalize_archive_source_subfolder(source_subfolder)
    ver_dir = get_mod_version_dir(mod_loader, mod_slug, version_label)
    archive_path = _resolve_mod_archive_path(ver_dir, preferred_file_name=preferred_file_name)
    if not archive_path:
        return 0
    return extract_archive_path_subfolder(archive_path, normalized_source, target_dir)


def extract_archive_path_subfolder(
    archive_path: str,
    source_subfolder: str,
    target_dir: str,
) -> int:
    normalized_source = _normalize_archive_source_subfolder(source_subfolder)
    if not archive_path or not os.path.isfile(archive_path):
        return 0

    os.makedirs(target_dir, exist_ok=True)
    source_prefix = f"{normalized_source}/" if normalized_source else ""
    extracted = 0

    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue

                raw_name = str(info.filename or "")
                normalized_name = raw_name.replace("\\", "/").lstrip("/")
                if not _is_safe_zip_entry_path(normalized_name):
                    continue

                if normalized_name.upper().startswith("META-INF/"):
                    continue

                if normalized_source:
                    if not normalized_name.startswith(source_prefix):
                        continue
                    relative_name = normalized_name[len(source_prefix):]
                else:
                    relative_name = normalized_name

                if not relative_name or relative_name.endswith("/"):
                    continue

                dest_path = os.path.normpath(os.path.join(target_dir, relative_name))
                if not _is_within_dir(target_dir, dest_path):
                    continue

                dest_parent = os.path.dirname(dest_path) or target_dir
                os.makedirs(dest_parent, exist_ok=True)
                with zf.open(info, "r") as src_file, open(dest_path, "wb") as dst_file:
                    shutil.copyfileobj(src_file, dst_file)
                extracted += 1
    except Exception as e:
        logger.error(f"Failed extracting archive subfolder from {archive_path}: {e}")
        return 0

    return extracted
