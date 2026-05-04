from __future__ import annotations

import os
import shutil
import subprocess
import sys

from core.subprocess_utils import no_window_kwargs


__all__ = ["send_desktop_notification"]


_NOTIFICATION_ICON_NAMES = {
    "default": "histolauncher_256x256",
    "success": "notification_success",
    "installed": "notification_installed",
    "failed": "notification_failed",
    "notice": "notification_notice",
}


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _icon_asset_dir() -> str:
    return os.path.join(
        _project_root(),
        "ui",
        "assets",
        "images",
    )


def _normalize_icon_kind(icon_kind: str) -> str:
    kind = str(icon_kind or "default").strip().lower()
    return kind if kind in _NOTIFICATION_ICON_NAMES else "default"


def _notification_icon_path(icon_kind: str = "default") -> str:
    kind = _normalize_icon_kind(icon_kind)
    extension = ".ico" if sys.platform.startswith("win") else ".png"
    image_dir = _icon_asset_dir()

    preferred = os.path.join(image_dir, f"{_NOTIFICATION_ICON_NAMES[kind]}{extension}")
    if os.path.isfile(preferred):
        return preferred

    fallback = os.path.join(
        image_dir,
        f"{_NOTIFICATION_ICON_NAMES['default']}{extension}",
    )
    return fallback if os.path.isfile(fallback) else ""


def _has_linux_notification_session() -> bool:
    return any(
        os.environ.get(name)
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "MIR_SOCKET")
    )


def _command_error_message(exc: subprocess.CalledProcessError) -> str:
    output = (exc.stderr or exc.stdout or "").strip()
    return output or str(exc)


def _notify_linux_with_notify_send(
    *,
    title: str,
    message: str,
    app_name: str,
    icon_path: str,
) -> None:
    summary = title or app_name
    body = message or ""
    command = ["notify-send", "--app-name", app_name]
    if icon_path:
        command.extend(["--icon", icon_path])
    command.extend([summary, body])

    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            **no_window_kwargs(),
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(_command_error_message(exc)) from exc


def _notify_linux_with_gdbus(
    *,
    title: str,
    message: str,
    app_name: str,
    icon_path: str,
) -> None:
    command = [
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.freedesktop.Notifications",
        "--object-path",
        "/org/freedesktop/Notifications",
        "--method",
        "org.freedesktop.Notifications.Notify",
        app_name,
        "0",
        icon_path,
        title or app_name,
        message or "",
        "[]",
        "{}",
        "10000",
    ]

    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            **no_window_kwargs(),
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(_command_error_message(exc)) from exc


def _notify_linux(
    *,
    title: str,
    message: str,
    app_name: str,
    icon_path: str,
) -> None:
    if not _has_linux_notification_session():
        raise RuntimeError("no graphical Linux notification session detected")

    errors: list[str] = []

    if shutil.which("notify-send"):
        try:
            _notify_linux_with_notify_send(
                title=title,
                message=message,
                app_name=app_name,
                icon_path=icon_path,
            )
            return
        except Exception as exc:  # noqa: BLE001
            errors.append(f"notify-send failed: {exc}")

    if shutil.which("gdbus"):
        try:
            _notify_linux_with_gdbus(
                title=title,
                message=message,
                app_name=app_name,
                icon_path=icon_path,
            )
            return
        except Exception as exc:  # noqa: BLE001
            errors.append(f"gdbus failed: {exc}")

    if errors:
        raise RuntimeError("; ".join(errors))
    raise RuntimeError(
        "no supported Linux notification backend found (notify-send or gdbus)"
    )


def _notify_with_plyer(
    *,
    title: str,
    message: str,
    app_name: str,
    icon_path: str,
) -> None:
    from plyer import notification

    kwargs = {
        "title": title,
        "message": message,
        "app_name": app_name,
    }
    if icon_path:
        kwargs["app_icon"] = icon_path
    notification.notify(**kwargs)


def _notify_windows(
    *,
    title: str,
    message: str,
    app_name: str,
    icon_path: str,
) -> None:
    from core._win_notify import show_windows_notification

    show_windows_notification(
        title=title,
        message=message,
        app_name=app_name,
        icon_path=icon_path,
    )


def send_desktop_notification(
    *,
    title: str,
    message: str,
    app_name: str = "Histolauncher",
    icon_kind: str = "default",
) -> None:
    try:
        from core.settings import load_global_settings

        settings = load_global_settings() or {}
        if str(settings.get("desktop_notifications_enabled", "1")).strip().lower() in {
            "0",
            "false",
            "no",
            "off",
        }:
            return
    except Exception:
        pass

    icon_path = _notification_icon_path(icon_kind)

    if sys.platform.startswith("linux"):
        _notify_linux(
            title=title,
            message=message,
            app_name=app_name,
            icon_path=icon_path,
        )
        return
    if sys.platform.startswith("win"):
        try:
            _notify_windows(
                title=title,
                message=message,
                app_name=app_name,
                icon_path=icon_path,
            )
            return
        except Exception:
            pass
    _notify_with_plyer(
        title=title,
        message=message,
        app_name=app_name,
        icon_path=icon_path,
    )