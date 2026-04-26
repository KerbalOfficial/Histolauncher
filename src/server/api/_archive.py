from __future__ import annotations

import io
import json
import os
import re
import zipfile
from typing import Any, Dict

from server.api._validation import _slugify_import_name, _validate_mod_slug


__all__ = [
    "_extract_import_archive_metadata",
    "_strip_minecraft_formatting",
    "_stringify_mc_text_component",
    "_extract_pack_mcmeta_description",
]


def _extract_import_archive_metadata(file_name: str, file_data: bytes) -> Dict[str, Any]:
    base_name = os.path.splitext(str(file_name or ""))[0].strip() or "Imported Mod"
    fallback_slug = _slugify_import_name(file_name)

    metadata = {
        "mod_slug": fallback_slug,
        "mod_name": base_name,
        "version_label": "imported",
        "detected_loader": "",
    }

    if not isinstance(file_data, (bytes, bytearray)) or not file_data:
        return metadata

    try:
        with zipfile.ZipFile(io.BytesIO(file_data), "r") as zf:
            names = {n.lower(): n for n in zf.namelist()}

            fab_name = names.get("fabric.mod.json")
            if fab_name:
                try:
                    fab = json.loads(zf.read(fab_name).decode("utf-8", errors="ignore"))
                    mod_id = str(fab.get("id") or "").strip().lower()
                    mod_name = str(fab.get("name") or "").strip()
                    mod_ver = str(fab.get("version") or "").strip()
                    if _validate_mod_slug(mod_id):
                        metadata["mod_slug"] = mod_id
                    if mod_name:
                        metadata["mod_name"] = mod_name
                    if mod_ver:
                        metadata["version_label"] = mod_ver
                    metadata["detected_loader"] = "fabric"
                    return metadata
                except Exception:
                    pass

            quilt_name = names.get("quilt.mod.json")
            if quilt_name:
                try:
                    quilt = json.loads(zf.read(quilt_name).decode("utf-8", errors="ignore"))
                    ql = quilt.get("quilt_loader") if isinstance(quilt, dict) else {}
                    if isinstance(ql, dict):
                        mod_id = str(ql.get("id") or "").strip().lower()
                        mod_ver = str(ql.get("version") or "").strip()
                        q_meta = ql.get("metadata") if isinstance(ql.get("metadata"), dict) else {}
                        mod_name = str(q_meta.get("name") or ql.get("id") or "").strip()
                        if _validate_mod_slug(mod_id):
                            metadata["mod_slug"] = mod_id
                        if mod_name:
                            metadata["mod_name"] = mod_name
                        if mod_ver:
                            metadata["version_label"] = mod_ver
                        metadata["detected_loader"] = "quilt"
                        return metadata
                except Exception:
                    pass

            toml_name = names.get("meta-inf/mods.toml")
            if toml_name:
                try:
                    text = zf.read(toml_name).decode("utf-8", errors="ignore")
                    mod_id_match = re.search(
                        r'(?mi)^\s*modId\s*=\s*"([a-z0-9._-]+)"\s*$', text
                    )
                    mod_name_match = re.search(
                        r'(?mi)^\s*displayName\s*=\s*"([^"]+)"\s*$', text
                    )
                    mod_ver_match = re.search(
                        r'(?mi)^\s*version\s*=\s*"([^"]+)"\s*$', text
                    )

                    mod_id = mod_id_match.group(1).strip().lower() if mod_id_match else ""
                    mod_name = mod_name_match.group(1).strip() if mod_name_match else ""
                    mod_ver = mod_ver_match.group(1).strip() if mod_ver_match else ""

                    if _validate_mod_slug(mod_id):
                        metadata["mod_slug"] = mod_id
                    if mod_name:
                        metadata["mod_name"] = mod_name
                    if mod_ver:
                        metadata["version_label"] = mod_ver

                    metadata["detected_loader"] = (
                        "neoforge" if "neoforge" in text.lower() else "forge"
                    )
                    return metadata
                except Exception:
                    pass

            mcmod_name = names.get("mcmod.info")
            if mcmod_name:
                try:
                    parsed = json.loads(zf.read(mcmod_name).decode("utf-8", errors="ignore"))
                    entry = None
                    if isinstance(parsed, list) and parsed:
                        entry = parsed[0]
                    elif isinstance(parsed, dict):
                        entry = parsed
                    if isinstance(entry, dict):
                        mod_id = str(entry.get("modid") or "").strip().lower()
                        mod_name = str(entry.get("name") or "").strip()
                        mod_ver = str(entry.get("version") or "").strip()
                        if _validate_mod_slug(mod_id):
                            metadata["mod_slug"] = mod_id
                        if mod_name:
                            metadata["mod_name"] = mod_name
                        if mod_ver:
                            metadata["version_label"] = mod_ver
                        metadata["detected_loader"] = "forge"
                        return metadata
                except Exception:
                    pass

            manifest_name = names.get("meta-inf/manifest.mf")
            if manifest_name:
                try:
                    text = zf.read(manifest_name).decode("utf-8", errors="ignore")
                    title_match = re.search(
                        r"(?mi)^\s*Implementation-Title\s*:\s*(.+)$", text
                    )
                    ver_match = re.search(
                        r"(?mi)^\s*Implementation-Version\s*:\s*(.+)$", text
                    )
                    if title_match:
                        metadata["mod_name"] = title_match.group(1).strip()
                        metadata["mod_slug"] = _slugify_import_name(metadata["mod_name"])
                    if ver_match:
                        metadata["version_label"] = ver_match.group(1).strip()
                except Exception:
                    pass
    except Exception:
        return metadata

    return metadata


