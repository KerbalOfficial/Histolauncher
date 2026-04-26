from __future__ import annotations

import os
import threading
from typing import Any, Final


def _default_username() -> str:
    return "Player" + str(os.getpid() % 10000)


DEFAULTS: Final[dict[str, dict[str, str]]] = {
    "account": {
        "username": _default_username(),
        "account_type": "Local",
    },
    "client": {
        "min_ram": "2048M",
        "max_ram": "4096M",
        "extra_jvm_args": "",
        "selected_version": "",
        "favorite_versions": "",
        "storage_directory": "global",
        "custom_storage_directory": "",
    },
    "mods": {
        "allow_override_classpath_all_modloaders": "0",
    },
    "launcher": {
        "java_path": "auto",
        "url_proxy": "",
        "low_data_mode": "0",
        "fast_download": "0",
        "show_third_party_versions": "0",
        "ygg_port": "25565",
        "versions_view": "grid",
        "addons_view": "grid",
        "worlds_view": "grid",
    },
}

DEPRECATED_KEYS: Final[frozenset[str]] = frozenset({"signature_hash"})

MAX_PROFILE_NAME_LEN: Final[int] = 32
MAX_PROFILE_ID_LEN: Final[int] = 48
PROFILE_ADD_SENTINEL: Final[str] = "__add_new_profile__"
PROFILE_SCOPES: Final[frozenset[str]] = frozenset({"settings", "versions", "addons"})

VALID_STORAGE_DIRECTORY_MODES: Final[frozenset[str]] = frozenset(
    {"global", "version", "custom"}
)

META_WRITE_LOCK: Final[threading.Lock] = threading.Lock()


def all_default_keys() -> set[str]:
    keys: set[str] = set()
    for section in DEFAULTS.values():
        keys.update(section)
    return keys


def merged_defaults() -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for section in DEFAULTS.values():
        merged.update(section)
    return merged
