from __future__ import annotations

import os
import re
from typing import Dict, Optional, Union
from core.logger import safe_print


__all__ = ["parse_multipart_form"]


_DISP_NAME_RE = re.compile(r'name="([^"]*)"', re.IGNORECASE)
_DISP_FILENAME_RE = re.compile(r'filename="([^"]*)"', re.IGNORECASE)
_BOUNDARY_RE = re.compile(r"^[A-Za-z0-9'()+_,\-./:=? ]{1,200}$")
_FIELD_NAME_RE = re.compile(r"^[A-Za-z0-9_\-.]{1,128}$")


def _sanitize_field_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    candidate = name.strip()
    if not candidate or "\x00" in candidate:
        return None
    if not _FIELD_NAME_RE.match(candidate):
        return None
    return candidate


def _sanitize_filename(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    candidate = str(raw)
    if "\x00" in candidate:
        return None
    candidate = candidate.replace("\\", "/")
    candidate = candidate.split("/")[-1]
    candidate = candidate.strip()
    if not candidate or candidate in (".", ".."):
        return None
    if any(ch in candidate for ch in ("\r", "\n", "\t")):
        return None
    return os.path.basename(candidate)


def parse_multipart_form(
    body_bytes: bytes, content_type_header: str
) -> Optional[Dict[str, Union[bytes, str]]]:
    try:
        boundary_match = content_type_header.split("boundary=")
        if len(boundary_match) < 2:
            return None

        raw_boundary = boundary_match[1].split(";", 1)[0].strip().strip('"')
        if not raw_boundary or not _BOUNDARY_RE.match(raw_boundary):
            return None

        boundary = raw_boundary.encode("utf-8")
        form_data: Dict[str, Union[bytes, str]] = {}

        parts = body_bytes.split(b"--" + boundary)

        for part in parts[1:-1]:
            if not part.strip():
                continue

            header_end = part.find(b"\r\n\r\n")
            if header_end == -1:
                header_end = part.find(b"\n\n")
                if header_end == -1:
                    continue
                headers_section = part[:header_end]
                content = part[header_end + 2:]
            else:
                headers_section = part[:header_end]
                content = part[header_end + 4:]

            if content.endswith(b"\r\n"):
                content = content[:-2]
            elif content.endswith(b"\n"):
                content = content[:-1]

            headers_text = headers_section.decode("utf-8", errors="ignore")
            field_name: Optional[str] = None
            file_name: Optional[str] = None
            is_file = False

            for header_line in headers_text.split("\n"):
                if "content-disposition" not in header_line.lower():
                    continue
                name_match = _DISP_NAME_RE.search(header_line)
                if name_match:
                    field_name = _sanitize_field_name(name_match.group(1))
                filename_match = _DISP_FILENAME_RE.search(header_line)
                if filename_match:
                    is_file = True
                    file_name = _sanitize_filename(filename_match.group(1))

            if not field_name:
                continue
            if is_file:
                if filename_match and file_name is None:
                    continue
                form_data[field_name] = content
                if file_name is not None:
                    form_data[f"{field_name}__filename"] = file_name
            else:
                form_data[field_name] = content.decode("utf-8", errors="ignore")

        return form_data
    except Exception as e:
        safe_print(f"[HTTP] Error parsing multipart form: {e}")
        return None
