from __future__ import annotations

import contextlib
import functools as _functools
import random
import re
import sys
import threading

from launcher.cli import keys
from launcher.cli.terminal import (
    BG, BOLD, DIM, FG, INVERT, ITALIC, RESET, c, clipboard_set, enable_ansi,
    enable_mouse_input, disable_mouse_input, term_size,
)


HEADER_ROWS = 2
FOOTER_ROWS = 3
MAX_BUFFER_LINES = 4000
WHEEL_STEP = 3
SUGG_MAX_ROWS = 8
SUGG_MAX_LABEL = 26
SUGG_MAX_DESC = 46
_ANIM_INTERVAL = 0.08

TIPS = [
    "Type 'help' to list every command, or 'help <command>' for details.",
    "Press Tab inside dialogs to move between options.",
    "Wrap arguments containing spaces in \"double quotes\".",
    "Use 'list-games' to see games currently running in the background.",
    "Run 'launch-version <ver>' with no loader to get an interactive picker.",
    "Switch profiles with 'versions-profile <id>' / 'addons-profile <id>'.",
    "Press Ctrl+C at the prompt to quit, or type 'exit'.",
    "'get-setting <key>' shows a setting value, 'set-setting <key> <value>' changes it.",
    "Account login: type 'login' for an interactive sign-in.",
    "Use 'clear' to wipe the output box.",
    "Use up/down arrows at the prompt to scroll through previous commands.",
    "Scroll using PgUp/PgDown or Mouse wheel.",
    "In debug mode, run 'logs left/right/top/bottom/hide/show' to move or toggle the logs panel.",
    "In debug mode, press Tab to switch keyboard scroll between Output and Logs.",
]


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------


_state = {
    "active": False,
    "debug": False,
    "width": 100,
    "height": 30,
    "tip": "",
    "prompt": "  \u203a ",
    "logs_pos": "top",
    "focus": "output",
    "mouse": True,
    "modal_backdrop": None,
    "modal_animator": None,
    "standalone": False,
    "modal_draggable": True,
}

_output_lines: list[str] = []
_log_lines: list[str] = []
_output_scroll: int = 0
_log_scroll: int = 0

_sel: dict | None = None
_window_drag: dict | None = None

_windows: dict[str, dict] = {
    "output": {"id": "output", "title": "Output",
               "minimized": False, "closable": False, "z": 0},
    "logs": {"id": "logs", "title": "Logs",
             "minimized": False, "closable": True, "z": 1},
}

_window_order: list[str] = ["output", "logs"]
_z_counter: int = 1

_taskbar_hits: list[tuple[int, int, str]] = []

_io_lock = threading.RLock()
_thread_local = threading.local()
_dialog_depth = 0

_orig_stdout = None
_orig_stderr = None

_ansi_re = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _win(win_id: str) -> dict | None:
    return _windows.get(win_id)


def _has_minimized() -> bool:
    return any(w["minimized"] for w in _windows.values())


def _focus_window(win_id: str) -> None:
    global _z_counter
    if win_id not in _windows:
        return
    _state["focus"] = win_id
    _z_counter += 1
    _windows[win_id]["z"] = _z_counter


def _output_paned() -> bool:
    return not _windows["output"]["minimized"]


def _logs_paned() -> bool:
    return (_state["debug"]
            and _state["logs_pos"] != "hidden"
            and not _windows["logs"]["minimized"])


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def enter(*, debug: bool = False) -> None:
    enable_ansi()
    enable_mouse_input()
    _refresh_size()
    _state["debug"] = bool(debug)
    _state["focus"] = "output"
    if not debug:
        _state["logs_pos"] = "hidden"
    elif _state["logs_pos"] == "hidden":
        _state["logs_pos"] = "top"
    out = sys.stdout
    out.write("\x1b[?1049h\x1b[2J\x1b[H")
    out.write("\x1b[?1000h\x1b[?1006h")
    out.flush()
    _state["active"] = True
    _install_stdio_capture()
    _apply_scroll_region_none()


def leave() -> None:
    if not _state["active"]:
        return
    _restore_stdio_capture()
    out = sys.stdout
    out.write("\x1b[?1000l\x1b[?1006l")
    out.write("\x1b[?25h\x1b[?1049l")
    out.flush()
    disable_mouse_input()
    _state["active"] = False


def is_active() -> bool:
    return bool(_state["active"])


def set_modal_backdrop(painter, animator=None) -> None:
    _state["modal_backdrop"] = painter
    _state["modal_animator"] = animator


def enable_standalone_modals(*, draggable: bool = False) -> None:
    enable_ansi()
    _refresh_size()
    _state["standalone"] = True
    _state["modal_draggable"] = bool(draggable)


def disable_standalone_modals() -> None:
    _state["standalone"] = False
    _state["modal_draggable"] = True
    if _state["active"]:
        _state["active"] = False
        disable_mouse_input()

# ---------------------------------------------------------------------------
# layout / size
# ---------------------------------------------------------------------------


def _refresh_size() -> bool:
    w, h = term_size()
    changed = (w != _state["width"]) or (h != _state["height"])
    _state["width"] = max(30, w)
    _state["height"] = max(12, h)
    return changed


def _apply_scroll_region_none() -> None:
    _raw_out().write("\x1b[r")
    _raw_out().flush()


def refresh_layout() -> None:
    if not _state["active"]:
        return
    if _refresh_size():
        _apply_scroll_region_none()
        _full_repaint()


def _chrome_bounds() -> tuple[int, int]:
    bottom = _state["height"] - FOOTER_ROWS
    if _has_minimized():
        bottom -= 1
    return HEADER_ROWS + 1, bottom


def _taskbar_row() -> int | None:
    if not _has_minimized():
        return None
    return _state["height"] - FOOTER_ROWS


