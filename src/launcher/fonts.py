from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tkinter
from tkinter import font as tkfont

from core.logger import colorize_log

from launcher._constants import SPLASH_FONT_FAMILY, SPLASH_FONT_PATH


__all__ = [
    "preinstall_linux_font",
    "remember_native_ui_font_family",
    "register_private_ui_fonts",
    "get_native_ui_font_family",
]


_STATE = {"native_family": None}
_REGISTERED_PRIVATE_UI_FONTS: set[str] = set()
_LINUX_FONT_INSTALLED: bool = False


def _fc_query_family(font_file: str) -> str:
    try:
        result = subprocess.run(
            ["fc-query", "--format=%{family}\n", font_file],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            # fontconfig may return "Name,LocalisedName" — take the first token
            first_line = result.stdout.strip().split("\n")[0]
            family = first_line.split(",")[0].strip()
            if family:
                return family
    except Exception:
        pass
    return ""


def preinstall_linux_font(
    font_path: str = SPLASH_FONT_PATH,
    family_name: str = SPLASH_FONT_FAMILY,
) -> bool:
    global _LINUX_FONT_INSTALLED
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return False
    if _LINUX_FONT_INSTALLED:
        return True
    if not os.path.isfile(font_path):
        print(colorize_log(f"[launcher] Linux font pre-install: source not found: {font_path}"))
        return False

    fonts_dir = os.path.join(
        os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
        "fonts",
        "histolauncher",
    )
    dest = os.path.join(fonts_dir, os.path.basename(font_path))

    # Fast path: we already copied the file on a previous run.
    if os.path.isfile(dest):
        detected = _fc_query_family(dest)
        if detected:
            _STATE["native_family"] = detected
            _LINUX_FONT_INSTALLED = True
            print(colorize_log(f"[launcher] UI font already installed (family: '{detected}')"))
            return True

    # Fast path: family is already known to fontconfig (e.g. system-wide install).
    try:
        result = subprocess.run(
            ["fc-list", f":family={family_name}"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            detected = _fc_query_family(font_path)
            if detected:
                _STATE["native_family"] = detected
            _LINUX_FONT_INSTALLED = True
            return True
    except Exception:
        pass

    # Install into user font directory and rebuild cache.
    try:
        os.makedirs(fonts_dir, exist_ok=True)
        shutil.copy2(font_path, dest)
        # Rebuild only the user font dir (faster than fc-cache -f globally).
        subprocess.run(
            ["fc-cache", "-f", fonts_dir],
            capture_output=True,
            timeout=10,
        )
        detected = _fc_query_family(dest)
        if detected:
            _STATE["native_family"] = detected
            print(colorize_log(
                f"[launcher] Installed UI font '{detected}' to {dest}"
            ))
        else:
            print(colorize_log(
                f"[launcher] Installed UI font to {dest} "
                f"(fc-query unavailable; family name undetected)"
            ))
        _LINUX_FONT_INSTALLED = True
        return True
    except Exception as e:
        print(colorize_log(f"[launcher] Could not install Linux UI font: {e}"))
        return False


def remember_native_ui_font_family(family):
    if family:
        _STATE["native_family"] = family
    return family


def register_private_ui_fonts():
    if not sys.platform.startswith("win"):
        return

    if not os.path.exists(SPLASH_FONT_PATH):
        return

    normalized_path = os.path.normcase(SPLASH_FONT_PATH)
    if normalized_path in _REGISTERED_PRIVATE_UI_FONTS:
        return

    try:
        import ctypes

        FR_PRIVATE = 0x10
        gdi32 = ctypes.windll.gdi32
        if gdi32.AddFontResourceExW(SPLASH_FONT_PATH, FR_PRIVATE, 0):
            _REGISTERED_PRIVATE_UI_FONTS.add(normalized_path)
    except Exception as e:
        print(colorize_log(f"[launcher] Could not register native UI font: {e}"))


def get_native_ui_font_family(root, fallbacks=("Segoe UI", "TkDefaultFont")):
    try:
        font_families_before = set(tkfont.families(root))
    except Exception:
        font_families_before = set()

    native_family = _STATE["native_family"]
    if native_family and native_family in font_families_before:
        return native_family
    if SPLASH_FONT_FAMILY in font_families_before:
        return remember_native_ui_font_family(SPLASH_FONT_FAMILY)

    register_private_ui_fonts()

    try:
        font_families_after = set(tkfont.families(root))
    except Exception:
        font_families_after = font_families_before

    native_family = _STATE["native_family"]
    if native_family and native_family in font_families_after:
        return native_family
    if SPLASH_FONT_FAMILY in font_families_after:
        return remember_native_ui_font_family(SPLASH_FONT_FAMILY)

    new_families = sorted(font_families_after - font_families_before)
    if new_families:
        return remember_native_ui_font_family(new_families[0])

    for family in fallbacks:
        if family in font_families_after:
            return remember_native_ui_font_family(family)

    return remember_native_ui_font_family(fallbacks[0])


# Keep a Tk-free reference accessible to tests (``tkinter`` is imported above
# so module import itself remains side-effect free apart from font discovery).
_TK_AVAILABLE = bool(tkinter)
