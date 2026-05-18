from __future__ import annotations

import os
import sys


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
    forced = os.environ.get("HISTOLAUNCHER_THEME", "").strip().lower()
    if forced:
        return forced
    try:
        from core.settings import load_global_settings

        return str((load_global_settings() or {}).get("launcher_theme") or "dark").strip().lower()
    except Exception:
        return "dark"


def _system_prefers_dark() -> bool:
    if sys.platform.startswith("win"):
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
    forced = os.environ.get("HISTOLAUNCHER_DARK_MODE", "").strip().lower()
    if forced in {"1", "true", "yes", "on", "dark"}:
        return True
    if forced in {"0", "false", "no", "off", "light"}:
        return False
    return False


def _native_theme_is_dark() -> bool:
    theme_name = _launcher_theme_name()
    if theme_name in {"system", "auto"}:
        return _system_prefers_dark()
    if "light" in theme_name:
        return False
    if "dark" in theme_name:
        return True
    return theme_name not in {"light", "light-contrast"}


_NATIVE_THEME_IS_DARK = _native_theme_is_dark()
_NATIVE_DARK_COLORS = {
    "splash_bg": "#111111",
    "splash_text": "#ffffff",
    "splash_border": "#333333",
    "panel_bg": "#111111",
    "panel_border": "#333333",
    "topbar_bg": "#1a1a1a",
    "topbar_active": "#222222",
    "text_primary": "#e5e7eb",
    "text_secondary": "#d1d5db",
    "focus": "#4d9eff",
    "input_bg": "#3c3f41",
    "input_border": "#1f2937",
    "input_popup_bg": "#111111",
    "input_selection_bg": "#17345d",
    "input_focus_ring": "#9fc6ff",
}
_NATIVE_LIGHT_COLORS = {
    "splash_bg": "#f6f8fb",
    "splash_text": "#111827",
    "splash_border": "#c7d2de",
    "panel_bg": "#ffffff",
    "panel_border": "#c7d2de",
    "topbar_bg": "#e8eef5",
    "topbar_active": "#dbe6f3",
    "text_primary": "#111827",
    "text_secondary": "#374151",
    "focus": "#2563eb",
    "input_bg": "#ffffff",
    "input_border": "#9aa7b8",
    "input_popup_bg": "#ffffff",
    "input_selection_bg": "#cfe2ff",
    "input_focus_ring": "#bfdbfe",
}
_NATIVE_COLORS = _NATIVE_DARK_COLORS if _NATIVE_THEME_IS_DARK else _NATIVE_LIGHT_COLORS


