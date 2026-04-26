from __future__ import annotations

import struct
from typing import Any, List

from core.nbt_editor.tags import (
    TAG_BYTE,
    TAG_BYTE_ARRAY,
    TAG_COMPOUND,
    TAG_DOUBLE,
    TAG_END,
    TAG_FLOAT,
    TAG_INT,
    TAG_INT_ARRAY,
    TAG_LIST,
    TAG_LONG,
    TAG_LONG_ARRAY,
    TAG_SHORT,
    TAG_STRING,
)


class NbtWriter:
    def __init__(self):
        self._chunks: List[bytes] = []

    def _write(self, chunk: bytes) -> None:
        self._chunks.append(chunk)

    def _u8(self, value: int) -> None:
        self._write(struct.pack(">B", int(value) & 0xFF))

    def _i8(self, value: int) -> None:
        self._write(struct.pack(">b", int(value)))

    def _i16(self, value: int) -> None:
        self._write(struct.pack(">h", int(value)))

    def _u16(self, value: int) -> None:
        self._write(struct.pack(">H", int(value)))

    def _i32(self, value: int) -> None:
        self._write(struct.pack(">i", int(value)))

    def _i64(self, value: int) -> None:
        self._write(struct.pack(">q", int(value)))

    def _f32(self, value: float) -> None:
        self._write(struct.pack(">f", float(value)))

    def _f64(self, value: float) -> None:
        self._write(struct.pack(">d", float(value)))

    def _string(self, value: str) -> None:
        encoded = str(value or "").encode("utf-8")
        self._u16(len(encoded))
        self._write(encoded)

    def named_tag(self, tag_type: int, name: str, value: Any) -> bytes:
        self._u8(tag_type)
        self._string(name)
        self.payload(tag_type, value)
        return b"".join(self._chunks)

    def payload(self, tag_type: int, value: Any) -> None:
        if tag_type == TAG_BYTE:
            self._i8(value)
            return
        if tag_type == TAG_SHORT:
            self._i16(value)
            return
        if tag_type == TAG_INT:
            self._i32(value)
            return
        if tag_type == TAG_LONG:
            self._i64(value)
            return
        if tag_type == TAG_FLOAT:
            self._f32(value)
            return
        if tag_type == TAG_DOUBLE:
            self._f64(value)
            return
        if tag_type == TAG_BYTE_ARRAY:
            payload = bytes(value or b"")
            self._i32(len(payload))
            self._write(payload)
            return
        if tag_type == TAG_STRING:
            self._string(value)
            return
        if tag_type == TAG_LIST:
            list_type = int((value or {}).get("list_type", TAG_END))
            items = list((value or {}).get("items", []))
            self._u8(list_type)
            self._i32(len(items))
            for item in items:
                self.payload(list_type, item)
            return
        if tag_type == TAG_COMPOUND:
            compound = value if isinstance(value, dict) else {}
            for name, tag in compound.items():
                if not isinstance(tag, dict):
                    continue
                inner_type = int(tag.get("type", TAG_END))
                self._u8(inner_type)
                self._string(name)
                self.payload(inner_type, tag.get("value"))
            self._u8(TAG_END)
            return
        if tag_type == TAG_INT_ARRAY:
            items = list(value or [])
            self._i32(len(items))
            for item in items:
                self._i32(item)
            return
        if tag_type == TAG_LONG_ARRAY:
            items = list(value or [])
            self._i32(len(items))
            for item in items:
                self._i64(item)
            return
        raise ValueError(f"Unsupported NBT tag type: {tag_type}")


__all__ = ["NbtWriter"]
