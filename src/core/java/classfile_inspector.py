from __future__ import annotations

import os
import zipfile
from typing import Final

__all__ = [
    "CAFEBABE_MAGIC",
    "MIN_CLASSFILE_MAJOR",
    "class_file_major_to_java_major",
    "detect_client_jar_java_major",
]


#: Java class file magic number, ``CAFEBABE``.
CAFEBABE_MAGIC: Final[bytes] = b"\xca\xfe\xba\xbe"

#: Class-file major version 45 corresponds to Java 1.0/1.1.
MIN_CLASSFILE_MAJOR: Final[int] = 45

_HEADER_BYTES: Final[int] = 8


def class_file_major_to_java_major(class_major: int) -> int:
    try:
        major = int(class_major or 0)
    except (TypeError, ValueError):
        return 0
    if major < MIN_CLASSFILE_MAJOR:
        return 0
    return major - 44


def detect_client_jar_java_major(version_dir: str) -> int:
    client_jar = os.path.join(version_dir, "client.jar")
    if not os.path.isfile(client_jar):
        return 0

    highest = 0
    try:
        with zipfile.ZipFile(client_jar, "r") as jar:
            for info in jar.infolist():
                if info.is_dir() or not str(info.filename or "").endswith(".class"):
                    continue
                try:
                    with jar.open(info, "r") as class_fp:
                        header = class_fp.read(_HEADER_BYTES)
                except (OSError, zipfile.BadZipFile):
                    continue
                if len(header) < _HEADER_BYTES or header[:4] != CAFEBABE_MAGIC:
                    continue
                class_major = int.from_bytes(header[6:8], "big")
                if class_major > highest:
                    highest = class_major
    except (OSError, zipfile.BadZipFile):
        return 0

    return class_file_major_to_java_major(highest)
