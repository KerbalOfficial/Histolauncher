from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable

from core.constants import ZIP_MAX_ENTRIES, ZIP_MAX_FILE_BYTES, ZIP_MAX_TOTAL_BYTES
from core.subprocess_utils import no_window_kwargs

__all__ = [
    "ZipSecurityError",
    "ArchiveExtractionError",
    "safe_extract_zip",
    "extract_rar",
    "MAX_ZIP_ENTRIES",
    "MAX_ZIP_SINGLE_FILE_SIZE",
    "MAX_ZIP_TOTAL_UNCOMPRESSED",
]


MAX_ZIP_ENTRIES = ZIP_MAX_ENTRIES
MAX_ZIP_SINGLE_FILE_SIZE = ZIP_MAX_FILE_BYTES
MAX_ZIP_TOTAL_UNCOMPRESSED = ZIP_MAX_TOTAL_BYTES

_DRIVE_LETTER_RE = re.compile(r"^[a-zA-Z]:")


class ZipSecurityError(RuntimeError):
    pass


class ArchiveExtractionError(RuntimeError):
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
    if _DRIVE_LETTER_RE.match(raw):
        raise ZipSecurityError(f"Drive-letter ZIP entry path is not allowed: {name}")

    parts: list[str] = []
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
    *,
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
                f"ZIP entry exceeds max file size "
                f"({file_size} > {max_single_file_size}): {info.filename}"
            )

        total_uncompressed += file_size
        if total_uncompressed > max_total_uncompressed:
            raise ZipSecurityError(
                f"ZIP exceeds max uncompressed size "
                f"({total_uncompressed} > {max_total_uncompressed})"
            )


MemberFilter = Callable[[str, zipfile.ZipInfo], bool]
NameTransform = Callable[[str, zipfile.ZipInfo], str | None]
ProgressCallback = Callable[[int, int, str, zipfile.ZipInfo], None]


def safe_extract_zip(
    zip_input: str | zipfile.ZipFile,
    destination_dir: str,
    *,
    max_entries: int = ZIP_MAX_ENTRIES,
    max_single_file_size: int = ZIP_MAX_FILE_BYTES,
    max_total_uncompressed: int = ZIP_MAX_TOTAL_BYTES,
    member_filter: MemberFilter | None = None,
    name_transform: NameTransform | None = None,
    progress_cb: ProgressCallback | None = None,
) -> int:
    os.makedirs(destination_dir, exist_ok=True)

    close_after = False
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

        selected: list[tuple[zipfile.ZipInfo, str]] = []
        seen_targets: set[str] = set()

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


def _rar_extractor_candidates(archive_path: str, dest_dir: str) -> list[list[str]]:
    candidates: list[list[str]] = []

    if sys.platform == "win32":
        sys_tar = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe"
        )
        if os.path.isfile(sys_tar):
            candidates.append([sys_tar, "-xf", archive_path, "-C", dest_dir])

    bsdtar = shutil.which("bsdtar")
    if bsdtar:
        candidates.append([bsdtar, "-xf", archive_path, "-C", dest_dir])

    unrar = shutil.which("unrar") or shutil.which("unrar-free")
    if unrar:
        candidates.append(
            [unrar, "x", "-o+", "-y", "-idq", archive_path, dest_dir + os.sep]
        )

    for name in ("7z", "7za", "7zz"):
        seven = shutil.which(name)
        if seven:
            candidates.append(
                [seven, "x", "-y", "-bso0", "-bsp0", "-o" + dest_dir, archive_path]
            )
            break

    generic_tar = shutil.which("tar")
    if generic_tar:
        candidates.append([generic_tar, "-xf", archive_path, "-C", dest_dir])

    return candidates


def _dir_has_files(root: str) -> bool:
    for _root, _dirs, files in os.walk(root):
        if files:
            return True
    return False


def _clear_dir(root: str) -> None:
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                pass


def _copy_tree_into(
    src_root: str,
    destination_dir: str,
    *,
    max_entries: int,
    max_single_file_size: int,
    max_total_uncompressed: int,
) -> int:
    files: list[str] = []
    for root, _dirs, names in os.walk(src_root):
        for name in names:
            files.append(os.path.join(root, name))

    if len(files) > max_entries:
        raise ArchiveExtractionError(
            f"Archive has too many entries ({len(files)} > {max_entries})"
        )

    total = 0
    copied = 0
    for src_path in files:
        if os.path.islink(src_path):
            raise ArchiveExtractionError(
                f"Archive symlink entries are not allowed: {src_path}"
            )

        size = os.path.getsize(src_path)
        if size > max_single_file_size:
            raise ArchiveExtractionError(
                f"Archive entry exceeds max file size "
                f"({size} > {max_single_file_size})"
            )
        total += size
        if total > max_total_uncompressed:
            raise ArchiveExtractionError(
                f"Archive exceeds max uncompressed size "
                f"({total} > {max_total_uncompressed})"
            )

        rel = os.path.relpath(src_path, src_root)
        normalized = _normalize_member_name(rel)
        if not normalized:
            continue
        target_path = _resolve_safe_target(destination_dir, normalized)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.copy2(src_path, target_path)
        copied += 1

    return copied


def extract_rar(
    archive_path: str,
    destination_dir: str,
    *,
    max_entries: int = ZIP_MAX_ENTRIES,
    max_single_file_size: int = ZIP_MAX_FILE_BYTES,
    max_total_uncompressed: int = ZIP_MAX_TOTAL_BYTES,
) -> int:
    os.makedirs(destination_dir, exist_ok=True)

    candidates = _rar_extractor_candidates(archive_path, "")
    if not candidates:
        raise ArchiveExtractionError(
            "Cannot extract RAR archive: no RAR-capable extractor found. "
            "Install 'unrar' or '7-Zip' (or re-host the file as .zip)."
        )

    with tempfile.TemporaryDirectory(prefix="histolauncher-rar-") as staging:
        attempts: list[str] = []
        extracted_ok = False
        for argv in _rar_extractor_candidates(archive_path, staging):
            tool = os.path.basename(argv[0])
            try:
                result = subprocess.run(
                    argv,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=120,
                    **no_window_kwargs(),
                )
            except (OSError, subprocess.SubprocessError) as exc:
                attempts.append(f"{tool}: {exc}")
                _clear_dir(staging)
                continue

            if result.returncode == 0 and _dir_has_files(staging):
                extracted_ok = True
                break

            detail = (result.stderr or b"").decode("utf-8", "replace").strip()
            attempts.append(
                f"{tool} rc={result.returncode}"
                + (f" ({detail[:120]})" if detail else "")
            )
            _clear_dir(staging)

        if not extracted_ok:
            raise ArchiveExtractionError(
                "Failed to extract RAR archive with any available extractor. "
                "Install 'unrar' or '7-Zip' (or re-host the file as .zip). "
                "Tried: " + "; ".join(attempts)
            )

        return _copy_tree_into(
            staging,
            destination_dir,
            max_entries=max_entries,
            max_single_file_size=max_single_file_size,
            max_total_uncompressed=max_total_uncompressed,
        )
