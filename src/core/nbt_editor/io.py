from __future__ import annotations

import gzip
import logging
import os
import zlib
from typing import Any, Dict, Optional, Tuple

from core.nbt_editor.reader import NbtReader
from core.nbt_editor.tags import TAG_COMPOUND
from core.nbt_editor.writer import NbtWriter


logger = logging.getLogger(__name__)


def read_nbt_file(path: str) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except Exception:
        return None, ""

    compression = "raw"
    payload = raw
    try:
        if raw[:2] == b"\x1f\x8b":
            payload = gzip.decompress(raw)
            compression = "gzip"
        else:
            try:
                payload = zlib.decompress(raw)
                compression = "zlib"
            except Exception:
                payload = raw
                compression = "raw"

        reader = NbtReader(payload)
        tag_type, name, value = reader.named_tag()
        if tag_type != TAG_COMPOUND or not isinstance(value, dict):
            return None, compression
        return {
            "type": tag_type,
            "name": name,
            "value": value,
        }, compression
    except Exception as exc:
        logger.warning(f"Failed to read NBT file {path}: {exc}")
        return None, compression


def write_nbt_file(path: str, nbt_root: Dict[str, Any], compression: str) -> bool:
    try:
        writer = NbtWriter()
        payload = writer.named_tag(
            int((nbt_root or {}).get("type", TAG_COMPOUND)),
            str((nbt_root or {}).get("name", "") or ""),
            (nbt_root or {}).get("value", {}),
        )
        if compression == "gzip":
            data = gzip.compress(payload)
        elif compression == "zlib":
            data = zlib.compress(payload)
        else:
            data = payload

        tmp_path = path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(data)
        os.replace(tmp_path, path)
        return True
    except Exception as exc:
        logger.error(f"Failed to write NBT file {path}: {exc}")
        return False


__all__ = ["read_nbt_file", "write_nbt_file"]
