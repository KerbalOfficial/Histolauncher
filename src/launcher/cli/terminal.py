from __future__ import annotations

import os
import shutil
import sys
from typing import Iterable, Sequence

# ---------------------------------------------------------------------------
# VT / ANSI enablement
# ---------------------------------------------------------------------------

_ANSI_ENABLED = False


def enable_ansi() -> bool:
    global _ANSI_ENABLED
    if _ANSI_ENABLED:
        return True
    if sys.platform.startswith("win"):
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            for handle_id in (-11, -12):
                handle = kernel32.GetStdHandle(handle_id)
                mode = ctypes.c_ulong()
                if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                    continue
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
            try:
                kernel32.SetConsoleOutputCP(65001)
            except Exception:
                pass
        except Exception:
            pass
    _ANSI_ENABLED = True
    return True


# ---------------------------------------------------------------------------
# mouse input (Windows)
# ---------------------------------------------------------------------------

_STDIN_PREV_MODE: int | None = None


def enable_mouse_input() -> bool:
    global _STDIN_PREV_MODE
    if not sys.platform.startswith("win"):
        try:
            from launcher.cli import keys as _keys

            _keys.enter_cbreak()
        except Exception:
            pass
        try:
            sys.stdout.write("\x1b[?1003h\x1b[?1006h")
            sys.stdout.flush()
        except Exception:
            pass
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        h_stdin = kernel32.GetStdHandle(-10)
        prev = ctypes.c_ulong()
        if not kernel32.GetConsoleMode(h_stdin, ctypes.byref(prev)):
            return False
        _STDIN_PREV_MODE = prev.value
        new_mode = (prev.value & ~0x0047 & ~0x0200) | 0x0008 | 0x0010 | 0x0080
        kernel32.SetConsoleMode(h_stdin, new_mode)
        try:
            sys.stdout.write("\x1b[?1003h\x1b[?1006h")
            sys.stdout.flush()
        except Exception:
            pass
        return True
    except Exception:
        return False


def disable_mouse_input() -> None:
    global _STDIN_PREV_MODE
    try:
        sys.stdout.write("\x1b[?1003l\x1b[?1006l")
        sys.stdout.flush()
    except Exception:
        pass
    if not sys.platform.startswith("win"):
        try:
            from launcher.cli import keys as _keys

            _keys.exit_cbreak()
        except Exception:
            pass
        return
    if _STDIN_PREV_MODE is None:
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        h_stdin = kernel32.GetStdHandle(-10)
        kernel32.SetConsoleMode(h_stdin, _STDIN_PREV_MODE)
    except Exception:
        pass
    _STDIN_PREV_MODE = None


# ---------------------------------------------------------------------------
# clipboard
# ---------------------------------------------------------------------------


def clipboard_set(text: str) -> bool:
    if not text:
        text = ""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
            kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
            kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
            user32.OpenClipboard.argtypes = [wintypes.HWND]
            user32.OpenClipboard.restype = wintypes.BOOL
            user32.EmptyClipboard.restype = wintypes.BOOL
            user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
            user32.SetClipboardData.restype = wintypes.HANDLE
            user32.CloseClipboard.restype = wintypes.BOOL
            kernel32.GetConsoleWindow.restype = wintypes.HWND

            data = text.encode("utf-16-le") + b"\x00\x00"
            h = kernel32.GlobalAlloc(GMEM_MOVEABLE, ctypes.c_size_t(len(data)))
            if not h:
                return False
            p = kernel32.GlobalLock(h)
            if not p:
                kernel32.GlobalFree(h)
                return False
            ctypes.memmove(p, data, len(data))
            kernel32.GlobalUnlock(h)

            hwnd = kernel32.GetConsoleWindow() or 0
            opened = False
            for _ in range(10):
                if user32.OpenClipboard(hwnd):
                    opened = True
                    break
                import time
                time.sleep(0.01)
            if not opened:
                kernel32.GlobalFree(h)
                return False
            try:
                user32.EmptyClipboard()
                set_handle = user32.SetClipboardData(CF_UNICODETEXT, h)
                if not set_handle:
                    kernel32.GlobalFree(h)
                    return False
                return True
            finally:
                user32.CloseClipboard()
        except Exception:
            return False
    import shutil
    import subprocess
    for cmd in (
        ["pbcopy"],
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
    ):
        if shutil.which(cmd[0]) is None:
            continue
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"))
            if p.returncode == 0:
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# colour palette
# ---------------------------------------------------------------------------

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
ITALIC = "\x1b[3m"
UNDERLINE = "\x1b[4m"
INVERT = "\x1b[7m"

