from __future__ import annotations

import json
import os
import urllib.parse
from typing import List, Tuple

from core.downloader.installers.loaders.spec import LoaderSpec
from core.downloader.errors import DownloadFailed
from core.http_client import HttpClient, HttpClientError


_ORNITHE_META_API = "https://meta.ornithemc.net/v3"

_MAVEN_CENTRAL = "https://repo1.maven.org/maven2/"
_EXTRA_PROFILE_LIBRARIES: List[dict] = [
    {"name": "org.apache.logging.log4j:log4j-api:2.17.1", "url": _MAVEN_CENTRAL},
    {"name": "org.apache.logging.log4j:log4j-core:2.17.1", "url": _MAVEN_CENTRAL},
]

_LEGACY_COMMON_LIBRARIES: List[dict] = [
    {"name": "com.google.code.gson:gson:2.8.9", "url": _MAVEN_CENTRAL},
    {"name": "com.google.guava:guava:31.0.1-jre", "url": _MAVEN_CENTRAL},
    {"name": "org.apache.commons:commons-lang3:3.12.0", "url": _MAVEN_CENTRAL},
    {"name": "commons-io:commons-io:2.11.0", "url": _MAVEN_CENTRAL},
    {"name": "commons-codec:commons-codec:1.15", "url": _MAVEN_CENTRAL},
    {"name": "org.apache.httpcomponents:httpclient:4.5.13", "url": _MAVEN_CENTRAL},
    {"name": "org.apache.httpcomponents:httpcore:4.4.13", "url": _MAVEN_CENTRAL},
    {"name": "commons-logging:commons-logging:1.2", "url": _MAVEN_CENTRAL},
    {"name": "net.sf.jopt-simple:jopt-simple:5.0.4", "url": _MAVEN_CENTRAL},
]


def _needs_legacy_common_libraries(mc_version: str) -> bool:
    try:
        from core.launch.args import _is_legacy_pre16_runtime

        return bool(_is_legacy_pre16_runtime(mc_version))
    except Exception:
        import re

        return bool(re.match(r"^(?:b1|a1|c0|inf-|in-|rd-)", str(mc_version or "").strip().lower()))


def _ornithe_target(mc_version: str) -> Tuple[str, str]:
    try:
        from core.modloaders.ornithe import resolve_ornithe_target

        resolved = resolve_ornithe_target(mc_version)
        if resolved:
            return resolved
    except Exception:
        pass

    return ("gen1", str(mc_version or "").strip())


def _gen_path(generation: str) -> str:
    return "gen2/" if generation == "gen2" else ""


def _resolve_installer_url(mc_version: str, loader_version: str) -> str:
    del mc_version, loader_version
    return ""


def _build_cli_args(mc_version: str, loader_version: str, fake_mc_dir: str) -> List[str]:
    del mc_version, loader_version, fake_mc_dir
    return []


def _predict_profile_id(mc_version: str, loader_version: str) -> str:
    generation = _ornithe_target(mc_version)[0]
    plain = str(mc_version or "").strip()
    return f"fabric-loader-{loader_version}-{plain}-ornithe-{generation}"


def _metadata_install(mc_version: str, loader_version: str, fake_mc_dir: str) -> None:
    generation, game_version = _ornithe_target(mc_version)
    mc_enc = urllib.parse.quote(game_version, safe="")
    loader_enc = urllib.parse.quote(loader_version, safe="")
    profile_url = (
        f"{_ORNITHE_META_API}/versions/{_gen_path(generation)}fabric-loader/"
        f"{mc_enc}/{loader_enc}/profile/json"
    )
    profile_id = _predict_profile_id(mc_version, loader_version)
    target_dir = os.path.join(fake_mc_dir, "versions", profile_id)
    os.makedirs(target_dir, exist_ok=True)
    target_file = os.path.join(target_dir, f"{profile_id}.json")

    try:
        profile = HttpClient(timeout=30.0).get_json(profile_url)
    except HttpClientError as exc:
        raise DownloadFailed(f"Ornithe metadata installation failed: {exc}") from exc

    if not isinstance(profile, dict):
        raise DownloadFailed(
            f"Ornithe profile metadata for {game_version} was not a JSON object"
        )

    libraries = profile.get("libraries")
    if not isinstance(libraries, list):
        libraries = []
    extras = list(_EXTRA_PROFILE_LIBRARIES)
    if _needs_legacy_common_libraries(mc_version):
        extras.extend(_LEGACY_COMMON_LIBRARIES)
    present = {
        str(lib.get("name", "")).rsplit(":", 1)[0]
        for lib in libraries
        if isinstance(lib, dict) and lib.get("name")
    }
    for extra in extras:
        if extra["name"].rsplit(":", 1)[0] not in present:
            libraries.append(dict(extra))
    profile["libraries"] = libraries

    try:
        with open(target_file, "w", encoding="utf-8") as fp:
            json.dump(profile, fp, indent=2)
    except OSError as exc:
        raise DownloadFailed(f"Ornithe metadata installation failed: {exc}") from exc


SPEC = LoaderSpec(
    name="ornithe",
    display_name="Ornithe",
    resolve_installer_url=_resolve_installer_url,
    build_cli_args=_build_cli_args,
    predict_profile_id=_predict_profile_id,
    fallback_install=_metadata_install,
    metadata_only=True,
)

__all__ = ["SPEC"]
