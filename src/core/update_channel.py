from __future__ import annotations

import os
import re
import threading


__all__ = [
    "CHANNEL_STABLE",
    "CHANNEL_SNAPSHOT",
    "VALID_CHANNELS",
    "normalize_channel",
    "channel_for_tag",
    "read_build_channel",
    "read_channel_preference",
    "write_channel_preference",
    "resolve_channel",
    "prefers_snapshots",
]


CHANNEL_STABLE = "stable"
CHANNEL_SNAPSHOT = "snapshot"
VALID_CHANNELS = (CHANNEL_STABLE, CHANNEL_SNAPSHOT)

_PREFERENCE_FILENAME = "update_channel"

_TAG_CHANNELS = {
    "r": CHANNEL_STABLE,
    "s": CHANNEL_SNAPSHOT,
    "b": CHANNEL_SNAPSHOT,
}

_PRE_SUFFIX_RE = re.compile(r"[-_.]pre\.?\d*$")

_IO_LOCK = threading.RLock()


def _default_project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _base_dir() -> str:
    from core.settings.paths import get_base_dir

    return get_base_dir()


def _preference_path() -> str:
    return os.path.join(_base_dir(), _PREFERENCE_FILENAME)


def normalize_channel(value) -> str | None:
    channel = str(value or "").strip().lower()
    if channel in VALID_CHANNELS:
        return channel
    if channel in {"beta", "prerelease", "pre-release", "unstable"}:
        return CHANNEL_SNAPSHOT
    if channel in {"release", "stable-only"}:
        return CHANNEL_STABLE
    return None


def channel_for_tag(tag) -> str | None:
    text = str(tag or "").strip().lower()
    if text.startswith("v") and len(text) > 1:
        text = text[1:]
    if not text:
        return None
    if _PRE_SUFFIX_RE.search(text):
        return CHANNEL_SNAPSHOT
    return _TAG_CHANNELS.get(text[0] if text[0].isalpha() else None)


def read_build_channel(project_root: str | None = None) -> str | None:
    root = project_root or _default_project_root()
    try:
        with open(os.path.join(root, "version.dat"), "r", encoding="utf-8") as handle:
            return channel_for_tag(handle.read())
    except Exception:
        return None


def read_channel_preference() -> str | None:
    try:
        with open(_preference_path(), "r", encoding="utf-8") as handle:
            return normalize_channel(handle.read())
    except Exception:
        return None


def write_channel_preference(value) -> bool:
    channel = normalize_channel(value)
    if channel is None:
        return False
    with _IO_LOCK:
        try:
            path = _preference_path()
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(channel)
            os.replace(tmp, path)
            return True
        except Exception:
            return False


def resolve_channel(project_root: str | None = None) -> str:
    with _IO_LOCK:
        preference = read_channel_preference()
        if preference is not None:
            return preference

        seeded = read_build_channel(project_root) or CHANNEL_STABLE
        write_channel_preference(seeded)
        return seeded


def prefers_snapshots(project_root: str | None = None) -> bool:
    return resolve_channel(project_root) == CHANNEL_SNAPSHOT
