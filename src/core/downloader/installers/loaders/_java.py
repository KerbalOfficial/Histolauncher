from __future__ import annotations

from typing import Optional


def get_java_executable() -> Optional[str]:
    from core.downloader._legacy.installer_subprocess import _get_java_executable
    return _get_java_executable()


__all__ = ["get_java_executable"]
