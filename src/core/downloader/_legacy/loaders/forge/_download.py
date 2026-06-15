from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.parse
from typing import Optional

from core.downloader._legacy._state import STATE
from core.downloader._legacy.progress import _update_progress
from core.downloader._legacy.transport import _safe_remove_file, download_file
from core.logger import safe_print
from core.zip_utils import safe_extract_zip

from core.downloader._legacy.loaders.forge._context import ForgeContext


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _download_forge_from_manifest(ctx: ForgeContext) -> Optional[bool]:
    from core.modloaders import get_forge_download_spec

    spec = get_forge_download_spec(ctx.mc_version, ctx.loader_version)
    if not spec:
        return None

    download_url = str(spec.get("download_url") or "").strip()
    if not download_url:
        safe_print(
            f"[forge] Manifest entry for {ctx.mc_version}-{ctx.loader_version} "
            "has no download_url"
        )
        return False

    if str(spec.get("download_kind") or "").lower() == "mediafire":
        try:
            from core.downloader._legacy.installer_subprocess import (
                _resolve_mediafire_download_url,
            )
            download_url = _resolve_mediafire_download_url(download_url)
        except Exception as exc:
            safe_print(f"[forge] Could not resolve MediaFire URL: {exc}")
            return False

    archive_ext = str(spec.get("archive_type") or "zip").strip().lower() or "zip"
    artifact_name = f"forge-{ctx.mc_version}-{ctx.loader_version}-client.{archive_ext}"
    artifact_path = os.path.join(ctx.temp_dir, artifact_name)

    def progress_hook(downloaded: int, total: Optional[int]) -> None:
        if STATE.cancel_flags.get(ctx.version_key):
            raise RuntimeError("Download cancelled by user")
        percent = int(100 * downloaded / total) if total else 0
        _update_progress(
            ctx.version_key, "download", percent,
            f"Downloading Forge {percent}%...", downloaded, 0,
        )

    safe_print(f"[forge] Downloading Forge from manifest: {download_url}")
    try:
        download_file(
            download_url, artifact_path,
            version_key=ctx.version_key, progress_cb=progress_hook,
        )
    except RuntimeError as exc:
        if "cancel" in str(exc).lower():
            _safe_remove_file(artifact_path)
            raise
        safe_print(f"[forge] Manifest download failed: {exc}")
        _safe_remove_file(artifact_path)
        return False
    except Exception as exc:
        safe_print(f"[forge] Manifest download failed: {exc}")
        _safe_remove_file(artifact_path)
        return False

    if not (os.path.exists(artifact_path) and os.path.getsize(artifact_path) > 0):
        return False

    expected_sha256 = str(spec.get("sha256") or "").strip().lower()
    if expected_sha256:
        actual = _sha256_file(artifact_path)
        if actual != expected_sha256:
            safe_print(
                f"[forge] Manifest SHA256 mismatch for {artifact_name}: "
                f"expected {expected_sha256}, got {actual}"
            )
            _safe_remove_file(artifact_path)
            return False

    ctx.downloaded_artifact_path = artifact_path
    ctx.downloaded_artifact_name = artifact_name
    ctx.is_installer_archive = False
    safe_print(f"[forge] Using manifest Forge artifact: {artifact_name}")
    return True


