from __future__ import annotations

from typing import Final

FABRIC_META_API: Final[str] = "https://meta.fabricmc.net/v2"
BABRIC_META_API: Final[str] = "https://meta.babric.glass-launcher.net/v2"
QUILT_META_API: Final[str] = "https://meta.quiltmc.org/v3"

FORGE_MAVEN_METADATA_API: Final[str] = (
    "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
)
NEOFORGE_MAVEN_METADATA_API: Final[str] = (
    "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
)

RISUGAMI_MODLOADER_MANIFEST_URL: Final[str] = (
    "https://manifest.histolauncher.org/modloader/risugami_modloader.json"
)

SUPPORTED_LOADER_TYPES: Final[tuple[str, ...]] = (
    "fabric",
    "babric",
    "forge",
    "modloader",
    "neoforge",
    "quilt",
)

LOADER_DISPLAY_NAMES: Final[dict[str, str]] = {
    "fabric": "Fabric",
    "babric": "Babric",
    "forge": "Forge",
    "modloader": "ModLoader",
    "neoforge": "NeoForge",
    "quilt": "Quilt",
}
