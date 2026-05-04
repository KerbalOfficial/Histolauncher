from __future__ import annotations

import os
import shutil

from core.logger import colorize_log
from core.settings import get_base_dir
from core.version_manager import get_clients_dir, scan_categories
from core.zip_utils import ZipSecurityError, safe_extract_zip
from launcher.i18n import t

from server.api._constants import CURRENT_MD_VERSION, VALID_LOADER_TYPES
from server.api._helpers import (
    _begin_operation,
    _clear_operation,
    _is_path_within,
    _raise_if_operation_cancelled,
)
from server.api._state import CancelledOperationError, STATE
from server.api._validation import (
    _validate_category_string,
    _validate_version_string,
)


__all__ = ["api_export_versions", "api_import_versions"]


def api_export_versions(data):
    operation_id = ""
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid request"}

        category = (data.get("category") or "").strip()
        folder = (data.get("folder") or "").strip()
        operation_id = _begin_operation(data.get("operation_id"))

        if not category or not folder:
            return {"ok": False, "error": "missing category or folder"}

        if not _validate_category_string(category):
            return {"ok": False, "error": "invalid category format"}

        if not _validate_version_string(folder):
            return {"ok": False, "error": "invalid folder format"}

        import tempfile
        import zipfile

        export_options = data.get("export_options", {})
        include_loaders = export_options.get("include_loaders", True)
        include_assets = export_options.get("include_assets", True)
        include_config = export_options.get("include_config", False)
        compression = export_options.get("compression", "standard")

        if compression not in ["quick", "standard", "full"]:
            compression = "standard"

        if compression == "quick":
            compress_type = zipfile.ZIP_STORED
        elif compression == "full":
            compress_type = zipfile.ZIP_DEFLATED
        else:
            compress_type = zipfile.ZIP_DEFLATED

        print(colorize_log(f"[api] Starting export of {category}/{folder}..."))
        print(colorize_log(
            f"[api] Export options: loaders={include_loaders}, assets={include_assets}, "
            f"config={include_config}, compression={compression}"
        ))

        clients_dir = get_clients_dir()
        version_path = os.path.join(clients_dir, category, folder)

        if not _is_path_within(clients_dir, version_path):
            return {"ok": False, "error": "invalid version path"}

        if not os.path.isdir(version_path):
            return {"ok": False, "error": "version not found"}

        temp_dir = tempfile.gettempdir()
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".hlvdf", prefix=f"{folder}_", dir=temp_dir
        ) as tmp_file:
            temp_path = tmp_file.name

        try:
            print(colorize_log(f"[api] Scanning files in {version_path}..."))
            file_count = 0

            with zipfile.ZipFile(temp_path, "w", compress_type) as zipf:
                def should_skip_file(relative_path, base_root):
                    if not include_loaders:
                        rel_lower = str(relative_path or "").lower()
                        for loader_type in VALID_LOADER_TYPES:
                            if f"{loader_type}-" in rel_lower:
                                return True
                    if relative_path.startswith("logs") or relative_path.startswith("crash-reports"):
                        return True
                    if not include_config:
                        if relative_path.startswith("config") or relative_path.startswith("saves"):
                            return True
                    return False

                for root, dirs, files in os.walk(version_path):
                    for file in files:
                        _raise_if_operation_cancelled(operation_id)
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, version_path)

                        if should_skip_file(arcname, version_path):
                            continue

                        if arcname == "data.ini":
                            existing_data = {}
                            try:
                                with open(file_path, "r", encoding="utf-8") as f:
                                    for line in f:
                                        line = line.strip()
                                        if "=" in line and not line.startswith("#"):
                                            k, v = line.split("=", 1)
                                            existing_data[k.strip()] = v.strip()
                            except Exception:
                                pass

                            if "md_version" not in existing_data:
                                existing_data["md_version"] = CURRENT_MD_VERSION
                            if "category" not in existing_data:
                                existing_data["category"] = category

                            modified_data = (
                                "\n".join(f"{k}={v}" for k, v in existing_data.items()) + "\n"
                            )
                            zipf.writestr(arcname, modified_data)

                            file_size_kb = len(modified_data) / 1024
                            print(colorize_log(
                                f"[api]   Adding: {arcname} ({file_size_kb:.1f} KB)"
                            ))
                        else:
                            file_size_kb = os.path.getsize(file_path) / 1024
                            print(colorize_log(
                                f"[api]   Adding: {arcname} ({file_size_kb:.1f} KB)"
                            ))
                            zipf.write(file_path, arcname)

                        file_count += 1

                if include_assets:
                    base_dir = get_base_dir()
                    assets_path = os.path.join(base_dir, "assets")
                    if os.path.isdir(assets_path):
                        print(colorize_log("[api] Including assets directory..."))
                        for root, dirs, files in os.walk(assets_path):
                            for file in files:
                                _raise_if_operation_cancelled(operation_id)
                                file_path = os.path.join(root, file)
                                arcname = os.path.join(
                                    "assets", os.path.relpath(file_path, assets_path)
                                )
                                file_size_kb = os.path.getsize(file_path) / 1024
                                print(colorize_log(
                                    f"[api]   Adding: {arcname} ({file_size_kb:.1f} KB)"
                                ))
                                zipf.write(file_path, arcname)
                                file_count += 1

            zip_size_mb = os.path.getsize(temp_path) / 1024 / 1024
            print(colorize_log(
                f"[api] Successfully created ZIP: {file_count} files, {zip_size_mb:.2f} MB"
            ))

            filename = f"{folder}.hlvdf"
            print(colorize_log(f"[api] Temporary file saved to {temp_path}..."))

            try:
                from tkinter import Tk
                from tkinter.filedialog import asksaveasfilename

                print(colorize_log("[api] Opening file save dialog..."))
                _raise_if_operation_cancelled(operation_id)

                root = Tk()
                root.withdraw()
                root.attributes("-topmost", True)

                initial_name = filename
                default_dir = os.path.expanduser("~")

                save_path = asksaveasfilename(
                    initialfile=initial_name,
                    defaultextension=".hlvdf",
                    filetypes=[
                        (t("native.fileDialogs.histolauncherVersion"), "*.hlvdf"),
                        (t("native.fileDialogs.allFiles"), "*.*"),
                    ],
                    initialdir=default_dir,
                    title=t(
                        "native.fileDialogs.saveVersionExportTitle",
                        {"category": category, "folder": folder},
                    ),
                )

                root.destroy()

                if save_path:
                    _raise_if_operation_cancelled(operation_id)
                    print(colorize_log(f"[api] Copying file to {save_path}..."))
                    shutil.copy2(temp_path, save_path)

                    try:
                        os.remove(temp_path)
                        print(colorize_log("[api] Cleaned up temporary file"))
                    except Exception:
                        pass

                    print(colorize_log("[api] [OK] Export completed successfully!"))
                    print(colorize_log(f"[api] File saved to: {save_path}"))

                    return {
                        "ok": True,
                        "filename": os.path.basename(save_path),
                        "filepath": save_path,
                        "size_bytes": os.path.getsize(save_path),
                        "message": f"Successfully exported {category}/{folder}",
                    }
                else:
                    print(colorize_log("[api] Export cancelled by user"))
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                    return {
                        "ok": False,
                        "cancelled": True,
                        "error": "Export cancelled by user",
                    }

            except ImportError:
                print(colorize_log(
                    "[api] tkinter not available, using Downloads folder fallback"
                ))
                _raise_if_operation_cancelled(operation_id)

                downloads_dir = os.path.expanduser("~/Downloads")
                if not os.path.isdir(downloads_dir):
                    downloads_dir = os.path.expanduser("~")

                save_path = os.path.join(downloads_dir, filename)

                base_name, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(save_path):
                    save_path = os.path.join(downloads_dir, f"{base_name}_{counter}{ext}")
                    counter += 1

                _raise_if_operation_cancelled(operation_id)
                print(colorize_log(f"[api] Copying file to {save_path}..."))
                shutil.copy2(temp_path, save_path)

                try:
                    os.remove(temp_path)
                    print(colorize_log("[api] Cleaned up temporary file"))
                except Exception:
                    pass

                print(colorize_log("[api] [OK] Export completed successfully!"))
                print(colorize_log(f"[api] File saved to: {save_path}"))

                try:
                    import platform
                    import subprocess

                    if platform.system() == "Windows":
                        os.startfile(os.path.dirname(save_path))
                    elif platform.system() == "Darwin":
                        subprocess.run(["open", os.path.dirname(save_path)])
                    else:
                        subprocess.run(["xdg-open", os.path.dirname(save_path)])
                except Exception:
                    pass

                return {
                    "ok": True,
                    "filename": os.path.basename(save_path),
                    "filepath": save_path,
                    "size_bytes": os.path.getsize(save_path),
                    "message": f"Exported to {os.path.dirname(save_path)}",
                }

        except CancelledOperationError:
            try:
                if "temp_path" in locals():
                    os.remove(temp_path)
            except Exception:
                pass
            raise
        except Exception as zip_err:
            print(colorize_log(f"[api] [FAILED] Export failed: {str(zip_err)}"))
            try:
                if "temp_path" in locals():
                    os.remove(temp_path)
            except Exception:
                pass
            return {"ok": False, "error": f"Failed to create ZIP: {str(zip_err)}"}

    except CancelledOperationError:
        return {
            "ok": False,
            "cancelled": True,
            "error": "Export cancelled by user",
        }
    except Exception as e:
        import traceback

        print(colorize_log(f"[api] [FAILED] Export error: {str(e)}"))
        traceback.print_exc()
        return {"ok": False, "error": f"Failed to export version: {str(e)}"}
    finally:
        _clear_operation(operation_id)


