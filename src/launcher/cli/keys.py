from __future__ import annotations

import os
import sys

KEY_UP = "up"
KEY_DOWN = "down"
KEY_LEFT = "left"
KEY_RIGHT = "right"
KEY_ENTER = "enter"
KEY_SPACE = "space"
KEY_TAB = "tab"
KEY_SHIFT_TAB = "shift_tab"
KEY_ESC = "esc"
KEY_BACKSPACE = "backspace"
KEY_DELETE = "delete"
KEY_HOME = "home"
KEY_END = "end"
KEY_PGUP = "page_up"
KEY_PGDN = "page_down"
KEY_MOUSE = "mouse"
KEY_IGNORE = ""
KEY_RESIZE = "resize"
KEY_CTRL_C = "ctrl_c"
KEY_TIMEOUT = "timeout"
KEY_WHEEL_UP_PREFIX = "wheel_up:"
KEY_WHEEL_DOWN_PREFIX = "wheel_down:"
KEY_MOUSE_DOWN_PREFIX = "mouse_down:"
KEY_MOUSE_DRAG_PREFIX = "mouse_drag:"
KEY_MOUSE_UP_PREFIX = "mouse_up:"
KEY_MOUSE_MOVE_PREFIX = "mouse_move:"


def read_key(timeout: float | None = None) -> str:
    if sys.platform.startswith("win"):
        return _read_key_windows(timeout)
    return _read_key_posix(timeout)


# ---------------------------------------------------------------------------
# Windows: ReadConsoleInputW path
# ---------------------------------------------------------------------------


_WIN_INIT = False
_kernel32 = None
_user32 = None
_h_stdin = None
_h_stdout = None
_INPUT_RECORD = None
_last_button_state = 0
_mouse_trace: list[str] = []

_left_held = False
_last_poll_cell: tuple[int, int] | None = None
_anchor_pt: tuple[int, int] | None = None
_anchor_cell: tuple[int, int] | None = None
_POLL_INTERVAL_MS = 25


def _trace_mouse(line: str) -> None:
    if _mouse_trace and _mouse_trace[-1] == line:
        return
    _mouse_trace.append(line)
    if len(_mouse_trace) > 200:
        del _mouse_trace[: len(_mouse_trace) - 200]


def _win_structs():
    import ctypes

    class COORD(ctypes.Structure):
        _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

    class _uChar(ctypes.Union):
        _fields_ = [
            ("UnicodeChar", ctypes.c_wchar),
            ("AsciiChar", ctypes.c_char),
        ]

    class KEY_EVENT_RECORD(ctypes.Structure):
        _fields_ = [
            ("bKeyDown", ctypes.c_int),
            ("wRepeatCount", ctypes.c_ushort),
            ("wVirtualKeyCode", ctypes.c_ushort),
            ("wVirtualScanCode", ctypes.c_ushort),
            ("uChar", _uChar),
            ("dwControlKeyState", ctypes.c_ulong),
        ]

    class MOUSE_EVENT_RECORD(ctypes.Structure):
        _fields_ = [
            ("dwMousePosition", COORD),
            ("dwButtonState", ctypes.c_ulong),
            ("dwControlKeyState", ctypes.c_ulong),
            ("dwEventFlags", ctypes.c_ulong),
        ]

    class WINDOW_BUFFER_SIZE_RECORD(ctypes.Structure):
        _fields_ = [("dwSize", COORD)]

    class MENU_EVENT_RECORD(ctypes.Structure):
        _fields_ = [("dwCommandId", ctypes.c_uint)]

    class FOCUS_EVENT_RECORD(ctypes.Structure):
        _fields_ = [("bSetFocus", ctypes.c_int)]

    class _EventUnion(ctypes.Union):
        _fields_ = [
            ("KeyEvent", KEY_EVENT_RECORD),
            ("MouseEvent", MOUSE_EVENT_RECORD),
            ("WindowBufferSizeEvent", WINDOW_BUFFER_SIZE_RECORD),
            ("MenuEvent", MENU_EVENT_RECORD),
            ("FocusEvent", FOCUS_EVENT_RECORD),
        ]

    class INPUT_RECORD(ctypes.Structure):
        _fields_ = [("EventType", ctypes.c_ushort), ("Event", _EventUnion)]

    return INPUT_RECORD


