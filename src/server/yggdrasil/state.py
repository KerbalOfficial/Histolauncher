from __future__ import annotations

import threading
from typing import Any, Dict, Optional


__all__ = [
    "STATE",
    "TEXTURES_API_HOSTNAME",
    "MODEL_CACHE_TTL_SECONDS",
    "CAPE_CACHE_TTL_SECONDS",
    "TEXTURE_METADATA_CACHE_TTL_SECONDS",
    "TEXTURE_PROP_CACHE_TTL_SECONDS",
    "SESSION_JOIN_TTL_SECONDS",
]


TEXTURES_API_HOSTNAME = "textures.histolauncher.org"

MODEL_CACHE_TTL_SECONDS = 60
CAPE_CACHE_TTL_SECONDS = 60
TEXTURE_METADATA_CACHE_TTL_SECONDS = 60
TEXTURE_PROP_CACHE_TTL_SECONDS = 60
SESSION_JOIN_TTL_SECONDS = 300


class _YggdrasilState:
    def __init__(self) -> None:
        self.model_cache: Dict[str, Dict[str, Any]] = {}
        self.cape_cache: Dict[str, Dict[str, Any]] = {}
        self.texture_metadata_cache: Dict[str, Dict[str, Any]] = {}
        self.texture_metadata_lock: threading.Lock = threading.Lock()
        self.texture_metadata_inflight: Dict[str, threading.Event] = {}
        self.texture_prop_cache: Dict[str, Dict[str, Any]] = {}
        self.session_join_cache: Dict[str, Dict[str, Any]] = {}
        self.uuid_name_cache: Dict[str, str] = {}
        self.private_key_cache: Optional[Any] = None

    def reset(self) -> None:
        self.model_cache.clear()
        self.cape_cache.clear()
        self.texture_metadata_cache.clear()
        self.texture_metadata_inflight.clear()
        self.texture_prop_cache.clear()
        self.session_join_cache.clear()
        self.uuid_name_cache.clear()
        self.private_key_cache = None
        self.texture_metadata_lock = threading.Lock()


STATE = _YggdrasilState()
