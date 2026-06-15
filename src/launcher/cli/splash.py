from __future__ import annotations

import os
import sys
import threading
import time

from launcher.cli.terminal import (
    BG,
    DIM,
    FG,
    RESET,
    c,
    enable_ansi,
    hide_cursor,
    show_cursor,
    term_size,
)

__all__ = ["CliSplash", "run_with_splash"]


_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_FRAME_INTERVAL = 0.08

_ICON_UNICODE_TRUECOLOR = (
    "\x1b[38;2;141;188;93;48;2;116;180;74m▄\x1b[38;2;89;61;41;48;2;118;182;76m▄\x1b[38;2;156;203;108;48;2;115;179;73m▄\x1b[38;2;100;164;58;48;2;102;166;60m▄\x1b[38;2;105;169;63;48;2;102;166;60m▄\x1b[38;2;89;61;41;48;2;111;175;69m▄\x1b[38;2;112;176;70;48;2;95;159;53m▄\x1b[38;2;89;61;41;48;2;108;172;66m▄\x1b[m",
    "\x1b[38;2;150;108;74;48;2;89;61;41m▄\x1b[38;2;121;85;58;48;2;108;108;108m▄\x1b[38;2;150;108;74;48;2;89;61;41m▄\x1b[38;2;185;154;131;48;2;89;61;41m▄\x1b[38;2;89;61;41;48;2;113;177;71m▄\x1b[38;2;150;108;74;48;2;89;61;41m▄\x1b[38;2;143;107;88;48;2;89;61;41m▄\x1b[38;2;121;85;58;48;2;89;61;41m▄\x1b[m",
    "\x1b[38;2;159;159;159;48;2;114;114;114m▄\x1b[38;2;29;84;13;48;2;114;114;114m▄\x1b[38;2;44;44;44;48;2;145;145;145m▄\x1b[38;2;33;33;33;48;2;143;143;143m▄\x1b[38;2;44;44;44;48;2;114;114;114m▄\x1b[38;2;33;33;33;48;2;114;114;114m▄\x1b[38;2;33;33;33;48;2;135;135;135m▄\x1b[38;2;159;159;159;48;2;114;114;114m▄\x1b[m",
    "\x1b[38;2;63;63;63;48;2;143;143;143m▄\x1b[38;2;69;69;69;48;2;33;33;33m▄\x1b[38;2;63;63;63;48;2;48;140;22m▄\x1b[38;2;63;63;63;48;2;44;44;44m▄\x1b[38;2;69;69;69;48;2;179;119;66m▄\x1b[38;2;76;76;76;48;2;138;92;51m▄\x1b[38;2;69;69;69;48;2;97;65;36m▄\x1b[38;2;69;69;69;48;2;143;143;143m▄\x1b[m",
)
_ICON_UNICODE_256 = (
    "\x1b[38;5;107;48;5;107m▄\x1b[38;5;237;48;5;107m▄\x1b[38;5;149;48;5;71m▄\x1b[38;5;71;48;5;71m▄▄\x1b[38;5;237;48;5;71m▄\x1b[38;5;71;48;5;71m▄\x1b[38;5;237;48;5;71m▄\x1b[m",
    "\x1b[38;5;95;48;5;237m▄\x1b[38;5;95;48;5;242m▄\x1b[38;5;95;48;5;237m▄\x1b[38;5;138;48;5;237m▄\x1b[38;5;237;48;5;71m▄\x1b[38;5;95;48;5;237m▄▄▄\x1b[m",
    "\x1b[38;5;247;48;5;243m▄\x1b[38;5;22;48;5;243m▄\x1b[38;5;236;48;5;246m▄\x1b[38;5;234;48;5;245m▄\x1b[38;5;236;48;5;243m▄\x1b[38;5;234;48;5;243m▄\x1b[38;5;234;48;5;102m▄\x1b[38;5;247;48;5;243m▄\x1b[m",
    "\x1b[38;5;237;48;5;245m▄\x1b[38;5;238;48;5;234m▄\x1b[38;5;237;48;5;64m▄\x1b[38;5;237;48;5;236m▄\x1b[38;5;238;48;5;137m▄\x1b[38;5;239;48;5;95m▄\x1b[38;5;238;48;5;238m▄\x1b[38;5;238;48;5;245m▄\x1b[m",
)
_ICON_BLOCKS_TRUECOLOR = (
    "\x1b[48;2;116;180;74m  \x1b[48;2;118;182;76m  \x1b[48;2;115;179;73m  \x1b[48;2;102;166;60m    \x1b[48;2;111;175;69m  \x1b[48;2;95;159;53m  \x1b[48;2;108;172;66m  \x1b[m",
    "\x1b[48;2;141;188;93m  \x1b[48;2;89;61;41m  \x1b[48;2;156;203;108m  \x1b[48;2;100;164;58m  \x1b[48;2;105;169;63m  \x1b[48;2;89;61;41m  \x1b[48;2;112;176;70m  \x1b[48;2;89;61;41m  \x1b[m",
    "\x1b[48;2;89;61;41m  \x1b[48;2;108;108;108m  \x1b[48;2;89;61;41m    \x1b[48;2;113;177;71m  \x1b[48;2;89;61;41m      \x1b[m",
    "\x1b[48;2;150;108;74m  \x1b[48;2;121;85;58m  \x1b[48;2;150;108;74m  \x1b[48;2;185;154;131m  \x1b[48;2;89;61;41m  \x1b[48;2;150;108;74m  \x1b[48;2;143;107;88m  \x1b[48;2;121;85;58m  \x1b[m",
    "\x1b[48;2;114;114;114m    \x1b[48;2;145;145;145m  \x1b[48;2;143;143;143m  \x1b[48;2;114;114;114m    \x1b[48;2;135;135;135m  \x1b[48;2;114;114;114m  \x1b[m",
    "\x1b[48;2;159;159;159m  \x1b[48;2;29;84;13m  \x1b[48;2;44;44;44m  \x1b[48;2;33;33;33m  \x1b[48;2;44;44;44m  \x1b[48;2;33;33;33m    \x1b[48;2;159;159;159m  \x1b[m",
    "\x1b[48;2;143;143;143m  \x1b[48;2;33;33;33m  \x1b[48;2;48;140;22m  \x1b[48;2;44;44;44m  \x1b[48;2;179;119;66m  \x1b[48;2;138;92;51m  \x1b[48;2;97;65;36m  \x1b[48;2;143;143;143m  \x1b[m",
    "\x1b[48;2;63;63;63m  \x1b[48;2;69;69;69m  \x1b[48;2;63;63;63m    \x1b[48;2;69;69;69m  \x1b[48;2;76;76;76m  \x1b[48;2;69;69;69m    \x1b[m",
)
_ICON_BLOCKS_256 = (
    "\x1b[48;5;107m    \x1b[48;5;71m            \x1b[m",
    "\x1b[48;5;107m  \x1b[48;5;237m  \x1b[48;5;149m  \x1b[48;5;71m    \x1b[48;5;237m  \x1b[48;5;71m  \x1b[48;5;237m  \x1b[m",
    "\x1b[48;5;237m  \x1b[48;5;242m  \x1b[48;5;237m    \x1b[48;5;71m  \x1b[48;5;237m      \x1b[m",
    "\x1b[48;5;95m      \x1b[48;5;138m  \x1b[48;5;237m  \x1b[48;5;95m      \x1b[m",
    "\x1b[48;5;243m    \x1b[48;5;246m  \x1b[48;5;245m  \x1b[48;5;243m    \x1b[48;5;102m  \x1b[48;5;243m  \x1b[m",
    "\x1b[48;5;247m  \x1b[48;5;22m  \x1b[48;5;236m  \x1b[48;5;234m  \x1b[48;5;236m  \x1b[48;5;234m    \x1b[48;5;247m  \x1b[m",
    "\x1b[48;5;245m  \x1b[48;5;234m  \x1b[48;5;64m  \x1b[48;5;236m  \x1b[48;5;137m  \x1b[48;5;95m  \x1b[48;5;238m  \x1b[48;5;245m  \x1b[m",
    "\x1b[48;5;237m  \x1b[48;5;238m  \x1b[48;5;237m    \x1b[48;5;238m  \x1b[48;5;239m  \x1b[48;5;238m    \x1b[m",
)

