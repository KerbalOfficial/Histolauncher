from __future__ import annotations

import io
import os
import shutil
import zipfile
from typing import List, Tuple

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
from core.zip_utils import (
    ZipSecurityError,
    _validate_archive_limits,
    safe_extract_zip,
)
from core.constants import ZIP_MAX_ENTRIES, ZIP_MAX_FILE_BYTES, ZIP_MAX_TOTAL_BYTES


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
            try:
                _validate_archive_limits(
                    zf,
                    max_entries=ZIP_MAX_ENTRIES,
                    max_single_file_size=ZIP_MAX_FILE_BYTES,
                    max_total_uncompressed=ZIP_MAX_TOTAL_BYTES,
                )
            except ZipSecurityError as exc:
                logger.warning(
                    f"Refusing to list archive {archive_path}: {exc}"
                )
                return [""]
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
    extracted_count = [0]

    def _filter(normalized_name: str, info: zipfile.ZipInfo) -> bool:
        if info.is_dir():
            return False
        if normalized_name.upper().startswith("META-INF/"):
            return False
        if normalized_source and not normalized_name.startswith(source_prefix):
            return False
        return True

    def _transform(normalized_name: str, info: zipfile.ZipInfo) -> str | None:
        if normalized_source and normalized_name.startswith(source_prefix):
            return normalized_name[len(source_prefix):]
        return normalized_name

    def _progress(done: int, total: int, name: str, info: zipfile.ZipInfo) -> None:
        extracted_count[0] = done

    try:
        safe_extract_zip(
            archive_path,
            target_dir,
            member_filter=_filter,
            name_transform=_transform,
            progress_cb=_progress,
        )
    except ZipSecurityError as exc:
        logger.error(f"Refusing to extract archive {archive_path}: {exc}")
        return 0
    except Exception as e:
        logger.error(f"Failed extracting archive subfolder from {archive_path}: {e}")
        return 0

    return extracted_count[0]


def validate_datapack_archive(file_data: bytes) -> Tuple[bool, str]:
    if not isinstance(file_data, (bytes, bytearray)) or not file_data:
        return False, "Datapack archive is empty"

    has_pack_mcmeta = False
    has_data_dir = False

    try:
        with zipfile.ZipFile(io.BytesIO(file_data), "r") as zf:
            try:
                _validate_archive_limits(
                    zf,
                    max_entries=ZIP_MAX_ENTRIES,
                    max_single_file_size=ZIP_MAX_FILE_BYTES,
                    max_total_uncompressed=ZIP_MAX_TOTAL_BYTES,
                )
            except ZipSecurityError as exc:
                return False, str(exc)

            for info in zf.infolist():
                raw_name = str(info.filename or "")
                normalized = raw_name.replace("\\", "/").strip("/")
                if not normalized or not _is_safe_zip_entry_path(normalized):
                    continue

                parts = [p for p in normalized.split("/") if p and p not in (".", "..")]
                if not parts:
                    continue

                if os.path.basename(normalized).lower() == "pack.mcmeta" and len(parts) == 1:
                    has_pack_mcmeta = True
                if parts[0].lower() == "data":
                    has_data_dir = True
    except zipfile.BadZipFile:
        return False, "Invalid datapack zip archive"
    except Exception as exc:
        return False, f"Failed to read datapack archive: {exc}"

    if not has_pack_mcmeta:
        return False, "Datapack archive must contain pack.mcmeta at the root"
    if not has_data_dir:
        return False, "Datapack archive must contain a data/ directory"
    return True, ""
