from __future__ import annotations

from typing import Any, Dict, Optional

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


def compound_child(compound: Any, key: str) -> Optional[Dict[str, Any]]:
    if not isinstance(compound, dict):
        return None
    value = compound.get(key)
    return value if isinstance(value, dict) else None


def tag_value(compound: Any, key: str, default: Any = None) -> Any:
    tag = compound_child(compound, key)
    if not tag:
        return default
    return tag.get("value", default)


def bool_value(value: Any) -> bool:
    try:
        return bool(int(value))
    except Exception:
        return bool(value)


def int_value(value: Any, default: Optional[int] = 0) -> Optional[int]:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except Exception:
        return default


def float_value(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except Exception:
        return default


def compound_tag_value(tag: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(tag, dict):
        return None
    try:
        if int(tag.get("type", TAG_END) or TAG_END) != TAG_COMPOUND:
            return None
    except Exception:
        return None
    value = tag.get("value")
    return value if isinstance(value, dict) else None


def ensure_root_value(root_tag: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance((root_tag or {}).get("value"), dict):
        root_tag["value"] = {}
    return root_tag["value"]


def ensure_compound_value(compound: Dict[str, Any], key: str) -> Dict[str, Any]:
    child = compound_child(compound, key)
    child_value = compound_tag_value(child)
    if child_value is None:
        child = {"type": TAG_COMPOUND, "value": {}}
        compound[key] = child
        child_value = child["value"]
    return child_value


def _coerce_numeric_for_tag(tag_type: int, value: Any) -> Any:
    if tag_type in {TAG_BYTE, TAG_SHORT, TAG_INT, TAG_LONG}:
        return int(value)
    if tag_type in {TAG_FLOAT, TAG_DOUBLE}:
        return float(value)
    return value


def set_compound_tag(compound: Dict[str, Any], key: str, tag_type: int, value: Any) -> None:
    if not isinstance(compound, dict):
        return

    existing = compound_child(compound, key)
    effective_type = tag_type
    try:
        existing_type = int((existing or {}).get("type", tag_type) or tag_type)
    except Exception:
        existing_type = tag_type

    if tag_type in {TAG_BYTE, TAG_SHORT, TAG_INT, TAG_LONG, TAG_FLOAT, TAG_DOUBLE} and existing_type in {
        TAG_BYTE, TAG_SHORT, TAG_INT, TAG_LONG, TAG_FLOAT, TAG_DOUBLE,
    }:
        effective_type = existing_type
    elif tag_type == TAG_STRING and existing_type == TAG_STRING:
        effective_type = TAG_STRING

    if effective_type in {TAG_BYTE, TAG_SHORT, TAG_INT, TAG_LONG, TAG_FLOAT, TAG_DOUBLE}:
        stored_value = _coerce_numeric_for_tag(effective_type, value)
    elif effective_type == TAG_STRING:
        stored_value = str(value or "")
    else:
        stored_value = value

    compound[key] = {"type": effective_type, "value": stored_value}


def nbt_to_json_safe(tag_type: int, value: Any) -> Any:
    if tag_type == TAG_COMPOUND:
        out = {}
        for child_name, child_tag in (value or {}).items():
            if not isinstance(child_tag, dict):
                continue
            child_type = int(child_tag.get("type", TAG_END) or TAG_END)
            if child_type == TAG_END:
                continue
            out[child_name] = {
                "type": child_type,
                "value": nbt_to_json_safe(child_type, child_tag.get("value")),
            }
        return out

    if tag_type == TAG_LIST:
        list_type = int((value or {}).get("list_type", TAG_END) or TAG_END)
        items = list((value or {}).get("items", []))
        return {
            "list_type": list_type,
            "items": [
                nbt_to_json_safe(list_type, item) if list_type != TAG_END else item
                for item in items
            ],
        }

    if tag_type == TAG_BYTE_ARRAY:
        return list(value or b"")

    if tag_type in {TAG_INT_ARRAY, TAG_LONG_ARRAY}:
        return [int(item) for item in list(value or [])]

    return value


def _coerce_json_tag_type(value: Any, path: str, *, allow_end: bool = False) -> int:
    try:
        tag_type = int(value)
    except Exception as exc:
        raise ValueError(f"{path} must be a valid numeric NBT tag type.") from exc

    valid_types = {
        TAG_BYTE,
        TAG_SHORT,
        TAG_INT,
        TAG_LONG,
        TAG_FLOAT,
        TAG_DOUBLE,
        TAG_BYTE_ARRAY,
        TAG_STRING,
        TAG_LIST,
        TAG_COMPOUND,
        TAG_INT_ARRAY,
        TAG_LONG_ARRAY,
    }
    if allow_end:
        valid_types.add(TAG_END)
    if tag_type not in valid_types:
        raise ValueError(f"{path} contains unsupported tag type {tag_type}.")
    return tag_type


def nbt_from_json_safe(tag_type: int, value: Any, path: str = "value") -> Any:
    if tag_type == TAG_BYTE:
        parsed = int_value(value, None)
        if parsed is None or parsed < -128 or parsed > 127:
            raise ValueError(f"{path} must be a byte between -128 and 127.")
        return parsed

    if tag_type == TAG_SHORT:
        parsed = int_value(value, None)
        if parsed is None or parsed < -32768 or parsed > 32767:
            raise ValueError(f"{path} must be a short between -32768 and 32767.")
        return parsed

    if tag_type == TAG_INT:
        parsed = int_value(value, None)
        if parsed is None or parsed < -2147483648 or parsed > 2147483647:
            raise ValueError(f"{path} must be a 32-bit integer.")
        return parsed

    if tag_type == TAG_LONG:
        parsed = int_value(value, None)
        if parsed is None or parsed < -9223372036854775808 or parsed > 9223372036854775807:
            raise ValueError(f"{path} must be a 64-bit integer.")
        return parsed

    if tag_type == TAG_FLOAT:
        parsed = float_value(value, None)
        if parsed is None:
            raise ValueError(f"{path} must be a number.")
        return parsed

    if tag_type == TAG_DOUBLE:
        parsed = float_value(value, None)
        if parsed is None:
            raise ValueError(f"{path} must be a number.")
        return parsed

    if tag_type == TAG_STRING:
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string.")
        return value

    if tag_type == TAG_BYTE_ARRAY:
        if not isinstance(value, list):
            raise ValueError(f"{path} must be a list of bytes.")
        out = []
        for index, item in enumerate(value):
            parsed = int_value(item, None)
            if parsed is None or parsed < 0 or parsed > 255:
                raise ValueError(f"{path}[{index}] must be between 0 and 255.")
            out.append(parsed)
        return bytes(out)

    if tag_type == TAG_INT_ARRAY:
        if not isinstance(value, list):
            raise ValueError(f"{path} must be a list of integers.")
        out = []
        for index, item in enumerate(value):
            parsed = int_value(item, None)
            if parsed is None or parsed < -2147483648 or parsed > 2147483647:
                raise ValueError(f"{path}[{index}] must be a 32-bit integer.")
            out.append(parsed)
        return out

    if tag_type == TAG_LONG_ARRAY:
        if not isinstance(value, list):
            raise ValueError(f"{path} must be a list of long integers.")
        out = []
        for index, item in enumerate(value):
            parsed = int_value(item, None)
            if parsed is None or parsed < -9223372036854775808 or parsed > 9223372036854775807:
                raise ValueError(f"{path}[{index}] must be a 64-bit integer.")
            out.append(parsed)
        return out

    if tag_type == TAG_LIST:
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be a list descriptor object.")
        list_type = _coerce_json_tag_type(value.get("list_type"), f"{path}.list_type", allow_end=True)
        items = value.get("items")
        if not isinstance(items, list):
            raise ValueError(f"{path}.items must be an array.")
        if list_type == TAG_END and items:
            raise ValueError(f"{path}.items must be empty when list_type is 0.")
        return {
            "list_type": list_type,
            "items": [
                nbt_from_json_safe(list_type, item, f"{path}.items[{index}]")
                for index, item in enumerate(items)
            ],
        }

    if tag_type == TAG_COMPOUND:
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object.")
        out = {}
        for child_name, child_tag in value.items():
            if not isinstance(child_name, str) or not child_name:
                raise ValueError(f"{path} contains an invalid child tag name.")
            if not isinstance(child_tag, dict):
                raise ValueError(f"{path}.{child_name} must be an object.")
            child_type = _coerce_json_tag_type(child_tag.get("type"), f"{path}.{child_name}.type")
            out[child_name] = {
                "type": child_type,
                "value": nbt_from_json_safe(child_type, child_tag.get("value"), f"{path}.{child_name}.value"),
            }
        return out

    raise ValueError(f"{path} uses unsupported tag type {tag_type}.")


def nbt_root_to_json_safe(root_tag: Dict[str, Any]) -> Dict[str, Any]:
    tag_type = int((root_tag or {}).get("type", TAG_COMPOUND) or TAG_COMPOUND)
    return {
        "type": tag_type,
        "name": str((root_tag or {}).get("name", "") or ""),
        "value": nbt_to_json_safe(tag_type, (root_tag or {}).get("value", {})),
    }


def nbt_root_from_json_safe(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("The advanced NBT payload must be a JSON object.")

    tag_type = _coerce_json_tag_type(value.get("type"), "root.type")
    if tag_type != TAG_COMPOUND:
        raise ValueError("The root NBT tag must be a compound tag (type 10).")

    name = value.get("name", "")
    if not isinstance(name, str):
        raise ValueError("root.name must be a string.")

    return {
        "type": tag_type,
        "name": name,
        "value": nbt_from_json_safe(tag_type, value.get("value", {}), "root.value"),
    }


__all__ = [
    "compound_child",
    "tag_value",
    "bool_value",
    "int_value",
    "float_value",
    "compound_tag_value",
    "ensure_root_value",
    "ensure_compound_value",
    "set_compound_tag",
    "nbt_to_json_safe",
    "nbt_from_json_safe",
    "nbt_root_to_json_safe",
    "nbt_root_from_json_safe",
]
