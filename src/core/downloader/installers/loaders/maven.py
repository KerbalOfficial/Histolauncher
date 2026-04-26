from __future__ import annotations

import os
import urllib.parse
from typing import Optional

from core.downloader._paths import BASE_DIR
from core.downloader.errors import DownloadFailed
from core.downloader.http import CLIENT
from core.logger import colorize_log


INSTALLER_JAR_CACHE_DIR: str = os.path.join(BASE_DIR, "cache", "installers", "jars")


def installer_jar_cache_path(url: str) -> str:
    os.makedirs(INSTALLER_JAR_CACHE_DIR, exist_ok=True)
    basename = os.path.basename(urllib.parse.urlparse(url).path) or "installer.jar"
    return os.path.join(INSTALLER_JAR_CACHE_DIR, basename)


def download_installer_jar(
    url: str,
    *,
    expected_sha1: Optional[str] = None,
    cancel_check=None,
) -> str:
    dest = installer_jar_cache_path(url)
    print(colorize_log(f"[loader-installer] resolving installer JAR: {url}"))
    try:
        CLIENT.download(
            url,
            dest,
            expected_sha1=expected_sha1,
            cancel_check=cancel_check,
        )
    except DownloadFailed as exc:
        raise DownloadFailed(
            f"Could not download installer JAR: {exc}",
            url=url,
            cause=exc.__cause__,
        ) from exc
    return dest


__all__ = [
    "INSTALLER_JAR_CACHE_DIR",
    "download_installer_jar",
    "installer_jar_cache_path",
]
