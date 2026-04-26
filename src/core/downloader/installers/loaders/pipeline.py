from __future__ import annotations

import os
import shutil
import tempfile
import time
from typing import Optional

from core.downloader.errors import DownloadCancelled, DownloadFailed
from core.downloader.installers.loaders import fake_mc_dir as fake_mc_mod
from core.downloader.installers.loaders import profile_import
from core.downloader.installers.loaders.installer_runner import run_installer_jar
from core.downloader.installers.loaders.maven import download_installer_jar
from core.downloader.installers.loaders.spec import LoaderSpec
from core.downloader.jobs import Job, JobState
from core.downloader.progress import (
    LOADER_STAGES,
    ProgressTracker,
    delete_progress,
    write_progress_dict,
)
from core.logger import colorize_log
from core.settings import get_versions_profile_dir
from core.version_manager import ensure_loaders_dir


def loader_install_dir(category: str, folder: str, loader_type: str, loader_version: str) -> str:
    return os.path.join(
        ensure_loaders_dir(category, folder), loader_type, loader_version
    )


def real_version_dir(category: str, folder: str) -> str:
    return os.path.join(get_versions_profile_dir(), category.lower(), folder)


def _ensure_vanilla_installed(
    *,
    job: Job,
    mc_version: str,
    category: str,
    tracker: ProgressTracker,
) -> None:
    if fake_mc_mod.vanilla_artifacts_present(category, mc_version):
        return

    print(colorize_log(
        f"[loader-pipeline] vanilla {category}/{mc_version} missing — installing first"
    ))
    tracker.update("download", 0,
                   f"Installing vanilla {mc_version} (required for loader)...")

    from core.downloader.installers.vanilla import install_version

    sub_job = install_version(
        mc_version,
        storage_category=category,
        full_assets=False,
        background=True,
    )
    if sub_job is None:
        deadline = time.time() + 1800
        while time.time() < deadline:
            job.checkpoint()
            if fake_mc_mod.vanilla_artifacts_present(category, mc_version):
                return
            time.sleep(0.5)
        raise DownloadFailed(
            f"Timed out waiting for concurrent vanilla install of {mc_version}",
            url=None,
        )

    while sub_job.state not in (JobState.COMPLETED, JobState.CANCELLED, JobState.FAILED):
        try:
            job.checkpoint()
        except DownloadCancelled:
            sub_job.cancel()
            raise
        time.sleep(0.25)

    if sub_job.state == JobState.CANCELLED:
        raise DownloadCancelled()
    if sub_job.state == JobState.FAILED:
        raise DownloadFailed(
            f"Vanilla {mc_version} install failed: {sub_job.error or 'unknown error'}",
            url=None,
        )


def _write_data_ini(
    *,
    install_dir: str,
    loader_type: str,
    loader_version: str,
    mc_version: str,
    profile_id: str,
    main_class: Optional[str],
) -> None:
    os.makedirs(install_dir, exist_ok=True)
    path = os.path.join(install_dir, "data.ini")
    lines = [
        f"loader_type={loader_type}",
        f"loader_version={loader_version}",
        f"mc_version={mc_version}",
        f"profile_id={profile_id}",
    ]
    if main_class:
        lines.append(f"main_class={main_class}")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")


