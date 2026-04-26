from __future__ import annotations

import os
import platform
import re
import subprocess
import urllib.request
from typing import List, Optional, Tuple

from core.downloader._legacy.transport import _iter_url_candidates
from core.settings import load_global_settings
from core.subprocess_utils import no_window_kwargs


# ---------------------------------------------------------------------------
# Maven library naming
# ---------------------------------------------------------------------------


def _parse_maven_library_name(
    lib_name: str,
) -> Optional[Tuple[str, str, str, str, str]]:
    parts = str(lib_name or "").split(":")
    if len(parts) < 3:
        return None

    group = parts[0].replace(".", "/")
    artifact = parts[1]
    version = parts[2]
    classifier = ""
    extension = "jar"

    if "@" in version:
        version, extension = version.split("@", 1)

    if len(parts) >= 4:
        classifier_part = parts[3]
        if "@" in classifier_part:
            classifier, extension = classifier_part.split("@", 1)
        else:
            classifier = classifier_part

    file_name = f"{artifact}-{version}"
    if classifier:
        file_name += f"-{classifier}"
    file_name += f".{extension}"

    return group, artifact, version, classifier, file_name


def _current_library_native_os_name() -> str:
    system = platform.system().lower()
    if "windows" in system:
        return "windows"
    if "linux" in system:
        return "linux"
    if "darwin" in system or "mac" in system:
        return "osx"
    return "windows"


# ---------------------------------------------------------------------------
# Proxy / installer JVM args
# ---------------------------------------------------------------------------


def _is_url_proxy_enabled() -> bool:
    try:
        settings = load_global_settings() or {}
        return bool(str(settings.get("url_proxy") or "").strip())
    except Exception:
        return False


def _get_local_proxy_bridge_port() -> Optional[int]:
    port_str = str(os.environ.get("HISTOLAUNCHER_PORT") or "").strip()
    if not port_str:
        return None
    try:
        port = int(port_str)
    except Exception:
        return None
    return port if 1 <= port <= 65535 else None


def _get_installer_proxy_jvm_args() -> List[str]:
    return []


def _build_java_installer_command(
    java_exe: str,
    installer_jar: str,
    installer_args: List[str],
    proxy_jvm_args: Optional[List[str]] = None,
) -> List[str]:
    cmd = [java_exe]
    if proxy_jvm_args:
        cmd.extend(proxy_jvm_args)
    cmd.extend(["-jar", installer_jar])
    cmd.extend(list(installer_args or []))
    return cmd


# ---------------------------------------------------------------------------
# MediaFire HTML scraping (used by Risugami ModLoader)
# ---------------------------------------------------------------------------


_MEDIAFIRE_HREF_PATTERNS: Tuple[str, ...] = (
    r'id="downloadButton"[^>]+href="([^"]+)"',
    r'href="([^"]+)"[^>]+id="downloadButton"',
    r'href="(https?://download[^"]+)"',
)


def _resolve_mediafire_download_url(page_url: str) -> str:
    raw_url = str(page_url or "").strip()
    if not raw_url:
        raise RuntimeError("MediaFire page URL is empty")

    last_error: Optional[BaseException] = None

    for candidate_url in _iter_url_candidates(raw_url):
        try:
            req = urllib.request.Request(
                candidate_url,
                headers={
                    "User-Agent": "Histolauncher/1.0",
                    "Referer": "https://www.mediafire.com/",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                html = response.read().decode("utf-8", errors="ignore")

            for pattern in _MEDIAFIRE_HREF_PATTERNS:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    return match.group(1).replace("&amp;", "&").strip()
        except Exception as e:
            last_error = e

    raise RuntimeError(
        f"Could not resolve MediaFire download URL: "
        f"{last_error or 'no download button found'}"
    )


# ---------------------------------------------------------------------------
# Java executable lookup
# ---------------------------------------------------------------------------


def _get_java_executable() -> Optional[str]:
    settings = load_global_settings()
    java_path = settings.get("java_path")

    if java_path and os.path.exists(java_path):
        return java_path

    try:
        result = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            **no_window_kwargs(),
        )
        if result.returncode == 0:
            return "java"
    except Exception:
        pass

    return None


__all__ = [
    "_build_java_installer_command",
    "_current_library_native_os_name",
    "_get_installer_proxy_jvm_args",
    "_get_java_executable",
    "_get_local_proxy_bridge_port",
    "_is_url_proxy_enabled",
    "_parse_maven_library_name",
    "_resolve_mediafire_download_url",
]
