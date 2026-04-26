from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Final

from core.logger import colorize_log

__all__ = [
    "DISCORD_CLIENT_ID",
    "DiscordRpcManager",
    "RPC_MAX_CONNECT_ATTEMPTS",
    "RPC_RETRY_INTERVAL_SECONDS",
    "RPC_UPDATE_INTERVAL_SECONDS",
    "set_game_presence",
    "set_install_presence",
    "set_launcher_presence",
    "set_launcher_version",
    "start_discord_rpc",
    "stop_discord_rpc",
    "update_discord_presence",
]


DISCORD_CLIENT_ID: Final[str] = "1479933973114257500"
RPC_RETRY_INTERVAL_SECONDS: Final[int] = 3
RPC_UPDATE_INTERVAL_SECONDS: Final[int] = 5
RPC_MAX_CONNECT_ATTEMPTS: Final[int] = 5

_MAX_FIELD_LEN: Final[int] = 128
_REPEATED_ERROR_THROTTLE_S: Final[float] = 30.0


try:
    from pypresence import Presence as _Presence  # type: ignore[import-untyped]
except Exception as _import_error:  # noqa: BLE001
    _Presence = None  # type: ignore[assignment]
    _PYPRESENCE_IMPORT_ERROR: Exception | None = _import_error
else:
    _PYPRESENCE_IMPORT_ERROR = None


def _sanitize_text(value: object, fallback: str) -> str:
    text = str(value or fallback).strip()
    if not text:
        text = fallback
    return text[:_MAX_FIELD_LEN]


def _format_version_name(version_identifier: object) -> str:
    value = str(version_identifier or "").replace("\\", "/").strip("/")
    if not value:
        return "Minecraft"
    if "/" in value:
        category, folder = value.split("/", 1)
        return f"{folder} ({category.title()})"[:_MAX_FIELD_LEN]
    return value[:_MAX_FIELD_LEN]


def _format_loader_name(loader_type: object, loader_version: object = None) -> str | None:
    lt = str(loader_type or "").strip().lower()
    if not lt:
        return None
    try:
        from core.modloaders import LOADER_DISPLAY_NAMES  # noqa: PLC0415

        base = LOADER_DISPLAY_NAMES.get(lt, lt.capitalize())
    except Exception:  # noqa: BLE001
        base = lt.capitalize()

    version = str(loader_version or "").strip()
    if version:
        return f"{base} {version}"[:_MAX_FIELD_LEN]
    return base[:_MAX_FIELD_LEN]


@dataclass
class _PresenceState:
    state: str = "Browsing launcher"
    details: str = "Histolauncher"
    start: int = field(default_factory=lambda: int(time.time()))