def run_loader_install(
    job: Job,
    *,
    spec: LoaderSpec,
    mc_version: str,
    loader_version: str,
    category: str,
    folder: str,
) -> None:
    version_key = f"{category.lower()}/{folder}/modloader-{spec.name}-{loader_version}"
    tracker = ProgressTracker(version_key, kind="loader", stages=LOADER_STAGES)
    install_dir = loader_install_dir(category, folder, spec.name, loader_version)
    real_vdir = real_version_dir(category, folder)
    fake_dir: Optional[str] = None

    try:
        tracker.set_status("running")
        tracker.update("download", 0,
                       f"Starting {spec.display_name} {loader_version} install...")

        # ---- prepare_vanilla -------------------------------------------------
        _ensure_vanilla_installed(
            job=job, mc_version=mc_version, category=category, tracker=tracker,
        )

        # ---- resolve_installer ----------------------------------------------
        job.checkpoint()
        tracker.update("download", 25,
                       f"Resolving {spec.display_name} installer URL...")
        installer_url = spec.resolve_installer_url(mc_version, loader_version)

        # ---- download_installer ---------------------------------------------
        job.checkpoint()
        tracker.update("download", 50,
                       f"Downloading {spec.display_name} installer JAR...")
        installer_jar = download_installer_jar(
            installer_url, cancel_check=job.checkpoint
        )

        # ---- run_installer ---------------------------------------------------
        job.checkpoint()
        tracker.update("downloading_libs", 0,
                       f"Running {spec.display_name} installer (Java)...")
        fake_dir = tempfile.mkdtemp(prefix=f"histolauncher-{spec.name}-")
        fake_mc_mod.build(
            fake_mc_dir=fake_dir, mc_version=mc_version, category=category,
        )

        def _line_sink(line: str) -> None:
            # Surface a brief snippet of installer output as the progress message
            # so the UI shows real-time activity.
            tracker.update(
                "downloading_libs", 25,
                f"{spec.display_name} installer: {line[:80]}",
            )

        try:
            run_installer_jar(
                installer_jar,
                spec.build_cli_args(mc_version, loader_version, fake_dir),
                cwd=fake_dir,
                cancel_check=job.checkpoint,
                line_sink=_line_sink,
            )
        except DownloadFailed as exc:
            if getattr(spec, "fallback_install", None) is not None:
                tracker.update(
                    "downloading_libs", 30,
                    f"{spec.display_name} installer failed, falling back to metadata mode...",
                )
                spec.fallback_install(mc_version, loader_version, fake_dir)
            else:
                raise exc

        # ---- import_profile + download_libraries -----------------------------
        job.checkpoint()
        tracker.update("downloading_libs", 60,
                       f"Importing {spec.display_name} profile and libraries...")

        expected_profile_id = spec.predict_profile_id(mc_version, loader_version)
        result = profile_import.import_profile(
            fake_mc_dir=fake_dir,
            real_version_dir=install_dir,
            expected_profile_id=expected_profile_id,
            cancel_check=job.checkpoint,
            progress_cb=lambda done, total: tracker.update(
                "downloading_libs",
                60 + 40 * (done / max(1, total)),
                f"Linking libraries {done}/{total}",
            ),
        )

        # ---- post_install hook (Forge log4j patch etc.) ---------------------
        if spec.post_install is not None:
            job.checkpoint()
            tracker.update("extracting_loader", 50,
                           f"Applying {spec.display_name} post-install patches...")
            spec.post_install(
                loader_version=loader_version,
                mc_version=mc_version,
                real_version_dir=install_dir,
                profile_id=result.profile_id,
                fake_mc_dir=fake_dir,
            )

        # ---- finalize --------------------------------------------------------
        # Copy profile JSON to .metadata/version.json (where launch reads it).
        metadata_dir = os.path.join(install_dir, ".metadata")
        os.makedirs(metadata_dir, exist_ok=True)
        shutil.copy2(
            result.profile_path,
            os.path.join(metadata_dir, "version.json"),
        )
        _write_data_ini(
            install_dir=install_dir,
            loader_type=spec.name,
            loader_version=loader_version,
            mc_version=mc_version,
            profile_id=result.profile_id,
            main_class=result.main_class,
        )
        
        if spec.name in ("fabric", "babric", "quilt"):
            tracker.update("finalize", 95, f"Setting up {spec.display_name} mappings...")
            from core.downloader.yarn import _download_yarn_mappings
            job.checkpoint()
            yarn_val = _download_yarn_mappings(install_dir, mc_version, "")
            if yarn_val:
                print(colorize_log(f"[launcher] Acquired yarn mappings during install: {yarn_val}"))
        
        tracker.finish(status="installed",
                       message=f"{spec.display_name} {loader_version} installed")

    except DownloadCancelled:
        tracker.finish(status="cancelled",
                       message=f"{spec.display_name} install cancelled")
        raise
    except Exception as exc:
        tracker.finish(status="failed",
                       message=f"{spec.display_name} install failed: {exc}")
        raise
    finally:
        if fake_dir and os.path.isdir(fake_dir):
            shutil.rmtree(fake_dir, ignore_errors=True)


__all__ = [
    "loader_install_dir",
    "real_version_dir",
    "run_loader_install",
]