FG = {
    "fg":       "\x1b[38;5;253m",
    "muted":    "\x1b[38;5;245m",
    "subtle":   "\x1b[38;5;240m",
    "primary":  "\x1b[38;5;75m",
    "accent":   "\x1b[38;5;111m",
    "success":  "\x1b[38;5;114m",
    "warn":     "\x1b[38;5;215m",
    "error":    "\x1b[38;5;203m",
    "info":     "\x1b[38;5;110m",
    "header":   "\x1b[38;5;231m",
    "tag":      "\x1b[38;5;180m",
    "value":    "\x1b[38;5;187m",
    "prompt":   "\x1b[38;5;81m",
    "input":    "\x1b[38;5;231m",
    "border":   "\x1b[38;5;240m",
}

BG = {
    "header":   "\x1b[48;5;236m",
    "panel":    "\x1b[48;5;234m",
    "dialog":   "\x1b[48;5;236m",
    "dim":      "\x1b[48;5;233m",
    "selected": "\x1b[48;5;24m",
}


def c(text: str, *codes: str) -> str:
    if not codes:
        return text
    return "".join(codes) + text + RESET


def colour(name: str, text: str) -> str:
    return c(text, FG.get(name, ""))


# ---------------------------------------------------------------------------
# terminal info
# ---------------------------------------------------------------------------


def term_size() -> tuple[int, int]:
    try:
        sz = shutil.get_terminal_size(fallback=(100, 30))
        return max(40, sz.columns), max(10, sz.lines)
    except Exception:
        return 100, 30


# ---------------------------------------------------------------------------
# high level writes
# ---------------------------------------------------------------------------


def write(text: str = "") -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def writeln(text: str = "") -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def clear_screen() -> None:
    enable_ansi()
    try:
        from launcher.cli import tui as _tui
        if _tui.is_active():
            _tui.clear_scroll_region()
            return
    except Exception:
        pass
    sys.stdout.write("\x1b[H\x1b[2J\x1b[3J")
    sys.stdout.flush()


def hide_cursor() -> None:
    sys.stdout.write("\x1b[?25l")
    sys.stdout.flush()


def show_cursor() -> None:
    sys.stdout.write("\x1b[?25h")
    sys.stdout.flush()


def move_cursor(row: int, col: int) -> None:
    sys.stdout.write(f"\x1b[{max(1, row)};{max(1, col)}H")
    sys.stdout.flush()


def query_cursor_position() -> tuple[int, int] | None:
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            class _COORD(ctypes.Structure):
                _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

            class _CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
                _fields_ = [
                    ("dwSize", _COORD),
                    ("dwCursorPosition", _COORD),
                    ("wAttributes", wintypes.WORD),
                    ("srWindow", wintypes.SMALL_RECT),
                    ("dwMaximumWindowSize", _COORD),
                ]

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            info = _CONSOLE_SCREEN_BUFFER_INFO()
            if not kernel32.GetConsoleScreenBufferInfo(
                handle, ctypes.byref(info)
            ):
                return None
            return info.dwCursorPosition.Y + 1, info.dwCursorPosition.X + 1
        except Exception:
            return None

    try:
        from launcher.cli import keys as _keys

        return _keys.query_cursor_position()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# banner / header
# ---------------------------------------------------------------------------

BAR_CHAR = "\u2500"


