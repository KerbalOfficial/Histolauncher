from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

from core.downloader.errors import DownloadFailed
from core.downloader.http import CLIENT
from core.downloader.jobs import Job
from core.downloader.progress import LOADER_STAGES, ProgressTracker
from core.logger import safe_print


_LIBRARY_REPOS = (
    "https://libraries.minecraft.net/",
    "https://repo1.maven.org/maven2/",
)

_LAUNCHWRAPPER_MAIN_CLASS = "net.minecraft.launchwrapper.Launch"


def _maven_coord_to_path(coord: str) -> Optional[str]:
    parts = str(coord or "").split(":")
    if len(parts) < 3:
        return None
    group, artifact, version = parts[0], parts[1], parts[2]
    file_name = f"{artifact}-{version}.jar"
    if len(parts) >= 4:
        classifier = parts[3].split("@", 1)[0]
        if classifier:
            file_name = f"{artifact}-{version}-{classifier}.jar"
    return "/".join([group.replace(".", "/"), artifact, version, file_name])


def _download_library(coord: str, libraries_dir: str, cancel_check) -> None:
    rel_path = _maven_coord_to_path(coord)
    if not rel_path:
        safe_print(f"[liteloader] Skipping malformed library coordinate: {coord}")
        return

    dest = os.path.join(libraries_dir, rel_path.replace("/", os.sep))
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    last_error: Optional[Exception] = None
    for repo in _LIBRARY_REPOS:
        try:
            CLIENT.download(repo + rel_path, dest, cancel_check=cancel_check)
            safe_print(f"[liteloader] Downloaded library {coord} from {repo}")
            return
        except DownloadFailed as exc:
            last_error = exc
            continue

    raise DownloadFailed(
        f"Could not download LiteLoader library {coord}: {last_error}", url=None,
    )


def _verify_md5(path: str, expected_md5: str) -> None:
    expected = str(expected_md5 or "").strip().lower()
    if not expected:
        return
    digest = hashlib.md5()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest().lower()
    if actual != expected:
        raise DownloadFailed(
            f"LiteLoader jar MD5 mismatch (expected {expected}, got {actual})", url=None,
        )


def install_liteloader(
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
    tracker.update("download", 0, f"Resolving LiteLoader {loader_version}...")

    from core.modloaders import get_liteloader_entry

    entry = get_liteloader_entry(mc_version, loader_version)
    if entry is None:
        raise DownloadFailed(
            f"LiteLoader {loader_version} is not available for Minecraft {mc_version}",
            url=None,
        )

    download_url = str(entry.get("download_url") or "").strip()
    if not download_url:
        raise DownloadFailed("LiteLoader manifest entry is missing download_url", url=None)

    os.makedirs(install_dir, exist_ok=True)
    loader_jar = os.path.join(install_dir, f"liteloader-{loader_version}.jar")

    # ---- download LiteLoader runtime jar ---------------------------------
    job.checkpoint()
    file_name = str(entry.get("file_name") or os.path.basename(download_url))
    tracker.update("download", 10, f"Downloading {file_name}...")

    def _progress(done: int, total: int) -> None:
        job.checkpoint()
        pct = (done / total * 80 + 10) if total > 0 else 10
        tracker.update(
            "download",
            pct,
            f"Downloading {file_name} ({done}/{total or '?'} bytes)",
            bytes_done=done,
            bytes_total=total,
        )

    CLIENT.download(
        download_url,
        loader_jar,
        progress_cb=_progress,
        cancel_check=job.checkpoint,
    )
    _verify_md5(loader_jar, str(entry.get("md5") or ""))

    # ---- download LaunchWrapper + support libraries -----------------------
    libraries = [str(c) for c in (entry.get("libraries") or []) if str(c or "").strip()]
    libraries_dir = os.path.join(install_dir, "libraries")
    for index, coord in enumerate(libraries):
        job.checkpoint()
        tracker.update(
            "downloading_libs",
            (index / max(1, len(libraries))) * 100,
            f"Downloading library {coord}...",
        )
        _download_library(coord, libraries_dir, job.checkpoint)

    # ---- write metadata + data.ini ----------------------------------------
    job.checkpoint()
    tracker.update("extracting_loader", 90, "Writing metadata...")
    tweak_class = str(entry.get("tweak_class") or "").strip()

    metadata_dir = os.path.join(install_dir, ".metadata")
    os.makedirs(metadata_dir, exist_ok=True)
    version_json = {
        "id": f"{mc_version}-liteloader-{loader_version}",
        "inheritsFrom": mc_version,
        "mainClass": _LAUNCHWRAPPER_MAIN_CLASS,
        "arguments": {"game": ["--tweakClass", tweak_class] if tweak_class else []},
        "libraries": [
            {"name": f"com.mumfrey:liteloader:{loader_version}"}
        ] + [{"name": coord} for coord in libraries],
    }
    with open(
        os.path.join(metadata_dir, "version.json"), "w", encoding="utf-8"
    ) as fp:
        json.dump(version_json, fp, indent=2)
    with open(
        os.path.join(metadata_dir, "manifest.json"), "w", encoding="utf-8"
    ) as fp:
        json.dump(dict(entry), fp, indent=2)

    _write_data_ini(
        install_dir=install_dir,
        loader_version=loader_version,
        mc_version=mc_version,
        jar_name=os.path.basename(loader_jar),
        tweak_class=tweak_class,
    )

    tracker.finish(
        status="installed",
        message=f"LiteLoader {loader_version} installed",
    )
    safe_print(
        f"[liteloader] Installed LiteLoader runtime jar: liteloader-{loader_version}.jar"
    )


def _write_data_ini(
    *,
    install_dir: str,
    loader_version: str,
    mc_version: str,
    jar_name: str,
    tweak_class: str,
) -> None:
    path = os.path.join(install_dir, "data.ini")
    lines = [
        "loader_type=liteloader",
        f"loader_version={loader_version}",
        f"mc_version={mc_version}",
        f"loader_jar={jar_name}",
        f"main_class={_LAUNCHWRAPPER_MAIN_CLASS}",
    ]
    if tweak_class:
        lines.append(f"tweak_class={tweak_class}")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")


__all__ = ["install_liteloader"]
