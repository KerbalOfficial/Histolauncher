from __future__ import annotations

import os
import urllib.parse
from typing import List

from core.downloader.installers.loaders.spec import LoaderSpec
from core.downloader.errors import DownloadFailed
from core.http_client import HttpClient, HttpClientError


_QUILT_INSTALLER_FALLBACK = (
    "https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/"
    "0.9.2/quilt-installer-0.9.2.jar"
)


def _resolve_installer_url(mc_version: str, loader_version: str) -> str:
    del mc_version, loader_version
    try:
        from core.modloaders._http import _http_get_json
    except Exception:
        return _QUILT_INSTALLER_FALLBACK
    try:
        installers = _http_get_json(
            "https://meta.quiltmc.org/v3/versions/installer"
        )
    except Exception:
        return _QUILT_INSTALLER_FALLBACK
    if not isinstance(installers, list) or not installers:
        return _QUILT_INSTALLER_FALLBACK
    latest = installers[0]
    if isinstance(latest, dict):
        url = latest.get("url")
        if isinstance(url, str) and url.endswith(".jar"):
            return url
        version = latest.get("version")
        if isinstance(version, str):
            return (
                "https://maven.quiltmc.org/repository/release/org/quiltmc/"
                f"quilt-installer/{version}/quilt-installer-{version}.jar"
            )
    return _QUILT_INSTALLER_FALLBACK


def _build_cli_args(mc_version: str, loader_version: str, fake_mc_dir: str) -> List[str]:
    return [
        "install", "client",
        mc_version, loader_version,
        "--install-dir", fake_mc_dir,
        "--no-profile",
    ]


def _predict_profile_id(mc_version: str, loader_version: str) -> str:
    return f"quilt-loader-{loader_version}-{mc_version}"


def _fallback_install(mc_version: str, loader_version: str, fake_mc_dir: str) -> None:
    mc_enc = urllib.parse.quote(mc_version, safe="")
    loader_enc = urllib.parse.quote(loader_version, safe="")
    profile_url = f"https://meta.quiltmc.org/v3/versions/loader/{mc_enc}/{loader_enc}/profile/json"
    
    profile_id = _predict_profile_id(mc_version, loader_version)
    target_dir = os.path.join(fake_mc_dir, "versions", profile_id)
    os.makedirs(target_dir, exist_ok=True)
    target_file = os.path.join(target_dir, f"{profile_id}.json")
    
    try:
        HttpClient(timeout=30.0).stream_to(profile_url, target_file)
    except HttpClientError as exc:
        raise DownloadFailed(f"Quilt metadata installation failed: {exc}") from exc


SPEC = LoaderSpec(
    name="quilt",
    display_name="Quilt",
    resolve_installer_url=_resolve_installer_url,
    build_cli_args=_build_cli_args,
    predict_profile_id=_predict_profile_id,
    fallback_install=_fallback_install,
)

__all__ = ["SPEC"]
