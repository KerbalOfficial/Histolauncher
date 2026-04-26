from __future__ import annotations

import logging
import os
import shutil
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from typing import Any, Dict

from core import mod_manager
from core.zip_utils import ZipSecurityError, safe_extract_zip

from core.world_manager.metadata import get_world_detail
from core.world_manager.storage import _pick_unique_world_id, resolve_storage_target


logger = logging.getLogger(__name__)


def _normalize_zip_member_name(name: str) -> str:
    raw = str(name or "").replace("\\", "/").strip("/")
    if not raw or raw.startswith("__MACOSX/"):
        return ""
    parts = [part for part in raw.split("/") if part and part not in (".", "..")]
    return "/".join(parts)


def _detect_world_archive_root(zf: zipfile.ZipFile) -> str:
    level_roots = []
    top_levels = set()
    for info in zf.infolist():
        normalized = _normalize_zip_member_name(info.filename)
        if not normalized:
            continue
        parts = normalized.split("/")
        top_levels.add(parts[0])
        if parts[-1].lower() == "level.dat":
            level_roots.append("/".join(parts[:-1]))

    unique_roots = sorted(set(level_roots), key=lambda value: (value.count("/"), len(value), value.lower()))
    if unique_roots:
        return unique_roots[0]
    if len(top_levels) == 1:
        return sorted(top_levels)[0]
    return ""