class DiscordRpcManager:
    def __init__(self, *, client_id: str = DISCORD_CLIENT_ID) -> None:
        self._client_id = client_id
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._rpc: Any | None = None
        self._connected = False
        self._connect_attempts = 0
        self._disabled = False
        self._launcher_version: str | None = None
        self._logged_successful_update = False

        self._last_error: str | None = None
        self._last_error_at: float = 0.0

        self._desired = _PresenceState(details=self._format_launcher_version())

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def set_launcher_version(self, version: object) -> None:
        value = str(version or "").strip()
        with self._lock:
            self._launcher_version = value or None
            self._desired.details = self._format_launcher_version()

    def update_presence(
        self,
        *,
        state: str = "Browsing launcher",
        details: str = "",
        start: float | None = None,
    ) -> None:
        with self._lock:
            fallback_details = self._format_launcher_version()
            self._desired.state = _sanitize_text(state, "Browsing launcher")
            self._desired.details = _sanitize_text(details, fallback_details)
            self._desired.start = int(start or time.time())

    def set_launcher_presence(self, *, state: str = "Browsing launcher") -> None:
        self.update_presence(state=state, details=self._format_launcher_version(), start=time.time())

    def set_install_presence(
        self,
        version_identifier: object,
        *,
        progress_percent: float | None = None,
        start_time: float | None = None,
        loader_type: str | None = None,
        loader_version: str | None = None,
    ) -> None:
        version_name = _format_version_name(version_identifier)
        loader_name = _format_loader_name(loader_type, loader_version)

        pct: int | None = None
        if progress_percent is not None:
            try:
                pct = max(0, min(100, int(progress_percent)))
            except (TypeError, ValueError):
                pct = None

        if loader_name:
            base = f"Installing {version_name} ({loader_name})"
        else:
            base = f"Downloading {version_name}"

        state = base if pct is None else f"{base} {pct}%"
        self.update_presence(
            state=state,
            details=self._format_launcher_version(),
            start=start_time or time.time(),
        )

    def set_game_presence(
        self,
        version_identifier: object,
        *,
        start_time: float | None = None,
        phase: str = "Playing",
        loader_type: str | None = None,
        loader_version: str | None = None,
    ) -> None:
        version_name = _format_version_name(version_identifier)
        phase_text = "Launching" if phase == "Launching" else "Playing"
        loader_name = _format_loader_name(loader_type, loader_version)

        suffix = f" ({loader_name})" if loader_name else ""
        state = f"{phase_text} {version_name}{suffix}"

        self.update_presence(
            state=state,
            details=self._format_launcher_version(),
            start=start_time or time.time(),
        )

    def start(self) -> None:
        if _Presence is None:
            if _PYPRESENCE_IMPORT_ERROR is not None:
                print(
                    colorize_log(
                        f"[discord_rpc] pypresence unavailable: {_PYPRESENCE_IMPORT_ERROR}"
                    )
                )
            return

        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="discord-rpc")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3)
        self._close_rpc(clear=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _format_launcher_version(self) -> str:
        version = str(self._launcher_version or "").strip()
        return (version or "Histolauncher")[:_MAX_FIELD_LEN]

    def _build_payload(self) -> dict[str, str | int]:
        with self._lock:
            snapshot = _PresenceState(
                state=self._desired.state,
                details=self._desired.details,
                start=self._desired.start,
            )
        return {
            "name": "Histolauncher",
            "state": _sanitize_text(snapshot.state, "Browsing launcher"),
            "details": _sanitize_text(snapshot.details, self._format_launcher_version()),
            "start": int(snapshot.start or int(time.time())),
        }

    def _close_rpc(self, *, clear: bool) -> None:
        if self._rpc is not None:
            if clear:
                try:
                    self._rpc.clear()
                except Exception:  # noqa: BLE001 — pypresence raises various
                    pass
            try:
                self._rpc.close()
            except Exception:  # noqa: BLE001
                pass
        self._rpc = None
        self._connected = False

    def _log_connect_failure(self, exc: BaseException) -> None:
        message = str(exc).strip() or exc.__class__.__name__
        now = time.time()
        if message != self._last_error or (now - self._last_error_at) >= _REPEATED_ERROR_THROTTLE_S:
            print(colorize_log(f"[discord_rpc] Connect failed: {message}"))
            self._last_error = message
            self._last_error_at = now

    def _connect(self) -> bool:
        if self._disabled or _Presence is None:
            return False
        try:
            client = _Presence(self._client_id)
            client.connect()
        except Exception as exc:  # noqa: BLE001 — pypresence variants
            self._close_rpc(clear=False)
            self._log_connect_failure(exc)
            self._connect_attempts += 1
            if self._connect_attempts >= RPC_MAX_CONNECT_ATTEMPTS:
                self._disabled = True
                print(
                    colorize_log(
                        f"[discord_rpc] Disabled after {RPC_MAX_CONNECT_ATTEMPTS} "
                        "failed connect attempts; will stop retrying."
                    )
                )
                self._stop_event.set()
            return False

        self._rpc = client
        self._connected = True
        self._last_error = None
        self._logged_successful_update = False
        self._connect_attempts = 0
        print(colorize_log("[discord_rpc] Connected to Discord client"))
        return True

    def _push_presence(self) -> bool:
        if not self._connected or self._rpc is None:
            return False
        payload = self._build_payload()
        try:
            self._rpc.update(**payload)
        except Exception as exc:  # noqa: BLE001
            print(colorize_log(f"[discord_rpc] Update failed: {exc}"))
            self._logged_successful_update = False
            self._close_rpc(clear=False)
            return False

        if not self._logged_successful_update:
            print(
                colorize_log(
                    "[discord_rpc] Presence update accepted: "
                    f"details='{payload['details']}', state='{payload['state']}'"
                )
            )
            self._logged_successful_update = True
        return True

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            if not self._connected and not self._connect():
                self._stop_event.wait(RPC_RETRY_INTERVAL_SECONDS)
                continue
            self._push_presence()
            self._stop_event.wait(RPC_UPDATE_INTERVAL_SECONDS)
        self._close_rpc(clear=True)


# ---------------------------------------------------------------------------
# Module-level singleton + thin wrappers.
# ---------------------------------------------------------------------------

_manager = DiscordRpcManager()


def start_discord_rpc() -> None:
    _manager.start()


def stop_discord_rpc() -> None:
    _manager.stop()


def set_launcher_version(version: object) -> None:
    _manager.set_launcher_version(version)


def update_discord_presence(
    state: str = "Browsing launcher",
    details: str = "",
    start: float | None = None,
) -> None:
    _manager.update_presence(state=state, details=details, start=start)


def set_launcher_presence(state: str = "Browsing launcher") -> None:
    _manager.set_launcher_presence(state=state)


def set_install_presence(
    version_identifier: object,
    progress_percent: float | None = None,
    start_time: float | None = None,
    loader_type: str | None = None,
    loader_version: str | None = None,
) -> None:
    _manager.set_install_presence(
        version_identifier,
        progress_percent=progress_percent,
        start_time=start_time,
        loader_type=loader_type,
        loader_version=loader_version,
    )


def set_game_presence(
    version_identifier: object,
    start_time: float | None = None,
    phase: str = "Playing",
    loader_type: str | None = None,
    loader_version: str | None = None,
) -> None:
    _manager.set_game_presence(
        version_identifier,
        start_time=start_time,
        phase=phase,
        loader_type=loader_type,
        loader_version=loader_version,
    )
