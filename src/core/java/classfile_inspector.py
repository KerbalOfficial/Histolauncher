from __future__ import annotations

import os
import zipfile
from collections.abc import Iterable
from typing import Final

__all__ = [
    "CAFEBABE_MAGIC",
    "MIN_CLASSFILE_MAJOR",
    "class_file_major_to_java_major",
    "detect_archive_java_major",
    "detect_client_jar_java_major",
    "detect_java_major_requirement",
    "detect_path_java_major",
]


#: Java class file magic number, ``CAFEBABE``.
CAFEBABE_MAGIC: Final[bytes] = b"\xca\xfe\xba\xbe"

#: Class-file major version 45 corresponds to Java 1.0/1.1.
MIN_CLASSFILE_MAJOR: Final[int] = 45

_HEADER_BYTES: Final[int] = 8
_SUPPORTED_ARCHIVE_EXTENSIONS: Final[tuple[str, ...]] = (".jar", ".zip")


def class_file_major_to_java_major(class_major: int) -> int:
    try:
        major = int(class_major or 0)
    except (TypeError, ValueError):
        return 0
    if major < MIN_CLASSFILE_MAJOR:
        return 0
    return major - 44


def _java_major_from_class_header(header: bytes) -> int:
    if len(header) < _HEADER_BYTES or header[:4] != CAFEBABE_MAGIC:
        return 0
    return class_file_major_to_java_major(int.from_bytes(header[6:8], "big"))


def _detect_class_file_java_major(path: str) -> int:
    try:
        with open(path, "rb") as class_fp:
            header = class_fp.read(_HEADER_BYTES)
    except OSError:
        return 0
    return _java_major_from_class_header(header)


def detect_archive_java_major(archive_path: str) -> int:
    if not os.path.isfile(archive_path):
        return 0

    highest = 0
    try:
        with zipfile.ZipFile(archive_path, "r") as jar:
            for info in jar.infolist():
                if info.is_dir() or not str(info.filename or "").endswith(".class"):
                    continue
                try:
                    with jar.open(info, "r") as class_fp:
                        header = class_fp.read(_HEADER_BYTES)
                except (OSError, zipfile.BadZipFile):
                    continue
                java_major = _java_major_from_class_header(header)
                if java_major > highest:
                    highest = java_major
    except (OSError, zipfile.BadZipFile):
        return 0

    return highest


def detect_path_java_major(path: str) -> int:
    if not path:
        return 0

    normalized_path = os.path.abspath(path)
    if os.path.isfile(normalized_path):
        lower_name = normalized_path.lower()
        if lower_name.endswith(".class"):
            return _detect_class_file_java_major(normalized_path)
        if lower_name.endswith(_SUPPORTED_ARCHIVE_EXTENSIONS):
            return detect_archive_java_major(normalized_path)
        return 0

    if not os.path.isdir(normalized_path):
        return 0

    highest = 0
    try:
        for root, dirs, files in os.walk(normalized_path):
            dirs[:] = [name for name in dirs if name not in {"__pycache__", ".git"}]
            for filename in files:
                lower_name = filename.lower()
                file_path = os.path.join(root, filename)
                if lower_name.endswith(".class"):
                    java_major = _detect_class_file_java_major(file_path)
                elif lower_name.endswith(_SUPPORTED_ARCHIVE_EXTENSIONS):
                    java_major = detect_archive_java_major(file_path)
                else:
                    continue
                if java_major > highest:
                    highest = java_major
    except OSError:
        return highest

    return highest


def detect_client_jar_java_major(version_dir: str) -> int:
    return detect_archive_java_major(os.path.join(version_dir, "client.jar"))


def detect_java_major_requirement(version_dir: str, extra_paths: Iterable[str] | None = None) -> int:
    highest = detect_client_jar_java_major(version_dir)
    for path in extra_paths or ():
        java_major = detect_path_java_major(str(path or ""))
        if java_major > highest:
            highest = java_major
    return highest