def install_world_archive(
    download_url: str,
    file_name: str,
    *,
    world_name: str = "",
    world_slug: str = "",
    storage_target: str = "default",
    custom_path: str = "",
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> Dict[str, Any]:
    if not download_url:
        return {"ok": False, "error": "Missing download URL."}
    if not file_name:
        return {"ok": False, "error": "Missing archive filename."}

    resolved = resolve_storage_target(storage_target, custom_path=custom_path, create_saves_dir=True)
    if not resolved.get("ok"):
        return {"ok": False, "error": resolved.get("error") or "Failed to resolve worlds storage directory."}

    safe_name = os.path.basename(str(file_name or "").strip())
    extension = os.path.splitext(safe_name)[1].lower()
    if extension != ".zip":
        return {"ok": False, "error": "World downloads must be ZIP archives."}

    normalized_url = mod_manager._normalize_download_url(download_url)
    request_url = mod_manager._apply_url_proxy(normalized_url)
    temp_path = ""

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension or ".zip") as tmp:
            temp_path = tmp.name

        req = urllib.request.Request(
            request_url,
            headers={"User-Agent": "Histolauncher/1.0", "Accept": "application/octet-stream"},
        )
        with urllib.request.urlopen(req, timeout=30.0) as response, open(temp_path, "wb") as f:
            total = 0
            length_header = response.headers.get("Content-Length")
            if length_header:
                try:
                    total = max(0, int(length_header))
                except (TypeError, ValueError):
                    total = 0
            downloaded = 0
            if progress_callback:
                progress_callback("download", downloaded, total)
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback("download", downloaded, total)
            if progress_callback:
                progress_callback("download", total or downloaded or 1, total or downloaded or 1)

        with zipfile.ZipFile(temp_path, "r") as zf:
            root_prefix = _detect_world_archive_root(zf)
            desired_name = os.path.basename(root_prefix) if root_prefix else (world_name or world_slug or os.path.splitext(safe_name)[0] or "world")
            saves_dir = str(resolved.get("saves_dir") or "")
            world_id = _pick_unique_world_id(saves_dir, desired_name)
            destination = os.path.join(saves_dir, world_id)
            os.makedirs(destination, exist_ok=False)

            try:
                if root_prefix:
                    prefix = f"{root_prefix}/"
                    if progress_callback:
                        progress_callback("extract", 0, 1)
                    safe_extract_zip(
                        zf,
                        destination,
                        member_filter=lambda normalized, _info: normalized == root_prefix or normalized.startswith(prefix),
                        name_transform=lambda normalized, _info: (
                            "" if normalized == root_prefix else normalized[len(prefix):]
                        ),
                        progress_cb=lambda done, total, _name, _info: progress_callback("extract", done, total) if progress_callback else None,
                    )
                else:
                    if progress_callback:
                        progress_callback("extract", 0, 1)
                    safe_extract_zip(
                        zf,
                        destination,
                        progress_cb=lambda done, total, _name, _info: progress_callback("extract", done, total) if progress_callback else None,
                    )

                if progress_callback:
                    progress_callback("extract", 1, 1)

                if not os.path.isfile(os.path.join(destination, "level.dat")):
                    shutil.rmtree(destination, ignore_errors=True)
                    return {"ok": False, "error": "Downloaded archive did not contain a valid Minecraft world (missing level.dat)."}
            except ZipSecurityError as e:
                shutil.rmtree(destination, ignore_errors=True)
                return {"ok": False, "error": str(e)}
            except Exception:
                shutil.rmtree(destination, ignore_errors=True)
                raise

        if progress_callback:
            progress_callback("finalize", 0, 1)

        detail = get_world_detail(storage_target, world_id, custom_path=custom_path)
        if not detail.get("ok"):
            return {"ok": False, "error": detail.get("error") or "World installed, but details could not be loaded."}

        detail.update({
            "ok": True,
            "message": f'Successfully installed world "{detail.get("title") or world_id}"',
        })
        return detail
    except Exception as e:
        logger.error(f"Failed to install world archive {safe_name}: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except Exception:
                pass


__all__ = [
    "install_world_archive",
    "export_world_zip",
    "scan_world_zip_bytes",
    "import_world_zip_bytes",
]


# --------------------------------------------------------------------------- #
# Export                                                                      #
# --------------------------------------------------------------------------- #


def export_world_zip(
    storage_target: str,
    world_id: str,
    *,
    custom_path: str = "",
) -> Dict[str, Any]:
    raw_world_id = str(world_id or "").strip()
    if not raw_world_id:
        return {"ok": False, "error": "Missing world id."}
    safe_world_id = os.path.basename(raw_world_id)
    if safe_world_id != raw_world_id or safe_world_id in (".", ".."):
        return {"ok": False, "error": "Invalid world id."}

    resolved = resolve_storage_target(storage_target, custom_path=custom_path, create_saves_dir=False)
    if not resolved.get("ok"):
        return {"ok": False, "error": resolved.get("error") or "Failed to resolve worlds storage directory."}

    saves_dir = str(resolved.get("saves_dir") or "")
    if not saves_dir or not os.path.isdir(saves_dir):
        return {"ok": False, "error": "Worlds storage directory is not available."}

    world_dir = os.path.join(saves_dir, safe_world_id)
    if not os.path.isdir(world_dir):
        return {"ok": False, "error": "World folder does not exist."}
    if not os.path.isfile(os.path.join(world_dir, "level.dat")):
        return {"ok": False, "error": "World folder is missing level.dat."}

    import io
    buffer = io.BytesIO()
    file_count = 0
    try:
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for current_dir, _dirs, files in os.walk(world_dir):
                for file_name in files:
                    abs_path = os.path.join(current_dir, file_name)
                    rel_path = os.path.relpath(abs_path, world_dir).replace(os.sep, "/")
                    arc_name = f"{safe_world_id}/{rel_path}"
                    try:
                        zf.write(abs_path, arc_name)
                        file_count += 1
                    except Exception as ex:  # pragma: no cover - defensive
                        logger.warning(f"Failed to add {abs_path} to world export: {ex}")
    except Exception as e:
        return {"ok": False, "error": f"Failed to build world zip: {e}"}

    if file_count <= 0:
        return {"ok": False, "error": "World folder did not contain any files."}

    return {
        "ok": True,
        "world_id": safe_world_id,
        "file_count": file_count,
        "zip_bytes": buffer.getvalue(),
        "suggested_filename": f"{safe_world_id}.zip",
    }


# --------------------------------------------------------------------------- #
# Import                                                                      #
# --------------------------------------------------------------------------- #


def _list_world_roots_in_zip(zf: zipfile.ZipFile) -> list:
    roots = []
    seen = set()
    for info in zf.infolist():
        normalized = _normalize_zip_member_name(info.filename)
        if not normalized:
            continue
        if info.is_dir():
            continue
        parts = normalized.split("/")
        if parts[-1].lower() != "level.dat":
            continue
        root_path = "/".join(parts[:-1])
        if root_path in seen:
            continue
        seen.add(root_path)
        label = os.path.basename(root_path) or root_path or "world"
        roots.append({
            "path": root_path,
            "label": label,
            "level_dat_size": int(info.file_size or 0),
        })

    roots.sort(key=lambda entry: (entry["path"].count("/"), entry["path"].lower()))
    return roots


def scan_world_zip_bytes(zip_bytes: bytes) -> Dict[str, Any]:
    if not zip_bytes:
        return {"ok": False, "error": "Empty zip payload."}

    try:
        import io
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            roots = _list_world_roots_in_zip(zf)
    except zipfile.BadZipFile:
        return {"ok": False, "error": "The uploaded file is not a valid zip archive."}
    except Exception as e:
        return {"ok": False, "error": f"Failed to read zip: {e}"}

    if not roots:
        return {"ok": False, "error": "No level.dat files were found inside the zip."}

    return {"ok": True, "roots": roots}


def import_world_zip_bytes(
    zip_bytes: bytes,
    storage_target: str,
    *,
    custom_path: str = "",
    selected_roots: list = None,
) -> Dict[str, Any]:
    if not zip_bytes:
        return {"ok": False, "error": "Empty zip payload."}

    resolved = resolve_storage_target(storage_target, custom_path=custom_path, create_saves_dir=True)
    if not resolved.get("ok"):
        return {"ok": False, "error": resolved.get("error") or "Failed to resolve worlds storage directory."}
    saves_dir = str(resolved.get("saves_dir") or "")
    if not saves_dir:
        return {"ok": False, "error": "Worlds storage directory is not available."}

    try:
        import io
        zf_outer = zipfile.ZipFile(io.BytesIO(zip_bytes), "r")
    except zipfile.BadZipFile:
        return {"ok": False, "error": "The uploaded file is not a valid zip archive."}
    except Exception as e:
        return {"ok": False, "error": f"Failed to read zip: {e}"}

    imported = []
    skipped = []
    errors = []

    try:
        with zf_outer as zf:
            available = _list_world_roots_in_zip(zf)
            if not available:
                return {"ok": False, "error": "No level.dat files were found inside the zip."}

            if selected_roots is None:
                chosen = list(available)
            else:
                requested = set(str(p or "").strip().strip("/") for p in selected_roots if p is not None)
                chosen = [entry for entry in available if entry["path"] in requested]
                if not chosen:
                    return {"ok": False, "error": "None of the selected world roots were found in the zip."}

            for entry in chosen:
                root_prefix = entry["path"]
                desired_name = os.path.basename(root_prefix) or root_prefix or "world"
                world_id = _pick_unique_world_id(saves_dir, desired_name)
                destination = os.path.join(saves_dir, world_id)
                try:
                    os.makedirs(destination, exist_ok=False)
                except FileExistsError:
                    skipped.append({"path": root_prefix, "reason": "destination already exists"})
                    continue

                try:
                    if root_prefix:
                        prefix = f"{root_prefix}/"
                        safe_extract_zip(
                            zf,
                            destination,
                            member_filter=lambda normalized, _info, prefix=prefix, root=root_prefix: (
                                normalized == root or normalized.startswith(prefix)
                            ),
                            name_transform=lambda normalized, _info, prefix=prefix, root=root_prefix: (
                                "" if normalized == root else normalized[len(prefix):]
                            ),
                        )
                    else:
                        safe_extract_zip(zf, destination)

                    if not os.path.isfile(os.path.join(destination, "level.dat")):
                        shutil.rmtree(destination, ignore_errors=True)
                        errors.append({"path": root_prefix, "error": "missing level.dat after extraction"})
                        continue

                    imported.append({
                        "path": root_prefix,
                        "world_id": world_id,
                    })
                except ZipSecurityError as e:
                    shutil.rmtree(destination, ignore_errors=True)
                    errors.append({"path": root_prefix, "error": str(e)})
                except Exception as e:
                    shutil.rmtree(destination, ignore_errors=True)
                    errors.append({"path": root_prefix, "error": str(e)})
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if not imported and errors:
        return {
            "ok": False,
            "error": "; ".join(f"{err['path']}: {err['error']}" for err in errors),
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
        }

    return {
        "ok": True,
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "message": f"Imported {len(imported)} world(s).",
    }