def download_forge_artifact(ctx: ForgeContext) -> Optional[str]:
    from core.modloaders import get_forge_artifact_urls

    # ---- manifest-hosted builds (beta-era / non-maven) take priority -----
    manifest_result = _download_forge_from_manifest(ctx)
    if manifest_result is True:
        return None
    if manifest_result is False:
        return "Failed to download Forge artifact from manifest"

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
        safe_print(f"[forge] Downloading Forge artifact from {artifact_url}")
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
                safe_print(f"[forge] Using Forge artifact: {artifact_name}")
                return None
        except RuntimeError as e:
            if "cancel" in str(e).lower():
                safe_print("[forge] Download cancelled")
                _safe_remove_file(artifact_path)
                raise
            last_download_error = str(e)
            _safe_remove_file(artifact_path)
            safe_print(f"[forge] Download failed for {artifact_name}: {e}")
        except Exception as e:
            last_download_error = str(e)
            _safe_remove_file(artifact_path)
            safe_print(f"[forge] Download failed for {artifact_name}: {e}")

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
            safe_print(f"[forge] ZIP extraction error: {e}")
            return f"Failed to extract Forge archive: {e}"
    elif ctx.is_installer_archive:
        try:
            safe_extract_zip(ctx.downloaded_artifact_path, ctx.extraction_dir)
        except Exception as e:
            safe_print(f"[forge] Installer extraction error: {e}")
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
            safe_print("[forge] Parsed install_profile.json")
            shutil.copy2(
                profile_path,
                os.path.join(ctx.metadata_dir, "install_profile.json"),
            )
            safe_print("[forge] Saved install_profile.json to metadata")
        except Exception as e:
            safe_print(f"[forge] WARNING: Could not parse install_profile.json: {e}")

    version_json_src = os.path.join(ctx.extraction_dir, "version.json")
    if os.path.exists(version_json_src):
        try:
            shutil.copy2(
                version_json_src,
                os.path.join(ctx.metadata_dir, "version.json"),
            )
            safe_print("[forge] Saved version.json to metadata")
        except Exception as e:
            safe_print(f"[forge] WARNING: Could not save version.json: {e}")


def copy_extracted_configs(ctx: ForgeContext) -> None:
    safe_print("[forge] Extracting configuration files...")
    for root, _, files in os.walk(ctx.extraction_dir):
        for filename in files:
            if filename in ("log4j2.xml", "log4j.properties", "log4j.xml") \
                    or filename.endswith(".properties"):
                src_file = os.path.join(root, filename)
                dst_file = os.path.join(ctx.loader_dest_dir, filename)
                try:
                    shutil.copy2(src_file, dst_file)
                    ctx.files_copied += 1
                    safe_print(f"[forge] Extracted config: {filename}")
                except Exception as e:
                    safe_print(f"[forge] Warning: Could not copy {filename}: {e}")


def extract_pre_staged_libraries(ctx: ForgeContext) -> int:
    libraries_extracted = 0

    maven_dir = os.path.join(ctx.extraction_dir, "maven")
    if os.path.isdir(maven_dir):
        safe_print("[forge] Extracting from maven directory (Forge 1.13+)...")
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
                            safe_print(f"[forge] Copied (structured): {rel_path}")
                    except Exception as e:
                        safe_print(f"[forge] Failed to copy {filename}: {e}")
                dst_jar_flat = os.path.join(ctx.loader_dest_dir, filename)
                if not os.path.exists(dst_jar_flat):
                    try:
                        shutil.copy2(src_jar, dst_jar_flat)
                    except Exception:
                        pass
        safe_print(f"[forge] Extracted {ctx.jars_copied} JARs from maven")

    libraries_dir = os.path.join(ctx.extraction_dir, "libraries")
    if os.path.isdir(libraries_dir):
        safe_print("[forge] Extracting from libraries directory (Forge < 1.13)...")
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
                        safe_print(f"[forge] Copied: {rel_path}")
                except Exception as e:
                    safe_print(f"[forge] Failed to copy {filename}: {e}")
        safe_print(
            f"[forge] Extracted {libraries_extracted} libraries from libraries/"
        )

    if libraries_extracted == 0:
        safe_print("[forge] WARNING: No pre-extracted libraries found!")
        safe_print("[forge] Will download all libraries from version.json metadata...")

    return libraries_extracted


__all__ = [
    "copy_extracted_configs",
    "download_forge_artifact",
    "extract_forge_artifact",
    "extract_pre_staged_libraries",
    "parse_install_profile_and_save_metadata",
]
