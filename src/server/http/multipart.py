from __future__ import annotations

from typing import Dict, Optional, Union


__all__ = ["parse_multipart_form"]


def parse_multipart_form(
    body_bytes: bytes, content_type_header: str
) -> Optional[Dict[str, Union[bytes, str]]]:
    try:
        boundary_match = content_type_header.split("boundary=")
        if len(boundary_match) < 2:
            return None

        boundary = boundary_match[1].strip('"').encode("utf-8")
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
            is_file = False

            for header_line in headers_text.split("\n"):
                if "Content-Disposition" in header_line:
                    if "name=" in header_line:
                        start = header_line.find('name="') + 6
                        end = header_line.find('"', start)
                        if start > 5 and end > start:
                            field_name = header_line[start:end]

                    if "filename=" in header_line:
                        is_file = True

            if field_name:
                if is_file:
                    form_data[field_name] = content
                else:
                    form_data[field_name] = content.decode("utf-8", errors="ignore")

        return form_data
    except Exception as e:
        print(f"[HTTP] Error parsing multipart form: {e}")
        return None
