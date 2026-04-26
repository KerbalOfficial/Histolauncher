from __future__ import annotations

import os
import subprocess
import sys
from tkinter import ttk


__all__ = ["is_dark_mode", "themed_colors"]


def _is_dark_mode_windows() -> bool:
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except Exception:
        return False


def _is_dark_mode_macos() -> bool:
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.returncode == 0 and "dark" in (result.stdout or "").strip().lower()
    except Exception:
        return False


def _is_dark_mode_linux() -> bool:
    # Honour an explicit override first.
    forced = os.environ.get("HISTOLAUNCHER_DARK_MODE", "").strip().lower()
    if forced in ("1", "true", "yes", "on", "dark"):
        return True
    if forced in ("0", "false", "no", "off", "light"):
        return False

    # GNOME / many GTK desktops expose this via gsettings.
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and "dark" in (result.stdout or "").strip().lower():
            return True
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and "dark" in (result.stdout or "").strip().lower():
            return True
    except Exception:
        pass

    # KDE / Plasma fallback.
    kde_globals = os.path.expanduser("~/.config/kdeglobals")
    if os.path.isfile(kde_globals):
        try:
            with open(kde_globals, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if line.strip().lower().startswith("colorscheme="):
                        return "dark" in line.lower()
        except Exception:
            pass

    return False


def is_dark_mode() -> bool:
    if sys.platform.startswith("win"):
        return _is_dark_mode_windows()
    if sys.platform == "darwin":
        return _is_dark_mode_macos()
    return _is_dark_mode_linux()


def themed_colors(root):
    if is_dark_mode():
        root.configure(bg="#111111")

        style = ttk.Style()
        style.theme_use("default")

        style.configure(".", background="#111111", foreground="white")
        style.configure("TLabel", background="#111111", foreground="white")
        style.configure("TButton", background="#2d2d2d", foreground="white")
        style.map("TButton", background=[("active", "#3a3a3a")])

        style.configure(
            "TProgressbar", background="#0078d4", troughcolor="#2d2d2d"
        )

        return {"bg": "#111111", "fg": "white"}

    return {"bg": None, "fg": None}
