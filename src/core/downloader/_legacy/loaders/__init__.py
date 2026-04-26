from __future__ import annotations

import os
import shutil
import time
from typing import Any, Dict

from core.downloader._legacy._constants import BLOCKED_FORGE_VERSIONS
from core.downloader._legacy._state import STATE
from core.downloader._legacy.loaders.forge import _install_forge_loader
from core.downloader._legacy.progress import (
    _update_progress,
    delete_progress,
    write_progress,
)
from core.logger import colorize_log


def _resolve_loader_name() -> str:
    try:
        from core.modloaders import LOADER_DISPLAY_NAMES
    except Exception:
        LOADER_DISPLAY_NAMES = {}  # type: ignore[assignment]
    return LOADER_DISPLAY_NAMES.get("forge", "Forge")


def download_legacy_forge(
    mc_version: str,
    loader_version: str,
    category: str,
    folder: str,
) -> Dict[str, Any]:
    if mc_version in BLOCKED_FORGE_VERSIONS:
        return {
            "ok": False,
            "error": (
                f"Forge installation is disabled for Minecraft {mc_version}. "
                "These legacy Forge builds are ModLoader addons and are not "
                "supported by automatic Forge installation."
            ),
        }

    version_key = (
        f"{category.lower()}/{folder}/modloader-forge-{loader_version}"
    )
    STATE.cancel_flags.pop(version_key, None)
    loader_name = _resolve_loader_name()
    loaders_dir = ""

    try:
        from core.version_manager import ensure_loaders_dir

        _update_progress(
            version_key, "download", 0, f"Starting {loader_name} installation..."
        )
        loaders_dir = ensure_loaders_dir(category, folder)
        _update_progress(
            version_key, "download", 10, f"Preparing {loader_name} installer..."
        )

        result = _install_forge_loader(
            mc_version, loader_version, loaders_dir, version_key
        )

        if result.get("ok"):
            _update_progress(
                version_key, "finalize", 100,
                f"{loader_name} installation complete",
            )
            write_progress(
                version_key,
                {
                    "status": "installed",
                    "stage": "finalize",
                    "stage_percent": 100,
                    "overall_percent": 100,
                    "message": f"{loader_name} installation complete",
                    "bytes_done": 0,
                    "bytes_total": 0,
                },
            )
            time.sleep(0.5)
            delete_progress(version_key)
        else:
            error_msg = result.get("error", "Unknown error")
            _update_progress(
                version_key, "error", 0,
                f"{loader_name} installation failed: {error_msg}",
            )
            write_progress(
                version_key,
                {
                    "status": "failed", "stage": "error",
                    "stage_percent": 0, "overall_percent": 0,
                    "message": error_msg, "bytes_done": 0, "bytes_total": 0,
                },
            )
            time.sleep(2.0)
            delete_progress(version_key)

        return result

    except RuntimeError as e:
        if "cancel" in str(e).lower():
            error_msg = "Loader installation cancelled by user"
            print(colorize_log(
                f"[downloader] {loader_name} loader installation cancelled"
            ))
            try:
                if loaders_dir:
                    loader_dir = os.path.join(
                        os.path.dirname(loaders_dir), "forge"
                    )
                    if os.path.exists(loader_dir):
                        version_dir = os.path.join(loader_dir, loader_version)
                        if os.path.exists(version_dir):
                            shutil.rmtree(version_dir, ignore_errors=True)
            except Exception as cleanup_err:
                print(colorize_log(
                    f"[downloader] Warning: Could not clean up partial loader: {cleanup_err}"
                ))

            write_progress(
                version_key,
                {
                    "status": "cancelled", "stage": "error",
                    "stage_percent": 0, "overall_percent": 0,
                    "message": error_msg, "bytes_done": 0, "bytes_total": 0,
                },
            )
            time.sleep(0.5)
            delete_progress(version_key)
            return {"ok": False, "error": error_msg}

        error_msg = f"Failed to install loader: {e}"
        print(colorize_log(
            f"[downloader] Error installing {loader_name} loader: {e}"
        ))
        write_progress(
            version_key,
            {
                "status": "failed", "stage": "error",
                "stage_percent": 0, "overall_percent": 0,
                "message": error_msg, "bytes_done": 0, "bytes_total": 0,
            },
        )
        time.sleep(2.0)
        delete_progress(version_key)
        return {"ok": False, "error": error_msg}

    except Exception as e:
        error_msg = f"Failed to install loader: {e}"
        print(colorize_log(
            f"[downloader] Error installing {loader_name} loader: {e}"
        ))
        write_progress(
            version_key,
            {
                "status": "failed", "stage": "error",
                "stage_percent": 0, "overall_percent": 0,
                "message": error_msg, "bytes_done": 0, "bytes_total": 0,
            },
        )
        time.sleep(2.0)
        delete_progress(version_key)
        return {"ok": False, "error": error_msg}


__all__ = ["download_legacy_forge"]
