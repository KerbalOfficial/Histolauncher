from __future__ import annotations

import sys
from typing import Callable, Sequence

from launcher.cli import keys, tui
from launcher.cli.terminal import (
    BG, BOLD, DIM, FG, INVERT, RESET,
    c, hide_cursor, show_cursor, term_size, writeln,
)


# ---------------------------------------------------------------------------
# public dialogs
# ---------------------------------------------------------------------------


def _visible_len(s: str) -> int:
    import re

    return len(re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", s or ""))


def show_message(title: str, message: str, *, kind: str = "info") -> None:
    lines = _wrap(message, term_size()[0] - 12)
    hint = c("[ Press Enter to continue ]", DIM, FG["muted"])

    def body() -> list[str]:
        return lines + ["", hint]

    def on_key(k: str):
        if k in (keys.KEY_ENTER, keys.KEY_ESC, keys.KEY_SPACE):
            return True, None
        return False, None

    tui.run_modal(title=title, kind=kind, body=body, on_key=on_key, align="center",
                  min_width=46)


def confirm(title: str, message: str, *, yes_label: str = "Yes", no_label: str = "No",
            default_yes: bool = False, kind: str = "question") -> bool:
    selection = 0 if default_yes else 1
    holder = {"wrapped": _wrap(message, term_size()[0] - 12)}

    def body() -> list[str]:
        wrapped = _wrap(message, term_size()[0] - 12)
        holder["wrapped"] = wrapped
        buttons = _render_buttons([(yes_label, selection == 0), (no_label, selection == 1)])
        return wrapped + [
            "",
            buttons,
            c("← →  switch    Enter  confirm    Esc  cancel", DIM, FG["muted"]),
        ]

    def on_key(k: str):
        nonlocal selection
        if k in (keys.KEY_LEFT, keys.KEY_RIGHT, keys.KEY_TAB, keys.KEY_SHIFT_TAB):
            selection = 1 - selection
        elif k == "y":
            selection = 0
            return True, True
        elif k == "n":
            selection = 1
            return True, False
        elif k in (keys.KEY_ENTER, keys.KEY_SPACE):
            return True, selection == 0
        elif k == keys.KEY_ESC:
            return True, False
        return False, None

    def on_click(rel_row: int, rel_col: int):
        if rel_row != len(holder["wrapped"]) + 1:
            return None
        yes_w = len(f"  {yes_label}  ")
        if 0 <= rel_col < yes_w:
            return True, True
        if rel_col >= yes_w + 2:
            return True, False
        return None

    result = tui.run_modal(title=title, kind=kind, body=body, on_key=on_key,
                           on_click=on_click, align="center", min_width=46)
    return bool(result)


def _render_buttons(buttons: list[tuple[str, bool]]) -> str:
    parts = []
    for label, selected in buttons:
        text = f"  {label}  "
        if selected:
            parts.append(c(text, BOLD, BG["selected"], FG["header"]))
        else:
            parts.append(c(text, FG["muted"]))
    return "  ".join(parts)


def select_one(title: str, prompt: str, options: Sequence[str], *, default: int = 0) -> int | None:
    if not options:
        return None
    index = max(0, min(default, len(options) - 1))
    top = 0
    geom = {"width": term_size()[0], "rows": 3, "header": 0}

    def body() -> list[str]:
        nonlocal top
        width, height = term_size()
        visible_rows = max(3, min(len(options), height - 14))
        geom["width"] = width
        geom["rows"] = visible_rows
        if index < top:
            top = index
        elif index >= top + visible_rows:
            top = index - visible_rows + 1
        lines: list[str] = []
        header = 0
        if prompt:
            for w in _wrap(prompt, width - 12):
                lines.append(w)
                header += 1
            lines.append("")
            header += 1
        geom["header"] = header
        for i in range(top, min(len(options), top + visible_rows)):
            label = options[i]
            if i == index:
                lines.append(c(f"  ▸ {label}", BOLD, FG["header"]))
            else:
                lines.append(c(f"    {label}", FG["fg"]))
        if len(options) > visible_rows:
            lines.append(c(f"  ({index + 1} of {len(options)})", DIM, FG["muted"]))
        lines.append("")
        lines.append(c("↑ ↓  move    Enter  select    Esc  cancel", DIM, FG["muted"]))
        return lines

    def on_key(k: str):
        nonlocal index
        visible_rows = geom["rows"]
        if k == keys.KEY_UP:
            index = (index - 1) % len(options)
        elif k == keys.KEY_DOWN:
            index = (index + 1) % len(options)
        elif k == keys.KEY_TAB:
            index = (index + 1) % len(options)
        elif k == keys.KEY_SHIFT_TAB:
            index = (index - 1) % len(options)
        elif k == keys.KEY_HOME:
            index = 0
        elif k == keys.KEY_END:
            index = len(options) - 1
        elif k == keys.KEY_PGUP:
            index = max(0, index - visible_rows)
        elif k == keys.KEY_PGDN:
            index = min(len(options) - 1, index + visible_rows)
        elif k in (keys.KEY_ENTER, keys.KEY_SPACE):
            return True, index
        elif k == keys.KEY_ESC:
            return True, None
        return False, None

    def on_click(rel_row: int, rel_col: int):
        nonlocal index
        header = geom["header"]
        visible_rows = geom["rows"]
        visible_count = min(len(options), top + visible_rows) - top
        pos = rel_row - header
        if 0 <= pos < visible_count:
            index = top + pos
            return True, index
        return None

    return tui.run_modal(title=title, kind="question", body=body, on_key=on_key,
                         on_click=on_click)


def text_input(title: str, prompt: str, *, default: str = "", password: bool = False,
               validator: Callable[[str], str | None] | None = None) -> str | None:
    value = default
    error: str | None = None
    _cancelled = object()

    def body() -> list[str]:
        width, _ = term_size()
        display_val = "•" * len(value) if password else value
        cursor_mark = c("▏", FG["header"])
        input_line = c("  ❯ ", FG["accent"]) + display_val + cursor_mark
        lines: list[str] = []
        if prompt:
            for w in _wrap(prompt, width - 12):
                lines.append(w)
            lines.append("")
        lines.append(input_line)
        if error:
            lines.append(c("  " + error, FG["error"]))
        lines.append("")
        lines.append(c("Enter  submit    Esc  cancel", DIM, FG["muted"]))
        return lines

    def on_key(k: str):
        nonlocal value, error
        if k == keys.KEY_ESC:
            return True, _cancelled
        if k == keys.KEY_ENTER:
            if validator is not None:
                msg = validator(value)
                if msg:
                    error = msg
                    return False, None
            return True, value
        if k == keys.KEY_BACKSPACE:
            value = value[:-1]
            error = None
        elif k == keys.KEY_SPACE:
            value += " "
            error = None
        elif len(k) == 1 and k.isprintable():
            value += k
            error = None
        return False, None

    result = tui.run_modal(title=title, kind="question", body=body, on_key=on_key)
    if result is _cancelled:
        return None
    return result


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _wrap(text: str, width: int) -> list[str]:
    out: list[str] = []
    for raw_line in (text or "").splitlines() or [""]:
        if not raw_line:
            out.append("")
            continue
        words = raw_line.split(" ")
        line = ""
        for word in words:
            if not line:
                line = word
                continue
            if len(line) + 1 + len(word) <= width:
                line += " " + word
            else:
                out.append(line)
                line = word
        if line:
            out.append(line)
    return out or [""]
