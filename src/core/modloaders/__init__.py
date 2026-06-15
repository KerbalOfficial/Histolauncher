from core.modloaders._endpoints import (
    BABRIC_META_API,
    FABRIC_META_API,
    FORGE_MAVEN_METADATA_API,
    LEGACY_FABRIC_META_API,
    LITELOADER_MAVEN_BASE,
    LITELOADER_VERSIONS_MANIFEST_URL,
    LOADER_DISPLAY_NAMES,
    NEOFORGE_MAVEN_METADATA_API,
    ORNITHE_META_API,
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
    FORGE_MODLOADER_DEPENDENT_VERSIONS,
    fetch_forge_versions,
    forge_requires_modloader,
    get_forge_artifact_urls,
    get_forge_download_spec,
    get_forge_installer_url,
    get_forge_versions_for_mc,
)
from core.modloaders.forge_legacy import (
    get_legacy_forge_entry,
    get_legacy_forge_versions_for_mc,
)
from core.modloaders.legacyfabric import (
    fetch_legacyfabric_game_versions,
    fetch_legacyfabric_loader_profile_libraries,
    fetch_legacyfabric_loaders,
    get_legacyfabric_loader_libraries,
    get_legacyfabric_loaders_for_version,
    supports_legacyfabric_mc_version,
)
from core.modloaders.liteloader import (
    LITELOADER_DEFAULT_TWEAK_CLASS,
    get_liteloader_entry,
    get_liteloader_versions_for_mc,
)
from core.modloaders.neoforge import (
    fetch_neoforge_versions,
    get_neoforge_artifact_urls,
    get_neoforge_installer_url,
    get_neoforge_versions_for_mc,
)
from core.modloaders.ornithe import (
    fetch_ornithe_game_versions,
    fetch_ornithe_loader_profile_libraries,
    fetch_ornithe_loaders,
    get_ornithe_loader_libraries,
    get_ornithe_loaders_for_version,
    ornithe_generation,
    resolve_ornithe_game_version,
    supported_ornithe_mc_versions,
    supports_ornithe_mc_version,
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
    # --- endpoints / display ---
    "BABRIC_META_API",
    "FABRIC_META_API",
    "FORGE_MAVEN_METADATA_API",
    "LEGACY_FABRIC_META_API",
    "LITELOADER_DEFAULT_TWEAK_CLASS",
    "LITELOADER_MAVEN_BASE",
    "LITELOADER_VERSIONS_MANIFEST_URL",
    "LOADER_DISPLAY_NAMES",
    "MODLOADER_MANIFEST_CACHE_KEY",
    "NEOFORGE_MAVEN_METADATA_API",
    "ORNITHE_META_API",
    "QUILT_META_API",
    "RISUGAMI_MODLOADER_MANIFEST_URL",
    "SUPPORTED_LOADER_TYPES",
    # --- helpers ---
    "_http_get_json",
    "clear_loader_cache",
    "current_library_os_name",
    "fetch_maven_metadata_versions",
    "loader_version_is_stable",
    "loader_version_sort_key",
    "parse_loader_type",
    # --- fabric ---
    "fetch_fabric_game_versions",
    "fetch_fabric_loader_dependencies",
    "fetch_fabric_loader_profile_libraries",
    "fetch_fabric_loaders",
    "get_fabric_installer_url",
    "get_fabric_loader_libraries",
    "get_fabric_loaders_for_version",
    "supports_fabric_mc_version",
    # --- babric ---
    "fetch_babric_game_versions",
    "fetch_babric_loader_profile_libraries",
    "fetch_babric_loaders",
    "get_babric_loader_libraries",
    "get_babric_loaders_for_version",
    "supports_babric_mc_version",
    # --- legacy fabric ---
    "fetch_legacyfabric_game_versions",
    "fetch_legacyfabric_loader_profile_libraries",
    "fetch_legacyfabric_loaders",
    "get_legacyfabric_loader_libraries",
    "get_legacyfabric_loaders_for_version",
    "supports_legacyfabric_mc_version",
    # --- ornithe ---
    "fetch_ornithe_game_versions",
    "fetch_ornithe_loader_profile_libraries",
    "fetch_ornithe_loaders",
    "get_ornithe_loader_libraries",
    "get_ornithe_loaders_for_version",
    "ornithe_generation",
    "resolve_ornithe_game_version",
    "supported_ornithe_mc_versions",
    "supports_ornithe_mc_version",
    # --- liteloader ---
    "get_liteloader_entry",
    "get_liteloader_versions_for_mc",
    # --- quilt ---
    "fetch_quilt_game_versions",
    "fetch_quilt_loader_profile_libraries",
    "fetch_quilt_loaders",
    "get_quilt_installer_url",
    "get_quilt_loader_libraries",
    "get_quilt_loaders_for_version",
    # --- forge ---
    "FORGE_MODLOADER_DEPENDENT_VERSIONS",
    "fetch_forge_versions",
    "forge_requires_modloader",
    "get_forge_artifact_urls",
    "get_forge_download_spec",
    "get_forge_installer_url",
    "get_forge_versions_for_mc",
    "get_legacy_forge_entry",
    "get_legacy_forge_versions_for_mc",
    # --- neoforge ---
    "fetch_neoforge_versions",
    "get_neoforge_artifact_urls",
    "get_neoforge_installer_url",
    "get_neoforge_versions_for_mc",
    # --- risugami modloader ---
    "get_modloader_versions_for_mc",
    # --- cross-loader summary ---
    "list_supported_mc_versions",
]
