from __future__ import annotations

import os
import urllib.parse
from typing import List

from core.downloader.installers.loaders.spec import LoaderSpec
from core.downloader.errors import DownloadFailed
from core.http_client import HttpClient, HttpClientError


_LEGACY_FABRIC_META_API = "https://meta.legacyfabric.net/v2"
_LEGACY_FABRIC_INSTALLER_FALLBACK_URL = (
    "https://maven.legacyfabric.net/net/legacyfabric/fabric-installer/"
    "1.1.1/fabric-installer-1.1.1.jar"
)


def _resolve_installer_url(mc_version: str, loader_version: str) -> str:
    del mc_version, loader_version
    try:
        data = HttpClient(timeout=15.0).get_json(f"{_LEGACY_FABRIC_META_API}/versions/installer")
        if isinstance(data, list) and data:
            stable = next((e for e in data if isinstance(e, dict) and e.get("stable")), None)
            entry = stable or data[0]
            url = entry.get("url") if isinstance(entry, dict) else None
            if url:
                return url
    except Exception:
        pass
    return _LEGACY_FABRIC_INSTALLER_FALLBACK_URL


def _build_cli_args(mc_version: str, loader_version: str, fake_mc_dir: str) -> List[str]:
    return [
        "client",
        "-mcversion", mc_version,
        "-loader", loader_version,
        "-dir", fake_mc_dir,
        "-noprofile",
    ]


def _predict_profile_id(mc_version: str, loader_version: str) -> str:
    return f"fabric-loader-{loader_version}-{mc_version}"


def _fallback_install(mc_version: str, loader_version: str, fake_mc_dir: str) -> None:
    mc_enc = urllib.parse.quote(mc_version, safe="")
    loader_enc = urllib.parse.quote(loader_version, safe="")
    profile_url = (
        f"{_LEGACY_FABRIC_META_API}/versions/loader/{mc_enc}/{loader_enc}/profile/json"
    )
    profile_id = _predict_profile_id(mc_version, loader_version)
    target_dir = os.path.join(fake_mc_dir, "versions", profile_id)
    os.makedirs(target_dir, exist_ok=True)
    target_file = os.path.join(target_dir, f"{profile_id}.json")

    try:
        HttpClient(timeout=30.0).stream_to(profile_url, target_file)
    except HttpClientError as exc:
        raise DownloadFailed(f"Legacy Fabric metadata installation failed: {exc}") from exc


SPEC = LoaderSpec(
    name="legacyfabric",
    display_name="Legacy Fabric",
    resolve_installer_url=_resolve_installer_url,
    build_cli_args=_build_cli_args,
    predict_profile_id=_predict_profile_id,
    fallback_install=_fallback_install,
)

__all__ = ["SPEC"]
