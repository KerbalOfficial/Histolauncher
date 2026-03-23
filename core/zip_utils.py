import os
import re
import shutil
import zipfile

from typing import Callable, Optional, Tuple, Union


MAX_ZIP_ENTRIES = 20_000
MAX_ZIP_SINGLE_FILE_SIZE = 512 * 1024 * 1024
MAX_ZIP_TOTAL_UNCOMPRESSED = 4 * 1024 * 1024 * 1024


class ZipSecurityError(RuntimeError):
    pass


def _is_symlink_entry(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == 0o120000


def _normalize_member_name(name: str) -> str:
    raw = str(name or "").replace("\\", "/").strip()
    if not raw:
        return ""
    if raw.startswith("/"):
        raise ZipSecurityError(f"Absolute ZIP entry path is not allowed: {name}")
    if "\x00" in raw:
        raise ZipSecurityError(f"NUL byte in ZIP entry name: {name}")
    if re.match(r"^[a-zA-Z]:", raw):
        raise ZipSecurityError(f"Drive-letter ZIP entry path is not allowed: {name}")

    parts = []
    for part in raw.split("/"):
        piece = part.strip()
        if not piece or piece == ".":
            continue
        if piece == "..":
            raise ZipSecurityError(f"Path traversal ZIP entry is not allowed: {name}")
        parts.append(piece)

    return "/".join(parts)


def _resolve_safe_target(root_dir: str, relative_name: str) -> str:
    root_real = os.path.realpath(root_dir)
    target = os.path.normpath(os.path.join(root_real, relative_name.replace("/", os.sep)))
    target_real = os.path.realpath(target)
    if os.path.commonpath([root_real, target_real]) != root_real:
        raise ZipSecurityError(f"ZIP entry escapes destination root: {relative_name}")
    return target_real


def _validate_archive_limits(
    zf: zipfile.ZipFile,
    max_entries: int,
    max_single_file_size: int,
    max_total_uncompressed: int,
) -> None:
    infos = zf.infolist()
    if len(infos) > max_entries:
        raise ZipSecurityError(f"ZIP has too many entries ({len(infos)} > {max_entries})")

    total_uncompressed = 0
    for info in infos:
        _normalize_member_name(info.filename)
        if _is_symlink_entry(info):
            raise ZipSecurityError(f"ZIP symlink entries are not allowed: {info.filename}")

        if info.is_dir():
            continue

        file_size = int(info.file_size or 0)
        if file_size < 0:
            raise ZipSecurityError(f"ZIP entry has invalid size: {info.filename}")
        if file_size > max_single_file_size:
            raise ZipSecurityError(
                f"ZIP entry exceeds max file size ({file_size} > {max_single_file_size}): {info.filename}"
            )

        total_uncompressed += file_size
        if total_uncompressed > max_total_uncompressed:
            raise ZipSecurityError(
                f"ZIP exceeds max uncompressed size ({total_uncompressed} > {max_total_uncompressed})"
            )


def safe_extract_zip(
    zip_input: Union[str, zipfile.ZipFile],
    destination_dir: str,
    *,
    max_entries: int = MAX_ZIP_ENTRIES,
    max_single_file_size: int = MAX_ZIP_SINGLE_FILE_SIZE,
    max_total_uncompressed: int = MAX_ZIP_TOTAL_UNCOMPRESSED,
    member_filter: Optional[Callable[[str, zipfile.ZipInfo], bool]] = None,
    name_transform: Optional[Callable[[str, zipfile.ZipInfo], Optional[str]]] = None,
    progress_cb: Optional[Callable[[int, int, str, zipfile.ZipInfo], None]] = None,
) -> int:
    os.makedirs(destination_dir, exist_ok=True)

    close_after = False
    zf: zipfile.ZipFile
    if isinstance(zip_input, zipfile.ZipFile):
        zf = zip_input
    else:
        zf = zipfile.ZipFile(zip_input, "r")
        close_after = True

    try:
        _validate_archive_limits(
            zf,
            max_entries=max_entries,
            max_single_file_size=max_single_file_size,
            max_total_uncompressed=max_total_uncompressed,
        )

        selected: list[Tuple[zipfile.ZipInfo, str]] = []
        seen_targets = set()

        for info in zf.infolist():
            normalized = _normalize_member_name(info.filename)
            if not normalized:
                continue
            if member_filter and not member_filter(normalized, info):
                continue

            final_name = normalized
            if name_transform:
                final_name = name_transform(normalized, info) or ""
            final_name = _normalize_member_name(final_name)
            if not final_name:
                continue

            key = final_name.lower()
            if key in seen_targets:
                raise ZipSecurityError(f"Duplicate ZIP destination path detected: {final_name}")
            seen_targets.add(key)

            selected.append((info, final_name))

        total_files = sum(0 if info.is_dir() else 1 for info, _ in selected)
        extracted_files = 0

        for info, final_name in selected:
            target_path = _resolve_safe_target(destination_dir, final_name)

            if info.is_dir():
                os.makedirs(target_path, exist_ok=True)
                continue

            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with zf.open(info, "r") as src, open(target_path, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)

            extracted_files += 1
            if progress_cb:
                progress_cb(extracted_files, total_files, final_name, info)

        return extracted_files
    finally:
        if close_after:
            zf.close()
