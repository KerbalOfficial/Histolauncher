from __future__ import annotations

from core.modloaders._endpoints import NEOFORGE_MAVEN_METADATA_API
from core.modloaders._http import fetch_maven_metadata_versions
from core.modloaders._versions import (
    loader_version_is_stable,
    loader_version_sort_key,
    neoforge_version_matches_mc,
)

__all__ = [
    "fetch_neoforge_versions",
    "get_neoforge_artifact_urls",
    "get_neoforge_installer_url",
    "get_neoforge_versions_for_mc",
]


def fetch_neoforge_versions() -> list[str] | None:
    return fetch_maven_metadata_versions(NEOFORGE_MAVEN_METADATA_API, "neoforge", "NeoForge")


def get_neoforge_versions_for_mc(mc_version: str) -> list[dict[str, str | bool]]:
    versions = fetch_neoforge_versions()
    if not versions:
        return []

    matching: list[dict[str, str | bool]] = []
    for version_str in versions:
        if neoforge_version_matches_mc(version_str, mc_version):
            matching.append(
                {
                    "mc_version": mc_version,
                    "neoforge_version": version_str,
                    "full_version": version_str,
                    "stable": loader_version_is_stable(version_str),
                }
            )

    matching.sort(
        key=lambda item: loader_version_sort_key(str(item.get("neoforge_version", ""))),
        reverse=True,
    )
    return matching


def get_neoforge_artifact_urls(mc_version: str, neoforge_version: str) -> list[str]:
    del mc_version
    version = str(neoforge_version or "").strip()
    if not version:
        return []

    maven_root = (
        f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{version}"
    )
    return [f"{maven_root}/neoforge-{version}-installer.jar"]


def get_neoforge_installer_url(mc_version: str, neoforge_version: str) -> str | None:
    artifact_urls = get_neoforge_artifact_urls(mc_version, neoforge_version)
    for url in artifact_urls:
        if url.endswith("-installer.jar"):
            return url
    return artifact_urls[0] if artifact_urls else None
