from __future__ import annotations

import struct
from typing import Any, Tuple

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


class NbtReader:
    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def _take(self, size: int) -> bytes:
        if self._pos + size > len(self._data):
            raise ValueError("NBT payload ended unexpectedly")
        chunk = self._data[self._pos:self._pos + size]
        self._pos += size
        return chunk

    def _u8(self) -> int:
        return struct.unpack(">B", self._take(1))[0]

    def _i8(self) -> int:
        return struct.unpack(">b", self._take(1))[0]

    def _i16(self) -> int:
        return struct.unpack(">h", self._take(2))[0]

    def _u16(self) -> int:
        return struct.unpack(">H", self._take(2))[0]

    def _i32(self) -> int:
        return struct.unpack(">i", self._take(4))[0]

    def _i64(self) -> int:
        return struct.unpack(">q", self._take(8))[0]

    def _f32(self) -> float:
        return struct.unpack(">f", self._take(4))[0]

    def _f64(self) -> float:
        return struct.unpack(">d", self._take(8))[0]

    def _string(self) -> str:
        size = self._u16()
        return self._take(size).decode("utf-8", errors="replace")

    def named_tag(self) -> Tuple[int, str, Any]:
        tag_type = self._u8()
        if tag_type == TAG_END:
            return TAG_END, "", None
        name = self._string()
        return tag_type, name, self.payload(tag_type)

    def payload(self, tag_type: int) -> Any:
        if tag_type == TAG_BYTE:
            return self._i8()
        if tag_type == TAG_SHORT:
            return self._i16()
        if tag_type == TAG_INT:
            return self._i32()
        if tag_type == TAG_LONG:
            return self._i64()
        if tag_type == TAG_FLOAT:
            return self._f32()
        if tag_type == TAG_DOUBLE:
            return self._f64()
        if tag_type == TAG_BYTE_ARRAY:
            size = self._i32()
            return self._take(size)
        if tag_type == TAG_STRING:
            return self._string()
        if tag_type == TAG_LIST:
            item_type = self._u8()
            size = self._i32()
            return {
                "list_type": item_type,
                "items": [self.payload(item_type) for _ in range(size)],
            }
        if tag_type == TAG_COMPOUND:
            out = {}
            while True:
                inner_type = self._u8()
                if inner_type == TAG_END:
                    break
                inner_name = self._string()
                out[inner_name] = {
                    "type": inner_type,
                    "value": self.payload(inner_type),
                }
            return out
        if tag_type == TAG_INT_ARRAY:
            size = self._i32()
            return [self._i32() for _ in range(size)]
        if tag_type == TAG_LONG_ARRAY:
            size = self._i32()
            return [self._i64() for _ in range(size)]
        raise ValueError(f"Unsupported NBT tag type: {tag_type}")


__all__ = ["NbtReader"]
