from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

InstallerUrlResolver = Callable[[str, str], str]

CliArgsBuilder = Callable[[str, str, str], List[str]]

ProfileIdPredictor = Callable[[str, str], str]

PostInstallHook = Callable[..., None]

FallbackInstallHook = Callable[[str, str, str], None]

@dataclass(frozen=True)
class LoaderSpec:
    name: str
    display_name: str
    resolve_installer_url: InstallerUrlResolver
    build_cli_args: CliArgsBuilder
    predict_profile_id: ProfileIdPredictor
    post_install: Optional[PostInstallHook] = None
    fallback_install: Optional[FallbackInstallHook] = None
    extra_data_ini: dict = field(default_factory=dict)


__all__ = [
    "CliArgsBuilder",
    "InstallerUrlResolver",
    "LoaderSpec",
    "PostInstallHook",
    "ProfileIdPredictor",
]
