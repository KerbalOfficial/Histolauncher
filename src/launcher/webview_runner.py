from __future__ import annotations

import time
import tkinter
import urllib.request
import webbrowser
from tkinter import ttk

from core.logger import colorize_log, dim_line

from launcher._constants import ICO_PATH, PNG_ICON_PATH
from launcher.linux_icon import (
    apply_gtk_window_icon,
    install_linux_window_icon,
)
from launcher.theme import themed_colors
from launcher.win32_icon import extract_pywebview_hwnd, replace_pywebview_icon


__all__ = [
    "wait_for_server",
    "open_in_browser",
    "open_with_webview",
    "control_panel_fallback_window",
]


def wait_for_server(url, timeout=5.0, poll_interval=0.05, on_poll=None):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if on_poll is not None:
            try:
                on_poll()
            except Exception:
                pass
        try:
            with urllib.request.urlopen(url, timeout=0.5) as resp:
                if resp.status in (200, 301, 302, 304):
                    return True
        except Exception:
            pass
        time.sleep(poll_interval)
    return False


def open_in_browser(port):
    url = f"http://127.0.0.1:{port}/"
    try:
        webbrowser.open_new_tab(url)
        print(colorize_log(
            f"[launcher] Opened launcher in default browser: {url}"
        ))
    except Exception as e:
        print(colorize_log(
            f"[launcher] Failed to open default browser! ({e}) You MUST "
            f"manually go to your browser and enter this link: {url}"
        ))


def open_with_webview(
    webview, port, title="Histolauncher", width=900, height=520, splash=None
):
    import os
    import sys

    if sys.platform.startswith("linux"):
        os.environ["PYWEBVIEW_GUI"] = "qt"
        os.environ["QT_API"] = "pyqt6"

    url = f"http://127.0.0.1:{port}/"
    try:
        use_png_icon = (
            not sys.platform.startswith("win")
            and os.path.isfile(PNG_ICON_PATH)
        )
        if use_png_icon and sys.platform.startswith("linux"):
            if os.environ.get("PYWEBVIEW_GUI", "").lower() != "qt":
                install_linux_window_icon(PNG_ICON_PATH)

        window = webview.create_window(title, url, width=width, height=height)

        if use_png_icon and sys.platform.startswith("linux"):
            def _apply_gtk_icon():
                if os.environ.get("PYWEBVIEW_GUI", "").lower() == "qt":
                    try:
                        native = getattr(window, "native", None)
                        if native is not None:
                            try:
                                from PyQt6.QtGui import QIcon
                                native.setWindowIcon(QIcon(PNG_ICON_PATH))
                            except Exception:
                                pass
                    except Exception:
                        pass
                    return
                native = getattr(window, "native", None)
                apply_gtk_window_icon(native, PNG_ICON_PATH)

            try:
                window.events.before_show += _apply_gtk_icon
            except Exception:
                pass
            try:
                window.events.shown += _apply_gtk_icon
            except Exception:
                pass

        def _on_webview_ready():
            replace_pywebview_icon(window)
            if sys.platform.startswith("win"):
                try:
                    hwnd = extract_pywebview_hwnd(window)
                    if hwnd:
                        from core._win_notify import set_launcher_hwnd
                        set_launcher_hwnd(hwnd)
                except Exception:
                    pass

        try:
            window.events.shown += _on_webview_ready
        except Exception:
            pass
        window.events.loaded += _on_webview_ready
        print(colorize_log(
            f"[launcher] Opened launcher in pywebview window: {url}"
        ))
        print(dim_line("------------------------------------------------"))
        if splash is not None:
            splash.close()
        start_kwargs = {"user_agent": "Histolauncher/1.0"}
        if use_png_icon:
            start_kwargs["icon"] = PNG_ICON_PATH
        try:
            webview.start(**start_kwargs)
        except TypeError:
            start_kwargs.pop("icon", None)
            webview.start(**start_kwargs)
        return True
    except Exception as e:
        print(colorize_log(f"[launcher] pywebview failed to open window: {e}"))
        print(dim_line("------------------------------------------------"))
        if splash is not None:
            splash.close(ensure_minimum=False)
        return False


def control_panel_fallback_window(port):
    root = tkinter.Tk()
    try:
        root.iconbitmap(ICO_PATH)
    except Exception:
        pass
    root.title("Histolauncher")
    colors = themed_colors(root)

    style = ttk.Style()
    try:
        style.theme_use("vista")
    except Exception:
        pass

    root.geometry("520x240")
    root.resizable(False, False)

    title = tkinter.Label(
        root,
        text="Histolauncher - Control Panel for Browser-users",
        font=("Segoe UI", 12, "bold"),
        bg=colors["bg"],
        fg=colors["fg"],
    )
    title.pack(pady=20)

    desc = tkinter.Label(
        root,
        text=(
            "This is the control panel for browser-users.\n\n"
            "Click 'Open Launcher' to open the launcher's web link onto your "
            "default browser.\n"
            "Click 'Close Launcher' to close the web server and exit "
            "Histolauncher."
        ),
        font=("Segoe UI", 9),
        bg=colors["bg"],
        fg=colors["fg"],
    )
    desc.pack(pady=10)

    open_btn = ttk.Button(
        root, text="Open Launcher", command=lambda: open_in_browser(port)
    )
    open_btn.pack(pady=5)

    close_btn = ttk.Button(root, text="Close Launcher", command=root.destroy)
    close_btn.pack(pady=5)

    root.mainloop()
