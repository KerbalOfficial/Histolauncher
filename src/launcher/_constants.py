from __future__ import annotations

import os

from launcher.css_theme import native_ui_colors, resolve_theme_name, theme_prefers_dark

__all__ = [
    "PROJECT_ROOT",
    "ICO_PATH",
    "PNG_ICON_PATH",
    "UI_ASSETS_ROOT",
    "SPLASH_LOGO_PATH",
    "SPLASH_LOADING_GIF_PATH",
    "SPLASH_FONT_PATH",
    "SPLASH_FONT_FAMILY",
    "SPLASH_BG_COLOR",
    "SPLASH_TEXT_COLOR",
    "SPLASH_BORDER_COLOR",
    "PANEL_BG_COLOR",
    "PANEL_BORDER_COLOR",
    "TOPBAR_BG_COLOR",
    "TOPBAR_ACTIVE_COLOR",
    "TEXT_PRIMARY_COLOR",
    "TEXT_SECONDARY_COLOR",
    "FOCUS_COLOR",
    "INPUT_BG_COLOR",
    "INPUT_BORDER_COLOR",
    "INPUT_POPUP_BG_COLOR",
    "INPUT_SELECTION_BG_COLOR",
    "INPUT_FOCUS_RING_COLOR",
    "AERO_GLASS_ENABLED",
    "AERO_GLASS_TRANSPARENT_KEY",
    "AERO_GLASS_TINT_ABGR",
    "DIALOG_KIND_STYLES",
    "BUTTON_STYLE_MAP",
    "DATA_DIR_PATH",
    "DATA_FILE_EXISTS",
    "EULA_ACCEPTANCE_MARKER",
    "has_accepted_mojang_eula",
    "REMOTE_TIMEOUT",
    "GITHUB_LATEST_RELEASE_URL",
    "GITHUB_RELEASES_URL",
    "GITHUB_API_RELEASES_URL",
]


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICO_PATH = os.path.join(PROJECT_ROOT, "ui", "favicon.ico")
UI_ASSETS_ROOT = os.path.join(PROJECT_ROOT, "ui", "assets")
PNG_ICON_PATH = os.path.join(UI_ASSETS_ROOT, "images", "histolauncher_256x256.png")
SPLASH_LOGO_PATH = os.path.join(UI_ASSETS_ROOT, "images", "histolauncher_256x256.png")
SPLASH_LOADING_GIF_PATH = os.path.join(UI_ASSETS_ROOT, "images", "settings.gif")
SPLASH_FONT_PATH = os.path.join(UI_ASSETS_ROOT, "fonts", "font.ttf")
SPLASH_FONT_FAMILY = "MacMC"


def _launcher_theme_name() -> str:
    return resolve_theme_name()


_NATIVE_THEME_IS_DARK = theme_prefers_dark()
_NATIVE_COLORS = native_ui_colors()

SPLASH_BG_COLOR = _NATIVE_COLORS["splash_bg"]
SPLASH_TEXT_COLOR = _NATIVE_COLORS["splash_text"]
SPLASH_BORDER_COLOR = _NATIVE_COLORS["splash_border"]
PANEL_BG_COLOR = _NATIVE_COLORS["panel_bg"]
PANEL_BORDER_COLOR = _NATIVE_COLORS["panel_border"]
TOPBAR_BG_COLOR = _NATIVE_COLORS["topbar_bg"]
TOPBAR_ACTIVE_COLOR = _NATIVE_COLORS["topbar_active"]
TEXT_PRIMARY_COLOR = _NATIVE_COLORS["text_primary"]
TEXT_SECONDARY_COLOR = _NATIVE_COLORS["text_secondary"]
FOCUS_COLOR = _NATIVE_COLORS["focus"]
INPUT_BG_COLOR = _NATIVE_COLORS["input_bg"]
INPUT_BORDER_COLOR = _NATIVE_COLORS["input_border"]
INPUT_POPUP_BG_COLOR = _NATIVE_COLORS["input_popup_bg"]
INPUT_SELECTION_BG_COLOR = _NATIVE_COLORS["input_selection_bg"]
INPUT_FOCUS_RING_COLOR = _NATIVE_COLORS["input_focus_ring"]


def _compute_aero_glass_tint() -> int:
    import re
    m = re.match(r"#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})", SPLASH_BG_COLOR)
    if not m:
        return 0x88000000
    r, g, b = int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16)
    alpha = 0x44
    return (alpha << 24) | (b << 16) | (g << 8) | r


_AERO_THEME_ACTIVE: bool = _launcher_theme_name().startswith("aero")
AERO_GLASS_ENABLED: bool = _AERO_THEME_ACTIVE
AERO_GLASS_TRANSPARENT_KEY: str = "#010203"
AERO_GLASS_TINT_ABGR: int = _compute_aero_glass_tint() if _AERO_THEME_ACTIVE else 0


DIALOG_KIND_STYLES = {
    "info": {
        "icon": "\u2139",
        "icon_color": "#2389c4",
        "button_style": "important",
        "sound": "info",
    },
    "warning": {
        "icon": "\u26a0",
        "icon_color": "#cc9600",
        "button_style": "mild",
        "sound": "warning",
    },
    "question": {
        "icon": "\ufffd",
        "icon_color": "#2389c4",
        "button_style": "primary",
        "sound": "question",
    },
    "error": {
        "icon": "\u2716",
        "icon_color": "#c52222",
        "button_style": "danger",
        "sound": "error",
    },
}

BUTTON_STYLE_MAP = {
    "default": {
        "bg": "#3d3d3d" if _NATIVE_THEME_IS_DARK else "#edf2f7",
        "active_bg": "#4a4d4f" if _NATIVE_THEME_IS_DARK else "#dbe6f3",
        "border": "#2b2b2b" if _NATIVE_THEME_IS_DARK else "#b8c4d2",
        "fg": TEXT_PRIMARY_COLOR,
    },
    "primary": {
        "bg": "#22c55e",
        "active_bg": "#59e78d",
        "border": "#12883d",
        "fg": "#022c10",
    },
    "mild": {
        "bg": "#cc9600",
        "active_bg": "#c5a026",
        "border": "#6e5100",
        "fg": "#fff8d7",
    },
    "important": {
        "bg": "#186a99",
        "active_bg": "#2389c4",
        "border": "#10405f",
        "fg": "#d0eeff",
    },
    "danger": {
        "bg": "#c52222",
        "active_bg": "#de4a4a",
        "border": "#771313",
        "fg": "#ffeaea",
    },
}

DATA_DIR_PATH = os.path.join(os.path.expanduser("~"), ".histolauncher")
EULA_ACCEPTANCE_MARKER = os.path.join(DATA_DIR_PATH, ".mojang_eula_accepted")


def has_accepted_mojang_eula() -> bool:
    return os.path.isfile(EULA_ACCEPTANCE_MARKER)


DATA_FILE_EXISTS = has_accepted_mojang_eula()

REMOTE_TIMEOUT = 5.0
GITHUB_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/KerbalOfficial/Histolauncher/releases/latest"
)
GITHUB_RELEASES_URL = (
    "https://github.com/KerbalOfficial/Histolauncher/releases"
)
GITHUB_API_RELEASES_URL = (
    "https://api.github.com/repos/KerbalOfficial/Histolauncher/releases"
)
