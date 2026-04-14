# core/discord_rpc.py

import threading
import time

from core.logger import colorize_log

DISCORD_CLIENT_ID = "1479933973114257500"
RPC_RETRY_INTERVAL_SECONDS = 3
RPC_UPDATE_INTERVAL_SECONDS = 5
RPC_MAX_CONNECT_ATTEMPTS = 5

try:
    from pypresence import Presence
except Exception as import_error:
    Presence = None
    _PYPRESENCE_IMPORT_ERROR = import_error
else:
    _PYPRESENCE_IMPORT_ERROR = None

_start_time  = int(time.time())
_rpc = None
_rpc_thread = None
_rpc_connected = False
_stop_event = threading.Event()
_state_lock = threading.Lock()
_launcher_version = None
_last_connect_error = None
_last_connect_error_at = 0.0
_logged_successful_update = False
_rpc_connect_attempts = 0
_rpc_disabled = False


def _sanitize_text(value, fallback):
    text = str(value or fallback).strip()
    if not text:
        text = fallback
    return text[:128]


def _format_version_name(version_identifier):
    value = str(version_identifier or "").replace("\\", "/").strip("/")
    if not value:
        return "Minecraft"

    if "/" in value:
        category, folder = value.split("/", 1)
        return f"{folder} ({category.title()})"[:128]

    return value[:128]


def _format_loader_name(loader_type, loader_version=None):
    lt = str(loader_type or "").strip().lower()
    if not lt:
        return None

    base = lt.capitalize()

    version = str(loader_version or "").strip()
    if version:
        return f"{base} {version}"[:128]
    return base[:128]


def _format_launcher_version():
    version = str(_launcher_version or "").strip()
    if not version:
        return "Histolauncher"
    return f"{version}"[:128]


_desired_presence = {
    "state": "Browsing launcher",
    "details": _format_launcher_version(),
    "start": _start_time,
}


# `_combine_presence_parts` was removed — state strings are now composed
# explicitly to avoid joining launcher version or username into `state`.


def _build_payload():
    with _state_lock:
        snapshot = dict(_desired_presence)

    return {
        "name": "Histolauncher",
        "state": _sanitize_text(snapshot.get("state"), "Browsing launcher"),
        "details": _sanitize_text(snapshot.get("details"), _format_launcher_version()),
        "start": int(snapshot.get("start") or _start_time),
    }


def _close_rpc(clear=False):
    global _rpc, _rpc_connected

    if _rpc:
        try:
            if clear:
                _rpc.clear()
        except Exception:
            pass
        try:
            _rpc.close()
        except Exception:
            pass

    _rpc = None
    _rpc_connected = False


def _log_connect_failure(exc):
    global _last_connect_error, _last_connect_error_at

    message = str(exc).strip() or exc.__class__.__name__
    now = time.time()
    should_log = (
        message != _last_connect_error
        or (now - _last_connect_error_at) >= 30
    )
    if should_log:
        print(colorize_log(f"[discord_rpc] Connect failed: {message}"))
        _last_connect_error = message
        _last_connect_error_at = now


def _connect_rpc():
    global _rpc, _rpc_connected, _last_connect_error, _logged_successful_update, _rpc_connect_attempts, _rpc_disabled

    if _rpc_disabled:
        return False

    if Presence is None:
        if _PYPRESENCE_IMPORT_ERROR is not None:
            print(colorize_log(f"[discord_rpc] Disabled: {_PYPRESENCE_IMPORT_ERROR}"))
        return False

    try:
        client = Presence(DISCORD_CLIENT_ID)
        client.connect()
        _rpc = client
        _rpc_connected = True
        _last_connect_error = None
        _logged_successful_update = False
        _rpc_connect_attempts = 0
        print(colorize_log("[discord_rpc] Connected to Discord client"))
        return True
    except Exception as exc:
        _close_rpc(clear=False)
        _log_connect_failure(exc)

        try:
            _rpc_connect_attempts += 1
        except Exception:
            _rpc_connect_attempts = 1

        if _rpc_connect_attempts >= RPC_MAX_CONNECT_ATTEMPTS:
            _rpc_disabled = True
            print(colorize_log(f"[discord_rpc] Disabled after {RPC_MAX_CONNECT_ATTEMPTS} failed connect attempts; will stop retrying."))
            try:
                _stop_event.set()
            except Exception:
                pass

        return False


