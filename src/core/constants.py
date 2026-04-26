from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

#: Default timeout (seconds) for short JSON / metadata requests.
HTTP_DEFAULT_TIMEOUT_S: Final[float] = 6.0

#: Timeout (seconds) for streaming binary downloads.
HTTP_DOWNLOAD_TIMEOUT_S: Final[float] = 30.0

#: How many attempts :class:`core.http_client.HttpClient` makes before raising.
HTTP_RETRY_ATTEMPTS: Final[int] = 3

#: Backoff (seconds) between retry attempts (multiplied by attempt index).
HTTP_RETRY_BACKOFF_S: Final[float] = 0.5

#: ``User-Agent`` header sent on every outbound request.
HTTP_USER_AGENT: Final[str] = "Histolauncher/1.0"

# ---------------------------------------------------------------------------
# Cache TTLs (seconds)
# ---------------------------------------------------------------------------

#: How long the Mojang / OmniArchive manifest stays cached in memory.
MANIFEST_CACHE_TTL_S: Final[float] = 300.0

#: Modloader API cache (Fabric / Quilt / Forge / NeoForge versions).
LOADER_CACHE_TTL_S: Final[float] = 3600.0

#: Java runtime auto-detection cache (rescanning ``PATH``/registry is slow).
JAVA_DETECT_CACHE_TTL_S: Final[float] = 30.0

#: Installed-version directory scan cache.
VERSION_SCAN_CACHE_TTL_S: Final[float] = 2.0

# ---------------------------------------------------------------------------
# ZIP safety limits — see :mod:`core.zip_utils`.
# ---------------------------------------------------------------------------

ZIP_MAX_ENTRIES: Final[int] = 20_000
ZIP_MAX_FILE_BYTES: Final[int] = 512 * 1024 * 1024            # 512 MiB
ZIP_MAX_TOTAL_BYTES: Final[int] = 4 * 1024 * 1024 * 1024      # 4 GiB

# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------

#: Read chunk size used by :func:`core.downloader.download_file`.
DOWNLOAD_CHUNK_BYTES: Final[int] = 8 * 1024

#: Default thread-pool size for parallel downloads.
DOWNLOAD_PARALLEL_WORKERS: Final[int] = 15

# ---------------------------------------------------------------------------
# Launch pipeline
# ---------------------------------------------------------------------------

#: How long ``launch_version`` waits for a stable JVM before falling back to
#: the next Java candidate.
LAUNCH_STABILITY_TIMEOUT_S: Final[float] = 8.0

# ---------------------------------------------------------------------------
# Yggdrasil / textures
# ---------------------------------------------------------------------------

#: Maximum number of texture metadata entries kept in memory.
YGG_TEXTURE_CACHE_MAX_ITEMS: Final[int] = 1024

#: Maximum number of recent ``hasJoined`` session IDs retained.
YGG_SESSION_JOIN_CACHE_MAX: Final[int] = 1024

#: TTL (seconds) for the ``hasJoined`` session cache.
YGG_SESSION_JOIN_TTL_S: Final[float] = 60.0

# ---------------------------------------------------------------------------
# API request validation (see ``server/api/``)
# ---------------------------------------------------------------------------

MAX_VERSION_ID_LENGTH: Final[int] = 64
MAX_CATEGORY_LENGTH: Final[int] = 64
MAX_USERNAME_LENGTH: Final[int] = 16
MAX_LOADER_VERSION_LENGTH: Final[int] = 64
MAX_MOD_SLUG_LENGTH: Final[int] = 128
MAX_MODPACK_SLUG_LENGTH: Final[int] = 128
MAX_VERSION_LABEL_LENGTH: Final[int] = 128
MAX_FILENAME_LENGTH: Final[int] = 255
MAX_ARCHIVE_SUBFOLDER_LENGTH: Final[int] = 512
MAX_VERSION_DISPLAY_NAME_LENGTH: Final[int] = 128
MAX_VERSION_IMAGE_URL_LENGTH: Final[int] = 2048
MAX_VERSION_IMAGE_UPLOAD_BYTES: Final[int] = 10 * 1024 * 1024
MAX_STORAGE_OVERRIDE_PATH_LENGTH: Final[int] = 2048

MAX_VERSIONS_IMPORT_PAYLOAD: Final[int] = 12 * 1024 * 1024 * 1024  # 12 GiB
MAX_MODS_IMPORT_PAYLOAD: Final[int] = 4 * 1024 * 1024 * 1024       # 4 GiB
MAX_MODPACKS_IMPORT_PAYLOAD: Final[int] = 8 * 1024 * 1024 * 1024   # 8 GiB
MAX_WORLDS_IMPORT_PAYLOAD: Final[int] = 512 * 1024 * 1024          # 512 MiB