def print_banner(*, version: str, debug: bool, scopes: dict[str, str], account: str | None) -> None:
    width, _ = term_size()
    mode = "cli" if not debug else "cli · debug"
    parts = [
        c(f"Histolauncher {version}", BOLD, FG["header"]),
        c(f"({mode})", FG["muted"]),
        c("·", FG["subtle"]),
        c("Versions: ", FG["muted"]) + c(scopes.get("versions", "default"), FG["tag"]),
        c("·", FG["subtle"]),
        c("Addons: ", FG["muted"]) + c(scopes.get("addons", "default"), FG["tag"]),
        c("·", FG["subtle"]),
        c("Settings: ", FG["muted"]) + c(scopes.get("settings", "default"), FG["tag"]),
    ]
    if account:
        parts.extend([
            c("·", FG["subtle"]),
            c("Account: ", FG["muted"]) + c(account, FG["accent"]),
        ])

    header = "  ".join(parts)
    bar = c(BAR_CHAR * width, FG["subtle"])
    writeln("")
    writeln(bar)
    writeln("  " + header)
    writeln(bar)


def print_section(title: str) -> None:
    writeln("")
    writeln(c("▌ " + title, BOLD, FG["primary"]))


def print_info(msg: str) -> None:
    writeln(c("· ", FG["info"]) + msg)


def print_success(msg: str) -> None:
    writeln(c("✓ ", FG["success"]) + msg)


def print_warn(msg: str) -> None:
    writeln(c("! ", FG["warn"]) + msg)


def print_error(msg: str) -> None:
    writeln(c("✗ ", FG["error"]) + msg)


def print_hint(msg: str) -> None:
    writeln(c("  " + msg, FG["muted"], ITALIC))


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------


def print_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[str]],
    *,
    align: Sequence[str] | None = None,
    max_widths: Sequence[int] | None = None,
) -> None:
    rows = [tuple(str(cell) for cell in row) for row in rows]
    cols = len(headers)
    if cols == 0:
        return
    align = list(align or ["left"] * cols)
    while len(align) < cols:
        align.append("left")
    max_widths = list(max_widths or [0] * cols)
    while len(max_widths) < cols:
        max_widths.append(0)

    term_width, _ = term_size()
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i in range(cols):
            if i < len(row):
                widths[i] = max(widths[i], len(row[i]))
    for i, cap in enumerate(max_widths):
        if cap > 0:
            widths[i] = min(widths[i], cap)
    total = sum(widths) + 3 * (cols - 1) + 2
    if total > term_width and widths:
        overflow = total - term_width
        widths[-1] = max(8, widths[-1] - overflow)

    def _fmt(cells: Sequence[str], *, bold: bool = False, fg: str | None = None) -> str:
        out: list[str] = []
        for i in range(cols):
            cell = cells[i] if i < len(cells) else ""
            if len(cell) > widths[i]:
                cell = cell[: max(1, widths[i] - 1)] + "…"
            if align[i] == "right":
                cell = cell.rjust(widths[i])
            else:
                cell = cell.ljust(widths[i])
            if fg:
                cell = c(cell, fg)
            if bold:
                cell = c(cell, BOLD)
            out.append(cell)
        return "  " + c(" \u2502 ", FG["subtle"]).join(out)

    writeln(_fmt(headers, bold=True, fg=FG["header"]))
    writeln("  " + c(BAR_CHAR * (sum(widths) + 3 * (cols - 1)), FG["subtle"]))
    for row in rows:
        writeln(_fmt(row, fg=FG["fg"]))


# ---------------------------------------------------------------------------
# progress
# ---------------------------------------------------------------------------


def render_progress(label: str, ratio: float, *, width: int | None = None, extra: str = "") -> str:
    if width is None:
        term_w, _ = term_size()
        width = max(20, min(40, term_w - len(label) - len(extra) - 16))
    ratio = max(0.0, min(1.0, float(ratio or 0.0)))
    filled = int(ratio * width)
    bar = "█" * filled + "░" * (width - filled)
    pct = f"{ratio * 100:5.1f}%"
    pieces = [c(label, FG["muted"]), c(bar, FG["primary"]), c(pct, FG["fg"])]
    if extra:
        pieces.append(c(extra, FG["muted"]))
    return "  ".join(pieces)


def overwrite_line(text: str) -> None:
    sys.stdout.write("\r\x1b[2K" + text)
    sys.stdout.flush()


def newline() -> None:
    sys.stdout.write("\n")
    sys.stdout.flush()
