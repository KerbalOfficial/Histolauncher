from __future__ import annotations

import struct
import zlib
from typing import Any


LEGACY_SKIN_OVERLAY_PARTS: tuple[str, ...] = (
    "head",
    "body",
    "right_arm",
    "left_arm",
    "right_leg",
    "left_leg",
)
LEGACY_SKIN_TEXTURE_TYPES: tuple[str, ...] = ("default", "legacy")
LEGACY_SKIN_MIRROR_SIDES: tuple[str, ...] = ("right", "left")

_OVERLAY_PART_ALIASES = {
    "hat": "head",
    "helmet": "head",
    "jacket": "body",
    "torso": "body",
    "rightarm": "right_arm",
    "right_arm": "right_arm",
    "right-sleeve": "right_arm",
    "right_sleeve": "right_arm",
    "rightsleeve": "right_arm",
    "leftarm": "left_arm",
    "left_arm": "left_arm",
    "left-sleeve": "left_arm",
    "left_sleeve": "left_arm",
    "leftsleeve": "left_arm",
    "rightleg": "right_leg",
    "right_leg": "right_leg",
    "right-pants": "right_leg",
    "right_pants": "right_leg",
    "rightpants": "right_leg",
    "leftleg": "left_leg",
    "left_leg": "left_leg",
    "left-pants": "left_leg",
    "left_pants": "left_leg",
    "leftpants": "left_leg",
}


def normalize_skin_overlay_parts(value: Any) -> list[str]:
    if value is True:
        return list(LEGACY_SKIN_OVERLAY_PARTS)
    if value in (None, False):
        return []
    if isinstance(value, str):
        items = re_split_overlay_parts(value)
    elif isinstance(value, dict):
        items = [key for key, enabled in value.items() if enabled]
    else:
        try:
            items = list(value)
        except TypeError:
            items = [value]

    flattened: list[Any] = []
    for item in items:
        if isinstance(item, str):
            flattened.extend(re_split_overlay_parts(item))
        else:
            flattened.append(item)

    out: list[str] = []
    for item in flattened:
        raw = str(item or "").strip().lower()
        key = raw.replace(" ", "_")
        clean = _OVERLAY_PART_ALIASES.get(key, key)
        if clean in LEGACY_SKIN_OVERLAY_PARTS and clean not in out:
            out.append(clean)
    return out


def re_split_overlay_parts(value: str) -> list[str]:
    return [part for part in value.replace("|", ",").replace(";", ",").split(",") if part.strip()]


def normalize_skin_texture_type(value: Any, *, source_height: int | None = None) -> str:
    if source_height == 32:
        return "legacy"
    raw = str(value or "").strip().lower().replace("-", "_")
    if raw in {"legacy", "classic", "old", "64x32", "legacy_64x32"}:
        return "legacy"
    return "default"


def normalize_skin_limb_mirror(value: Any, *, default: str = "right") -> str:
    fallback = "left" if str(default or "").strip().lower() == "left" else "right"
    raw = str(value or "").strip().lower().replace("-", "_")
    if raw in {"left", "l", "left_side", "left_limb"}:
        return "left"
    if raw in {"right", "r", "right_side", "right_limb"}:
        return "right"
    return fallback


def normalize_skin_overlay_parts_for_texture_type(
    value: Any,
    *,
    texture_type: Any = None,
    source_height: int | None = None,
    arm_mirror: Any = "right",
    leg_mirror: Any = "right",
) -> list[str]:
    parts = normalize_skin_overlay_parts(value)
    if source_height == 32:
        return [part for part in parts if part == "head"]
    if source_height != 64:
        return []

    clean_texture_type = normalize_skin_texture_type(texture_type, source_height=source_height)
    if clean_texture_type != "legacy":
        return parts

    clean_arm_mirror = normalize_skin_limb_mirror(arm_mirror)
    clean_leg_mirror = normalize_skin_limb_mirror(leg_mirror)
    sanitized = list(parts)
    if "right_arm" in sanitized and "left_arm" in sanitized:
        rejected_arm = "right_arm" if clean_arm_mirror == "left" else "left_arm"
        sanitized = [part for part in sanitized if part != rejected_arm]
    if "right_leg" in sanitized and "left_leg" in sanitized:
        rejected_leg = "right_leg" if clean_leg_mirror == "left" else "left_leg"
        sanitized = [part for part in sanitized if part != rejected_leg]
    return sanitized


