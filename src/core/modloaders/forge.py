from __future__ import annotations

from core.modloaders._endpoints import FORGE_MAVEN_METADATA_API
from core.modloaders._http import fetch_maven_metadata_versions
from core.modloaders._versions import loader_version_sort_key
from core.modloaders.forge_legacy import (
    get_legacy_forge_entry,
    get_legacy_forge_versions_for_mc,
)

FORGE_MODLOADER_DEPENDENT_VERSIONS: frozenset[str] = frozenset(
    {"1.1", "1.2.3", "1.2.4"}
)

__all__ = [
    "FORGE_MODLOADER_DEPENDENT_VERSIONS",
    "fetch_forge_versions",
    "forge_requires_modloader",
    "get_forge_artifact_urls",
    "get_forge_download_spec",
    "get_forge_installer_url",
    "get_forge_versions_for_mc",
]


def fetch_forge_versions() -> list[str] | None:
    return fetch_maven_metadata_versions(FORGE_MAVEN_METADATA_API, "forge", "Forge")


def get_forge_versions_for_mc(mc_version: str) -> list[dict[str, str]]:
    matching: list[dict[str, str]] = []
    seen: set[str] = set()

    # ---- self-hosted manifest (beta-era / non-maven Forge) ----------------
    for entry in get_legacy_forge_versions_for_mc(mc_version):
        v_forge = str(entry.get("loader_version") or "").strip()
        if not v_forge or v_forge in seen:
            continue
        seen.add(v_forge)
        matching.append(
            {
                "mc_version": str(entry.get("mc_version") or mc_version),
                "forge_version": v_forge,
                "full_version": f"{mc_version}-{v_forge}",
                "source": "manifest",
            }
        )

    # ---- official Forge maven --------------------------------------------
    versions = fetch_forge_versions()
    for version_str in versions or []:
        if "-" not in version_str:
            continue
        v_mc, v_forge = version_str.rsplit("-", 1)
        if v_mc == mc_version and v_forge not in seen:
            seen.add(v_forge)
            matching.append(
                {
                    "mc_version": v_mc,
                    "forge_version": v_forge,
                    "full_version": version_str,
                    "source": "maven",
                }
            )

    matching.sort(
        key=lambda item: loader_version_sort_key(item.get("forge_version", "")),
        reverse=True,
    )
    return matching


def forge_requires_modloader(mc_version: str, forge_version: str = "") -> bool:
    if str(mc_version or "").strip() in FORGE_MODLOADER_DEPENDENT_VERSIONS:
        return True
    entry = get_legacy_forge_entry(mc_version, forge_version) if forge_version else None
    return bool(entry and entry.get("requires_modloader"))


def get_forge_download_spec(mc_version: str, forge_version: str) -> dict | None:
    entry = get_legacy_forge_entry(mc_version, forge_version)
    if not entry:
        return None
    return {
        "download_url": entry.get("download_url", ""),
        "sha256": entry.get("sha256", ""),
        "download_kind": entry.get("download_kind", "direct"),
        "archive_type": entry.get("archive_type", "zip"),
        "file_name": entry.get("file_name", ""),
        "requires_modloader": bool(entry.get("requires_modloader")),
        "modloader_version": entry.get("modloader_version", ""),
    }


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
