from __future__ import annotations

import threading
import time
from typing import Any, Generic, TypeVar

from core.constants import LOADER_CACHE_TTL_S

__all__ = ["TTLCache", "clear_loader_cache", "register_cache"]


T = TypeVar("T")

_DEFAULT_MAX_ENTRIES = 256


class TTLCache(Generic[T]):
    def __init__(
        self,
        *,
        ttl_seconds: float = LOADER_CACHE_TTL_S,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._ttl = float(ttl_seconds)
        self._max_entries = max(1, int(max_entries))
        self._store: dict[str, tuple[float, T]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> T | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, value = entry
            if (time.time() - ts) > self._ttl:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value: T) -> None:
        now = time.time()
        with self._lock:
            self._store[key] = (now, value)
            if len(self._store) > self._max_entries:
                cutoff = now - self._ttl
                expired = [k for k, (ts, _) in self._store.items() if ts < cutoff]
                for k in expired:
                    self._store.pop(k, None)
                if len(self._store) > self._max_entries:
                    overflow = len(self._store) - self._max_entries
                    oldest = sorted(
                        self._store.items(), key=lambda kv: kv[1][0]
                    )[:overflow]
                    for k, _ in oldest:
                        self._store.pop(k, None)

    def pop(self, key: str) -> T | None:
        with self._lock:
            entry = self._store.pop(key, None)
            return entry[1] if entry else None

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_registered: list[TTLCache[Any]] = []


def register_cache(cache: TTLCache[Any]) -> TTLCache[Any]:
    _registered.append(cache)
    return cache


def clear_loader_cache() -> None:
    for cache in _registered:
        cache.clear()
