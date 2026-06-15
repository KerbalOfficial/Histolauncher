from __future__ import annotations

from typing import Final

FABRIC_META_API: Final[str] = "https://meta.fabricmc.net/v2"
BABRIC_META_API: Final[str] = "https://meta.babric.glass-launcher.net/v2"
LEGACY_FABRIC_META_API: Final[str] = "https://meta.legacyfabric.net/v2"
ORNITHE_META_API: Final[str] = "https://meta.ornithemc.net/v3"
QUILT_META_API: Final[str] = "https://meta.quiltmc.org/v3"

LITELOADER_VERSIONS_MANIFEST_URL: Final[str] = (
    "https://dl.liteloader.com/versions/versions.json"
)
LITELOADER_MAVEN_BASE: Final[str] = "https://dl.liteloader.com/versions/"

FORGE_MAVEN_METADATA_API: Final[str] = (
    "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
)
NEOFORGE_MAVEN_METADATA_API: Final[str] = (
    "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
)

RISUGAMI_MODLOADER_MANIFEST_URL: Final[str] = (
    "https://manifest.histolauncher.org/modloader/risugami_modloader.json"
)

FORGE_LEGACY_MANIFEST_URL: Final[str] = (
    "https://manifest.histolauncher.org/modloader/legacy_forge.json"
)

SUPPORTED_LOADER_TYPES: Final[tuple[str, ...]] = (
    "fabric",
    "legacyfabric",
    "babric",
    "ornithe",
    "forge",
    "liteloader",
    "modloader",
    "neoforge",
    "quilt",
)

LOADER_DISPLAY_NAMES: Final[dict[str, str]] = {
    "fabric": "Fabric",
    "legacyfabric": "Legacy Fabric",
    "babric": "Babric",
    "ornithe": "Ornithe",
    "forge": "Forge",
    "liteloader": "LiteLoader",
    "modloader": "ModLoader",
    "neoforge": "NeoForge",
    "quilt": "Quilt",
}
