from __future__ import annotations

from core.nbt_editor.converters import (
    bool_value,
    compound_child,
    compound_tag_value,
    ensure_compound_value,
    ensure_root_value,
    float_value,
    int_value,
    nbt_from_json_safe,
    nbt_root_from_json_safe,
    nbt_root_to_json_safe,
    nbt_to_json_safe,
    set_compound_tag,
    tag_value,
)
from core.nbt_editor.io import read_nbt_file, write_nbt_file
from core.nbt_editor.reader import NbtReader
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
from core.nbt_editor.writer import NbtWriter


__all__ = [
    # Tag constants
    "TAG_END",
    "TAG_BYTE",
    "TAG_SHORT",
    "TAG_INT",
    "TAG_LONG",
    "TAG_FLOAT",
    "TAG_DOUBLE",
    "TAG_BYTE_ARRAY",
    "TAG_STRING",
    "TAG_LIST",
    "TAG_COMPOUND",
    "TAG_INT_ARRAY",
    "TAG_LONG_ARRAY",
    # Reader/writer classes
    "NbtReader",
    "NbtWriter",
    # File I/O
    "read_nbt_file",
    "write_nbt_file",
    # Accessors / coercion
    "compound_child",
    "tag_value",
    "bool_value",
    "int_value",
    "float_value",
    "compound_tag_value",
    "ensure_root_value",
    "ensure_compound_value",
    "set_compound_tag",
    # JSON bridge
    "nbt_to_json_safe",
    "nbt_from_json_safe",
    "nbt_root_to_json_safe",
    "nbt_root_from_json_safe",
]
