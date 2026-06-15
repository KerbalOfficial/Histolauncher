from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Tuple

__all__ = [
    "THEME_ALIASES",
    "color_to_hex",
    "native_ui_colors",
    "parse_color",
    "reset_cache",
    "resolve_css_vars",
    "resolve_theme_name",
    "theme_prefers_dark",
    "tk_palette_colors",
]

NATIVE_UI_COLOR_MAP: dict[str, str] = {
    "splash_bg": "--color-app-bg",
    "splash_text": "--color-text-primary",
    "splash_border": "--color-border-strong",
    "panel_bg": "--color-surface-panel",
    "panel_border": "--color-border-strong",
    "topbar_bg": "--color-surface-card",
    "topbar_active": "--color-surface-card-hover",
    "text_primary": "--color-text-primary",
    "text_secondary": "--color-text-secondary",
    "focus": "--color-focus",
    "input_bg": "--color-surface-input",
    "input_border": "--color-border-input-strong",
    "input_popup_bg": "--color-surface-panel",
    "input_selection_bg": "--color-selection-bg",
    "input_focus_ring": "--color-link-hover",
}

TK_PALETTE_MAP: dict[str, str] = {
    "bg": "--color-app-bg",
    "fg": "--color-text-primary",
    "muted": "--color-text-muted",
    "button_bg": "--color-button-bg",
    "button_active_bg": "--color-surface-interactive-hover",
    "progress_bg": "--color-info",
    "trough_bg": "--color-surface-control",
}

_BLOCK_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.DOTALL)
_VAR_RE = re.compile(r"(--color-[A-Za-z0-9_-]+)\s*:\s*([^;]+);")
_HEX_RE = re.compile(r"#([0-9a-fA-F]{3,8})")
_RGBA_RE = re.compile(r"rgba?\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)")


def _ui_css_dir() -> Optional[Path]:
    here = Path(__file__).resolve()
    candidate = here.parent.parent / "ui" / "css"
    if candidate.is_dir():
        return candidate
    return None


def _parse_blocks(css_text: str) -> list[tuple[str, dict[str, str]]]:
    out: list[tuple[str, dict[str, str]]] = []
    cleaned = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)
    for match in _BLOCK_RE.finditer(cleaned):
        selector = match.group(1).strip()
        body = match.group(2)
        vars_in_block = {m.group(1): m.group(2).strip() for m in _VAR_RE.finditer(body)}
        if vars_in_block:
            out.append((selector, vars_in_block))
    return out


def _selector_matches(selector: str, theme_name: str) -> bool:
    parts = [p.strip() for p in selector.split(",")]
    for part in parts:
        if part == ":root":
            return True
        m = re.match(r":root\[data-theme(\^=|\$=|=)\"([^\"]+)\"\]\s*$", part)
        if not m:
            continue
        op, value = m.group(1), m.group(2)
        if op == "=" and value == theme_name:
            return True
        if op == "^=" and theme_name.startswith(value):
            return True
        if op == "$=" and theme_name.endswith(value):
            return True
    return False


@lru_cache(maxsize=1)
def _load_all_blocks() -> tuple[tuple[str, dict[str, str]], ...]:
    css_dir = _ui_css_dir()
    if css_dir is None:
        return ()
    blocks: list[tuple[str, dict[str, str]]] = []
    for fname in ("tokens.css", "themes.css"):
        path = css_dir / fname
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        blocks.extend(_parse_blocks(text))
    return tuple(blocks)


def reset_cache() -> None:
    _load_all_blocks.cache_clear()
    _resolve_css_vars_cached.cache_clear()


def resolve_theme_name(name: Optional[str] = None) -> str:
    if name is None:
        forced = os.environ.get("HISTOLAUNCHER_THEME", "").strip().lower()
        if forced:
            name = forced
        else:
            try:
                from core.settings import load_global_settings

                name = str((load_global_settings() or {}).get("launcher_theme") or "dark")
            except Exception:
                name = "dark"

    name = (name or "dark").strip().lower()

    if name in {"system", "auto"}:
        try:
            from launcher.theme import is_dark_mode

            return "dark" if is_dark_mode() else "light"
        except Exception:
            return "dark"

    if name == "custom":
        try:
            from core.settings import load_global_settings

            base = str((load_global_settings() or {}).get("launcher_theme_base") or "dark").strip().lower()
            return base if base != "custom" else "dark"
        except Exception:
            return "dark"

    return name


def theme_prefers_dark(theme_name: Optional[str] = None) -> bool:
    resolved = resolve_theme_name(theme_name)
    if resolved in {"system", "auto"}:
        try:
            from launcher.theme import is_dark_mode

            return is_dark_mode()
        except Exception:
            return True
    if "light" in resolved:
        return False
    if "dark" in resolved:
        return True
    return resolved not in {"light", "light-contrast"}


@lru_cache(maxsize=64)
def _resolve_css_vars_cached(theme_name: str) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for selector, vars_in_block in _load_all_blocks():
        if _selector_matches(selector, theme_name):
            resolved.update(vars_in_block)
    return resolved


def resolve_css_vars(theme_name: Optional[str] = None) -> dict[str, str]:
    return dict(_resolve_css_vars_cached(resolve_theme_name(theme_name)))


def parse_color(value: str) -> Optional[tuple[int, int, int]]:
    value = (value or "").strip()
    if not value:
        return None
    m = _HEX_RE.match(value)
    if m:
        hx = m.group(1)
        if len(hx) == 3:
            r, g, b = (int(c * 2, 16) for c in hx)
            return r, g, b
        if len(hx) == 4:
            r, g, b = (int(c * 2, 16) for c in hx[:3])
            return r, g, b
        if len(hx) in (6, 8):
            r = int(hx[0:2], 16)
            g = int(hx[2:4], 16)
            b = int(hx[4:6], 16)
            return r, g, b
    m = _RGBA_RE.match(value)
    if m:
        try:
            r, g, b = (int(float(m.group(i))) for i in (1, 2, 3))
            return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
        except (TypeError, ValueError):
            return None
    return None


def color_to_hex(value: str, fallback: str = "#000000") -> str:
    rgb = parse_color(value)
    if rgb is None:
        return fallback
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def _colors_from_map(
    theme_name: Optional[str],
    mapping: dict[str, str],
    fallback_theme: str,
) -> dict[str, str]:
    resolved_name = resolve_theme_name(theme_name)
    vars_map = resolve_css_vars(resolved_name)
    fallback_vars = resolve_css_vars(fallback_theme)
    out: dict[str, str] = {}
    for key, css_var in mapping.items():
        raw = vars_map.get(css_var, "")
        fallback = color_to_hex(fallback_vars.get(css_var, ""), "#000000")
        out[key] = color_to_hex(raw, fallback)
    return out


def native_ui_colors(theme_name: Optional[str] = None) -> dict[str, str]:
    fallback_theme = "dark" if theme_prefers_dark(theme_name) else "light"
    return _colors_from_map(theme_name, NATIVE_UI_COLOR_MAP, fallback_theme)


def tk_palette_colors(theme_name: Optional[str] = None) -> dict[str, str]:
    fallback_theme = "dark" if theme_prefers_dark(theme_name) else "light"
    return _colors_from_map(theme_name, TK_PALETTE_MAP, fallback_theme)