def _make_png_chunk(chunk_type: bytes, chunk_data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(chunk_data))
        + chunk_type
        + chunk_data
        + struct.pack(">I", crc)
    )


def _read_skin_png(data: bytes) -> dict[str, Any] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None

    def read_chunk(pos: int):
        if pos + 12 > len(data):
            return None, None, pos
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        chunk_type = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + length]
        return chunk_type, chunk_data, pos + 12 + length

    pos = 8
    chunk_type, ihdr_data, pos = read_chunk(pos)
    if chunk_type != b"IHDR" or len(ihdr_data or b"") < 13:
        return None

    width = struct.unpack(">I", ihdr_data[0:4])[0]
    height = struct.unpack(">I", ihdr_data[4:8])[0]
    if width != 64 or height not in {32, 64}:
        return None

    bit_depth = ihdr_data[8]
    color_type = ihdr_data[9]
    compression_method = ihdr_data[10]
    filter_method = ihdr_data[11]
    interlace_method = ihdr_data[12]
    if bit_depth != 8 or compression_method != 0 or filter_method != 0 or interlace_method != 0:
        return None

    bytes_per_pixel = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if not bytes_per_pixel:
        return None

    row_size = 1 + width * bytes_per_pixel
    ancillary: list[tuple[bytes, bytes]] = []
    idat_raw = b""
    while pos < len(data):
        chunk_type, chunk_data, pos = read_chunk(pos)
        if chunk_type is None:
            break
        if chunk_type == b"IDAT":
            idat_raw += chunk_data
        elif chunk_type == b"IEND":
            break
        elif chunk_type != b"IHDR":
            ancillary.append((chunk_type, chunk_data))

    try:
        raw = zlib.decompress(idat_raw)
    except Exception:
        return None

    if len(raw) < row_size * height:
        return None

    return {
        "data": data,
        "width": width,
        "height": height,
        "row_size": row_size,
        "ihdr_data": ihdr_data,
        "ancillary": ancillary,
        "raw": raw,
        "color_type": color_type,
    }


def _encode_skin_png(ihdr_data: bytes, ancillary: list[tuple[bytes, bytes]], raw: bytes, height: int) -> bytes:
    new_ihdr = ihdr_data[:4] + struct.pack(">I", height) + ihdr_data[8:]
    out = b"\x89PNG\r\n\x1a\n"
    out += _make_png_chunk(b"IHDR", new_ihdr)
    for chunk_type, chunk_data in ancillary:
        out += _make_png_chunk(chunk_type, chunk_data)
    out += _make_png_chunk(b"IDAT", zlib.compress(raw, 6))
    out += _make_png_chunk(b"IEND", b"")
    return out


