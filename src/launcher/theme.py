from __future__ import annotations

import os
import subprocess
import sys
from tkinter import ttk

from launcher.css_theme import (
    theme_prefers_dark as css_theme_prefers_dark,
    tk_palette_colors,
)


__all__ = ["is_dark_mode", "launcher_theme_prefers_dark", "native_palette", "themed_colors"]


def _is_dark_mode_windows() -> bool:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
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
    forced = os.environ.get("HISTOLAUNCHER_DARK_MODE", "").strip().lower()
    if forced in ("1", "true", "yes", "on", "dark"):
        return True
    if forced in ("0", "false", "no", "off", "light"):
        return False

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


def launcher_theme_prefers_dark() -> bool:
    return css_theme_prefers_dark()


def native_palette() -> dict:
    return tk_palette_colors()


def themed_colors(root):
    colors = native_palette()
    root.configure(bg=colors["bg"])

    style = ttk.Style()
    try:
        style.theme_use("default")
    except Exception:
        pass

    style.configure(".", background=colors["bg"], foreground=colors["fg"])
    style.configure("TLabel", background=colors["bg"], foreground=colors["fg"])
    style.configure("TButton", background=colors["button_bg"], foreground=colors["fg"])
    style.map("TButton", background=[("active", colors["button_active_bg"])])

    style.configure(
        "TProgressbar",
        background=colors["progress_bg"],
        troughcolor=colors["trough_bg"],
    )

    return {"bg": colors["bg"], "fg": colors["fg"], "muted": colors["muted"]}
