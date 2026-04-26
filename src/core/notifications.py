from __future__ import annotations

import os
import shutil
import subprocess
import sys

from core.subprocess_utils import no_window_kwargs


__all__ = ["send_desktop_notification"]


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _png_icon_path() -> str:
    return os.path.join(
        _project_root(),
        "ui",
        "assets",
        "images",
        "histolauncher_256x256.png",
    )


def _ico_icon_path() -> str:
    return os.path.join(
        _project_root(),
        "ui",
        "assets",
        "images",
        "histolauncher_256x256.ico",
    )


def _notification_icon_path() -> str:
    if sys.platform.startswith("win"):
        icon_path = _ico_icon_path()
    else:
        icon_path = _png_icon_path()
    return icon_path if os.path.isfile(icon_path) else ""


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
) -> None:
    summary = title or app_name
    body = message or ""
    command = ["notify-send", "--app-name", app_name]
    icon_path = _notification_icon_path()
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
        _notification_icon_path(),
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
) -> None:
    from plyer import notification

    kwargs = {
        "title": title,
        "message": message,
        "app_name": app_name,
    }
    icon_path = _notification_icon_path()
    if icon_path:
        kwargs["app_icon"] = icon_path
    notification.notify(**kwargs)


def _notify_windows(
    *,
    title: str,
    message: str,
    app_name: str,
) -> None:
    from core._win_notify import show_windows_notification

    show_windows_notification(
        title=title,
        message=message,
        app_name=app_name,
        icon_path=_notification_icon_path(),
    )


def send_desktop_notification(
    *,
    title: str,
    message: str,
    app_name: str = "Histolauncher",
) -> None:
    if sys.platform.startswith("linux"):
        _notify_linux(title=title, message=message, app_name=app_name)
        return
    if sys.platform.startswith("win"):
        try:
            _notify_windows(title=title, message=message, app_name=app_name)
            return
        except Exception:
            pass
    _notify_with_plyer(title=title, message=message, app_name=app_name)