def merge_skin_overlay_into_base(
    png_data: bytes,
    *,
    merge_overlay: bool = False,
    overlay_parts: Any = None,
    arm_mirror: Any = "right",
    leg_mirror: Any = "right",
    legacy_layout: bool = False,
) -> bytes:
    data = bytes(png_data or b"")
    image = _read_skin_png(data)
    if not image:
        return data

    selected_parts = set(normalize_skin_overlay_parts(
        LEGACY_SKIN_OVERLAY_PARTS if merge_overlay and overlay_parts is None else overlay_parts
    ))
    clean_arm_mirror = normalize_skin_limb_mirror(arm_mirror)
    clean_leg_mirror = normalize_skin_limb_mirror(leg_mirror)
    mirror_left_limb = image["height"] == 64 and (
        clean_arm_mirror == "left" or clean_leg_mirror == "left"
    )
    if not selected_parts and not mirror_left_limb:
        return data
    if image["color_type"] != 6:
        return data

    rows = _decode_rgba_rows(image["raw"], image["width"], image["height"], image["row_size"])
    if not rows:
        return data
    if mirror_left_limb:
        _apply_limb_mirrors(rows, clean_arm_mirror, clean_leg_mirror)
    if "head" in selected_parts:
        _merge_head_overlay(rows)
    if image["height"] == 64:
        if legacy_layout:
            _merge_legacy_body_overlay(rows, selected_parts)
        else:
            _merge_modern_body_overlay(rows, selected_parts)
    new_raw = b"".join(b"\x00" + bytes(rows[row]) for row in range(image["height"]))
    return _encode_skin_png(image["ihdr_data"], image["ancillary"], new_raw, image["height"])


def convert_skin_to_legacy_format(
    png_data: bytes,
    *,
    merge_overlay: bool = False,
    overlay_parts: Any = None,
    arm_mirror: Any = "right",
    leg_mirror: Any = "right",
) -> bytes:
    data = bytes(png_data or b"")
    merged = merge_skin_overlay_into_base(
        data,
        merge_overlay=merge_overlay,
        overlay_parts=overlay_parts,
        arm_mirror=arm_mirror,
        leg_mirror=leg_mirror,
        legacy_layout=True,
    )
    image = _read_skin_png(merged)
    if not image:
        return data
    if image["height"] == 32:
        return merged
    new_raw = image["raw"][: image["row_size"] * 32]
    return _encode_skin_png(image["ihdr_data"], image["ancillary"], new_raw, 32)


