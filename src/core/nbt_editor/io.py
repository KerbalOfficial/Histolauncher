from __future__ import annotations

import gzip
import io
import logging
import os
import zlib
from typing import Any, Dict, Optional, Tuple

from core.nbt_editor.reader import NbtReader
from core.nbt_editor.tags import TAG_COMPOUND
from core.nbt_editor.writer import NbtWriter


logger = logging.getLogger(__name__)

_MAX_NBT_DECOMPRESSED_BYTES = 64 * 1024 * 1024
_DECOMPRESS_CHUNK = 64 * 1024


def _bounded_gzip_decompress(raw: bytes) -> bytes:
    out = bytearray()
    with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as gz:
        while True:
            chunk = gz.read(_DECOMPRESS_CHUNK)
            if not chunk:
                break
            out.extend(chunk)
            if len(out) > _MAX_NBT_DECOMPRESSED_BYTES:
                raise ValueError("NBT gzip payload exceeds decompression limit")
    return bytes(out)


def _bounded_zlib_decompress(raw: bytes) -> bytes:
    decompressor = zlib.decompressobj()
    out = bytearray()
    pos = 0
    while pos < len(raw):
        chunk = decompressor.decompress(raw[pos:pos + _DECOMPRESS_CHUNK], _DECOMPRESS_CHUNK)
        pos += _DECOMPRESS_CHUNK
        out.extend(chunk)
        if len(out) > _MAX_NBT_DECOMPRESSED_BYTES:
            raise ValueError("NBT zlib payload exceeds decompression limit")
        while decompressor.unconsumed_tail:
            chunk = decompressor.decompress(decompressor.unconsumed_tail, _DECOMPRESS_CHUNK)
            out.extend(chunk)
            if len(out) > _MAX_NBT_DECOMPRESSED_BYTES:
                raise ValueError("NBT zlib payload exceeds decompression limit")
    out.extend(decompressor.flush())
    if len(out) > _MAX_NBT_DECOMPRESSED_BYTES:
        raise ValueError("NBT zlib payload exceeds decompression limit")
    return bytes(out)


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
            payload = _bounded_gzip_decompress(raw)
            compression = "gzip"
        else:
            try:
                payload = _bounded_zlib_decompress(raw)
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
    tmp_path = path + ".tmp"
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

        with open(tmp_path, "wb") as f:
            f.write(data)
        os.replace(tmp_path, path)
        return True
    except Exception as exc:
        logger.error(f"Failed to write NBT file {path}: {exc}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False


__all__ = ["read_nbt_file", "write_nbt_file"]
