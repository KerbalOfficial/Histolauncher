from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

from launcher.cli import terminal
from launcher.css_theme import (
    parse_color,
    reset_cache as reset_css_theme_cache,
    resolve_css_vars,
    resolve_theme_name,
)


_FG_MAP: Dict[str, str] = {
    "fg":      "--color-text-primary",
    "muted":   "--color-text-muted",
    "subtle":  "--color-text-dim",
    "primary": "--color-link",
    "accent":  "--color-link",
    "success": "--color-success",
    "warn":    "--color-warning",
    "error":   "--color-danger",
    "info":    "--color-link",
    "header":  "--color-text-title-strong",
    "tag":     "--color-text-secondary",
    "value":   "--color-text-secondary-strong",
    "prompt":  "--color-link-hover",
    "input":   "--color-text-primary",
    "border":  "--color-link",
}

_BG_MAP: Dict[str, str] = {
    "header":   "--color-surface-panel",
    "panel":    "--color-app-bg",
    "dialog":   "--color-surface-panel",
    "dim":      "--color-surface-panel",
    "selected": "--color-selection-bg",
}


_palette_cache: dict[str, Tuple[Dict[str, str], Dict[str, str]]] = {}
_current_theme: Optional[str] = None
_saved_defaults: Optional[Tuple[Dict[str, str], Dict[str, str]]] = None
_osc_applied: bool = False


def _fg_escape(rgb: Tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"\x1b[38;2;{r};{g};{b}m"


def _bg_escape(rgb: Tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"\x1b[48;2;{r};{g};{b}m"


def _emit_osc(bg_rgb: Optional[Tuple[int, int, int]], fg_rgb: Optional[Tuple[int, int, int]]) -> None:
    global _osc_applied
    import sys
    parts: list[str] = []
    if fg_rgb is not None:
        r, g, b = fg_rgb
        parts.append(f"\x1b]10;rgb:{r:02x}/{g:02x}/{b:02x}\x07")
    if bg_rgb is not None:
        r, g, b = bg_rgb
        parts.append(f"\x1b]11;rgb:{r:02x}/{g:02x}/{b:02x}\x07")
    if not parts:
        return
    try:
        out = sys.__stdout__ or sys.stdout
        out.write("".join(parts))
        out.flush()
        _osc_applied = True
    except Exception:
        pass


def reset_terminal_colors() -> None:
    global _osc_applied
    if not _osc_applied:
        return
    import sys
    try:
        out = sys.__stdout__ or sys.stdout
        out.write("\x1b]110\x07\x1b]111\x07")
        out.flush()
    except Exception:
        pass
    _osc_applied = False


def _build_palette(theme_name: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    cached = _palette_cache.get(theme_name)
    if cached is not None:
        return cached
    vars_map = resolve_css_vars(theme_name)
    fg: Dict[str, str] = {}
    for key, css_var in _FG_MAP.items():
        rgb = parse_color(vars_map.get(css_var, ""))
        if rgb is not None:
            fg[key] = _fg_escape(rgb)
    bg: Dict[str, str] = {}
    for key, css_var in _BG_MAP.items():
        rgb = parse_color(vars_map.get(css_var, ""))
        if rgb is not None:
            bg[key] = _bg_escape(rgb)
    _palette_cache[theme_name] = (fg, bg)
    return fg, bg


def apply_theme(theme_name: Optional[str] = None) -> str:
    global _current_theme, _saved_defaults

    resolved = resolve_theme_name(theme_name)

    if _saved_defaults is None:
        _saved_defaults = (dict(terminal.FG), dict(terminal.BG))

    fg, bg = _build_palette(resolved)

    prev_fg = dict(terminal.FG)
    prev_bg = dict(terminal.BG)

    base_fg, base_bg = _saved_defaults
    terminal.FG.clear()
    terminal.FG.update(base_fg)
    terminal.FG.update(fg)
    terminal.BG.clear()
    terminal.BG.update(base_bg)
    terminal.BG.update(bg)

    replacements: dict[str, str] = {}
    for key, old in prev_fg.items():
        new = terminal.FG.get(key)
        if new and old != new:
            replacements[old] = new
    for key, old in prev_bg.items():
        new = terminal.BG.get(key)
        if new and old != new:
            replacements[old] = new
    if replacements:
        try:
            from launcher.cli import tui
            tui.remap_buffered_colors(replacements)
        except Exception:
            pass

    vars_map = resolve_css_vars(resolved)
    bg_rgb = parse_color(vars_map.get("--color-app-bg", ""))
    fg_rgb = parse_color(vars_map.get("--color-text-primary", ""))
    _emit_osc(bg_rgb, fg_rgb)

    _current_theme = resolved
    return resolved


def current_theme() -> Optional[str]:
    return _current_theme


def reset_cache() -> None:
    _palette_cache.clear()
    reset_css_theme_cache()