def _compute_regions() -> tuple[tuple[int, int, int, int],
                                tuple[int, int, int, int] | None,
                                None]:
    top, bottom = _chrome_bounds()
    width = _state["width"]
    pos = _state["logs_pos"]
    out_paned = _output_paned()
    logs_paned = _logs_paned()
    if not out_paned and not logs_paned:
        return None, None, None
    if out_paned and not logs_paned:
        return (top, bottom, 1, width), None, None
    if logs_paned and not out_paned:
        return None, (top, bottom, 1, width), None
    if pos == "bottom":
        mid = top + max(5, (bottom - top) // 2)
        out_box = (top, mid, 1, width)
        logs_box = (mid + 1, bottom, 1, width)
        return out_box, logs_box, None
    if pos == "top":
        mid = top + max(5, (bottom - top) // 2)
        logs_box = (top, mid, 1, width)
        out_box = (mid + 1, bottom, 1, width)
        return out_box, logs_box, None
    if pos == "left":
        col = max(22, width // 2)
        logs_box = (top, bottom, 1, col)
        out_box = (top, bottom, col + 1, width)
        return out_box, logs_box, None
    if pos == "right":
        col = max(22, width // 2)
        out_box = (top, bottom, 1, col)
        logs_box = (top, bottom, col + 1, width)
        return out_box, logs_box, None
    return (top, bottom, 1, width), None, None


def _inner_box(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    top, bottom, left, right = box
    return (top + 1, bottom - 1, left + 1, right - 1)


def _regions_for(pos: str) -> tuple[tuple[int, int, int, int],
                                    tuple[int, int, int, int] | None]:
    saved = _state["logs_pos"]
    try:
        _state["logs_pos"] = pos
        out_box, logs_box, _ = _compute_regions()
    finally:
        _state["logs_pos"] = saved
    return out_box, logs_box


def _opposite_zone(zone: str) -> str:
    return {"top": "bottom", "bottom": "top",
            "left": "right", "right": "left"}.get(zone, zone)


def _draw_snap_preview(zone: str, target: str) -> None:
    if not _state["active"] or zone not in ("top", "bottom", "left", "right"):
        return
    pos = zone if target == "logs" else _opposite_zone(zone)
    out_box, logs_box = _regions_for(pos)
    box = logs_box if target == "logs" else out_box
    if box is None:
        return
    top, bottom, left, right = box
    width = right - left + 1
    height = bottom - top + 1
    if width < 4 or height < 3:
        return
    accent = FG["accent"]
    fill = BG.get("selected", "")
    label = f" \u25a3 Snap: {zone.upper()} "
    out = _raw_out()
    out.write("\x1b[s")
    # bold accent frame
    top_line = c("\u2554" + ("\u2550" * (width - 2)) + "\u2557", BOLD, accent)
    bot_line = c("\u255a" + ("\u2550" * (width - 2)) + "\u255d", BOLD, accent)
    out.write(f"\x1b[{top};{left}H{top_line}")
    out.write(f"\x1b[{bottom};{left}H{bot_line}")
    for y in range(top + 1, bottom):
        out.write(f"\x1b[{y};{left}H" + c("\u2551", BOLD, accent))
        out.write(f"\x1b[{y};{right}H" + c("\u2551", BOLD, accent))
    # centered label
    ly = top + height // 2
    lx = left + max(1, (width - len(label)) // 2)
    out.write(f"\x1b[{ly};{lx}H" + c(label, BOLD, fill, accent))
    out.write("\x1b[u")
    out.flush()


def _snap_zone(x: int, y: int) -> str:
    w = _state["width"]
    h = _state["height"]
    top_d = y
    bot_d = max(1, h - y)
    left_d = x
    right_d = max(1, w - x)
    nearest = min(("top", top_d), ("bottom", bot_d),
                  ("left", left_d), ("right", right_d),
                  key=lambda t: t[1])
    return nearest[0]


def set_mouse_capture(enabled: bool) -> None:
    enabled = bool(enabled)
    if _state["mouse"] == enabled:
        return
    _state["mouse"] = enabled
    if not _state["active"]:
        return
    out = _raw_out()
    if enabled:
        enable_mouse_input()
        out.write("\x1b[?1000h\x1b[?1006h")
    else:
        disable_mouse_input()
        out.write("\x1b[?1000l\x1b[?1006l")
    out.flush()


def get_mouse_capture() -> bool:
    return bool(_state["mouse"])


def set_logs_position(pos: str) -> None:
    if pos not in ("hidden", "bottom", "top", "left", "right"):
        return
    if not _state["debug"] and pos != "hidden":
        return
    _state["logs_pos"] = pos
    if _state["focus"] == "logs" and pos == "hidden":
        _state["focus"] = "output"
    if _state["active"]:
        _full_repaint()


def get_logs_position() -> str:
    return _state["logs_pos"]


# Back-compat shims --------------------------------------------------------

def output_region_bounds() -> tuple[int, int]:
    out_box, _, _ = _compute_regions()
    if out_box is None:
        return (0, -1)
    return out_box[0], out_box[1]


def logs_region_bounds() -> tuple[int, int]:
    _, logs, _ = _compute_regions()
    if logs is None:
        return (0, -1)
    return logs[0], logs[1]


def scroll_region_bounds() -> tuple[int, int]:
    return output_region_bounds()


# ---------------------------------------------------------------------------
# stdio capture (TEE)
# ---------------------------------------------------------------------------


class _TuiStream:
    def __init__(self, real, *, kind: str):
        self._real = real
        self._kind = kind
        self._buf = ""
        self._buf_is_log = False

    def _classify(self) -> bool:
        try:
            from core.logger import is_in_safe_print
            if is_in_safe_print():
                return True
        except Exception:
            pass
        return self._kind == "stderr"

    def write(self, data):
        if not isinstance(data, str):
            try:
                data = data.decode("utf-8", errors="replace")
            except Exception:
                data = str(data)
        if not _state["active"] or _in_chrome_mode():
            try:
                return self._real.write(data)
            except Exception:
                return len(data)
        is_log = self._classify()
        with _io_lock:
            if self._buf and is_log != self._buf_is_log:
                _dispatch_lines(self._buf, partial=True, is_log=self._buf_is_log)
                self._buf = ""
            self._buf_is_log = is_log
            self._buf += data
            if "\n" not in self._buf:
                return len(data)
            head, _, tail = self._buf.rpartition("\n")
            self._buf = tail
            _dispatch_lines(head, is_log=is_log)
        return len(data)

    def flush(self):
        with _io_lock:
            if self._buf:
                _dispatch_lines(self._buf, partial=True, is_log=self._buf_is_log)
                self._buf = ""
        try:
            self._real.flush()
        except Exception:
            pass

    def isatty(self):
        try:
            return self._real.isatty()
        except Exception:
            return False

    def fileno(self):
        return self._real.fileno()

    @property
    def encoding(self):
        return getattr(self._real, "encoding", "utf-8")


def _install_stdio_capture() -> None:
    global _orig_stdout, _orig_stderr
    if _orig_stdout is not None:
        return
    _orig_stdout = sys.stdout
    _orig_stderr = sys.stderr
    sys.stdout = _TuiStream(_orig_stdout, kind="stdout")  # type: ignore
    sys.stderr = _TuiStream(_orig_stderr, kind="stderr")  # type: ignore


def _restore_stdio_capture() -> None:
    global _orig_stdout, _orig_stderr
    try:
        if isinstance(sys.stdout, _TuiStream):
            sys.stdout.flush()
        if isinstance(sys.stderr, _TuiStream):
            sys.stderr.flush()
    except Exception:
        pass
    if _orig_stdout is not None:
        sys.stdout = _orig_stdout
    if _orig_stderr is not None:
        sys.stderr = _orig_stderr
    _orig_stdout = None
    _orig_stderr = None


def _raw_out():
    return _orig_stdout if _orig_stdout is not None else sys.__stdout__


# ---------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------


def _route_for_current_thread() -> list[str]:
    if threading.current_thread() is threading.main_thread():
        return _output_lines
    if _state["debug"]:
        return _log_lines
    return _output_lines


def _dispatch_lines(text: str, *, partial: bool = False, is_log: bool = False) -> None:
    if not text:
        return
    parts = text.split("\n") if not partial else [text]
    touched_output = False
    touched_logs = False
    for part in parts:
        part = part.rstrip("\r")
        if is_log:
            if not _state["debug"]:
                continue
            _log_lines.append(part)
            touched_logs = True
        else:
            _output_lines.append(part)
            touched_output = True
    if touched_output and len(_output_lines) > MAX_BUFFER_LINES:
        del _output_lines[: len(_output_lines) - MAX_BUFFER_LINES]
    if touched_logs and len(_log_lines) > MAX_BUFFER_LINES:
        del _log_lines[: len(_log_lines) - MAX_BUFFER_LINES]
    if _dialog_depth == 0:
        if touched_output:
            _render_output()
        if touched_logs:
            _render_logs()
        if touched_output or touched_logs:
            _restore_input_cursor()


@contextlib.contextmanager
def command_scope():
    yield


def _in_chrome_mode() -> bool:
    return bool(getattr(_thread_local, "chrome", False))


# ---------------------------------------------------------------------------
# buffer management
# ---------------------------------------------------------------------------


def _append_lines(target: list[str], text: str, *, partial: bool = False) -> None:
    if not text:
        return
    parts = text.split("\n") if not partial else [text]
    for part in parts:
        target.append(part.rstrip("\r"))
    if len(target) > MAX_BUFFER_LINES:
        del target[: len(target) - MAX_BUFFER_LINES]


def _wrap_to_width(line: str, width: int) -> list[str]:
    if width <= 1:
        return [line]
    visible = _ansi_re.sub("", line)
    if len(visible) <= width:
        return [line] if line else [""]
    out: list[str] = []
    buf = ""
    count = 0
    i = 0
    while i < len(line):
        m = _ansi_re.match(line, i)
        if m:
            buf += m.group(0)
            i = m.end()
            continue
        buf += line[i]
        count += 1
        i += 1
        if count >= width:
            out.append(buf)
            buf = ""
            count = 0
    if buf or not out:
        out.append(buf)
    return out


def _visible_window(buffer: list[str], scroll: int,
                    rows: int, width: int) -> list[str]:
    if rows <= 0:
        return []
    needed = rows + scroll
    visual: list[str] = []
    for raw in reversed(buffer):
        wrapped = _wrap_to_width(raw, width)
        visual = wrapped + visual
        if len(visual) >= needed:
            break
    end = len(visual) - scroll
    end = max(0, min(end, len(visual)))
    start = max(0, end - rows)
    window = visual[start:end]
    if len(window) < rows:
        window = [""] * (rows - len(window)) + window
    return window


@_functools.lru_cache(maxsize=16384)
def _visual_row_count(line: str, width: int) -> int:
    return len(_wrap_to_width(line, width))


def _total_visual_rows(buffer: list[str], width: int) -> int:
    return sum(_visual_row_count(l, width) for l in buffer)


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def _render_region(buffer: list[str], scroll: int,
                   box: tuple[int, int, int, int],
                   region_id: str | None = None, *, dim: bool = False) -> None:
    top, bottom, left, right = box
    rows = bottom - top + 1
    width = right - left + 1
    window = _visible_window(buffer, scroll, rows, width)
    out = _raw_out()
    out.write("\x1b[s")
    pad_template = " " * width
    for i, line in enumerate(window):
        out.write(f"\x1b[{top + i};{left}H{pad_template}")
        if line:
            if dim:
                line = c(_strip_ansi(line), DIM, FG["subtle"])
            out.write(f"\x1b[{top + i};{left}H{line}")
    if scroll > 0 and not dim:
        marker = c(f" \u2191 {scroll} ", DIM, FG["muted"])
        mx = max(left, right - 8)
        out.write(f"\x1b[{bottom};{mx}H{marker}")
    out.write("\x1b[u")
    out.flush()
    if not dim and region_id is not None and _sel is not None and _sel["region"] == region_id:
        _overlay_selection_region(buffer, scroll, box, region_id)


def _render_output() -> None:
    if not _state["active"]:
        return
    out_box, _, _ = _compute_regions()
    if out_box is None:
        return
    _render_region(_output_lines, _output_scroll, _inner_box(out_box), "output")
    _draw_frame(out_box, "Output", focused=(_state["focus"] == "output"),
                win_id="output")


def _render_logs() -> None:
    if not _state["active"]:
        return
    _, logs_box, _ = _compute_regions()
    if logs_box is None:
        return
    _render_region(_log_lines, _log_scroll, _inner_box(logs_box), "logs")
    _draw_frame(logs_box, "Logs", focused=(_state["focus"] == "logs"),
                win_id="logs")


def _draw_frame(box: tuple[int, int, int, int], title: str,
                focused: bool = False, win_id: str | None = None,
                *, dim: bool = False) -> None:
    if not _state["active"]:
        return
    top, bottom, left, right = box
    width = right - left + 1
    height = bottom - top + 1
    if width < 4 or height < 3:
        return
    border = FG.get("border", FG["subtle"])
    accent = FG["accent"]
    if dim:
        edge_color = FG["subtle"]
        title_color = FG["subtle"]
    else:
        edge_color = accent if focused else border
        title_color = accent if focused else FG.get("header", FG["fg"])
    movable = win_id is not None and not dim
    grip = "\u2237 " if movable else ""
    label = f" {grip}{title} "
    if len(label) + 4 > width:
        label = (label[:max(0, width - 4)])
    title_styled = c(label, BOLD, title_color)
    bar_len = max(0, width - 2 - len(label))
    left_pad = 1
    right_pad = bar_len - left_pad if bar_len >= left_pad else 0
    top_line = (
        c("\u250c", edge_color)
        + c("\u2500" * left_pad, edge_color)
        + title_styled
        + c("\u2500" * right_pad, edge_color)
        + c("\u2510", edge_color)
    )
    bottom_line = c("\u2514" + ("\u2500" * (width - 2)) + "\u2518", edge_color)
    out = _raw_out()
    out.write("\x1b[s")
    out.write(f"\x1b[{top};{left}H{top_line}")
    for y in range(top + 1, bottom):
        out.write(f"\x1b[{y};{left}H" + c("\u2502", edge_color))
        out.write(f"\x1b[{y};{right}H" + c("\u2502", edge_color))
    out.write(f"\x1b[{bottom};{left}H{bottom_line}")
    if win_id is not None and width >= 10:
        buttons = _frame_button_cells(box, win_id)
        for bx_start, _bx_end, kind in buttons:
            glyph = "_" if kind.startswith("min") else "x"
            seg = (c("[", border)
                   + c(glyph, BOLD, accent)
                   + c("]", border))
            out.write(f"\x1b[{top};{bx_start}H{seg}")
    out.write("\x1b[u")
    out.flush()


def _frame_button_cells(box: tuple[int, int, int, int],
                        win_id: str) -> list[tuple[int, int, str]]:
    _top, _bottom, _left, right = box
    win = _windows.get(win_id, {})
    cells: list[tuple[int, int, str]] = []
    x_end = right - 1
    start = x_end - 2
    cells.append((start, x_end, f"min:{win_id}"))
    if win.get("closable"):
        x_end2 = start - 2
        start2 = x_end2 - 2
        cells.append((start2, x_end2, f"close:{win_id}"))
    return cells


def _render_target(target: list[str]) -> None:
    if target is _output_lines:
        _render_output()
    else:
        _render_logs()


def render_all() -> None:
    if not _state["active"]:
        return
    _render_output()
    _render_logs()
    _render_taskbar()


def _render_taskbar() -> None:
    global _taskbar_hits
    _taskbar_hits = []
    row = _taskbar_row()
    if row is None or not _state["active"]:
        return
    width = _state["width"]
    out = _raw_out()
    out.write("\x1b[s")
    out.write(f"\x1b[{row};1H\x1b[2K")
    border = FG.get("border", FG["subtle"])
    accent = FG["accent"]
    prefix = c(" Minimized ", DIM, FG["muted"])
    out.write(f"\x1b[{row};1H{prefix}")
    x = 1 + len(" Minimized ") + 1
    for wid in _window_order:
        win = _windows.get(wid)
        if not win or not win["minimized"]:
            continue
        text = f" \u25a3 {win['title']} "
        chip_w = len(text) + 2
        if x + chip_w > width:
            break
        chip = c("[", border) + c(text, BOLD, accent) + c("]", border)
        out.write(f"\x1b[{row};{x}H{chip}")
        _taskbar_hits.append((x, x + chip_w - 1, wid))
        x += chip_w + 1
    out.write("\x1b[u")
    out.flush()


def set_window_minimized(win_id: str, value: bool) -> None:
    win = _windows.get(win_id)
    if win is None:
        return
    win["minimized"] = bool(value)
    if value:
        if _state["focus"] == win_id:
            other = "logs" if win_id == "output" else "output"
            if not _windows[other]["minimized"]:
                _state["focus"] = other
    else:
        _focus_window(win_id)
    if _state["active"]:
        _full_repaint()


def toggle_window_minimized(win_id: str) -> None:
    win = _windows.get(win_id)
    if win is None:
        return
    set_window_minimized(win_id, not win["minimized"])


MODAL_CANCEL = object()

_MODAL_ACCENT = {
    "info": "info",
    "confirm": "primary",
    "question": "primary",
    "warn": "warn",
    "error": "error",
    "success": "success",
}


def _build_modal_box_lines(
    content: list[str],
    *,
    title: str,
    kind: str,
    align: str = "left",
    min_width: int = 30,
) -> list[str]:
    sw, _ = term_size()
    content_w = max((_visible_len(line) for line in content), default=0)
    inner_w = max(content_w, _visible_len(title) + 6, min_width)
    box_w = min(inner_w + 4, max(30, sw - 1))
    accent = FG.get(_MODAL_ACCENT.get(kind, "primary"), FG["accent"])
    border = FG.get("border", FG["subtle"])

    label = f"─ {title} "
    label_styled = c(label, BOLD, accent)
    close = c("[", border) + c("x", BOLD, accent) + c("]", border)
    bar_fill = max(0, box_w - 2 - _visible_len(label_styled) - _visible_len(close))
    top_line = (
        c("┌", accent)
        + label_styled
        + c("─" * bar_fill, accent)
        + close
        + c("┐", accent)
    )

    text_w = box_w - 4
    lines = [top_line]
    for line in content:
        plain_w = _visible_len(line)
        if align == "center" and plain_w < text_w:
            lead = (text_w - plain_w) // 2
        else:
            lead = 0
        trail = max(0, text_w - plain_w - lead)
        lines.append(
            c("│", accent)
            + " "
            + (" " * lead)
            + line
            + (" " * trail)
            + " "
            + c("│", accent)
        )
    lines.append(c("└" + ("─" * (box_w - 2)) + "┘", accent))
    return lines


def _write_inline_block(lines: list[str], *, previous: int) -> None:
    out = sys.stdout
    if previous:
        out.write(f"\x1b[{previous}A")
    for line in lines:
        out.write("\x1b[2K\r")
        out.write(line + "\n")
    for _ in range(max(0, previous - len(lines))):
        out.write("\x1b[2K\r\n")
    out.flush()


def _inline_modal_hits(lines: list[str], *, box_top: int) -> dict:
    box_h = len(lines)
    box_w = _visible_len(lines[0]) if lines else 30
    left = 1
    right = left + box_w - 1
    top = box_top
    bottom = top + box_h - 1
    close_w = 3
    close_x0 = right - close_w
    close_x1 = close_x0 + close_w - 1
    return {
        "top": top,
        "left": left,
        "right": right,
        "bottom": bottom,
        "title_y": top,
        "close_x0": close_x0,
        "close_x1": close_x1,
        "w": box_w,
        "h": box_h,
    }


def _inline_mouse_xy(key_str: str) -> tuple[int, int]:
    parts = key_str.split(":")
    try:
        return int(parts[-2]), int(parts[-1])
    except (ValueError, IndexError):
        return 0, 0


def _run_inline_modal(
    *,
    title: str,
    kind: str,
    body,
    on_key,
    on_click=None,
    align: str = "left",
    min_width: int = 30,
) -> object:
    from launcher.cli.terminal import hide_cursor, query_cursor_position, show_cursor

    enable_mouse_input()
    hide_cursor()
    rendered = 0
    box_top: int | None = None
    hits: dict = {}
    result = None
    try:
        while True:
            lines = _build_modal_box_lines(
                body(), title=title, kind=kind, align=align, min_width=min_width,
            )
            _write_inline_block(lines, previous=rendered)
            rendered = len(lines)

            cursor = query_cursor_position()
            if cursor is not None:
                box_top = max(1, cursor[0] - rendered)
            elif box_top is None:
                _, height = term_size()
                box_top = max(1, height - rendered + 1)
            hits = _inline_modal_hits(lines, box_top=box_top)

            k = keys.read_key()
            if k == keys.KEY_RESIZE:
                box_top = None
                continue
            if k.startswith(("wheel_", "mouse_move:", "mouse_drag:", "mouse_up:")):
                continue
            if k.startswith("mouse_down:"):
                x, y = _inline_mouse_xy(k)
                if y == hits.get("title_y") and hits.get("close_x0", 0) <= x <= hits.get("close_x1", 0):
                    done, value = on_key(keys.KEY_ESC)
                    if done:
                        result = value
                        break
                    continue
                if (
                    on_click is not None
                    and hits.get("top", 0) < y < hits.get("bottom", 0)
                    and hits.get("left", 0) < x < hits.get("right", 0)
                ):
                    rel_row = y - (hits["top"] + 1)
                    rel_col = x - (hits["left"] + 2)
                    res = on_click(rel_row, rel_col)
                    if res is not None:
                        done, value = res
                        if done:
                            result = value
                            break
                continue
            done, value = on_key(k)
            if done:
                result = value
                break
    except KeyboardInterrupt:
        result = None
    finally:
        show_cursor()
        disable_mouse_input()
        if rendered:
            sys.stdout.write("\n")
            sys.stdout.flush()
    return result


def _paint_modal_backdrop() -> None:
    if not _state["active"]:
        return
    out = _raw_out()
    out.write("\x1b[H")
    out.flush()
    _redraw_header_chrome()
    out_box, logs_box, _ = _compute_regions()
    for box, buf, scroll, title in (
        (out_box, _output_lines, _output_scroll, "Output"),
        (logs_box, _log_lines, _log_scroll, "Logs"),
    ):
        if box is None:
            continue
        _render_region(buf, scroll, _inner_box(box), None, dim=True)
        _draw_frame(box, title, focused=False, win_id=None, dim=True)
    _render_taskbar()
    draw_footer(new_tip=False)


def _modal_geometry(content: list[str], title: str,
                    anchor: tuple[int, int] | None,
                    min_width: int = 30) -> dict:
    sw = _state["width"]
    sh = _state["height"]
    content_w = max((_visible_len(l) for l in content), default=0)
    inner_w = max(content_w, _visible_len(title) + 6, min_width)
    box_w = min(inner_w + 4, sw - 6)
    box_h = len(content) + 2
    if _state.get("standalone"):
        max_h = sh - 2
    else:
        max_h = sh - HEADER_ROWS - FOOTER_ROWS - 2
    if box_h > max_h:
        box_h = max(5, max_h)
    if anchor is None:
        left = max(2, (sw - box_w) // 2 + 1)
        if _state.get("standalone"):
            chrome_top = 1
            chrome_bottom = sh
        else:
            chrome_top = HEADER_ROWS + 1
            chrome_bottom = sh - FOOTER_ROWS
        top = max(chrome_top, (chrome_top + chrome_bottom - box_h) // 2)
    else:
        top, left = anchor
        top = max(HEADER_ROWS + 1, min(top, sh - FOOTER_ROWS - box_h))
        left = max(2, min(left, sw - box_w - 1))
    return {"top": top, "left": left, "w": box_w, "h": box_h,
            "right": left + box_w - 1, "bottom": top + box_h - 1}


def _draw_floating_modal(content: list[str], *, title: str, kind: str,
                         geo: dict, align: str = "left") -> dict:
    top, left = geo["top"], geo["left"]
    box_w, box_h = geo["w"], geo["h"]
    right = left + box_w - 1
    bottom = top + box_h - 1
    accent = FG.get(_MODAL_ACCENT.get(kind, "primary"), FG["accent"])
    bg = BG.get("dialog", "")
    border = FG.get("border", FG["subtle"])
    shadow = BG.get("dim", "")
    out = _raw_out()
    out.write("\x1b[s")
    shadow_cell = shadow + " " + RESET
    if shadow:
        for y in range(top + 1, bottom + 2):
            if y <= _state["height"] - FOOTER_ROWS:
                out.write(f"\x1b[{y};{right + 1}H{shadow_cell}")
        srow = bottom + 1
        if srow <= _state["height"] - FOOTER_ROWS:
            out.write(f"\x1b[{srow};{left + 1}H{shadow + (' ' * box_w) + RESET}")
    grip = "\u2237 " if _state.get("modal_draggable", True) else ""
    label = f" {grip}{title} "
    if len(label) + 6 > box_w:
        label = label[:max(0, box_w - 6)]
    title_styled = c(label, BOLD, accent)
    close_w = 3
    bar_fill = max(0, box_w - 7 - _visible_len(title_styled))
    close_x = right - close_w
    top_line = (
        bg + c("\u250c", accent)
        + c("\u2500", accent)
        + title_styled
        + c("\u2500" * bar_fill, accent)
        + c(" ", accent)
        + c("[", border) + c("x", BOLD, accent) + c("]", border)
        + bg + c("\u2510", accent) + RESET
    )
    out.write(f"\x1b[{top};{left}H{top_line}")
    text_w = box_w - 3
    body_rows = box_h - 2
    row_offsets: list[int] = []
    for i in range(body_rows):
        line = content[i] if i < len(content) else ""
        plain_w = _visible_len(line)
        if align == "center" and plain_w < text_w:
            lead = (text_w - plain_w) // 2
        else:
            lead = 0
        row_offsets.append(lead)
        trail = max(0, text_w - plain_w - lead)
        row = (bg + c("\u2502", accent) + bg + " "
               + (" " * lead) + line + bg + (" " * trail)
               + c("\u2502", accent) + RESET)
        out.write(f"\x1b[{top + 1 + i};{left}H{row}")
    bottom_line = bg + c("\u2514" + ("\u2500" * (box_w - 2)) + "\u2518", accent) + RESET
    out.write(f"\x1b[{bottom};{left}H{bottom_line}")
    out.write("\x1b[u")
    out.flush()
    return {
        "top": top, "left": left, "right": right, "bottom": bottom,
        "title_y": top, "title_x0": left, "title_x1": right,
        "close_x0": close_x, "close_x1": close_x + close_w - 1,
        "row_offsets": row_offsets,
        "w": box_w, "h": box_h,
    }


def run_modal(*, title: str, kind: str, body, on_key, on_click=None,
              align: str = "left", min_width: int = 30) -> object:
    if _state.get("standalone"):
        return _run_inline_modal(
            title=title,
            kind=kind,
            body=body,
            on_key=on_key,
            on_click=on_click,
            align=align,
            min_width=min_width,
        )

    backdrop = _state.get("modal_backdrop")
    standalone = False
    external = backdrop is not None and not _state["active"]
    if not _state["active"] and not external:
        while True:
            k = keys.read_key()
            if k.startswith(("mouse_", "wheel_")):
                continue
            done, result = on_key(k)
            if done:
                return result
    if external:
        enable_mouse_input()
        _refresh_size()
        _state["active"] = True
    anchor: tuple[int, int] | None = None
    drag: dict | None = None
    draggable = bool(_state.get("modal_draggable", True))
    keys._mouse_trace.clear()
    hide_result = None
    out = _raw_out()
    out.write("\x1b[?25l")
    out.flush()

    animator = _state.get("modal_animator") if external else None
    state = {"hits": {}, "footprint": None}
    paint_backdrop = backdrop if external else _paint_modal_backdrop

    def _mouse_xy(key_str: str) -> tuple[int, int]:
        parts = key_str.split(":")
        try:
            return int(parts[-2]), int(parts[-1])
        except (ValueError, IndexError):
            return 0, 0

    def _render(*, full: bool, paint_back: bool = True) -> None:
        content = body()
        geo = _modal_geometry(content, title, anchor, min_width)
        footprint = (geo["top"], geo["left"], geo["w"], geo["h"])
        if paint_back and (full or footprint != state["footprint"]):
            paint_backdrop()
        state["hits"] = _draw_floating_modal(content, title=title, kind=kind,
                                             geo=geo, align=align)
        state["footprint"] = footprint

    try:
        _render(full=True)
        while True:
            k = keys.read_key(_ANIM_INTERVAL) if animator is not None else keys.read_key()
            if k == keys.KEY_TIMEOUT:
                if animator is not None and animator():
                    _render(full=False, paint_back=False)
                continue
            if k == keys.KEY_RESIZE:
                _refresh_size()
                _render(full=True)
                continue
            hits = state["hits"]
            if k.startswith("mouse_down:"):
                x, y = _mouse_xy(k)
                if (y == hits["title_y"]
                        and hits["close_x0"] <= x <= hits["close_x1"]):
                    done, result = on_key(keys.KEY_ESC)
                    if done:
                        hide_result = result
                        break
                    _render(full=False)
                elif (draggable
                        and y == hits["title_y"]
                        and hits["title_x0"] <= x <= hits["title_x1"]):
                    drag = {"dx": x - hits["left"], "dy": y - hits["top"]}
                elif (on_click is not None
                        and hits["top"] < y < hits["bottom"]
                        and hits["left"] < x < hits["right"]):
                    rel_row = y - (hits["top"] + 1)
                    rel_col = x - (hits["left"] + 2)
                    res = on_click(rel_row, rel_col)
                    if res is not None:
                        done, result = res
                        if done:
                            hide_result = result
                            break
                        _render(full=False)
                continue
            if k.startswith("mouse_drag:"):
                if drag is not None:
                    x, y = _mouse_xy(k)
                    anchor = (y - drag["dy"], x - drag["dx"])
                    _render(full=True)
                continue
            if k.startswith("mouse_up:"):
                drag = None
                continue
            if k.startswith(("wheel_", "mouse_move:")):
                continue
            done, result = on_key(k)
            if done:
                hide_result = result
                break
            _render(full=False)
    finally:
        out.write("\x1b[?25h")
        out.flush()
        if external:
            _state["active"] = False
            disable_mouse_input()
            backdrop()
        else:
            _full_repaint()
    return hide_result


def _full_repaint() -> None:
    if not _state["active"]:
        return
    out = _raw_out()
    out.write("\x1b[2J\x1b[H")
    out.flush()
    _redraw_header_chrome()
    render_all()
    draw_footer(new_tip=False)
    _restore_input_cursor()


def full_repaint() -> None:
    _full_repaint()


def pump_idle(timeout: float = 0.2) -> str:
    if not _state["active"]:
        return keys.read_key(timeout)
    k = keys.read_key(timeout)
    if k in (keys.KEY_TIMEOUT, keys.KEY_IGNORE):
        return k
    if k == keys.KEY_RESIZE:
        _refresh_size()
        _full_repaint()
        return keys.KEY_IGNORE
    if k.startswith((keys.KEY_WHEEL_UP_PREFIX, keys.KEY_WHEEL_DOWN_PREFIX)):
        x, y = _parse_xy(k)
        _wheel(x, y, WHEEL_STEP if k.startswith(keys.KEY_WHEEL_UP_PREFIX) else -WHEEL_STEP)
        _restore_input_cursor()
        return keys.KEY_IGNORE
    if k.startswith((keys.KEY_MOUSE_DOWN_PREFIX, keys.KEY_MOUSE_DRAG_PREFIX,
                     keys.KEY_MOUSE_UP_PREFIX)):
        try:
            _, _, xs, ys = k.split(":", 3)
            mx, my = int(xs), int(ys)
        except (ValueError, IndexError):
            return keys.KEY_IGNORE
        if k.startswith(keys.KEY_MOUSE_DOWN_PREFIX):
            _on_mouse_down(mx, my)
        elif k.startswith(keys.KEY_MOUSE_DRAG_PREFIX):
            _on_mouse_drag(mx, my)
        else:
            _on_mouse_up(mx, my)
        _restore_input_cursor()
        return keys.KEY_IGNORE
    if k.startswith(keys.KEY_MOUSE_MOVE_PREFIX):
        return keys.KEY_IGNORE
    if k == keys.KEY_PGUP:
        _scroll_focused(+10)
        _restore_input_cursor()
        return keys.KEY_IGNORE
    if k == keys.KEY_PGDN:
        _scroll_focused(-10)
        _restore_input_cursor()
        return keys.KEY_IGNORE
    if k == keys.KEY_CTRL_C:
        if _sel is not None:
            text = _selected_text()
            if text:
                ok = clipboard_set(text)
                status = (f"Copied {len(text)} chars" if ok
                          else f"Copy FAILED ({len(text)} chars)")
                draw_footer(prompt_text="", new_tip=False, status=status)
            _clear_selection()
            _restore_input_cursor()
            return keys.KEY_IGNORE
        return keys.KEY_CTRL_C
    if k == keys.KEY_ESC:
        if _sel is not None:
            _clear_selection()
            _restore_input_cursor()
            return keys.KEY_IGNORE
        return keys.KEY_ESC
    return k


def remap_buffered_colors(replacements: dict[str, str]) -> None:
    if not replacements:
        return
    with _io_lock:
        for buf in (_output_lines, _log_lines):
            for i, line in enumerate(buf):
                new_line = line
                for old, new in replacements.items():
                    if old and old != new and old in new_line:
                        new_line = new_line.replace(old, new)
                if new_line is not line:
                    buf[i] = new_line


def clear_scroll_region() -> None:
    global _output_scroll
    with _io_lock:
        _output_lines.clear()
        _output_scroll = 0
    if _state["active"]:
        _render_output()
        _restore_input_cursor()


def clear_logs() -> None:
    global _log_scroll
    with _io_lock:
        _log_lines.clear()
        _log_scroll = 0
    if _state["active"]:
        _render_logs()
        _restore_input_cursor()


# ---------------------------------------------------------------------------
# header / footer
# ---------------------------------------------------------------------------


_header_args = {"version": "", "debug": False, "scopes": {}, "account": None, "account_type": None}


def draw_header(*, version, debug, scopes, account, account_type) -> None:
    _header_args.update({
        "version": version, "debug": debug, "scopes": scopes,
        "account": account, "account_type": account_type,
    })
    _state["debug"] = bool(debug)
    _redraw_header_chrome()


def _redraw_header_chrome() -> None:
    if not _state["active"]:
        return
    version = _header_args["version"]
    debug = _header_args["debug"]
    scopes = _header_args["scopes"] or {}
    account = _header_args["account"]
    account_type = _header_args["account_type"]

    mode = "debug" if debug else "user"
    pieces: list[str] = []
    pieces.append(c(f"Histolauncher {version}", BOLD, FG["header"]))
    pieces.append(c(f"(cli \u00b7 {mode})", DIM, FG["muted"]))
    pieces.append(c("\u00b7", FG["subtle"]))
    pieces.append(c("Versions ", FG["muted"]) + c(scopes.get("versions") or "default", FG["tag"]))
    pieces.append(c("\u00b7", FG["subtle"]))
    pieces.append(c("Addons ", FG["muted"]) + c(scopes.get("addons") or "default", FG["tag"]))
    pieces.append(c("\u00b7", FG["subtle"]))
    pieces.append(c("Settings ", FG["muted"]) + c(scopes.get("settings") or "default", FG["tag"]))
    if account:
        acc_text = c(account, FG["accent"])
        if account_type:
            acc_text += " " + c(f"({account_type})", DIM, FG["muted"])
        pieces.append(c("\u00b7", FG["subtle"]))
        pieces.append(c("Account ", FG["muted"]) + acc_text)
    text = "  ".join(pieces)
    _state["header_text"] = _ansi_re.sub("", " " + text)
    width = _state["width"]
    bar = c("\u2500" * width, FG.get("border", FG["subtle"]))
    out = _raw_out()
    out.write("\x1b[s")
    out.write("\x1b[1;1H\x1b[2K ")
    out.write(text)
    out.write("\x1b[2;1H\x1b[2K")
    out.write(bar)
    out.write("\x1b[u")
    out.flush()


def draw_footer(*, prompt_text: str = "", new_tip: bool = False,
                status: str | None = None) -> None:
    if not _state["active"]:
        return
    h = _state["height"]
    w = _state["width"]
    bar = c("\u2500" * w, FG.get("border", FG["subtle"]))
    if new_tip or not _state["tip"]:
        _state["tip"] = random.choice(TIPS)
    out = _raw_out()
    out.write("\x1b[s")
    out.write(f"\x1b[{h - 2};1H\x1b[2K{bar}")
    out.write(f"\x1b[{h - 1};1H\x1b[2K")
    out.write(c(_state["prompt"], FG["accent"]) + prompt_text)
    out.write(f"\x1b[{h};1H\x1b[2K")
    if status:
        out.write("  " + c(status, BOLD, FG["accent"]))
    else:
        out.write("  " + c("Tip: ", DIM, FG["muted"]) + c(_state["tip"], DIM, FG["muted"]))
    out.write("\x1b[u")
    out.flush()


def _restore_input_cursor() -> None:
    if not _state["active"]:
        return
    h = _state["height"]
    out = _raw_out()
    out.write(f"\x1b[{h - 1};1H")
    out.flush()


# ---------------------------------------------------------------------------
# dialog scope
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def dialog_scope():
    global _dialog_depth
    if not _state["active"]:
        yield
        return
    _dialog_depth += 1
    _thread_local.chrome = True
    out = _raw_out()
    out_box, _, _ = _compute_regions()
    if out_box is None:
        top, bottom = _chrome_bounds()
        out_box = (top, bottom, 1, _state["width"])
    top, bottom, left, right = out_box
    out.write("\x1b[s")
    pad = " " * (right - left + 1)
    for row in range(top, bottom + 1):
        out.write(f"\x1b[{row};{left}H{pad}")
    out.write(f"\x1b[{top};{left}H")
    out.flush()
    try:
        yield
    finally:
        _thread_local.chrome = False
        _dialog_depth -= 1
        if _dialog_depth <= 0:
            _dialog_depth = 0
            with _io_lock:
                _full_repaint()


def begin_dialog() -> None:
    global _dialog_depth
    if not _state["active"]:
        return
    _dialog_depth += 1
    _thread_local.chrome = True
    out = _raw_out()
    out_box, _, _ = _compute_regions()
    if out_box is None:
        top, bottom = _chrome_bounds()
        out_box = (top, bottom, 1, _state["width"])
    top, bottom, left, right = out_box
    out.write("\x1b[s")
    pad = " " * (right - left + 1)
    for row in range(top, bottom + 1):
        out.write(f"\x1b[{row};{left}H{pad}")
    out.write(f"\x1b[{top};{left}H")
    out.flush()


def end_dialog() -> None:
    global _dialog_depth
    if not _state["active"]:
        return
    _thread_local.chrome = False
    _dialog_depth -= 1
    if _dialog_depth <= 0:
        _dialog_depth = 0
        with _io_lock:
            _full_repaint()


# ---------------------------------------------------------------------------
# echo of typed commands
# ---------------------------------------------------------------------------


def echo_command(prompt: str, buf: str, coloured_buf: str) -> None:
    with _io_lock:
        _append_lines(_output_lines, c(prompt, FG["accent"]) + coloured_buf)
        _render_output()
        _restore_input_cursor()


# ---------------------------------------------------------------------------
# input line
# ---------------------------------------------------------------------------


def read_input_line(history=None, *, validator=None, suggester=None):
    if not _state["active"]:
        try:
            return input(_state["prompt"])
        except (EOFError, KeyboardInterrupt):
            return None

    refresh_layout()
    history = history if history is not None else []
    buf = ""
    cursor = 0
    hist_idx = len(history)

    S = {
        "payload": None,
        "sel": 0,
        "scroll": 0,
        "dismissed": False,
        "prev_rows": 0,
        "geom": None,
    }

    def _colourise(text: str) -> str:
        if not text:
            return ""
        if validator is None:
            return c(text, FG["fg"])
        i = 0
        while i < len(text) and not text[i].isspace():
            i += 1
        first = text[:i]
        rest = text[i:]
        if not first:
            return rest
        try:
            ok = bool(validator(first))
        except Exception:
            ok = False
        if ok:
            colour = FG.get("input") or FG.get("header") or "\x1b[97m"
        else:
            colour = FG.get("error") or "\x1b[31m"
        return c(first, colour) + rest

    def _repaint_input() -> None:
        h = _state["height"]
        prompt_w = _visible_len(_state["prompt"])
        out = _raw_out()
        with _io_lock:
            out.write(f"\x1b[{h - 1};1H\x1b[2K")
            out.write(c(_state["prompt"], FG["accent"]) + _colourise(buf))
            if _sel is not None and _sel["region"] == "input":
                a, b = _norm_sel()
                col_s = max(0, min(a[1], len(buf)))
                col_e = max(col_s, min(b[1], len(buf)))
                if col_e > col_s:
                    seg = buf[col_s:col_e]
                    out.write(f"\x1b[{h - 1};{1 + prompt_w + col_s}H")
                    out.write(INVERT + seg + RESET)
            else:
                ghost = _ghost_text()
                if ghost:
                    out.write(f"\x1b[{h - 1};{1 + prompt_w + cursor}H")
                    out.write(DIM + ITALIC + FG["subtle"] + ghost + RESET)
            out.write(f"\x1b[{h - 1};{1 + prompt_w + cursor}H")
            out.flush()

    def _ghost_text() -> str:
        payload = S["payload"]
        if payload is None or _sel is not None or not payload["items"]:
            return ""
        if cursor != len(buf):
            return ""
        item = payload["items"][max(0, min(S["sel"], len(payload["items"]) - 1))]
        insert = item["insert"]
        start = payload["start"]
        prefix = buf[start:cursor]
        if not insert.lower().startswith(prefix.lower()):
            return ""
        return insert[len(prefix):]


    def _input_getter():
        return buf

    def _recompute_sugg() -> None:
        if suggester is None or S["dismissed"] or _sel is not None:
            S["payload"] = None
            return
        try:
            payload = suggester(buf, cursor)
        except Exception:
            payload = None
        S["payload"] = payload
        if payload is None:
            S["sel"] = 0
            S["scroll"] = 0
        elif S["sel"] >= len(payload["items"]):
            S["sel"] = 0
            S["scroll"] = 0

    def _sugg_metrics(payload):
        items = payload["items"]
        h = _state["height"]
        w = _state["width"]
        rows = min(len(items), SUGG_MAX_ROWS, max(0, (h - 2) - (HEADER_ROWS + 1)))
        if rows <= 0:
            return None
        label_w = min(max(len(it["label"]) for it in items), SUGG_MAX_LABEL)
        has_desc = any(it["desc"] for it in items)
        desc_w = 0
        if has_desc:
            desc_w = min(max((len(it["desc"]) for it in items), default=0),
                         SUGG_MAX_DESC)
        inner = 2 + label_w + ((2 + desc_w) if desc_w else 0)
        width = min(inner + 1, max(8, w - 2))
        prompt_w = _visible_len(_state["prompt"])
        left = 1 + prompt_w + payload["start"]
        left = max(1, min(left, w - width + 1))
        top = (h - 2) - rows + 1
        return rows, top, left, width, label_w, desc_w

    def _restore_under_sugg() -> None:
        if S["prev_rows"]:
            _render_output()
            _render_logs()
            draw_footer(prompt_text="")
            S["prev_rows"] = 0
            S["geom"] = None

    def _paint_sugg() -> None:
        payload = S["payload"]
        if payload is None:
            _restore_under_sugg()
            return
        metrics = _sugg_metrics(payload)
        if metrics is None:
            _restore_under_sugg()
            return
        rows, top, left, width, label_w, desc_w = metrics
        items = payload["items"]
        n = len(items)
        sel = max(0, min(S["sel"], n - 1))
        scroll = S["scroll"]
        if sel < scroll:
            scroll = sel
        elif sel >= scroll + rows:
            scroll = sel - rows + 1
        scroll = max(0, min(scroll, max(0, n - rows)))
        S["sel"], S["scroll"] = sel, scroll
        prev = S["geom"]
        moved = prev is not None and (
            prev["top"] != top or prev["left"] != left
            or prev["width"] != width or prev["rows"] != rows
        )
        if moved or rows < S["prev_rows"]:
            _render_output()
            _render_logs()
            draw_footer(prompt_text="")
        out = _raw_out()
        with _io_lock:
            for r in range(rows):
                item = items[scroll + r]
                selected = (scroll + r) == sel
                y = top + r
                marker = "\u203a " if selected else "  "
                label = item["label"]
                if len(label) > label_w:
                    label = label[: label_w - 1] + "\u2026"
                label = label.ljust(label_w)
                bg = BG["selected"] if selected else BG.get("dialog", BG["panel"])
                lbl_col = FG["accent"] if selected else FG["fg"]
                line = bg + lbl_col + marker + label
                used = 2 + label_w
                if desc_w:
                    desc = item["desc"]
                    if len(desc) > desc_w:
                        desc = desc[: desc_w - 1] + "\u2026"
                    line += FG["muted"] + "  " + desc.ljust(desc_w)
                    used += 2 + desc_w
                if used < width:
                    line += bg + " " * (width - used)
                line += RESET
                out.write(f"\x1b[{y};{left}H" + line)
            out.flush()
        S["prev_rows"] = rows
        S["geom"] = {"top": top, "left": left, "width": width,
                     "rows": rows, "scroll": scroll}

    def _paint() -> None:
        _paint_sugg()
        _repaint_input()

    def _sugg_index_at(mx: int, my: int):
        geom = S["geom"]
        if geom is None or S["payload"] is None:
            return None
        top, left, width, rows, scroll = (
            geom["top"], geom["left"], geom["width"], geom["rows"], geom["scroll"],
        )
        if top <= my <= top + rows - 1 and left <= mx <= left + width - 1:
            idx = scroll + (my - top)
            if 0 <= idx < len(S["payload"]["items"]):
                return idx
        return None

    def _sugg_scroll(delta: int) -> None:
        payload = S["payload"]
        geom = S["geom"]
        if payload is None or geom is None:
            return
        rows = geom["rows"]
        n = len(payload["items"])
        S["scroll"] = max(0, min(S["scroll"] + delta, max(0, n - rows)))
        if S["sel"] < S["scroll"]:
            S["sel"] = S["scroll"]
        elif S["sel"] >= S["scroll"] + rows:
            S["sel"] = S["scroll"] + rows - 1

    def _sugg_insert() -> None:
        nonlocal buf, cursor
        payload = S["payload"]
        if payload is None:
            return
        item = payload["items"][max(0, min(S["sel"], len(payload["items"]) - 1))]
        insert = item["insert"]
        if " " in insert:
            insert = '"' + insert + '"'
        start = payload["start"]
        buf = buf[:start] + insert + " " + buf[cursor:]
        cursor = start + len(insert) + 1
        S["dismissed"] = False

    out = _raw_out()
    out.write("\x1b[?25h")
    out.flush()
    _recompute_sugg()
    _paint()

    while True:
        try:
            k = keys.read_key()
        except KeyboardInterrupt:
            return None

        if _refresh_size():
            _full_repaint()
            S["prev_rows"] = 0
            S["geom"] = None
            _recompute_sugg()
            _paint()
            continue

        if keys._mouse_trace:
            keys._mouse_trace.clear()

        if k == keys.KEY_IGNORE:
            continue

        if k == keys.KEY_RESIZE:
            _refresh_size()
            _full_repaint()
            S["prev_rows"] = 0
            S["geom"] = None
            _recompute_sugg()
            _paint()
            continue

        if k.startswith(keys.KEY_WHEEL_UP_PREFIX):
            x, y = _parse_xy(k)
            if _sugg_index_at(x, y) is not None or (
                S["geom"] is not None and S["payload"] is not None
                and S["geom"]["top"] <= y <= S["geom"]["top"] + S["geom"]["rows"] - 1
            ):
                _sugg_scroll(-1)
                _paint()
                continue
            _wheel(x, y, +WHEEL_STEP)
            _paint()
            continue
        if k.startswith(keys.KEY_WHEEL_DOWN_PREFIX):
            x, y = _parse_xy(k)
            if _sugg_index_at(x, y) is not None or (
                S["geom"] is not None and S["payload"] is not None
                and S["geom"]["top"] <= y <= S["geom"]["top"] + S["geom"]["rows"] - 1
            ):
                _sugg_scroll(+1)
                _paint()
                continue
            _wheel(x, y, -WHEEL_STEP)
            _paint()
            continue

        if k.startswith(keys.KEY_MOUSE_DOWN_PREFIX):
            _, _, xs, ys = k.split(":", 3)
            mx, my = int(xs), int(ys)
            hit = _sugg_index_at(mx, my)
            if hit is not None:
                S["sel"] = hit
                _sugg_insert()
                _recompute_sugg()
                _paint()
                continue
            _on_mouse_down(mx, my)
            if _sel is not None:
                _sel["input_getter"] = _input_getter
            _paint()
            continue
        if k.startswith(keys.KEY_MOUSE_DRAG_PREFIX):
            _, _, xs, ys = k.split(":", 3)
            mx, my = int(xs), int(ys)
            _on_mouse_drag(mx, my)
            _paint()
            continue
        if k.startswith(keys.KEY_MOUSE_UP_PREFIX):
            _, _, xs, ys = k.split(":", 3)
            mx, my = int(xs), int(ys)
            _on_mouse_up(mx, my)
            _paint()
            continue
        if k.startswith("mouse_move:"):
            _, _, xs, ys = k.split(":", 3)
            mx, my = int(xs), int(ys)
            hit = _sugg_index_at(mx, my)
            if hit is not None and hit != S["sel"]:
                S["sel"] = hit
                _paint()
            continue

        # ----- suggestion popup keyboard navigation (when open) -----
        if S["payload"] is not None:
            if k == keys.KEY_UP:
                S["sel"] = max(0, S["sel"] - 1)
                _paint()
                continue
            if k == keys.KEY_DOWN:
                S["sel"] = min(len(S["payload"]["items"]) - 1, S["sel"] + 1)
                _paint()
                continue
            if k in (keys.KEY_TAB, keys.KEY_SHIFT_TAB):
                _sugg_insert()
                _recompute_sugg()
                _paint()
                continue
            if k == keys.KEY_ESC and _sel is None:
                S["dismissed"] = True
                _recompute_sugg()
                _paint()
                continue

        if k == keys.KEY_ENTER:
            _clear_selection()
            if S["prev_rows"]:
                S["payload"] = None
                _paint_sugg()
            echo_command(_state["prompt"], buf, _colourise(buf))
            return buf
        if k == keys.KEY_CTRL_C:
            if _sel is not None:
                text = _selected_text()
                if text:
                    ok = clipboard_set(text)
                    status = (
                        f"Copied {len(text)} chars"
                        if ok
                        else f"Copy FAILED ({len(text)} chars)"
                    )
                    draw_footer(prompt_text="", new_tip=False, status=status)
                _clear_selection()
                _paint()
                continue
            raise KeyboardInterrupt
        if k == keys.KEY_ESC:
            if _sel is not None:
                _clear_selection()
                _paint()
                continue
            buf = ""
            cursor = 0
            hist_idx = len(history)
            S["dismissed"] = False
        elif k == keys.KEY_BACKSPACE:
            if cursor > 0:
                buf = buf[: cursor - 1] + buf[cursor:]
                cursor -= 1
            S["dismissed"] = False
        elif k == keys.KEY_DELETE:
            if cursor < len(buf):
                buf = buf[: cursor] + buf[cursor + 1:]
            S["dismissed"] = False
        elif k == keys.KEY_LEFT:
            if cursor > 0:
                cursor -= 1
        elif k == keys.KEY_RIGHT:
            if cursor < len(buf):
                cursor += 1
        elif k == keys.KEY_HOME:
            cursor = 0
        elif k == keys.KEY_END:
            cursor = len(buf)
        elif k == keys.KEY_UP:
            if history and hist_idx > 0:
                hist_idx -= 1
                buf = history[hist_idx]
                cursor = len(buf)
                S["dismissed"] = True
        elif k == keys.KEY_DOWN:
            if history and hist_idx < len(history):
                hist_idx += 1
                buf = history[hist_idx] if hist_idx < len(history) else ""
                cursor = len(buf)
                S["dismissed"] = True
        elif k == keys.KEY_PGUP:
            _scroll_focused(+10)
        elif k == keys.KEY_PGDN:
            _scroll_focused(-10)
        elif k == keys.KEY_TAB:
            if _state["debug"] and _state["logs_pos"] != "hidden":
                _toggle_focus()
                _paint()
                continue
        elif k == keys.KEY_SHIFT_TAB:
            if _state["debug"] and _state["logs_pos"] != "hidden":
                _toggle_focus()
                _paint()
                continue
        elif k == keys.KEY_SPACE:
            buf = buf[:cursor] + " " + buf[cursor:]
            cursor += 1
            S["dismissed"] = False
        elif len(k) == 1 and k.isprintable():
            buf = buf[:cursor] + k + buf[cursor:]
            cursor += 1
            S["dismissed"] = False
        else:
            continue
        _recompute_sugg()
        _paint()



# ---------------------------------------------------------------------------
# scroll helpers
# ---------------------------------------------------------------------------


def _parse_xy(k: str) -> tuple[int, int]:
    try:
        _, payload = k.split(":", 1)
        x_s, y_s = payload.split(":", 1)
        return int(x_s), int(y_s)
    except Exception:
        return 0, 0


def _wheel(x: int, y: int, delta: int) -> None:
    if _state["debug"]:
        _, logs_box, _ = _compute_regions()
        if logs_box is not None:
            ltop, lbot, lleft, lright = logs_box
            if ltop <= y <= lbot and lleft <= x <= lright:
                _scroll_logs(delta)
                return
    _scroll_output(delta)


def _toggle_focus() -> None:
    out_ok = _output_paned()
    logs_ok = _logs_paned()
    if not (out_ok and logs_ok):
        if out_ok:
            _focus_window("output")
        elif logs_ok:
            _focus_window("logs")
        return
    _focus_window("logs" if _state["focus"] == "output" else "output")
    _render_output()
    _render_logs()


def _scroll_focused(delta: int) -> None:
    if _state["focus"] == "logs" and _logs_paned():
        _scroll_logs(delta)
    else:
        _scroll_output(delta)


def _scroll_output(delta: int) -> None:
    global _output_scroll
    with _io_lock:
        out_box, _, _ = _compute_regions()
        if out_box is None:
            return
        out_inner = _inner_box(out_box)
        rows = out_inner[1] - out_inner[0] + 1
        width = out_inner[3] - out_inner[2] + 1
        max_back = max(0, _total_visual_rows(_output_lines, width) - rows)
        _output_scroll = max(0, min(_output_scroll + delta, max_back))
        _render_output()


def _scroll_logs(delta: int) -> None:
    global _log_scroll
    with _io_lock:
        _, logs_box, _ = _compute_regions()
        if logs_box is None:
            return
        logs_inner = _inner_box(logs_box)
        rows = logs_inner[1] - logs_inner[0] + 1
        width = logs_inner[3] - logs_inner[2] + 1
        max_back = max(0, _total_visual_rows(_log_lines, width) - rows)
        _log_scroll = max(0, min(_log_scroll + delta, max_back))
        _render_logs()


# ---------------------------------------------------------------------------
# misc helpers
# ---------------------------------------------------------------------------


def _visible_len(s: str) -> int:
    return len(_ansi_re.sub("", s or ""))


def park_in_scroll_region() -> None:
    if not _state["active"]:
        return
    out_box, _, _ = _compute_regions()
    if out_box is None:
        return
    inner = _inner_box(out_box)
    out = _raw_out()
    out.write(f"\x1b[{inner[0]};{inner[2]}H")
    out.flush()


def park_at_scroll_bottom() -> None:
    if not _state["active"]:
        return
    out_box, _, _ = _compute_regions()
    if out_box is None:
        return
    inner = _inner_box(out_box)
    out = _raw_out()
    out.write(f"\x1b[{inner[1]};{inner[2]}H")
    out.flush()


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------


def _compute_buffer_visuals(buffer: list[str], width: int) -> list[str]:
    visuals: list[str] = []
    for raw in buffer:
        wrapped = _wrap_to_width(raw, width)
        if not wrapped:
            visuals.append("")
        else:
            visuals.extend(wrapped)
    return visuals


def _hit_test(x: int, y: int) -> tuple[str, int, int] | None:
    out_box, logs_box, _ = _compute_regions()
    # header
    if y == 1:
        return ("header", 0, max(0, x - 1))
    h = _state["height"]
    if y == h - 1:
        prompt_w = _visible_len(_state["prompt"])
        return ("input", 0, max(0, x - 1 - prompt_w))

    # taskbar strip
    tb_row = _taskbar_row()
    if tb_row is not None and y == tb_row:
        for bx_start, bx_end, wid in _taskbar_hits:
            if bx_start <= x <= bx_end:
                return (f"taskbar:{wid}", 0, 0)
        return ("taskbar", 0, 0)

    # title-bar buttons
    for box, wid in ((out_box, "output"), (logs_box, "logs")):
        if box is None or box[0] != y:
            continue
        for bx_start, bx_end, kind in _frame_button_cells(box, wid):
            if bx_start <= x <= bx_end:
                return (f"btn:{kind}", 0, 0)

    # title bars
    if (out_box is not None
            and out_box[0] == y
            and out_box[2] <= x <= out_box[3]):
        return ("titlebar_output", 0, max(0, x - out_box[2]))
    if (logs_box is not None
            and logs_box[0] == y
            and logs_box[2] <= x <= logs_box[3]):
        return ("titlebar_logs", 0, max(0, x - logs_box[2]))

    # output box
    if out_box is not None:
        out_inner = _inner_box(out_box)
        if (out_inner[0] <= y <= out_inner[1]
                and out_inner[2] <= x <= out_inner[3]):
            width = out_inner[3] - out_inner[2] + 1
            total = _total_visual_rows(_output_lines, width)
            bot_vline = total - 1 - _output_scroll
            vline = bot_vline - (out_inner[1] - y)
            if vline < 0:
                return None
            col = max(0, x - out_inner[2])
            return ("output", vline, col)
    # logs box
    if logs_box is not None:
        logs_inner = _inner_box(logs_box)
        if (logs_inner[0] <= y <= logs_inner[1]
                and logs_inner[2] <= x <= logs_inner[3]):
            width = logs_inner[3] - logs_inner[2] + 1
            total = _total_visual_rows(_log_lines, width)
            bot_vline = total - 1 - _log_scroll
            vline = bot_vline - (logs_inner[1] - y)
            if vline < 0:
                return None
            col = max(0, x - logs_inner[2])
            return ("logs", vline, col)

    return None


def _strip_ansi(text: str) -> str:
    return _ansi_re.sub("", text or "")


def _norm_sel() -> tuple[tuple[int, int], tuple[int, int]]:
    a = _sel["anchor"]
    b = _sel["end"]
    if (a[0], a[1]) > (b[0], b[1]):
        return b, a
    return a, b


def _selected_text() -> str:
    if _sel is None:
        return ""
    region = _sel["region"]
    a, b = _norm_sel()
    if region == "output":
        out_box, _, _ = _compute_regions()
        if out_box is None:
            return ""
        width = out_box[3] - out_box[2] + 1
        visuals = _compute_buffer_visuals(_output_lines, width)
    elif region == "logs":
        _, logs_box, _ = _compute_regions()
        if logs_box is None:
            return ""
        width = logs_box[3] - logs_box[2] + 1
        visuals = _compute_buffer_visuals(_log_lines, width)
    elif region == "input":
        getter = _sel.get("input_getter")
        text = getter() if callable(getter) else ""
        return text[a[1]:b[1]]
    elif region == "header":
        text = _strip_ansi(_state.get("header_text", "") or "")
        return text[a[1]:b[1]]
    else:
        return ""
    if not visuals:
        return ""
    a_v = max(0, min(a[0], len(visuals) - 1))
    b_v = max(0, min(b[0], len(visuals) - 1))
    if a_v == b_v:
        line = _strip_ansi(visuals[a_v])
        return line[a[1]:b[1]]
    parts = [_strip_ansi(visuals[a_v])[a[1]:]]
    for i in range(a_v + 1, b_v):
        parts.append(_strip_ansi(visuals[i]))
    parts.append(_strip_ansi(visuals[b_v])[:b[1]])
    return "\n".join(parts)


def _overlay_selection_region(buffer: list[str], scroll: int,
                              box: tuple[int, int, int, int],
                              region_id: str) -> None:
    if _sel is None or _sel["region"] != region_id:
        return
    top, bottom, left, right = box
    rows = bottom - top + 1
    width = right - left + 1
    visuals = _compute_buffer_visuals(buffer, width)
    total = len(visuals)
    bot_vline = total - 1 - scroll
    top_vline = bot_vline - (rows - 1)
    a, b = _norm_sel()
    out = _raw_out()
    out.write("\x1b[s")
    for screen_row in range(top, bottom + 1):
        vline = top_vline + (screen_row - top)
        if vline < 0 or vline >= total:
            continue
        if vline < a[0] or vline > b[0]:
            continue
        visual_text = _strip_ansi(visuals[vline])
        if vline == a[0] and vline == b[0]:
            col_s, col_e = a[1], b[1]
        elif vline == a[0]:
            col_s, col_e = a[1], width
        elif vline == b[0]:
            col_s, col_e = 0, b[1]
        else:
            col_s, col_e = 0, width
        col_s = max(0, min(col_s, width))
        col_e = max(col_s, min(col_e, width))
        if col_e <= col_s:
            continue
        segment = visual_text[col_s:col_e]
        if len(segment) < (col_e - col_s):
            segment = segment + " " * ((col_e - col_s) - len(segment))
        out.write(f"\x1b[{screen_row};{left + col_s}H")
        out.write(INVERT + segment + RESET)
    out.write("\x1b[u")
    out.flush()


def _clear_selection() -> None:
    global _sel
    if _sel is None:
        return
    _sel = None
    render_all()


def _autoscroll_during_drag(x: int, y: int) -> None:
    if _sel is None:
        return
    region = _sel["region"]
    if region not in ("output", "logs"):
        return
    out_box, logs_box, _ = _compute_regions()
    box = out_box if region == "output" else logs_box
    if box is None:
        return
    top, bottom, _, _ = box
    if y < top:
        if region == "output":
            _scroll_output(+1)
        else:
            _scroll_logs(+1)
    elif y > bottom:
        if region == "output":
            _scroll_output(-1)
        else:
            _scroll_logs(-1)


def _on_mouse_down(x: int, y: int) -> None:
    global _sel, _window_drag
    hit = _hit_test(x, y)
    prev_region = _sel.get("region") if _sel else None
    if hit is None:
        _clear_selection()
        return
    region, vline, col = hit
    if region.startswith("btn:"):
        kind = region[4:]
        action, _, wid = kind.partition(":")
        if action == "min":
            set_window_minimized(wid, True)
        elif action == "close":
            win = _windows.get(wid)
            if win and win.get("closable"):
                if wid == "logs":
                    set_logs_position("hidden")
                else:
                    set_window_minimized(wid, True)
        _clear_selection()
        return
    if region.startswith("taskbar"):
        _, _, wid = region.partition(":")
        if wid:
            set_window_minimized(wid, False)
        _clear_selection()
        return
    if region in ("titlebar_output", "titlebar_logs"):
        target = "logs" if region == "titlebar_logs" else "output"
        _focus_window(target)
        movable = _state["debug"] and _state["logs_pos"] != "hidden"
        if movable:
            _window_drag = {
                "target": target,
                "start": (x, y),
                "current": (x, y),
                "preview_zone": None,
            }
        _clear_selection()
        return
    if region in ("output", "logs"):
        _focus_window(region)
    _sel = {
        "region": region,
        "anchor": (vline, col),
        "end": (vline, col),
        "active": True,
        "input_getter": _sel.get("input_getter") if _sel else None,
    }
    if prev_region and prev_region != region:
        if prev_region == "output":
            _render_output()
        elif prev_region == "logs":
            _render_logs()
        elif prev_region == "header":
            _redraw_header_chrome()
    if region == "output":
        _render_output()
    elif region == "logs":
        _render_logs()
    elif region == "input":
        pass
    elif region == "header":
        _redraw_header_chrome()
        _overlay_header_selection()


def _on_mouse_drag(x: int, y: int) -> None:
    global _window_drag
    if _window_drag is not None:
        _window_drag["current"] = (x, y)
        sx, sy = _window_drag["start"]
        if abs(x - sx) < 2 and abs(y - sy) < 2:
            return
        zone = _snap_zone(x, y)
        if zone != _window_drag.get("preview_zone"):
            _window_drag["preview_zone"] = zone
            _full_repaint()
            _draw_snap_preview(zone, _window_drag["target"])
        return
    if _sel is None:
        return
    _autoscroll_during_drag(x, y)
    region = _sel["region"]
    out_box, logs_box, _ = _compute_regions()
    if region == "output":
        box = out_box
    elif region == "logs":
        box = logs_box
        if box is None:
            return
    elif region == "input":
        h = _state["height"]
        prompt_w = _visible_len(_state["prompt"])
        col = max(0, x - 1 - prompt_w)
        _sel["end"] = (0, col)
        return
    elif region == "header":
        col = max(0, x - 1)
        _sel["end"] = (0, col)
        _redraw_header_chrome()
        _overlay_header_selection()
        return
    else:
        return
    cx = max(box[2], min(x, box[3]))
    cy = max(box[0], min(y, box[1]))
    width = box[3] - box[2] + 1
    if region == "output":
        total = _total_visual_rows(_output_lines, width)
        bot_vline = total - 1 - _output_scroll
    else:
        total = _total_visual_rows(_log_lines, width)
        bot_vline = total - 1 - _log_scroll
    vline = bot_vline - (box[1] - cy)
    vline = max(0, vline)
    col = max(0, cx - box[2])
    _sel["end"] = (vline, col)
    if region == "output":
        _render_output()
    else:
        _render_logs()


def _on_mouse_up(x: int, y: int) -> None:
    global _window_drag
    if _window_drag is not None:
        drag = _window_drag
        _window_drag = None
        sx, sy = drag["start"]
        if abs(x - sx) >= 2 or abs(y - sy) >= 2:
            zone = _snap_zone(x, y)
            target = drag["target"]
            new_pos = zone if target == "logs" else _opposite_zone(zone)
            set_logs_position(new_pos)
        else:
            _full_repaint()
        return
    if _sel is None:
        return
    _sel["active"] = False


def _overlay_header_selection() -> None:
    if _sel is None or _sel["region"] != "header":
        return
    a, b = _norm_sel()
    text = _strip_ansi(_state.get("header_text", "") or "")
    width = _state["width"]
    col_s = max(0, min(a[1], width))
    col_e = max(col_s, min(b[1], width))
    if col_e <= col_s:
        return
    segment = text[col_s:col_e]
    if len(segment) < (col_e - col_s):
        segment = segment + " " * ((col_e - col_s) - len(segment))
    out = _raw_out()
    out.write("\x1b[s")
    out.write(f"\x1b[1;{1 + col_s}H")
    out.write(INVERT + segment + RESET)
    out.write("\x1b[u")
    out.flush()
