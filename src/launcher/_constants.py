from __future__ import annotations

import os


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

SPLASH_BG_COLOR = "#111111"
SPLASH_TEXT_COLOR = "#ffffff"
SPLASH_BORDER_COLOR = "#333333"
PANEL_BG_COLOR = "#111111"
PANEL_BORDER_COLOR = "#333333"
TOPBAR_BG_COLOR = "#1a1a1a"
TOPBAR_ACTIVE_COLOR = "#222222"
TEXT_PRIMARY_COLOR = "#e5e7eb"
TEXT_SECONDARY_COLOR = "#d1d5db"
FOCUS_COLOR = "#4d9eff"

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
        "bg": "#3d3d3d",
        "active_bg": "#4a4d4f",
        "border": "#2b2b2b",
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
