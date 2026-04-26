from __future__ import annotations

import json
import os
import shutil
from typing import Optional

from core import manifest
from core.logger import colorize_log
from core.settings import get_versions_profile_dir


def _real_version_dir(category: str, mc_version: str) -> str:
    return os.path.join(get_versions_profile_dir(), category.lower(), mc_version)


def vanilla_artifacts_present(category: str, mc_version: str) -> bool:
    vdir = _real_version_dir(category, mc_version)
    if not os.path.isfile(os.path.join(vdir, "client.jar")):
        return False
    return (
        os.path.isfile(os.path.join(vdir, f"{mc_version}.json"))
        or os.path.isfile(os.path.join(vdir, "data.ini"))
    )


def build(
    *,
    fake_mc_dir: str,
    mc_version: str,
    category: str,
) -> None:
    os.makedirs(fake_mc_dir, exist_ok=True)
    mc_ver_dir = os.path.join(fake_mc_dir, "versions", mc_version)
    os.makedirs(mc_ver_dir, exist_ok=True)
    os.makedirs(os.path.join(fake_mc_dir, "libraries"), exist_ok=True)

    real_vdir = _real_version_dir(category, mc_version)

    real_client = os.path.join(real_vdir, "client.jar")
    fake_client = os.path.join(mc_ver_dir, f"{mc_version}.jar")
    if os.path.isfile(real_client) and not os.path.exists(fake_client):
        try:
            shutil.copy2(real_client, fake_client)
        except OSError as exc:
            print(colorize_log(
                f"[fake-mc] could not copy client.jar ({exc}); installer will re-download"
            ))

    fake_json_path = os.path.join(mc_ver_dir, f"{mc_version}.json")
    real_json_path = os.path.join(real_vdir, f"{mc_version}.json")
    if not os.path.exists(fake_json_path):
        version_data: Optional[dict] = None
        if os.path.isfile(real_json_path):
            try:
                with open(real_json_path, "r", encoding="utf-8") as fp:
                    version_data = json.load(fp)
            except (OSError, json.JSONDecodeError):
                version_data = None
        if version_data is None:
            entry = manifest.get_version_entry(mc_version)
            url = entry.get("url") if isinstance(entry, dict) else None
            if not url:
                raise RuntimeError(
                    f"Could not resolve Mojang manifest entry for {mc_version}"
                )
            version_data = manifest.fetch_version_json(url)
        with open(fake_json_path, "w", encoding="utf-8") as fp:
            json.dump(version_data, fp)

    profiles_path = os.path.join(fake_mc_dir, "launcher_profiles.json")
    if not os.path.exists(profiles_path):
        with open(profiles_path, "w", encoding="utf-8") as fp:
            json.dump(
                {
                    "profiles": {
                        "(Default)": {
                            "name": "(Default)",
                            "type": "latest-release",
                        }
                    },
                    "selectedProfile": "(Default)",
                    "authenticationDatabase": {},
                    "clientToken": "histolauncher-fake-token",
                    "launcherVersion": {
                        "format": 21,
                        "name": "2.2.1234",
                        "profilesFormat": 2,
                    },
                },
                fp,
                indent=2,
            )


__all__ = [
    "build",
    "vanilla_artifacts_present",
]