def _push_presence():
    global _logged_successful_update

    if not _rpc_connected or _rpc is None:
        return False

    payload = _build_payload()

    try:
        _rpc.update(**payload)
        if not _logged_successful_update:
            print(
                colorize_log(
                    f"[discord_rpc] Presence update accepted: details='{payload['details']}', state='{payload['state']}'"
                )
            )
            _logged_successful_update = True
        return True
    except Exception as exc:
        print(colorize_log(f"[discord_rpc] Update failed: {exc}"))
        _logged_successful_update = False
        _close_rpc(clear=False)
        return False


def _worker():
    while not _stop_event.is_set():
        if not _rpc_connected and not _connect_rpc():
            _stop_event.wait(RPC_RETRY_INTERVAL_SECONDS)
            continue

        _push_presence()
        _stop_event.wait(RPC_UPDATE_INTERVAL_SECONDS)

    _close_rpc(clear=True)


def start_discord_rpc():
    global _rpc_thread

    if Presence is None:
        if _PYPRESENCE_IMPORT_ERROR is not None:
            print(colorize_log(f"[discord_rpc] pypresence unavailable: {_PYPRESENCE_IMPORT_ERROR}"))
        return

    if _rpc_thread and _rpc_thread.is_alive():
        return

    _stop_event.clear()
    _rpc_thread = threading.Thread(target=_worker, daemon=True, name="discord-rpc")
    _rpc_thread.start()


def set_launcher_version(version):
    global _launcher_version
    value = str(version or "").strip()
    _launcher_version = value or None


def update_discord_presence(state="Browsing launcher", details="", start=None):
    with _state_lock:
        _desired_presence["state"] = _sanitize_text(state, "Browsing launcher")
        _desired_presence["details"] = _sanitize_text(details, _format_launcher_version())
        _desired_presence["start"] = int(start or time.time())


def set_launcher_presence(state="Browsing launcher"):
    update_discord_presence(
        state=state,
        details=_format_launcher_version(),
        start=time.time(),
    )


def set_install_presence(
    version_identifier,
    progress_percent=None,
    start_time=None,
    loader_type=None,
    loader_version=None,
):
    version_name = _format_version_name(version_identifier)
    loader_name = _format_loader_name(loader_type, loader_version)

    pct = None
    try:
        if progress_percent is not None:
            pct = max(0, min(100, int(progress_percent)))
    except Exception:
        pct = None

    if loader_name:
        install_info = f"Installing {version_name} ({loader_name})"
    else:
        install_info = f"Downloading {version_name}"

    if pct is None:
        state = install_info
    else:
        state = f"{install_info} {pct}%"

    update_discord_presence(
        state=state,
        details=_format_launcher_version(),
        start=start_time or time.time(),
    )


def set_game_presence(version_identifier, start_time=None, phase="Playing", loader_type=None, loader_version=None):
    version_name = _format_version_name(version_identifier)
    phase_text = "Launching" if phase == "Launching" else "Playing"
    loader_name = _format_loader_name(loader_type, loader_version)

    state = f"{phase_text} {version_name}" + (" ({loader_name})" if loader_name else "")

    update_discord_presence(
        state=state,
        details=_format_launcher_version(),
        start=start_time or time.time(),
    )


def stop_discord_rpc():
    _stop_event.set()

    thread = _rpc_thread
    if thread and thread.is_alive():
        thread.join(timeout=3)

    _close_rpc(clear=True)