def _strip_minecraft_formatting(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""

    out = []
    i = 0
    while i < len(value):
        if value[i] == "§":
            i += 2
            continue
        out.append(value[i])
        i += 1
    return "".join(out)


def _stringify_mc_text_component(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_stringify_mc_text_component(v) for v in value)
    if isinstance(value, dict):
        text = ""

        raw_text = value.get("text")
        if isinstance(raw_text, str):
            text += raw_text
        elif raw_text is not None:
            text += str(raw_text)

        extra = value.get("extra")
        if isinstance(extra, list):
            text += "".join(_stringify_mc_text_component(v) for v in extra)

        if not text:
            translate = value.get("translate")
            if isinstance(translate, str):
                text = translate

        return text

    return str(value)


def _extract_pack_mcmeta_description(file_data: bytes) -> str:
    if not isinstance(file_data, (bytes, bytearray)) or not file_data:
        return ""

    max_mcmeta_bytes = 256 * 1024
    raw = b""

    try:
        with zipfile.ZipFile(io.BytesIO(file_data), "r") as zf:
            candidates = []
            for info in zf.infolist():
                if info.is_dir():
                    continue

                entry_name = str(info.filename or "")
                normalized = entry_name.replace("\\", "/").strip("/")
                if not normalized or normalized.endswith("/"):
                    continue

                if os.path.basename(normalized).lower() != "pack.mcmeta":
                    continue

                if "\x00" in normalized:
                    continue

                parts = [p for p in normalized.split("/") if p]
                if any(p in (".", "..") for p in parts):
                    continue

                candidates.append((len(parts), normalized, info))

            if not candidates:
                return ""

            candidates.sort(key=lambda t: (t[0], t[1].lower()))
            _, _, selected_info = candidates[0]

            try:
                if int(getattr(selected_info, "file_size", 0) or 0) > max_mcmeta_bytes:
                    return ""
            except Exception:
                return ""

            with zf.open(selected_info, "r") as f:
                raw = f.read(max_mcmeta_bytes + 1)

        if len(raw) > max_mcmeta_bytes:
            return ""

        parsed = json.loads(raw.decode("utf-8-sig", errors="replace"))
        if not isinstance(parsed, dict):
            return ""

        pack = parsed.get("pack")
        if not isinstance(pack, dict):
            return ""

        desc = _stringify_mc_text_component(pack.get("description")).strip()
        if not desc:
            return ""

        cleaned = _strip_minecraft_formatting(desc).strip()
        return cleaned
    except Exception:
        return ""