def _win_init():
    global _WIN_INIT, _kernel32, _user32, _h_stdin, _h_stdout, _INPUT_RECORD
    if _WIN_INIT:
        return
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.windll.kernel32
    _user32 = ctypes.windll.user32
    _kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    _kernel32.GetStdHandle.restype = wintypes.HANDLE
    _kernel32.GetConsoleWindow.argtypes = []
    _kernel32.GetConsoleWindow.restype = wintypes.HWND
    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.GetConsoleScreenBufferInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    _kernel32.GetConsoleScreenBufferInfo.restype = wintypes.BOOL
    _user32.GetCursorPos.argtypes = [ctypes.c_void_p]
    _user32.GetCursorPos.restype = wintypes.BOOL
    _user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.c_void_p]
    _user32.ScreenToClient.restype = wintypes.BOOL
    _user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
    _user32.GetClientRect.restype = wintypes.BOOL
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _h_stdin = _kernel32.GetStdHandle(wintypes.DWORD(-10 & 0xFFFFFFFF))
    _h_stdout = _kernel32.GetStdHandle(wintypes.DWORD(-11 & 0xFFFFFFFF))
    _INPUT_RECORD = _win_structs()
    _WIN_INIT = True

def _get_cursor_client_pt() -> tuple[int, int, int, int] | None:
    import ctypes
    from ctypes import wintypes

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    class RECT(ctypes.Structure):
        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                    ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

    class COORDsmall(ctypes.Structure):
        _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

    class SMALL_RECT(ctypes.Structure):
        _fields_ = [("Left", ctypes.c_short), ("Top", ctypes.c_short),
                    ("Right", ctypes.c_short), ("Bottom", ctypes.c_short)]

    class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
        _fields_ = [
            ("dwSize", COORDsmall),
            ("dwCursorPosition", COORDsmall),
            ("wAttributes", ctypes.c_ushort),
            ("srWindow", SMALL_RECT),
            ("dwMaximumWindowSize", COORDsmall),
        ]

    try:
        hwnd = _kernel32.GetConsoleWindow()
        pt = POINT()
        if not _user32.GetCursorPos(ctypes.byref(pt)):
            return None
        rc = RECT()
        use_hwnd = hwnd
        ok = bool(hwnd) and bool(_user32.GetClientRect(hwnd, ctypes.byref(rc)))
        if ok and (rc.right - rc.left <= 0 or rc.bottom - rc.top <= 0):
            ok = False
        if not ok:
            fhwnd = _user32.GetForegroundWindow()
            if not fhwnd or not _user32.GetClientRect(fhwnd, ctypes.byref(rc)):
                return None
            if rc.right - rc.left <= 0 or rc.bottom - rc.top <= 0:
                return None
            use_hwnd = fhwnd
        if not _user32.ScreenToClient(use_hwnd, ctypes.byref(pt)):
            return None
        client_w = rc.right - rc.left
        client_h = rc.bottom - rc.top
        info = CONSOLE_SCREEN_BUFFER_INFO()
        if not _kernel32.GetConsoleScreenBufferInfo(
            _h_stdout, ctypes.byref(info)
        ):
            return None
        win_w = info.srWindow.Right - info.srWindow.Left + 1
        win_h = info.srWindow.Bottom - info.srWindow.Top + 1
        if win_w <= 0 or win_h <= 0:
            return None
        cell_w = max(1, client_w // win_w)
        cell_h = max(1, client_h // win_h)
        return pt.x, pt.y, cell_w, cell_h
    except Exception:
        return None


def _poll_cursor_cell() -> tuple[int, int] | None:
    cur = _get_cursor_client_pt()
    if cur is None:
        _trace_mouse("poll_cell: geometry failed")
        return None
    px, py, cell_w, cell_h = cur
    if _anchor_pt is not None and _anchor_cell is not None:
        ax, ay = _anchor_pt
        acol, arow = _anchor_cell
        dx = px - ax
        if dx >= 0:
            col = dx // cell_w + acol
        else:
            col = -((-dx + cell_w - 1) // cell_w) + acol
        row = ((py - ay) + cell_h // 2) // cell_h + arow
    else:
        col = px // cell_w + 1
        row = py // cell_h + 1
    if col < 1:
        col = 1
    if row < 1:
        row = 1
    return col, row


def _lbutton_is_down() -> bool:
    import ctypes
    VK_LBUTTON = 0x01
    try:
        _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        _user32.GetAsyncKeyState.restype = ctypes.c_short
        return bool(_user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
    except Exception:
        return False


def _vk_to_name(vk: int, ctrl: bool, shift: bool, ch: str) -> str:
    table = {
        0x08: KEY_BACKSPACE,
        0x09: KEY_SHIFT_TAB if shift else KEY_TAB,
        0x0D: KEY_ENTER,
        0x1B: KEY_ESC,
        0x20: KEY_SPACE,
        0x21: KEY_PGUP,
        0x22: KEY_PGDN,
        0x23: KEY_END,
        0x24: KEY_HOME,
        0x25: KEY_LEFT,
        0x26: KEY_UP,
        0x27: KEY_RIGHT,
        0x28: KEY_DOWN,
        0x2E: KEY_DELETE,
    }
    if vk in table:
        return table[vk]
    if ctrl and vk == 0x43:
        return KEY_CTRL_C
    if ch and ch != "\x00":
        if ch == "\r" or ch == "\n":
            return KEY_ENTER
        if ch == "\t":
            return KEY_SHIFT_TAB if shift else KEY_TAB
        if ch == " ":
            return KEY_SPACE
        if ch == "\x1b":
            return KEY_ESC
        if ch in ("\x08", "\x7f"):
            return KEY_BACKSPACE
        if ch == "\x03":
            return KEY_CTRL_C
        return ch
    return KEY_IGNORE


def _read_key_windows(timeout: float | None = None) -> str:
    import ctypes
    import time

    _win_init()
    SHIFT_PRESSED = 0x0010
    LEFT_CTRL_PRESSED = 0x0008
    RIGHT_CTRL_PRESSED = 0x0004
    MOUSE_MOVED = 0x0001
    MOUSE_WHEELED = 0x0004
    LEFT_BUTTON = 0x0001
    WAIT_OBJECT_0 = 0x00000000
    WAIT_TIMEOUT = 0x00000102

    global _last_button_state, _left_held, _last_poll_cell, _anchor_pt, _anchor_cell
    rec = _INPUT_RECORD()
    read = ctypes.c_ulong(0)

    deadline = None if timeout is None else time.monotonic() + timeout

    while True:
        if _left_held:
            rc = _kernel32.WaitForSingleObject(_h_stdin, _POLL_INTERVAL_MS)
            if rc != WAIT_OBJECT_0:
                btn_down = _lbutton_is_down()
                pos = _poll_cursor_cell()
                _trace_mouse(
                    f"poll wait={rc:#06x} btn_down={btn_down} pos={pos} last={_last_poll_cell}"
                )
                if not btn_down:
                    _left_held = False
                    end = pos or _last_poll_cell
                    if end is not None:
                        return f"mouse_up:1:{end[0]}:{end[1]}"
                    continue
                if pos is not None and pos != _last_poll_cell:
                    _last_poll_cell = pos
                    return f"mouse_drag:1:{pos[0]}:{pos[1]}"
                continue
            else:
                _trace_mouse("poll wait=WAIT_OBJECT_0 (event arrived)")
        elif deadline is not None:
            remaining_ms = int(max(0.0, deadline - time.monotonic()) * 1000)
            rc = _kernel32.WaitForSingleObject(_h_stdin, remaining_ms)
            if rc == WAIT_TIMEOUT:
                return KEY_TIMEOUT
            if rc != WAIT_OBJECT_0:
                time.sleep(0.05)
                return KEY_TIMEOUT
        ok = _kernel32.ReadConsoleInputW(
            _h_stdin, ctypes.byref(rec), 1, ctypes.byref(read)
        )
        if not ok or read.value == 0:
            time.sleep(0.05)
            return KEY_IGNORE

        et = rec.EventType
        if et == 0x0001:  # KEY_EVENT
            ke = rec.Event.KeyEvent
            if not ke.bKeyDown:
                continue
            ctrl = bool(
                ke.dwControlKeyState & (LEFT_CTRL_PRESSED | RIGHT_CTRL_PRESSED)
            )
            shift = bool(ke.dwControlKeyState & SHIFT_PRESSED)
            ch = ke.uChar.UnicodeChar
            name = _vk_to_name(ke.wVirtualKeyCode, ctrl, shift, ch)
            if name == KEY_IGNORE:
                continue
            return name

        if et == 0x0002:  # MOUSE_EVENT
            me = rec.Event.MouseEvent
            x = me.dwMousePosition.X + 1
            y = me.dwMousePosition.Y + 1
            flags = me.dwEventFlags
            btn = me.dwButtonState
            _trace_mouse(f"raw flags=0x{flags:04x} btn=0x{btn:08x} x={x} y={y}")
            if flags & MOUSE_WHEELED:
                hi = (btn >> 16) & 0xFFFF
                if hi & 0x8000:
                    hi = hi - 0x10000
                if hi > 0:
                    return f"wheel_up:{x}:{y}"
                return f"wheel_down:{x}:{y}"
            if flags & MOUSE_MOVED:
                _last_button_state = btn
                if btn & LEFT_BUTTON:
                    _left_held = True
                    if _anchor_pt is None:
                        cur = _get_cursor_client_pt()
                        if cur is not None:
                            _anchor_pt = (cur[0], cur[1])
                            _anchor_cell = (x, y)
                    _last_poll_cell = (x, y)
                    return f"mouse_drag:1:{x}:{y}"
                return f"mouse_move:1:{x}:{y}"
            prev = _last_button_state
            _last_button_state = btn
            if (btn & LEFT_BUTTON) and not (prev & LEFT_BUTTON):
                _left_held = True
                cur = _get_cursor_client_pt()
                if cur is not None:
                    _anchor_pt = (cur[0], cur[1])
                    _anchor_cell = (x, y)
                else:
                    _anchor_pt = None
                    _anchor_cell = None
                _last_poll_cell = (x, y)
                return f"mouse_down:1:{x}:{y}"
            if not (btn & LEFT_BUTTON) and (prev & LEFT_BUTTON):
                if _lbutton_is_down():
                    _last_button_state = prev
                    if _left_held:
                        pos = _poll_cursor_cell() or (x, y)
                        if pos != _last_poll_cell:
                            _last_poll_cell = pos
                            return f"mouse_drag:1:{pos[0]}:{pos[1]}"
                    continue
                _left_held = False
                _last_poll_cell = None
                _anchor_pt = None
                _anchor_cell = None
                return f"mouse_up:1:{x}:{y}"
            continue

        if et == 0x0004:
            return KEY_RESIZE

        continue


# ---------------------------------------------------------------------------
# POSIX
# ---------------------------------------------------------------------------

_pending = bytearray()

_CBREAK_DEPTH = 0
_CBREAK_SAVED: list | None = None
_WINCH_R: int | None = None
_WINCH_W: int | None = None
_ESC_WAIT = 0.025
_SS3_KEYS = {
    "A": KEY_UP, "B": KEY_DOWN, "C": KEY_RIGHT, "D": KEY_LEFT,
    "H": KEY_HOME, "F": KEY_END,
}
_CTRL_KEYS = {
    0x03: KEY_CTRL_C,
    0x08: KEY_BACKSPACE,
    0x09: KEY_TAB,
    0x0A: KEY_ENTER,
    0x0D: KEY_ENTER,
    0x1B: KEY_ESC,
    0x7F: KEY_BACKSPACE,
}


def enter_cbreak() -> None:
    global _CBREAK_DEPTH, _CBREAK_SAVED
    if sys.platform.startswith("win"):
        return
    _CBREAK_DEPTH += 1
    if _CBREAK_DEPTH != 1 or _CBREAK_SAVED is not None:
        return
    try:
        import atexit
        import termios
        import tty

        if not sys.stdin.isatty():
            return
        fd = sys.stdin.fileno()
        _CBREAK_SAVED = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        mode = termios.tcgetattr(fd)
        mode[3] &= ~termios.ISIG  # lflag
        termios.tcsetattr(fd, termios.TCSADRAIN, mode)
        atexit.register(_restore_terminal)
    except Exception:
        _CBREAK_SAVED = None


def exit_cbreak() -> None:
    global _CBREAK_DEPTH
    if sys.platform.startswith("win"):
        return
    _CBREAK_DEPTH = max(0, _CBREAK_DEPTH - 1)
    if _CBREAK_DEPTH == 0:
        _restore_terminal()


def _restore_terminal() -> None:
    global _CBREAK_SAVED
    if _CBREAK_SAVED is None:
        return
    try:
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _CBREAK_SAVED)
    except Exception:
        pass
    _CBREAK_SAVED = None


def _init_winch() -> None:
    global _WINCH_R, _WINCH_W
    if _WINCH_R is not None:
        return
    import signal

    if not hasattr(signal, "SIGWINCH"):
        _WINCH_R = -1
        return
    try:
        r, w = os.pipe()
        os.set_blocking(r, False)
        os.set_blocking(w, False)

        def _on_winch(_sig, _frame) -> None:
            try:
                os.write(w, b"w")
            except OSError:
                pass

        signal.signal(signal.SIGWINCH, _on_winch)
    except (ValueError, OSError):
        _WINCH_R = -1
        return
    _WINCH_R, _WINCH_W = r, w


def _fill_more(fd: int, wait: float) -> bool:
    import select

    try:
        ready, _, _ = select.select([fd], [], [], wait)
        if not ready:
            return False
        chunk = os.read(fd, 4096)
    except (OSError, ValueError):
        return False
    if not chunk:
        return False
    _pending.extend(chunk)
    return True


def _read_key_posix(timeout: float | None = None) -> str:
    try:
        return _posix_read_event(timeout)
    except KeyboardInterrupt:
        return KEY_CTRL_C


def _posix_read_event(timeout: float | None) -> str:
    import select
    import time

    _init_winch()
    fd = sys.stdin.fileno()

    temporary = _CBREAK_SAVED is None and sys.stdin.isatty()
    saved = None
    if temporary:
        import termios
        import tty

        saved = termios.tcgetattr(fd)
        tty.setcbreak(fd)
    try:
        deadline = None if timeout is None else time.monotonic() + timeout
        watch = [fd] if (_WINCH_R is None or _WINCH_R < 0) else [fd, _WINCH_R]
        while True:
            if _pending:
                ev = _parse_event(fd)
                if ev != KEY_IGNORE:
                    return ev
                continue
            if deadline is None:
                ready, _, _ = select.select(watch, [], [])
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return KEY_TIMEOUT
                ready, _, _ = select.select(watch, [], [], remaining)
                if not ready:
                    return KEY_TIMEOUT
            if _WINCH_R in ready:
                try:
                    while os.read(_WINCH_R, 64):
                        pass
                except OSError:
                    pass
                return KEY_RESIZE
            if fd in ready:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    return KEY_IGNORE
                if not chunk:
                    return KEY_IGNORE  # EOF
                _pending.extend(chunk)
    finally:
        if saved is not None:
            import termios

            termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def _parse_event(fd: int) -> str:
    b0 = _pending[0]
    if b0 == 0x1B:
        if len(_pending) == 1 and not _fill_more(fd, _ESC_WAIT):
            del _pending[:1]
            return KEY_ESC
        b1 = _pending[1]
        if b1 == ord("["):
            return _parse_csi(fd)
        if b1 == ord("O"):
            if len(_pending) < 3 and not _fill_more(fd, _ESC_WAIT):
                del _pending[:2]
                return KEY_ESC
            final = chr(_pending[2])
            del _pending[:3]
            return _SS3_KEYS.get(final, KEY_IGNORE)
        del _pending[:1]
        return KEY_ESC
    if b0 == 0x20:
        del _pending[:1]
        return KEY_SPACE
    if b0 < 0x20 or b0 == 0x7F:
        del _pending[:1]
        return _CTRL_KEYS.get(b0, KEY_IGNORE)
    if b0 < 0x80:
        del _pending[:1]
        return chr(b0)
    need = 2 if b0 < 0xE0 else 3 if b0 < 0xF0 else 4 if b0 < 0xF8 else 1
    while len(_pending) < need:
        if not _fill_more(fd, _ESC_WAIT):
            break
    raw = bytes(_pending[:need])
    del _pending[:need]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return KEY_IGNORE


def _parse_csi(fd: int) -> str:
    i = 2
    while True:
        while i < len(_pending):
            b = _pending[i]
            if 0x40 <= b <= 0x7E:
                seq = _pending[2:i + 1].decode("ascii", "replace")
                del _pending[:i + 1]
                return _decode_csi(seq)
            i += 1
            if i > 64:
                del _pending[:i]
                return KEY_IGNORE
        if not _fill_more(fd, _ESC_WAIT):
            del _pending[:i]
            return KEY_IGNORE


def query_cursor_position(timeout: float = 0.2) -> tuple[int, int] | None:
    import re
    import select
    import time

    fd = sys.stdin.fileno()
    try:
        sys.stdout.write("\x1b[6n")
        sys.stdout.flush()
    except Exception:
        return None
    pattern = re.compile(rb"\x1b\[(\d+);(\d+)R")
    deadline = time.monotonic() + timeout
    while True:
        m = pattern.search(bytes(_pending))
        if m:
            del _pending[m.start():m.end()]
            return int(m.group(1)), int(m.group(2))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                return None
            chunk = os.read(fd, 4096)
        except (OSError, ValueError):
            return None
        if not chunk:
            return None
        _pending.extend(chunk)


def _decode_csi(seq: str) -> str:
    if not seq:
        return KEY_IGNORE
    final = seq[-1]
    if seq.startswith("<"):
        if final not in ("M", "m"):
            return KEY_IGNORE
        try:
            cb_s, x_s, y_s = seq[1:-1].split(";")
            cb = int(cb_s)
            x = int(x_s)
            y = int(y_s)
        except Exception:
            return KEY_IGNORE
        if cb & 0x40 and not (cb & 0x20):
            if final != "M":
                return KEY_IGNORE
            low = cb & 0x03
            if low == 0:
                return f"wheel_up:{x}:{y}"
            if low == 1:
                return f"wheel_down:{x}:{y}"
            return KEY_IGNORE
        button = cb & 0x03
        if cb & 0x20:
            if button == 3:
                return f"mouse_move:1:{x}:{y}"
            if button == 0:
                return f"mouse_drag:1:{x}:{y}"
            return KEY_IGNORE
        if button != 0:
            return KEY_IGNORE
        if final == "M":
            return f"mouse_down:1:{x}:{y}"
        return f"mouse_up:1:{x}:{y}"
    if seq.startswith("M") or final in ("M", "m"):
        return KEY_IGNORE
    if final == "A":
        return KEY_UP
    if final == "B":
        return KEY_DOWN
    if final == "C":
        return KEY_RIGHT
    if final == "D":
        return KEY_LEFT
    if final == "H":
        return KEY_HOME
    if final == "F":
        return KEY_END
    if final == "Z":
        return KEY_SHIFT_TAB
    if final == "~":
        code = seq[:-1]
        return {
            "3": KEY_DELETE,
            "5": KEY_PGUP,
            "6": KEY_PGDN,
            "1": KEY_HOME,
            "4": KEY_END,
            "7": KEY_HOME,
            "8": KEY_END,
        }.get(code, KEY_IGNORE)
    return KEY_IGNORE