def _theme_variant_colors(theme_name: str) -> dict[str, str]:
    variants = {
        "dark-contrast":    {"splash_bg": "#000000", "splash_border": "#ffffff", "panel_bg": "#050505", "panel_border": "#ffffff", "topbar_bg": "#101010", "topbar_active": "#1f1f1f", "input_bg": "#000000", "input_border": "#ffffff", "input_popup_bg": "#050505", "input_selection_bg": "#17345d", "input_focus_ring": "#ffd54a", "focus": "#ffd54a"},
        "light-contrast":   {"splash_bg": "#ffffff", "splash_border": "#000000", "panel_bg": "#ffffff", "panel_border": "#000000", "topbar_bg": "#f7f7f7", "topbar_active": "#ececec", "input_bg": "#ffffff", "input_border": "#000000", "input_popup_bg": "#ffffff", "input_selection_bg": "#d8e8ff", "input_focus_ring": "#005fcc", "focus": "#005fcc"},
        "chocolate-dark":   {"splash_bg": "#20140d", "splash_border": "#6b4a32", "panel_bg": "#130c08", "panel_border": "#6b4a32", "topbar_bg": "#050404", "topbar_active": "#302016", "input_bg": "#3a2619", "input_border": "#4d3323", "input_popup_bg": "#130c08", "input_selection_bg": "#4a2f1e", "input_focus_ring": "#f59e0b", "focus": "#f59e0b"},
        "chocolate-light":  {"splash_bg": "#f4ece2", "splash_border": "#b08968", "panel_bg": "#fff8ef", "panel_border": "#b08968", "topbar_bg": "#e6d5c2", "topbar_active": "#f2e4d3", "input_bg": "#fffaf3", "input_border": "#9a7351", "input_popup_bg": "#fff8ef", "input_selection_bg": "#ead1b5", "input_focus_ring": "#92400e", "focus": "#92400e"},
        "strawberry-dark":  {"splash_bg": "#211015", "splash_border": "#9f4761", "panel_bg": "#14090d", "panel_border": "#9f4761", "topbar_bg": "#2b141b", "topbar_active": "#371923", "input_bg": "#421e2a", "input_border": "#6e2d3f", "input_popup_bg": "#14090d", "input_selection_bg": "#5a2434", "input_focus_ring": "#fb7185", "focus": "#fb7185"},
        "strawberry-light": {"splash_bg": "#fff1f4", "splash_border": "#da7f96", "panel_bg": "#fff9fb", "panel_border": "#da7f96", "topbar_bg": "#f8dce4", "topbar_active": "#fbe8ee", "input_bg": "#ffffff", "input_border": "#c66780", "input_popup_bg": "#fff9fb", "input_selection_bg": "#ffd6e1", "input_focus_ring": "#be123c", "focus": "#be123c"},
        "blueberry-dark":   {"splash_bg": "#101827", "splash_border": "#4f6fa8", "panel_bg": "#0a1020", "panel_border": "#4f6fa8", "topbar_bg": "#17233a", "topbar_active": "#1e2d49", "input_bg": "#243451", "input_border": "#33496e", "input_popup_bg": "#0a1020", "input_selection_bg": "#263e65", "input_focus_ring": "#60a5fa", "focus": "#60a5fa"},
        "blueberry-light":  {"splash_bg": "#eff6ff", "splash_border": "#6b93ca", "panel_bg": "#f8fbff", "panel_border": "#6b93ca", "topbar_bg": "#dbeafe", "topbar_active": "#e8f1ff", "input_bg": "#ffffff", "input_border": "#4f79b8", "input_popup_bg": "#f8fbff", "input_selection_bg": "#dbeafe", "input_focus_ring": "#1d4ed8", "focus": "#1d4ed8"},
        "leaf-dark":        {"splash_bg": "#111b11", "splash_border": "#4f7a4f", "panel_bg": "#091109", "panel_border": "#4f7a4f", "topbar_bg": "#182718", "topbar_active": "#203320", "input_bg": "#273b27", "input_border": "#335233", "input_popup_bg": "#091109", "input_selection_bg": "#214021", "input_focus_ring": "#22c55e", "focus": "#22c55e"},
        "leaf-light":       {"splash_bg": "#eff8ec", "splash_border": "#7da36f", "panel_bg": "#fbfff8", "panel_border": "#7da36f", "topbar_bg": "#dbeed4", "topbar_active": "#e8f4e2", "input_bg": "#ffffff", "input_border": "#638b55", "input_popup_bg": "#fbfff8", "input_selection_bg": "#d8f0cf", "input_focus_ring": "#15803d", "focus": "#15803d"},
        "aero-dark":        {"splash_bg": "#0c141d", "splash_border": "#6e97be", "panel_bg": "#0f1924", "panel_border": "#6e97be", "topbar_bg": "#182634", "topbar_active": "#283e52", "input_bg": "#14202d", "input_border": "#6e97be", "input_popup_bg": "#0f1924", "input_selection_bg": "#24384c", "input_focus_ring": "#38bdf8", "focus": "#38bdf8"},
        "aero-light":       {"splash_bg": "#e8f5fb", "splash_border": "#447eab", "panel_bg": "#f6fcff", "panel_border": "#447eab", "topbar_bg": "#e2f3fc", "topbar_active": "#cfe9f8", "input_bg": "#ffffff", "input_border": "#4177a2", "input_popup_bg": "#f6fcff", "input_selection_bg": "#d7effc", "input_focus_ring": "#0284c7", "focus": "#0284c7"},
    }
    return variants.get(theme_name, {})


_NATIVE_COLORS = {**_NATIVE_COLORS, **_theme_variant_colors(_launcher_theme_name())}

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
    alpha = 0x44  # ~27 % tint opacity — light enough to clearly show the blur
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
