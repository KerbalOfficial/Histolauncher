from __future__ import annotations

import traceback
from typing import Any, Callable, Dict, Optional

from core.downloader.errors import DownloadCancelled, DownloadFailed
from core.downloader.installers.loaders.babric import SPEC as BABRIC_SPEC
from core.downloader.installers.loaders.fabric import SPEC as FABRIC_SPEC
from core.downloader.installers.loaders.forge import install_forge
from core.downloader.installers.loaders.modloader import install_modloader
from core.downloader.installers.loaders.neoforge import install_neoforge
from core.downloader.installers.loaders.pipeline import (
    loader_install_dir,
    run_loader_install,
)
from core.downloader.installers.loaders.quilt import SPEC as QUILT_SPEC
from core.downloader.installers.loaders.spec import LoaderSpec
from core.downloader.jobs import REGISTRY, Job
from core.logger import colorize_log


_NEW_SPECS: Dict[str, LoaderSpec] = {
    "fabric": FABRIC_SPEC,
    "quilt": QUILT_SPEC,
    "babric": BABRIC_SPEC,
}


_CUSTOM_RUNNERS: Dict[str, Callable[..., None]] = {
    "neoforge": install_neoforge,
    "modloader": install_modloader,
    "forge": install_forge,
}


def _is_modlauncher_era_forge(mc_version: str) -> bool:
    try:
        parts = (mc_version or "").split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        return major > 1 or (major == 1 and minor >= 13)
    except Exception:
        return False


def _job_key(category: str, folder: str, loader_type: str, loader_version: str) -> str:
    return f"{category.lower()}/{folder}/loader-{loader_type}-{loader_version}"


def download_loader(
    loader_type: str,
    mc_version: str,
    loader_version: str,
    category: str,
    folder: str,
) -> Dict[str, Any]:
    loader_type_l = (loader_type or "").lower()

    if loader_type_l == "forge" and not _is_modlauncher_era_forge(mc_version):
        from core.downloader._legacy.loaders import download_legacy_forge
        print(colorize_log(
            f"[loader-dispatch] forge {mc_version} is pre-modlauncher; "
            "using legacy install path"
        ))
        return download_legacy_forge(mc_version, loader_version, category, folder)

    if loader_type_l not in _NEW_SPECS and loader_type_l not in _CUSTOM_RUNNERS:
        return {
            "ok": False,
            "error": f"Unsupported loader type: {loader_type}",
        }

    job_key = _job_key(category, folder, loader_type_l, loader_version)
    version_key = (
        f"{category.lower()}/{folder}/modloader-{loader_type_l}-{loader_version}"
    )
    install_dir = loader_install_dir(category, folder, loader_type_l, loader_version)

    error_holder: Dict[str, Optional[str]] = {"error": None}

    if loader_type_l in _NEW_SPECS:
        spec = _NEW_SPECS[loader_type_l]
        kind = f"loader-{spec.name}"

        def _target(job: Job) -> None:
            try:
                run_loader_install(
                    job,
                    spec=spec,
                    mc_version=mc_version,
                    loader_version=loader_version,
                    category=category,
                    folder=folder,
                )
            except DownloadCancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                error_holder["error"] = str(exc)
                print(colorize_log(
                    f"[loader-dispatch] {spec.name} install error: {exc}\n"
                    f"{traceback.format_exc()}"
                ))
                raise
    else:
        runner = _CUSTOM_RUNNERS[loader_type_l]
        kind = f"loader-{loader_type_l}"

        def _target(job: Job) -> None:
            try:
                runner(
                    job,
                    mc_version=mc_version,
                    loader_version=loader_version,
                    install_dir=install_dir,
                    category=category,
                    folder=folder,
                    version_key=version_key,
                )
            except DownloadCancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                error_holder["error"] = str(exc)
                print(colorize_log(
                    f"[loader-dispatch] {loader_type_l} install error: {exc}\n"
                    f"{traceback.format_exc()}"
                ))
                raise

    job = REGISTRY.submit(
        job_key,
        kind=kind,
        target=_target,
        metadata={
            "loader_type": loader_type_l,
            "loader_version": loader_version,
            "mc_version": mc_version,
            "category": category,
            "folder": folder,
        },
    )

    job.wait()

    from core.downloader.jobs import JobState

    if job.state == JobState.COMPLETED:
        return {
            "ok": True,
            "loader_version": loader_version,
        }

    if job.state == JobState.CANCELLED:
        return {
            "ok": False,
            "error": "Loader installation cancelled by user",
            "cancelled": True,
        }

    err = error_holder["error"] or job.error or "unknown error"
    return {"ok": False, "error": err}


__all__ = ["download_loader"]
