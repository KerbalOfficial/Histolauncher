from __future__ import annotations

import json
import os
import shutil
import urllib.parse
from typing import Optional

from core.downloader._legacy._state import STATE
from core.downloader._legacy.progress import _update_progress
from core.downloader._legacy.transport import _safe_remove_file, download_file
from core.logger import colorize_log
from core.zip_utils import safe_extract_zip

from core.downloader._legacy.loaders.forge._context import ForgeContext


def download_forge_artifact(ctx: ForgeContext) -> Optional[str]:
    from core.modloaders import get_forge_artifact_urls

    artifact_urls = get_forge_artifact_urls(ctx.mc_version, ctx.loader_version)
    if not artifact_urls:
        return "Could not resolve Forge artifact URLs"

    _update_progress(ctx.version_key, "download", 0, "Downloading Forge package...")

    def progress_hook(downloaded: int, total: int) -> None:
        if STATE.cancel_flags.get(ctx.version_key):
            raise RuntimeError("Download cancelled by user")
        percent = int(100 * downloaded / total) if total > 0 else 0
        _update_progress(
            ctx.version_key, "download", percent,
            f"Downloading installer {percent}%...", downloaded, 0,
        )

    last_download_error: Optional[str] = None
    for artifact_url in artifact_urls:
        artifact_name = (
            os.path.basename(urllib.parse.urlparse(artifact_url).path)
            or "forge-artifact.jar"
        )
        artifact_path = os.path.join(ctx.temp_dir, artifact_name)
        print(f"[forge] Downloading Forge artifact from {artifact_url}")
        try:
            download_file(
                artifact_url, artifact_path,
                version_key=ctx.version_key, progress_cb=progress_hook,
            )
            if os.path.exists(artifact_path) and os.path.getsize(artifact_path) > 0:
                ctx.downloaded_artifact_path = artifact_path
                ctx.downloaded_artifact_name = artifact_name
                ctx.is_installer_archive = artifact_name.lower().endswith(
                    "-installer.jar"
                )
                print(colorize_log(f"[forge] Using Forge artifact: {artifact_name}"))
                return None
        except RuntimeError as e:
            if "cancel" in str(e).lower():
                print(colorize_log("[forge] Download cancelled"))
                _safe_remove_file(artifact_path)
                raise
            last_download_error = str(e)
            _safe_remove_file(artifact_path)
            print(colorize_log(f"[forge] Download failed for {artifact_name}: {e}"))
        except Exception as e:
            last_download_error = str(e)
            _safe_remove_file(artifact_path)
            print(colorize_log(f"[forge] Download failed for {artifact_name}: {e}"))

    return f"Failed to download Forge artifact: {last_download_error or 'all URLs failed'}"


def extract_forge_artifact(ctx: ForgeContext) -> Optional[str]:
    _update_progress(
        ctx.version_key, "extracting_loader", 25, "Preparing Forge package..."
    )
    ctx.extraction_dir = os.path.join(ctx.temp_dir, "forge_extracted")
    os.makedirs(ctx.extraction_dir, exist_ok=True)

    lower_name = ctx.downloaded_artifact_name.lower()
    ctx.is_legacy_universal_archive = (
        lower_name.endswith(".zip")
        and (not ctx.is_installer_archive)
        and (not ctx.modlauncher_era)
    )

    if lower_name.endswith(".zip"):
        try:
            safe_extract_zip(ctx.downloaded_artifact_path, ctx.extraction_dir)
        except Exception as e:
            print(f"[forge] ZIP extraction error: {e}")
            return f"Failed to extract Forge archive: {e}"
    elif ctx.is_installer_archive:
        try:
            safe_extract_zip(ctx.downloaded_artifact_path, ctx.extraction_dir)
        except Exception as e:
            print(f"[forge] Installer extraction error: {e}")
            return f"Failed to extract Forge installer: {e}"
    else:
        try:
            shutil.copy2(
                ctx.downloaded_artifact_path,
                os.path.join(ctx.extraction_dir, ctx.downloaded_artifact_name),
            )
        except Exception as e:
            return f"Failed to stage Forge artifact: {e}"

    return None


