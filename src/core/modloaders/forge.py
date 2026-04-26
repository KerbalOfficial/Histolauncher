from __future__ import annotations

from core.modloaders._endpoints import FORGE_MAVEN_METADATA_API
from core.modloaders._http import fetch_maven_metadata_versions
from core.modloaders._versions import loader_version_sort_key

__all__ = [
    "fetch_forge_versions",
    "get_forge_artifact_urls",
    "get_forge_installer_url",
    "get_forge_versions_for_mc",
]


def fetch_forge_versions() -> list[str] | None:
    return fetch_maven_metadata_versions(FORGE_MAVEN_METADATA_API, "forge", "Forge")


def get_forge_versions_for_mc(mc_version: str) -> list[dict[str, str]]:
    versions = fetch_forge_versions()
    if not versions:
        return []

    matching: list[dict[str, str]] = []
    for version_str in versions:
        if "-" not in version_str:
            continue
        v_mc, v_forge = version_str.rsplit("-", 1)
        if v_mc == mc_version:
            matching.append(
                {
                    "mc_version": v_mc,
                    "forge_version": v_forge,
                    "full_version": version_str,
                }
            )

    matching.sort(
        key=lambda item: loader_version_sort_key(item.get("forge_version", "")),
        reverse=True,
    )
    return matching


def _is_pre_1_6(version: str) -> bool:
    try:
        parts = (version or "").split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        return major == 1 and minor < 6
    except ValueError:
        return False


def get_forge_artifact_urls(mc_version: str, forge_version: str) -> list[str]:
    base = f"{mc_version}-{forge_version}"
    maven_root = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{base}"

    if _is_pre_1_6(mc_version):
        candidates = [
            f"{maven_root}/forge-{base}-universal.zip",
            f"{maven_root}/forge-{base}-universal.jar",
            f"{maven_root}/forge-{base}-client.zip",
            f"{maven_root}/minecraftforge-universal-{base}.zip",
            f"{maven_root}/minecraftforge-universal-{base}.jar",
            f"{maven_root}/minecraftforge-client-{base}.zip",
            f"{maven_root}/forge-{base}-installer.jar",
        ]
    else:
        candidates = [
            f"{maven_root}/forge-{base}-installer.jar",
            f"{maven_root}/forge-{base}-universal.jar",
            f"{maven_root}/forge-{base}-universal.zip",
            f"{maven_root}/forge-{base}-client.zip",
            f"{maven_root}/minecraftforge-universal-{base}.jar",
            f"{maven_root}/minecraftforge-universal-{base}.zip",
            f"{maven_root}/minecraftforge-client-{base}.zip",
        ]

    seen: set[str] = set()
    deduped: list[str] = []
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped


def get_forge_installer_url(mc_version: str, forge_version: str) -> str | None:
    artifact_urls = get_forge_artifact_urls(mc_version, forge_version)
    for url in artifact_urls:
        if url.endswith("-installer.jar"):
            return url
    return artifact_urls[0] if artifact_urls else None
