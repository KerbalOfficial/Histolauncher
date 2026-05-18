from __future__ import annotations

import threading
from typing import Any, Dict


__all__ = [
    "STATE",
    "TEXTURES_API_HOSTNAME",
    "MODEL_CACHE_TTL_SECONDS",
    "CAPE_CACHE_TTL_SECONDS",
    "TEXTURE_METADATA_CACHE_TTL_SECONDS",
    "HISTOLAUNCHER_TEXTURE_METADATA_TTL_SECONDS",
    "TEXTURE_PROP_CACHE_TTL_SECONDS",
    "SESSION_JOIN_TTL_SECONDS",
]


TEXTURES_API_HOSTNAME = "textures.histolauncher.org"

MODEL_CACHE_TTL_SECONDS = 60
CAPE_CACHE_TTL_SECONDS = 60
TEXTURE_METADATA_CACHE_TTL_SECONDS = 600
HISTOLAUNCHER_TEXTURE_METADATA_TTL_SECONDS = 60
TEXTURE_PROP_CACHE_TTL_SECONDS = 60
SESSION_JOIN_TTL_SECONDS = 300


class _YggdrasilState:
    def __init__(self) -> None:
        self.model_cache: Dict[str, Dict[str, Any]] = {}
        self.model_cache_lock: threading.Lock = threading.Lock()
        self.cape_cache: Dict[str, Dict[str, Any]] = {}
        self.cape_cache_lock: threading.Lock = threading.Lock()
        self.texture_metadata_cache: Dict[str, Dict[str, Any]] = {}
        self.texture_metadata_lock: threading.Lock = threading.Lock()
        self.texture_metadata_inflight: Dict[str, threading.Event] = {}
        self.texture_metadata_inflight_lock: threading.Lock = threading.Lock()
        self.texture_prop_cache: Dict[str, Dict[str, Any]] = {}
        self.texture_prop_cache_lock: threading.Lock = threading.Lock()
        self.session_join_cache: Dict[str, Dict[str, Any]] = {}
        self.session_join_cache_lock: threading.Lock = threading.Lock()
        self.uuid_name_cache: Dict[str, str] = {}
        self.uuid_name_cache_lock: threading.Lock = threading.Lock()

    def reset(self) -> None:
        with self.model_cache_lock:
            self.model_cache.clear()
        with self.cape_cache_lock:
            self.cape_cache.clear()
        with self.texture_metadata_lock:
            self.texture_metadata_cache.clear()
        with self.texture_metadata_inflight_lock:
            self.texture_metadata_inflight.clear()
        with self.texture_prop_cache_lock:
            self.texture_prop_cache.clear()
        with self.session_join_cache_lock:
            self.session_join_cache.clear()
        with self.uuid_name_cache_lock:
            self.uuid_name_cache.clear()


STATE = _YggdrasilState()
