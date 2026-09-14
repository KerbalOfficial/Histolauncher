from __future__ import annotations

import os


__all__ = [
    "read_local_version",
    "is_launcher_outdated",
]


def _resolve_project_root(project_root: str = None, base_dir: str = None) -> str:
    if project_root is None and base_dir is not None:
        project_root = base_dir
    if project_root is None:
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
    return project_root


def read_local_version(project_root: str = None, base_dir: str = None) -> str:
    try:
        path = os.path.join(_resolve_project_root(project_root, base_dir), "version.dat")
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None


def is_launcher_outdated() -> bool:
    try:
        from launcher.updater import (
            select_latest_release_for_local,
            should_prompt_update,
        )

        local = read_local_version()
        if not local:
            return False

        release, _reason = select_latest_release_for_local(local)
        remote = (release or {}).get("tag_name")
        prompt, _reason = should_prompt_update(local, remote)
        return bool(prompt)
    except Exception:
        return False