def _decode_rgba_rows(raw: bytes, width: int, height: int, row_size: int) -> list[bytearray]:
    bpp = 4
    rows: list[bytearray] = []
    prev = bytearray(width * bpp)
    for y in range(height):
        start = y * row_size
        if start + row_size > len(raw):
            return []
        filter_type = raw[start]
        row = bytearray(raw[start + 1 : start + row_size])
        row_len = width * bpp
        if filter_type == 1:
            for index in range(bpp, row_len):
                row[index] = (row[index] + row[index - bpp]) & 0xFF
        elif filter_type == 2:
            for index in range(row_len):
                row[index] = (row[index] + prev[index]) & 0xFF
        elif filter_type == 3:
            for index in range(row_len):
                left = row[index - bpp] if index >= bpp else 0
                row[index] = (row[index] + (left + prev[index]) // 2) & 0xFF
        elif filter_type == 4:
            for index in range(row_len):
                left = row[index - bpp] if index >= bpp else 0
                up = prev[index]
                up_left = prev[index - bpp] if index >= bpp else 0
                row[index] = (row[index] + _paeth(left, up, up_left)) & 0xFF
        elif filter_type != 0:
            return []
        rows.append(row)
        prev = bytearray(row)
    return rows


def _paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    dist_left = abs(estimate - left)
    dist_up = abs(estimate - up)
    dist_up_left = abs(estimate - up_left)
    if dist_left <= dist_up and dist_left <= dist_up_left:
        return left
    if dist_up <= dist_up_left:
        return up
    return up_left


def _merge_pixel(row: bytearray, target_x: int, source_row: bytearray, source_x: int) -> None:
    target = target_x * 4
    source = source_x * 4
    source_alpha = source_row[source + 3]
    if source_alpha == 0:
        return
    if source_alpha == 255:
        row[target : target + 4] = source_row[source : source + 4]
        return

    target_alpha = row[target + 3]
    out_alpha = source_alpha + target_alpha * (255 - source_alpha) // 255
    if out_alpha <= 0:
        row[target : target + 4] = b"\x00\x00\x00\x00"
        return

    for offset in range(3):
        row[target + offset] = (
            source_row[source + offset] * source_alpha
            + row[target + offset] * target_alpha * (255 - source_alpha) // 255
        ) // out_alpha
    row[target + 3] = out_alpha


def _clear_pixel(row: bytearray, x: int) -> None:
    start = x * 4
    row[start : start + 4] = b"\x00\x00\x00\x00"


def _merge_head_overlay(rows: list[bytearray]) -> None:
    for y in range(16):
        row = rows[y]
        for x in range(32):
            _merge_pixel(row, x, row, x + 32)
            _clear_pixel(row, x + 32)


def _merge_rect(
    rows: list[bytearray],
    target_x: int,
    target_y: int,
    source_x: int,
    source_y: int,
    width: int,
    height: int,
) -> None:
    for dy in range(height):
        base_row = rows[target_y + dy]
        overlay_row = rows[source_y + dy]
        for dx in range(width):
            _merge_pixel(base_row, target_x + dx, overlay_row, source_x + dx)


def _clear_rect(
    rows: list[bytearray],
    x: int,
    y: int,
    width: int,
    height: int,
) -> None:
    for dy in range(height):
        row = rows[y + dy]
        for dx in range(width):
            _clear_pixel(row, x + dx)


def _copy_rect(
    rows: list[bytearray],
    target_x: int,
    target_y: int,
    source_x: int,
    source_y: int,
    width: int,
    height: int,
) -> None:
    bpp = 4
    copied = [
        bytes(rows[source_y + dy][source_x * bpp : (source_x + width) * bpp])
        for dy in range(height)
    ]
    for dy, chunk in enumerate(copied):
        start = target_x * bpp
        rows[target_y + dy][start : start + len(chunk)] = chunk


def _apply_limb_mirrors(rows: list[bytearray], arm_mirror: str, leg_mirror: str) -> None:
    if len(rows) < 64:
        return
    if leg_mirror == "left":
        _copy_rect(rows, 0, 16, 16, 48, 16, 16)
    if arm_mirror == "left":
        _copy_rect(rows, 40, 16, 32, 48, 16, 16)


def _merge_modern_body_overlay(rows: list[bytearray], selected_parts: set[str]) -> None:
    if "right_leg" in selected_parts:
        _merge_rect(rows, 0, 16, 0, 32, 16, 16)
        _clear_rect(rows, 0, 32, 16, 16)
    if "body" in selected_parts:
        _merge_rect(rows, 16, 16, 16, 32, 24, 16)
        _clear_rect(rows, 16, 32, 24, 16)
    if "right_arm" in selected_parts:
        _merge_rect(rows, 40, 16, 40, 32, 16, 16)
        _clear_rect(rows, 40, 32, 16, 16)
    if "left_leg" in selected_parts:
        _merge_rect(rows, 16, 48, 0, 48, 16, 16)
        _clear_rect(rows, 0, 48, 16, 16)
    if "left_arm" in selected_parts:
        _merge_rect(rows, 32, 48, 48, 48, 16, 16)
        _clear_rect(rows, 48, 48, 16, 16)


def _merge_legacy_body_overlay(rows: list[bytearray], selected_parts: set[str]) -> None:
    if "right_leg" in selected_parts:
        _merge_rect(rows, 0, 16, 0, 32, 16, 16)
        _clear_rect(rows, 0, 32, 16, 16)
    if "body" in selected_parts:
        _merge_rect(rows, 16, 16, 16, 32, 24, 16)
        _clear_rect(rows, 16, 32, 24, 16)
    if "right_arm" in selected_parts:
        _merge_rect(rows, 40, 16, 40, 32, 16, 16)
        _clear_rect(rows, 40, 32, 16, 16)
    if "left_leg" in selected_parts:
        _merge_rect(rows, 0, 16, 0, 48, 16, 16)
        _clear_rect(rows, 0, 48, 16, 16)
    if "left_arm" in selected_parts:
        _merge_rect(rows, 40, 16, 48, 48, 16, 16)
        _clear_rect(rows, 48, 48, 16, 16)