def parse_install_profile_and_save_metadata(ctx: ForgeContext) -> None:
    os.makedirs(ctx.loader_dest_dir, exist_ok=True)
    os.makedirs(ctx.metadata_dir, exist_ok=True)

    profile_path = os.path.join(ctx.extraction_dir, "install_profile.json")
    if os.path.exists(profile_path):
        try:
            with open(profile_path, "r") as f:
                ctx.profile_data = json.load(f)
            print("[forge] Parsed install_profile.json")
            shutil.copy2(
                profile_path,
                os.path.join(ctx.metadata_dir, "install_profile.json"),
            )
            print("[forge] Saved install_profile.json to metadata")
        except Exception as e:
            print(f"[forge] WARNING: Could not parse install_profile.json: {e}")

    version_json_src = os.path.join(ctx.extraction_dir, "version.json")
    if os.path.exists(version_json_src):
        try:
            shutil.copy2(
                version_json_src,
                os.path.join(ctx.metadata_dir, "version.json"),
            )
            print("[forge] Saved version.json to metadata")
        except Exception as e:
            print(f"[forge] WARNING: Could not save version.json: {e}")


def copy_extracted_configs(ctx: ForgeContext) -> None:
    print("[forge] Extracting configuration files...")
    for root, _, files in os.walk(ctx.extraction_dir):
        for filename in files:
            if filename in ("log4j2.xml", "log4j.properties", "log4j.xml") \
                    or filename.endswith(".properties"):
                src_file = os.path.join(root, filename)
                dst_file = os.path.join(ctx.loader_dest_dir, filename)
                try:
                    shutil.copy2(src_file, dst_file)
                    ctx.files_copied += 1
                    print(f"[forge] Extracted config: {filename}")
                except Exception as e:
                    print(f"[forge] Warning: Could not copy {filename}: {e}")


def extract_pre_staged_libraries(ctx: ForgeContext) -> int:
    libraries_extracted = 0

    maven_dir = os.path.join(ctx.extraction_dir, "maven")
    if os.path.isdir(maven_dir):
        print("[forge] Extracting from maven directory (Forge 1.13+)...")
        for root, _, files in os.walk(maven_dir):
            for filename in files:
                if not filename.endswith(".jar"):
                    continue
                src_jar = os.path.join(root, filename)
                rel_path = os.path.relpath(src_jar, maven_dir)
                dst_jar_structured = os.path.join(
                    ctx.loader_dest_dir, "libraries", rel_path
                )
                os.makedirs(os.path.dirname(dst_jar_structured), exist_ok=True)
                if not os.path.exists(dst_jar_structured):
                    try:
                        shutil.copy2(src_jar, dst_jar_structured)
                        ctx.jars_copied += 1
                        libraries_extracted += 1
                        if libraries_extracted <= 20:
                            print(f"[forge] Copied (structured): {rel_path}")
                    except Exception as e:
                        print(f"[forge] Failed to copy {filename}: {e}")
                dst_jar_flat = os.path.join(ctx.loader_dest_dir, filename)
                if not os.path.exists(dst_jar_flat):
                    try:
                        shutil.copy2(src_jar, dst_jar_flat)
                    except Exception:
                        pass
        print(f"[forge] Extracted {ctx.jars_copied} JARs from maven")

    libraries_dir = os.path.join(ctx.extraction_dir, "libraries")
    if os.path.isdir(libraries_dir):
        print("[forge] Extracting from libraries directory (Forge < 1.13)...")
        dst_libraries_dir = os.path.join(ctx.loader_dest_dir, "libraries")
        os.makedirs(dst_libraries_dir, exist_ok=True)

        for root, _, files in os.walk(libraries_dir):
            for filename in files:
                if not filename.endswith(".jar"):
                    continue
                src_jar = os.path.join(root, filename)
                rel_path = os.path.relpath(src_jar, libraries_dir)
                dst_jar = os.path.join(dst_libraries_dir, rel_path)
                os.makedirs(os.path.dirname(dst_jar), exist_ok=True)
                try:
                    shutil.copy2(src_jar, dst_jar)
                    ctx.jars_copied += 1
                    libraries_extracted += 1
                    if libraries_extracted <= 20:
                        print(f"[forge] Copied: {rel_path}")
                except Exception as e:
                    print(f"[forge] Failed to copy {filename}: {e}")
        print(
            f"[forge] Extracted {libraries_extracted} libraries from libraries/"
        )

    if libraries_extracted == 0:
        print("[forge] WARNING: No pre-extracted libraries found!")
        print("[forge] Will download all libraries from version.json metadata...")

    return libraries_extracted


__all__ = [
    "copy_extracted_configs",
    "download_forge_artifact",
    "extract_forge_artifact",
    "extract_pre_staged_libraries",
    "parse_install_profile_and_save_metadata",
]
