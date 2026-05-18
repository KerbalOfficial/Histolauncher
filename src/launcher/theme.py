from __future__ import annotations

import os
import subprocess
import sys
from tkinter import ttk


__all__ = ["is_dark_mode", "launcher_theme_prefers_dark", "native_palette", "themed_colors"]


def _launcher_theme_name() -> str:
    forced = os.environ.get("HISTOLAUNCHER_THEME", "").strip().lower()
    if forced:
        return forced
    try:
        from core.settings import load_global_settings

        return str((load_global_settings() or {}).get("launcher_theme") or "dark").strip().lower()
    except Exception:
        return "dark"


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


def launcher_theme_prefers_dark() -> bool:
    theme_name = _launcher_theme_name()
    if theme_name in {"system", "auto"}:
        return is_dark_mode()
    if "light" in theme_name:
        return False
    if "dark" in theme_name:
        return True
    return theme_name not in {"light", "light-contrast"}


def native_palette() -> dict:
    theme_name = _launcher_theme_name()
    if launcher_theme_prefers_dark():
        colors = {
            "bg": "#111111",
            "fg": "#ffffff",
            "muted": "#d1d5db",
            "button_bg": "#2d2d2d",
            "button_active_bg": "#3a3a3a",
            "progress_bg": "#0078d4",
            "trough_bg": "#2d2d2d",
        }
    else:
        colors = {
        "bg": "#f6f8fb",
        "fg": "#111827",
        "muted": "#374151",
        "button_bg": "#edf2f7",
        "button_active_bg": "#dbe6f3",
        "progress_bg": "#2563eb",
        "trough_bg": "#d7e1ec",
        }

    variants = {
        "chocolate-dark": {"bg": "#20140d", "button_bg": "#261810", "button_active_bg": "#302016", "progress_bg": "#f59e0b", "trough_bg": "#3a2619"},
        "chocolate-light": {"bg": "#f4ece2", "button_bg": "#fff8ef", "button_active_bg": "#f2e4d3", "progress_bg": "#92400e", "trough_bg": "#e6d5c2"},
        "strawberry-dark": {"bg": "#211015", "button_bg": "#2b141b", "button_active_bg": "#371923", "progress_bg": "#fb7185", "trough_bg": "#421e2a"},
        "strawberry-light": {"bg": "#fff1f4", "button_bg": "#fff9fb", "button_active_bg": "#fbe8ee", "progress_bg": "#be123c", "trough_bg": "#f8dce4"},
        "blueberry-dark": {"bg": "#101827", "button_bg": "#17233a", "button_active_bg": "#1e2d49", "progress_bg": "#60a5fa", "trough_bg": "#243451"},
        "blueberry-light": {"bg": "#eff6ff", "button_bg": "#f8fbff", "button_active_bg": "#e8f1ff", "progress_bg": "#1d4ed8", "trough_bg": "#dbeafe"},
        "leaf-dark": {"bg": "#111b11", "button_bg": "#182718", "button_active_bg": "#203320", "progress_bg": "#22c55e", "trough_bg": "#273b27"},
        "leaf-light": {"bg": "#eff8ec", "button_bg": "#fbfff8", "button_active_bg": "#e8f4e2", "progress_bg": "#15803d", "trough_bg": "#dbeed4"},
        "aero-dark": {"bg": "#0c141d", "button_bg": "#182634", "button_active_bg": "#283e52", "progress_bg": "#38bdf8", "trough_bg": "#14202d"},
        "aero-light": {"bg": "#e8f5fb", "button_bg": "#f6fcff", "button_active_bg": "#cfe9f8", "progress_bg": "#0284c7", "trough_bg": "#e2f3fc"},
    }
    colors.update(variants.get(theme_name, {}))
    return colors


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
