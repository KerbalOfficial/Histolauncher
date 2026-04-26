from __future__ import annotations

import time
from typing import Any, Generic, TypeVar

from core.constants import LOADER_CACHE_TTL_S

__all__ = ["TTLCache", "clear_loader_cache", "register_cache"]


T = TypeVar("T")


class TTLCache(Generic[T]):
    def __init__(self, *, ttl_seconds: float = LOADER_CACHE_TTL_S) -> None:
        self._ttl = float(ttl_seconds)
        self._store: dict[str, tuple[float, T]] = {}

    def get(self, key: str) -> T | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if (time.time() - ts) > self._ttl:
            return None
        return value

    def set(self, key: str, value: T) -> None:
        self._store[key] = (time.time(), value)

    def pop(self, key: str) -> T | None:
        entry = self._store.pop(key, None)
        return entry[1] if entry else None

    def clear(self) -> None:
        self._store.clear()


_registered: list[TTLCache[Any]] = []


def register_cache(cache: TTLCache[Any]) -> TTLCache[Any]:
    _registered.append(cache)
    return cache


def clear_loader_cache() -> None:
    for cache in _registered:
        cache.clear()
