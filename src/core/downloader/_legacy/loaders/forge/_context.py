from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ForgeContext:
    # ---- request inputs ------------------------------------------------
    mc_version: str
    loader_version: str
    loaders_dir: str        # cache/<category>/<folder>/loaders/
    version_key: str        # progress key

    # ---- derived once at start ----------------------------------------
    version_dir: str = ""           # parent of loaders_dir
    loader_dest_dir: str = ""       # loaders_dir/forge/<loader_version>
    metadata_dir: str = ""          # loader_dest_dir/.metadata
    loader_libraries_dir: str = ""  # loader_dest_dir/libraries
    modlauncher_era: bool = False

    # ---- temp workspace (set by download phase) -----------------------
    temp_dir: str = ""
    extraction_dir: str = ""
    downloaded_artifact_path: str = ""
    downloaded_artifact_name: str = ""
    is_installer_archive: bool = False
    is_legacy_universal_archive: bool = False

    # ---- parsed metadata ----------------------------------------------
    profile_data: Optional[Dict[str, Any]] = None
    mc_version_data: Dict[str, Any] = field(default_factory=dict)

    # ---- modern-installer workspace -----------------------------------
    fake_mc_dir: str = ""
    fake_libs_dir: str = ""
    client_jar_src: str = ""
    client_jar_dst: str = ""
    installer_maven: str = ""
    downloaded_lib_cache: str = ""

    # ---- counters used by the final summary ---------------------------
    jars_copied: int = 0
    files_copied: int = 0
    installer_completed_cleanly: bool = True

    def init_paths(self) -> None:
        self.version_dir = os.path.dirname(self.loaders_dir)
        self.loader_dest_dir = os.path.join(
            self.loaders_dir, "forge", self.loader_version
        )
        self.metadata_dir = os.path.join(self.loader_dest_dir, ".metadata")
        self.loader_libraries_dir = os.path.join(self.loader_dest_dir, "libraries")
        self.modlauncher_era = is_modlauncher_era(self.mc_version)


def is_modlauncher_era(mc_ver: str) -> bool:
    try:
        parts = (mc_ver or "").split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        return major > 1 or (major == 1 and minor >= 13)
    except Exception:
        return False


__all__ = ["ForgeContext", "is_modlauncher_era"]