_LOADING_TEXT = "Loading..."


def _supports_truecolor() -> bool:
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return True
    if os.environ.get("WT_SESSION") or os.environ.get("VSCODE_INJECTION"):
        return True
    return False


def _supports_unicode() -> bool:
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    if "utf" in enc:
        return True
    try:
        "▄".encode(sys.stdout.encoding or "ascii")
        return True
    except Exception:
        return False


def _select_icon() -> tuple[tuple[str, ...], int]:
    if _supports_unicode():
        lines = _ICON_UNICODE_TRUECOLOR if _supports_truecolor() else _ICON_UNICODE_256
        return lines, 8
    lines = _ICON_BLOCKS_TRUECOLOR if _supports_truecolor() else _ICON_BLOCKS_256
    return lines, 16


def _visible_len(text: str) -> int:
    import re

    return len(re.sub(r"\x1b\[[0-9;]*m", "", text))


class CliSplash:
    CARD_WIDTH = 44
    MIN_VISIBLE_SECONDS = 1.2

    def __init__(self) -> None:
        self._active = False
        self._frame = 0
        self._shown_at: float | None = None
        self._top = 1
        self._left = 1
        self._height = 0
        self._icon_lines: tuple[str, ...] = ()
        self._icon_width = 0
        self._body_rows: list[str] = []
        self._lock = threading.RLock()

    # -- lifecycle ----------------------------------------------------------
    def show(self) -> None:
        if self._active:
            return
        enable_ansi()
        self._active = True
        self._shown_at = time.time()
        sys.stdout.write("\x1b[H\x1b[2J\x1b[3J")
        hide_cursor()
        self._compute_geometry()
        self._draw_static()
        self._draw_status_line()
        sys.stdout.flush()

    def tick(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._frame = (self._frame + 1) % len(_SPINNER_FRAMES)
            self._draw_status_line()
            sys.stdout.flush()

    def close(self, *, ensure_minimum: bool = True) -> None:
        with self._lock:
            if not self._active:
                return
            if ensure_minimum and self._shown_at is not None:
                remaining = (self._shown_at + self.MIN_VISIBLE_SECONDS) - time.time()
                while remaining > 0:
                    self._frame = (self._frame + 1) % len(_SPINNER_FRAMES)
                    self._draw_status_line()
                    sys.stdout.flush()
                    time.sleep(min(_FRAME_INTERVAL, remaining))
                    remaining = (self._shown_at + self.MIN_VISIBLE_SECONDS) - time.time()
            self._active = False
            sys.stdout.write("\x1b[H\x1b[2J\x1b[3J")
            show_cursor()
            sys.stdout.flush()

    def draw_dimmed(self) -> None:
        self._compute_geometry()
        _w, height = term_size()
        out = sys.stdout
        for r in range(1, height + 1):
            out.write(f"\x1b[{r};1H\x1b[2K")
        self._draw_static()
        self._draw_status_line()
        out.flush()

    def advance(self) -> bool:
        with self._lock:
            if not self._active:
                return False
            self._frame = (self._frame + 1) % len(_SPINNER_FRAMES)
            self._draw_status_line()
            sys.stdout.flush()
            return True

    # -- drawing ------------------------------------------------------------
    def _compute_geometry(self) -> None:
        width, height = term_size()
        self._icon_lines, self._icon_width = _select_icon()
        body = ["", ""]
        body.extend(self._icon_lines)
        body.extend(["", "", "", "", ""])
        self._height = len(body) + 2
        self._width = min(self.CARD_WIDTH, max(24, width - 4))
        self._left = max(1, (width - self._width) // 2 + 1)
        self._top = max(1, (height - self._height) // 2 + 1)
        self._body_rows = body

    def _put(self, row: int, col: int, text: str) -> None:
        sys.stdout.write(f"\x1b[{row};{col}H{text}")

    def _center(self, text: str) -> str:
        inner = self._width - 2
        plain = _visible_len(text)
        if plain >= inner:
            return text
        lead = (inner - plain) // 2
        trail = inner - plain - lead
        return (" " * lead) + text + (" " * trail)

    def _draw_static(self) -> None:
        w = self._width
        top = self._top
        left = self._left
        edge = FG["border"]
        bg = BG["dialog"]
        # top border
        self._put(top, left, c("\u250c" + "\u2500" * (w - 2) + "\u2510", edge, bg))
        inner = self._width - 2
        # body rows
        for i, raw in enumerate(self._body_rows):
            row = top + 1 + i
            if raw in self._icon_lines:
                lead = max(0, (inner - self._icon_width) // 2)
                trail = max(0, inner - self._icon_width - lead)
                content = bg + (" " * lead) + raw + bg + (" " * trail)
                self._put(row, left, c("\u2502", edge, bg) + content + RESET + c("\u2502", edge, bg))
                continue
            else:
                styled = ""
            line = self._center(styled)
            self._put(row, left, c("\u2502", edge, bg) + bg + line + RESET + c("\u2502", edge, bg))
        # bottom border
        bottom = top + self._height - 1
        self._put(bottom, left, c("\u2514" + "\u2500" * (w - 2) + "\u2518", edge, bg))

    def _draw_status_line(self) -> None:
        row = self._top + self._height - 2
        left = self._left
        edge = FG["border"]
        bg = BG["dialog"]
        inner = self._width - 2
        spinner = c(_SPINNER_FRAMES[self._frame], FG["accent"])
        status = c(_LOADING_TEXT, FG["fg"])
        content = " " + spinner + "  " + status
        plain = _visible_len(content)
        trail = max(0, inner - plain)
        line = content + (" " * trail)
        self._put(row, left, c("\u2502", edge, bg) + bg + line + RESET + c("\u2502", edge, bg))


def run_with_splash(splash: CliSplash, func, *args, **kwargs):
    result: dict[str, object] = {}

    def _worker() -> None:
        try:
            result["value"] = func(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    while thread.is_alive():
        splash.tick()
        time.sleep(_FRAME_INTERVAL)
    thread.join()
    if "error" in result:
        raise result["error"]  # type: ignore[misc]
    return result.get("value")
