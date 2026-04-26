from __future__ import annotations

import os
import urllib.request

from core.settings import _apply_url_proxy

from server.api._constants import GITHUB_RAW_VERSION_URL, REMOTE_TIMEOUT


__all__ = [
    "read_local_version",
    "fetch_remote_version",
    "parse_version",
    "is_launcher_outdated",
]


def read_local_version(project_root: str = None, base_dir: str = None) -> str:
    try:
        if project_root is None and base_dir is not None:
            project_root = base_dir
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(project_root, "version.dat")
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None


def fetch_remote_version(timeout=REMOTE_TIMEOUT):
    try:
        url = _apply_url_proxy(GITHUB_RAW_VERSION_URL)
        req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception:
        return None


def parse_version(ver):
    if not ver or len(ver) < 2:
        return None, None
    letter = ver[0]
    try:
        num = int(ver[1:])
        return letter, num
    except Exception:
        return None, None


def is_launcher_outdated():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local = read_local_version(project_root=project_root)
    remote = fetch_remote_version()

    if not local or not remote:
        return False

    l_letter, l_num = parse_version(local)
    r_letter, r_num = parse_version(remote)

    if l_letter is None or r_letter is None:
        return False

    if l_letter != r_letter:
        return False

    return r_num > l_num