def api_import_versions(data):
    operation_id = ""
    try:
        print(colorize_log(
            f"[api] api_import_versions called with data type: {type(data)}, "
            f"data: {str(data)[:200] if data else 'None'}"
        ))

        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid request"}

        version_name = (data.get("version_name") or "").strip()
        operation_id = _begin_operation(data.get("operation_id"))
        zip_bytes_raw = data.get("zip_bytes")
        zip_data_base64 = (data.get("zip_data") or "").strip()

        zip_bytes = None
        if isinstance(zip_bytes_raw, (bytes, bytearray)):
            zip_bytes = bytes(zip_bytes_raw)
        elif zip_data_base64:
            import base64

            zip_bytes = base64.b64decode(zip_data_base64)

        zip_len = len(zip_bytes) if isinstance(zip_bytes, (bytes, bytearray)) else 0
        print(colorize_log(f"[api] version_name: '{version_name}', zip bytes length: {zip_len}"))

        if not version_name or not zip_bytes:
            return {"ok": False, "error": "missing version_name or zip data"}

        if not _validate_version_string(version_name):
            return {"ok": False, "error": "invalid version_name format"}
        _raise_if_operation_cancelled(operation_id)

        import io
        import zipfile

        try:
            zip_buffer = io.BytesIO(zip_bytes)

            category = None
            existing_data = {}

            with zipfile.ZipFile(zip_buffer, "r") as zipf:
                data_ini_entry = None
                for info in zipf.infolist():
                    normalized = str(info.filename or "").replace("\\", "/").lstrip("/")
                    if normalized == "data.ini":
                        data_ini_entry = info
                        break

                if data_ini_entry and int(data_ini_entry.file_size or 0) <= 1024 * 1024:
                    try:
                        with zipf.open(data_ini_entry, "r") as f:
                            content = f.read().decode("utf-8")
                            for line in content.split("\n"):
                                line = line.strip()
                                if "=" in line and not line.startswith("#"):
                                    k, v = line.split("=", 1)
                                    existing_data[k.strip()] = v.strip()
                    except Exception as read_err:
                        print(colorize_log(
                            f"[api] Warning: Could not read data.ini from ZIP: {str(read_err)}"
                        ))

            category = existing_data.get("category", "").strip()

            if not category:
                print(colorize_log(
                    "[api] Warning: No category found in data.ini, defaulting to Release"
                ))
                category = "Release"

            if not _validate_category_string(category):
                return {"ok": False, "error": f"invalid category in data.ini: {category}"}

            clients_dir = get_clients_dir()
            version_path = os.path.join(clients_dir, category, version_name)

            if not _is_path_within(clients_dir, version_path):
                return {"ok": False, "error": "invalid version path"}

            if os.path.isdir(version_path):
                return {
                    "ok": False,
                    "error": (
                        f"Version already exists at {category}/{version_name}."
                        "<br><i>Delete it and try again.</i>"
                    ),
                }

            category_path = os.path.join(clients_dir, category)
            os.makedirs(category_path, exist_ok=True)

            try:
                zip_buffer.seek(0)
                with zipfile.ZipFile(zip_buffer, "r") as zipf:
                    os.makedirs(version_path, exist_ok=True)

                    def extraction_progress(_done, _total, _name, _info):
                        _raise_if_operation_cancelled(operation_id)

                    safe_extract_zip(
                        zipf,
                        version_path,
                        member_filter=lambda n, info: not n.startswith("assets/"),
                        progress_cb=extraction_progress,
                    )

                    base_dir = get_base_dir()
                    assets_path = os.path.join(base_dir, "assets")
                    os.makedirs(assets_path, exist_ok=True)

                    safe_extract_zip(
                        zipf,
                        assets_path,
                        member_filter=lambda n, info: n.startswith("assets/"),
                        name_transform=lambda n, info: n[len("assets/"):],
                        progress_cb=extraction_progress,
                    )
            except (zipfile.BadZipFile, ZipSecurityError):
                if version_path and os.path.isdir(version_path):
                    shutil.rmtree(version_path, ignore_errors=True)
                return {"ok": False, "error": "Invalid ZIP file"}

            old_md_version = existing_data.get("md_version", "missing").strip()
            if not old_md_version or old_md_version == "missing":
                print(colorize_log(
                    f"[api] Auto-upgrading old version from no metadata version to "
                    f"{CURRENT_MD_VERSION}"
                ))

            data_ini_path = os.path.join(version_path, "data.ini")
            if os.path.exists(data_ini_path):
                with open(data_ini_path, "r", encoding="utf-8") as f:
                    existing_data = {}
                    for line in f:
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            k, v = line.split("=", 1)
                            existing_data[k.strip()] = v.strip()

                existing_data["imported"] = "true"
                existing_data["md_version"] = CURRENT_MD_VERSION
                existing_data["category"] = category

                with open(data_ini_path, "w", encoding="utf-8") as f:
                    for k, v in existing_data.items():
                        f.write(f"{k}={v}\n")
            else:
                with open(data_ini_path, "w", encoding="utf-8") as f:
                    f.write("imported=true\n")
                    f.write(f"md_version={CURRENT_MD_VERSION}\n")
                    f.write(f"category={category}\n")

            scan_categories(force_refresh=True)

            print(colorize_log(f"[api] [OK] Imported version: {category}/{version_name}"))

            return {
                "ok": True,
                "message": f"Successfully imported {category}/{version_name}",
                "category": category,
                "folder": version_name,
                "is_imported": True,
            }

        except CancelledOperationError:
            try:
                if (
                    "version_path" in locals()
                    and version_path
                    and os.path.isdir(version_path)
                ):
                    shutil.rmtree(version_path, ignore_errors=True)
            except Exception:
                pass
            return {
                "ok": False,
                "cancelled": True,
                "error": "Import cancelled by user",
            }
        except Exception as zip_err:
            try:
                if (
                    "version_path" in locals()
                    and version_path
                    and os.path.isdir(version_path)
                ):
                    shutil.rmtree(version_path, ignore_errors=True)
            except Exception:
                pass
            print(colorize_log(f"[api] [FAILED] Import failed: {str(zip_err)}"))
            return {"ok": False, "error": f"Failed to extract ZIP: {str(zip_err)}"}

    except CancelledOperationError:
        return {
            "ok": False,
            "cancelled": True,
            "error": "Import cancelled by user",
        }
    except Exception as e:
        import traceback

        print(colorize_log(f"[api] [FAILED] Import error: {str(e)}"))
        traceback.print_exc()
        return {"ok": False, "error": f"Failed to import version: {str(e)}"}
    finally:
        _clear_operation(operation_id)
