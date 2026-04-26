from __future__ import annotations

import json
import os
import shutil
import tempfile
import urllib.parse
import zipfile
from typing import Optional

from core.downloader.errors import DownloadCancelled, DownloadFailed
from core.downloader.http import CLIENT
from core.downloader.jobs import Job
from core.downloader.progress import LOADER_STAGES, ProgressTracker
from core.logger import colorize_log
from core.zip_utils import safe_extract_zip


def _resolve_download_url(url: str) -> str:
    if "mediafire.com" not in urllib.parse.urlparse(url).netloc.lower():
        return url
    # Lazy import — keep new package independent of legacy except where needed.
    from core.downloader._legacy.installer_subprocess import _resolve_mediafire_download_url
    return _resolve_mediafire_download_url(url)


def _select_jar_or_repack(extracted_dir: str, dest_jar: str) -> None:
    jar_candidates = []
    for root, _, files in os.walk(extracted_dir):
        for filename in files:
            if filename.lower().endswith(".jar"):
                jar_candidates.append(os.path.join(root, filename))

    if jar_candidates:
        shutil.copy2(jar_candidates[0], dest_jar)
        return

    with zipfile.ZipFile(dest_jar, "w", compression=zipfile.ZIP_DEFLATED) as jar_out:
        for root, _, files in os.walk(extracted_dir):
            for filename in files:
                src_path = os.path.join(root, filename)
                rel_path = os.path.relpath(src_path, extracted_dir).replace("\\", "/")
                if (
                    not rel_path
                    or rel_path.endswith("/")
                    or rel_path.upper().startswith("META-INF/")
                ):
                    continue
                jar_out.write(src_path, rel_path)


def install_modloader(
    job: Job,
    *,
    mc_version: str,
    loader_version: str,
    install_dir: str,
    version_key: str,
    category: str = "",
    folder: str = "",
) -> None:
    tracker = ProgressTracker(version_key, kind="loader", stages=LOADER_STAGES)
    tracker.set_status("running")
    tracker.update("download", 0, f"Resolving ModLoader {loader_version}...")

    # ---- resolve manifest entry -----------------------------------------
    from core.modloaders import get_modloader_versions_for_mc

    entries = get_modloader_versions_for_mc(mc_version)
    entry: Optional[dict] = next(
        (e for e in entries
         if str(e.get("modloader_version") or "").strip() == loader_version),
        None,
    )
    if entry is None:
        raise DownloadFailed(
            f"ModLoader {loader_version} is not available for Minecraft {mc_version}",
            url=None,
        )

    download_url = str(entry.get("download_url") or "").strip()
    archive_type = str(entry.get("archive_type") or "zip").strip().lower()
    expected_sha256 = str(entry.get("sha256") or "").strip().lower() or None
    if archive_type != "zip":
        raise DownloadFailed(
            f"Unsupported ModLoader archive format: {archive_type}", url=None,
        )
    if not download_url:
        raise DownloadFailed("ModLoader manifest entry is missing download_url",
                             url=None)

    metadata_dir = os.path.join(install_dir, ".metadata")
    os.makedirs(metadata_dir, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="histolauncher-modloader-") as temp_dir:
        # ---- resolve mediafire (if applicable) --------------------------
        job.checkpoint()
        tracker.update("download", 5, "Resolving download URL...")
        resolved_url = _resolve_download_url(download_url)

        archive_name = str(entry.get("file_name") or "").strip()
        if not archive_name:
            archive_name = (
                os.path.basename(urllib.parse.urlparse(resolved_url).path)
                or "modloader.zip"
            )
        archive_path = os.path.join(temp_dir, archive_name)

        # ---- download archive -------------------------------------------
        job.checkpoint()
        tracker.update("download", 10,
                       f"Downloading {archive_name}...")

        def _progress(done: int, total: int) -> None:
            job.checkpoint()
            pct = (done / total * 90 + 10) if total > 0 else 10
            tracker.update(
                "download",
                pct,
                f"Downloading {archive_name} ({done}/{total or '?'} bytes)",
                bytes_done=done,
                bytes_total=total,
            )

        CLIENT.download(
            resolved_url,
            archive_path,
            expected_sha256=expected_sha256,
            progress_cb=_progress,
            cancel_check=job.checkpoint,
        )

        # ---- extract + repackage ----------------------------------------
        job.checkpoint()
        tracker.update("extracting_loader", 30, "Extracting ModLoader archive...")
        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        safe_extract_zip(archive_path, extract_dir)

        job.checkpoint()
        tracker.update("extracting_loader", 70, "Packaging ModLoader runtime jar...")
        loader_jar = os.path.join(install_dir, f"modloader-{loader_version}.jar")
        _select_jar_or_repack(extract_dir, loader_jar)

        if not os.path.isfile(loader_jar):
            raise DownloadFailed(
                "Failed to package ModLoader runtime jar", url=None,
            )

        # ---- write metadata + data.ini ----------------------------------
        job.checkpoint()
        tracker.update("extracting_loader", 95, "Writing metadata...")
        metadata = dict(entry)
        metadata["installed_archive"] = archive_name
        metadata["resolved_download_url"] = resolved_url
        with open(
            os.path.join(metadata_dir, "manifest.json"), "w", encoding="utf-8"
        ) as fp:
            json.dump(metadata, fp, indent=2)

        # ModLoader's "main class" lives inside the patched MC client jar at
        # runtime; the launch system already knows how to handle this loader,
        # so we just record a sentinel.
        _write_data_ini(
            install_dir=install_dir,
            loader_version=loader_version,
            mc_version=mc_version,
            jar_name=os.path.basename(loader_jar),
        )

    tracker.finish(
        status="installed",
        message=f"ModLoader {loader_version} installed",
    )
    print(colorize_log(
        f"[modloader] Installed ModLoader runtime jar: modloader-{loader_version}.jar"
    ))


def _write_data_ini(
    *,
    install_dir: str,
    loader_version: str,
    mc_version: str,
    jar_name: str,
) -> None:
    path = os.path.join(install_dir, "data.ini")
    lines = [
        "loader_type=modloader",
        f"loader_version={loader_version}",
        f"mc_version={mc_version}",
        f"loader_jar={jar_name}",
    ]
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")


__all__ = ["install_modloader"]
