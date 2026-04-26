from core.modloaders._endpoints import (
    BABRIC_META_API,
    FABRIC_META_API,
    FORGE_MAVEN_METADATA_API,
    LOADER_DISPLAY_NAMES,
    NEOFORGE_MAVEN_METADATA_API,
    QUILT_META_API,
    RISUGAMI_MODLOADER_MANIFEST_URL,
    SUPPORTED_LOADER_TYPES,
)
from core.modloaders._http import _http_get_json, fetch_maven_metadata_versions
from core.modloaders._versions import (
    current_library_os_name,
    loader_version_is_stable,
    loader_version_sort_key,
    parse_loader_type,
)
from core.modloaders.babric import (
    fetch_babric_game_versions,
    fetch_babric_loader_profile_libraries,
    fetch_babric_loaders,
    get_babric_loader_libraries,
    get_babric_loaders_for_version,
    supports_babric_mc_version,
)
from core.modloaders.cache import clear_loader_cache
from core.modloaders.fabric import (
    fetch_fabric_game_versions,
    fetch_fabric_loader_dependencies,
    fetch_fabric_loader_profile_libraries,
    fetch_fabric_loaders,
    get_fabric_installer_url,
    get_fabric_loader_libraries,
    get_fabric_loaders_for_version,
    supports_fabric_mc_version,
)
from core.modloaders.forge import (
    fetch_forge_versions,
    get_forge_artifact_urls,
    get_forge_installer_url,
    get_forge_versions_for_mc,
)
from core.modloaders.neoforge import (
    fetch_neoforge_versions,
    get_neoforge_artifact_urls,
    get_neoforge_installer_url,
    get_neoforge_versions_for_mc,
)
from core.modloaders.quilt import (
    fetch_quilt_game_versions,
    fetch_quilt_loader_profile_libraries,
    fetch_quilt_loaders,
    get_quilt_installer_url,
    get_quilt_loader_libraries,
    get_quilt_loaders_for_version,
)
from core.modloaders.risugami import (
    MODLOADER_MANIFEST_CACHE_KEY,
    get_modloader_versions_for_mc,
)
from core.modloaders.summary import list_supported_mc_versions

__all__ = [
    # Endpoints / display
    "BABRIC_META_API",
    "FABRIC_META_API",
    "FORGE_MAVEN_METADATA_API",
    "LOADER_DISPLAY_NAMES",
    "MODLOADER_MANIFEST_CACHE_KEY",
    "NEOFORGE_MAVEN_METADATA_API",
    "QUILT_META_API",
    "RISUGAMI_MODLOADER_MANIFEST_URL",
    "SUPPORTED_LOADER_TYPES",
    # Helpers
    "_http_get_json",
    "clear_loader_cache",
    "current_library_os_name",
    "fetch_maven_metadata_versions",
    "loader_version_is_stable",
    "loader_version_sort_key",
    "parse_loader_type",
    # Fabric
    "fetch_fabric_game_versions",
    "fetch_fabric_loader_dependencies",
    "fetch_fabric_loader_profile_libraries",
    "fetch_fabric_loaders",
    "get_fabric_installer_url",
    "get_fabric_loader_libraries",
    "get_fabric_loaders_for_version",
    "supports_fabric_mc_version",
    # Babric
    "fetch_babric_game_versions",
    "fetch_babric_loader_profile_libraries",
    "fetch_babric_loaders",
    "get_babric_loader_libraries",
    "get_babric_loaders_for_version",
    "supports_babric_mc_version",
    # Quilt
    "fetch_quilt_game_versions",
    "fetch_quilt_loader_profile_libraries",
    "fetch_quilt_loaders",
    "get_quilt_installer_url",
    "get_quilt_loader_libraries",
    "get_quilt_loaders_for_version",
    # Forge
    "fetch_forge_versions",
    "get_forge_artifact_urls",
    "get_forge_installer_url",
    "get_forge_versions_for_mc",
    # NeoForge
    "fetch_neoforge_versions",
    "get_neoforge_artifact_urls",
    "get_neoforge_installer_url",
    "get_neoforge_versions_for_mc",
    # Risugami ModLoader
    "get_modloader_versions_for_mc",
    # Cross-loader summary
    "list_supported_mc_versions",
]
