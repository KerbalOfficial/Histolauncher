from __future__ import annotations

import re
import sys
import tkinter

from launcher._constants import (
    BUTTON_STYLE_MAP,
    DIALOG_KIND_STYLES,
    FOCUS_COLOR,
    ICO_PATH,
    INPUT_BG_COLOR,
    INPUT_BORDER_COLOR,
    INPUT_FOCUS_RING_COLOR,
    INPUT_POPUP_BG_COLOR,
    INPUT_SELECTION_BG_COLOR,
    PANEL_BG_COLOR,
    PANEL_BORDER_COLOR,
    TEXT_PRIMARY_COLOR,
    TEXT_SECONDARY_COLOR,
    TOPBAR_ACTIVE_COLOR,
    TOPBAR_BG_COLOR,
)
from launcher.fonts import get_native_ui_font_family
from launcher.i18n import available_languages, set_temporary_language, t, tk_direction_options


__all__ = [
    "resolve_dialog_owner",
    "center_dialog_window",
    "play_dialog_sound",
    "build_dropdown_selector",
    "build_language_selector",
    "show_custom_dialog",
    "show_custom_info",
    "show_custom_warning",
    "show_custom_error",
    "ask_custom_okcancel",
    "ask_custom_yesno",
]


def resolve_dialog_owner(parent=None):
    if parent is not None:
        try:
            if parent.winfo_exists():
                return parent, False
        except Exception:
            pass

    try:
        default_root = getattr(tkinter, "_default_root", None)
        if default_root is not None and default_root.winfo_exists():
            return default_root, False
    except Exception:
        pass

    owner = tkinter.Tk()
    owner.withdraw()
    return owner, True


def center_dialog_window(dialog, owner=None):
    dialog.update_idletasks()
    width = dialog.winfo_reqwidth()
    height = dialog.winfo_reqheight()

    geometry_match = re.match(r"^(\d+)x(\d+)", dialog.wm_geometry())
    if geometry_match is not None:
        width = max(width, int(geometry_match.group(1)))
        height = max(height, int(geometry_match.group(2)))

    x = (dialog.winfo_screenwidth() - width) // 2
    y = (dialog.winfo_screenheight() - height) // 2

    if owner is not None:
        try:
            if owner.winfo_viewable():
                owner.update_idletasks()
                x = owner.winfo_rootx() + ((owner.winfo_width() - width) // 2)
                y = owner.winfo_rooty() + ((owner.winfo_height() - height) // 2)
        except Exception:
            pass

    dialog.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")


def play_dialog_sound(kind="info", widget=None):
    if sys.platform.startswith("win"):
        try:
            import winsound

            sound_map = {
                "info": winsound.MB_ICONASTERISK,
                "warning": winsound.MB_ICONEXCLAMATION,
                "question": winsound.MB_ICONQUESTION,
                "error": winsound.MB_ICONHAND,
            }
            winsound.MessageBeep(sound_map.get(kind, winsound.MB_OK))
            return
        except Exception:
            pass

    if widget is not None:
        try:
            widget.bell()
        except Exception:
            pass


def build_dropdown_selector(
    parent,
    dialog,
    ui_font,
    direction,
    options,
    initial_value=None,
    label_text=None,
    on_change=None,
    refresh_dialog=None,
):
    if not options:
        return None

    values = [o["value"] for o in options]
    labels = [o["label"] for o in options]
    rtl_flags = [bool(o.get("rtl")) for o in options]

    current = initial_value if initial_value in values else values[0]
    selected = {"value": current}

    # --- optional label above the combo ---
    label_widget = None
    if label_text is not None:
        label_widget = tkinter.Label(
            parent,
            text=label_text() if callable(label_text) else label_text,
            bg=PANEL_BG_COLOR,
            fg=TEXT_PRIMARY_COLOR,
            font=(ui_font, 10, "bold"),
            anchor=direction["anchor"],
            justify=direction["justify"],
        )
        label_widget.pack(fill="x", pady=(14, 6))

    # --- combo shell ---
    combo_wrap = tkinter.Frame(parent, bg=INPUT_BORDER_COLOR, padx=1, pady=1)
    combo_wrap.pack(fill="x")
    combo_wrap.grid_columnconfigure(0, weight=1)

    combo_focus = tkinter.Frame(combo_wrap, bg=INPUT_BG_COLOR, padx=1, pady=1)
    combo_focus.grid(row=0, column=0, sticky="ew")
    combo_focus.grid_columnconfigure(0, weight=1)

    combo_shell = tkinter.Frame(
        combo_focus,
        bg=INPUT_BG_COLOR,
        cursor="hand2",
        takefocus=True,
    )
    combo_shell.grid(row=0, column=0, sticky="ew")
    combo_shell.grid_columnconfigure(0, weight=1)

    display_var = tkinter.StringVar()
    popup_state = {"window": None}

    selected_label = tkinter.Label(
        combo_shell,
        textvariable=display_var,
        bg=INPUT_BG_COLOR,
        fg=TEXT_PRIMARY_COLOR,
        font=(ui_font, 11),
        padx=10,
        pady=7,
        anchor="w",
        justify=direction["justify"],
        cursor="hand2",
    )
    selected_label.grid(row=0, column=0, sticky="ew")

    arrow_label = tkinter.Label(
        combo_shell,
        text="\u25be",
        bg=INPUT_BG_COLOR,
        fg=TEXT_SECONDARY_COLOR,
        font=(ui_font, 11, "bold"),
        padx=10,
        pady=7,
        cursor="hand2",
    )
    arrow_label.grid(row=0, column=1, sticky="ns")

    def get_value():
        return selected["value"]

    def _update_display():
        try:
            idx = values.index(selected["value"])
        except ValueError:
            idx = 0
            selected["value"] = values[0]
        display_var.set(labels[idx])

    def _apply_direction(d):
        if label_widget is not None:
            label_widget.configure(
                text=label_text() if callable(label_text) else (label_text or ""),
                anchor=d["anchor"],
                justify=d["justify"],
            )
        selected_label.configure(anchor=d["anchor"], justify=d["justify"])
        if d["start_side"] == "right":
            selected_label.grid_configure(column=1)
            arrow_label.grid_configure(column=0)
        else:
            selected_label.grid_configure(column=0)
            arrow_label.grid_configure(column=1)

    def _set_focus_ring(active):
        combo_wrap.configure(bg=FOCUS_COLOR if active else INPUT_BORDER_COLOR)
        combo_focus.configure(bg=INPUT_FOCUS_RING_COLOR if active else INPUT_BG_COLOR)

    def _close_menu(_event=None):
        popup = popup_state["window"]
        popup_state["window"] = None
        cb = popup_state.pop("_configure_cb", None)
        if cb is not None:
            try:
                dialog.unbind("<Configure>", None)
            except Exception:
                pass
        if popup is not None:
            try:
                popup.destroy()
            except Exception:
                pass
        arrow_label.configure(text="\u25be")

    def _commit(idx):
        if not (0 <= idx < len(values)):
            return "break"
        selected["value"] = values[idx]
        _update_display()
        if callable(on_change):
            on_change(selected["value"])
        if callable(refresh_dialog):
            refresh_dialog()
        else:
            _apply_direction(tk_direction_options())
        _close_menu()
        combo_shell.focus_set()
        return "break"

    def _open_menu(_event=None):
        if popup_state["window"] is not None:
            _close_menu()
            return "break"

        dialog.update_idletasks()
        popup = tkinter.Toplevel(dialog)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.configure(bg=INPUT_BORDER_COLOR)
        try:
            popup.transient(dialog)
        except Exception:
            pass

        shell_x = combo_wrap.winfo_rootx()
        shell_y = combo_wrap.winfo_rooty() + combo_wrap.winfo_height() + 4
        shell_width = max(combo_wrap.winfo_width(), 320)
        visible_rows = min(9, len(labels))

        popup_border = tkinter.Frame(popup, bg=INPUT_BORDER_COLOR, padx=1, pady=1)
        popup_border.pack(fill="both", expand=True)

        popup_body = tkinter.Frame(popup_border, bg=INPUT_POPUP_BG_COLOR)
        popup_body.pack(fill="both", expand=True)

        try:
            cur_idx = values.index(selected["value"])
        except ValueError:
            cur_idx = 0

        row_state = {"hover": -1, "sel": cur_idx}
        row_labels = []
        _ROW_HOVER_BG = "#1a2d3d"

        def _row_bg(i):
            if i == row_state["sel"]:
                return INPUT_SELECTION_BG_COLOR
            if i == row_state["hover"]:
                return _ROW_HOVER_BG
            return INPUT_POPUP_BG_COLOR

        def _refresh_row(i):
            if 0 <= i < len(row_labels):
                row_labels[i].configure(bg=_row_bg(i))

        scrollbar = tkinter.Scrollbar(
            popup_body,
            orient="vertical",
            troughcolor=INPUT_POPUP_BG_COLOR,
            activebackground="#4a4d4f",
            bg="#2b2b2b",
            elementborderwidth=0,
            borderwidth=0,
        )
        canvas = tkinter.Canvas(
            popup_body,
            bg=INPUT_POPUP_BG_COLOR,
            highlightthickness=0,
            bd=0,
            relief="flat",
            yscrollcommand=scrollbar.set,
        )
        scrollbar.configure(command=canvas.yview)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        inner_frame = tkinter.Frame(canvas, bg=INPUT_POPUP_BG_COLOR)
        canvas_win = canvas.create_window((0, 0), window=inner_frame, anchor="nw")

        for i, (lbl, is_rtl) in enumerate(zip(labels, rtl_flags)):
            anchor = "e" if is_rtl else "w"
            row_label = tkinter.Label(
                inner_frame,
                text=lbl,
                bg=_row_bg(i),
                fg=TEXT_PRIMARY_COLOR,
                font=(ui_font, 11),
                padx=10,
                pady=6,
                anchor=anchor,
                justify="right" if is_rtl else "left",
            )
            row_label.pack(fill="x")
            row_labels.append(row_label)

        def _scroll_into_view(i):
            if not row_labels:
                return
            canvas.update_idletasks()
            total_h = inner_frame.winfo_height()
            if total_h <= 0:
                return
            row_y = row_labels[i].winfo_y()
            row_h = row_labels[i].winfo_height()
            view_h = canvas.winfo_height()
            view_top = canvas.canvasy(0)
            view_bot = view_top + view_h
            if row_y < view_top:
                canvas.yview_moveto(row_y / total_h)
            elif row_y + row_h > view_bot:
                canvas.yview_moveto((row_y + row_h - view_h) / total_h)

        def _set_sel(i):
            old = row_state["sel"]
            row_state["sel"] = i
            _refresh_row(old)
            _refresh_row(i)
            _scroll_into_view(i)

        def _row_at_canvas_y(canvas_y):
            frame_y = canvas.canvasy(canvas_y)
            for i, lbl in enumerate(row_labels):
                ry = lbl.winfo_y()
                if ry <= frame_y < ry + lbl.winfo_height():
                    return i
            return -1

        def _on_motion(event):
            i = _row_at_canvas_y(event.y)
            old = row_state["hover"]
            if i == old:
                return
            row_state["hover"] = i
            _refresh_row(old)
            _refresh_row(i)

        def _on_leave(_ev=None):
            old = row_state["hover"]
            row_state["hover"] = -1
            _refresh_row(old)

        def _on_click(event):
            i = _row_at_canvas_y(event.y)
            if i >= 0:
                _set_sel(i)
                _commit(i)

        def _on_mouse_wheel(event):
            delta = getattr(event, "delta", 0)
            if delta:
                step = -1 if delta > 0 else 1
                canvas.yview_scroll(step, "units")
            else:
                num = getattr(event, "num", None)
                if num == 4:
                    canvas.yview_scroll(-1, "units")
                elif num == 5:
                    canvas.yview_scroll(1, "units")
            return "break"

        def _on_key_up(_ev=None):
            i = max(0, row_state["sel"] - 1)
            _set_sel(i)
            return "break"

        def _on_key_down(_ev=None):
            i = min(len(labels) - 1, row_state["sel"] + 1)
            _set_sel(i)
            return "break"

        def _commit_current(_ev=None):
            return _commit(row_state["sel"])

        def _maybe_close(_ev=None):
            popup.after(
                1,
                lambda: _close_menu() if not popup.focus_displayof() else None,
            )

        canvas.bind("<Motion>", _on_motion)
        canvas.bind("<Leave>", _on_leave)
        canvas.bind("<ButtonRelease-1>", _on_click)
        canvas.bind("<Up>", _on_key_up)
        canvas.bind("<Down>", _on_key_down)
        canvas.bind("<Return>", _commit_current)
        canvas.bind("<KP_Enter>", _commit_current)
        canvas.bind("<Escape>", lambda _ev: _close_menu() or "break")
        canvas.bind("<MouseWheel>", _on_mouse_wheel)
        canvas.bind("<Button-4>", _on_mouse_wheel)
        canvas.bind("<Button-5>", _on_mouse_wheel)
        canvas.bind("<FocusOut>", _maybe_close)
        popup.bind("<FocusOut>", _maybe_close)

        for rl in row_labels:
            rl.bind("<Motion>", lambda e: _on_motion(
                type("_E", (), {"y": e.y + e.widget.winfo_y() - canvas.canvasy(0)})()
            ))
            rl.bind("<Leave>", _on_leave)
            rl.bind("<ButtonRelease-1>", lambda e: _on_click(
                type("_E", (), {"y": e.y + e.widget.winfo_y() - canvas.canvasy(0)})()
            ))
            rl.bind("<MouseWheel>", _on_mouse_wheel)
            rl.bind("<Button-4>", _on_mouse_wheel)
            rl.bind("<Button-5>", _on_mouse_wheel)

        inner_frame.update_idletasks()
        canvas.configure(
            scrollregion=canvas.bbox("all"),
            width=shell_width - 2,
        )

        def _on_inner_configure(_ev=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            w = canvas.winfo_width()
            if w > 1:
                canvas.itemconfigure(canvas_win, width=w)

        inner_frame.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_inner_configure)

        row_h = row_labels[0].winfo_reqheight() if row_labels else 28
        canvas_h = visible_rows * row_h
        canvas.configure(height=canvas_h)
        _scroll_into_view(cur_idx)

        popup.update_idletasks()
        popup_height = popup.winfo_reqheight()
        popup.geometry(f"{shell_width}x{popup_height}+{shell_x}+{shell_y}")
        popup.attributes("-topmost", True)
        popup.deiconify()
        popup.lift()
        popup_state["window"] = popup
        arrow_label.configure(text="\u25b4")
        canvas.focus_set()

        def _on_dialog_configure(_ev=None):
            if popup_state["window"] is popup:
                _close_menu()

        popup_state["_configure_cb"] = _on_dialog_configure
        dialog.bind("<Configure>", _on_dialog_configure, add=True)
        return "break"

    def _focus_in(_ev=None):
        _set_focus_ring(True)

    def _focus_out(_ev=None):
        if popup_state["window"] is None:
            _set_focus_ring(False)

    for widget in (combo_shell, selected_label, arrow_label):
        widget.bind("<Button-1>", _open_menu)
        widget.bind("<space>", _open_menu)
        widget.bind("<Return>", _open_menu)
        widget.bind("<Down>", _open_menu)
        widget.bind("<FocusIn>", _focus_in)
        widget.bind("<FocusOut>", _focus_out)

    _update_display()
    _apply_direction(direction)

    return {
        "get_value": get_value,
        "initial_focus": combo_shell,
        "close": _close_menu,
        "refresh": _apply_direction,
    }


def build_language_selector(
    parent,
    dialog,
    ui_font,
    direction,
    initial_code=None,
    refresh_dialog=None,
):
    language_options = available_languages()
    if not language_options:
        return None

    options = []
    for opt in language_options:
        native = opt.get("nativeName") or opt["name"]
        english = opt.get("name") or opt["code"]
        label = native if native.casefold() == english.casefold() else f"{native} - {english}"
        options.append({"value": opt["code"], "label": label, "rtl": opt["dir"] == "rtl"})

    return build_dropdown_selector(
        parent,
        dialog,
        ui_font,
        direction,
        options=options,
        initial_value=initial_code,
        label_text=lambda: t("settings.appearance.language"),
        on_change=set_temporary_language,
        refresh_dialog=refresh_dialog,
    )


def show_custom_dialog(
    title,
    message,
    kind="info",
    buttons=None,
    parent=None,
    show_icon=True,
    content_builder=None,
):
    style = DIALOG_KIND_STYLES.get(kind, DIALOG_KIND_STYLES["info"])
    buttons = list(buttons or [])
    if not buttons:
        buttons = [
            {
                "label": t("common.ok"),
                "value": True,
                "style": style["button_style"],
                "primary": True,
                "cancel": True,
            }
        ]

    close_value = next(
        (btn.get("value") for btn in buttons if btn.get("cancel")),
        buttons[-1].get("value"),
    )
    owner, owns_owner = resolve_dialog_owner(parent=parent)

    dialog = tkinter.Toplevel(owner)
    try:
        dialog.iconbitmap(ICO_PATH)
    except Exception:
        pass
    dialog.withdraw()
    dialog.title(title or "Histolauncher")
    dialog.configure(bg="#000000")
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)
    dialog.overrideredirect(True)
    try:
        dialog.wm_attributes("-toolwindow", True)
    except Exception:
        pass
    try:
        dialog.transient(owner)
    except Exception:
        pass

    ui_font = get_native_ui_font_family(dialog)
    direction = tk_direction_options()
    result = {"value": close_value}
    drag_state = {"x": 0, "y": 0}

    outer = tkinter.Frame(dialog, bg=PANEL_BORDER_COLOR, padx=4, pady=4)
    outer.pack(fill="both", expand=True)

    card = tkinter.Frame(outer, bg=PANEL_BG_COLOR)
    card.pack(fill="both", expand=True)

    topbar = tkinter.Frame(card, bg=TOPBAR_BG_COLOR, height=34)
    topbar.pack(fill="x")
    topbar.pack_propagate(False)

    topbar_title = tkinter.Label(
        topbar,
        text=title or "Histolauncher",
        bg=TOPBAR_BG_COLOR,
        fg=TEXT_PRIMARY_COLOR,
        font=(ui_font, 10, "bold"),
        anchor=direction["anchor"],
        justify=direction["justify"],
        padx=12,
    )
    topbar_title.pack(side=direction["start_side"], fill="both", expand=True)

    def invoke_cancel():
        for index, button_spec in enumerate(buttons):
            if button_spec.get("cancel"):
                button_widgets[index].invoke()
                return
        finish(close_value)

    close_button = tkinter.Button(
        topbar,
        text="\u2715",
        command=invoke_cancel,
        bg=TOPBAR_BG_COLOR,
        fg=TEXT_PRIMARY_COLOR,
        activebackground=TOPBAR_ACTIVE_COLOR,
        activeforeground=TEXT_PRIMARY_COLOR,
        highlightthickness=0,
        bd=0,
        relief="flat",
        padx=12,
        pady=6,
        cursor="hand2",
        takefocus=False,
        font=(ui_font, 10, "bold"),
    )
    close_button.pack(side=direction["end_side"], fill="y")

    def start_drag(event):
        drag_state["x"] = event.x_root - dialog.winfo_x()
        drag_state["y"] = event.y_root - dialog.winfo_y()

    def do_drag(event):
        new_x = event.x_root - drag_state["x"]
        new_y = event.y_root - drag_state["y"]
        dialog.geometry(f"+{max(0, new_x)}+{max(0, new_y)}")

    for draggable in (topbar, topbar_title):
        draggable.bind("<ButtonPress-1>", start_drag)
        draggable.bind("<B1-Motion>", do_drag)

    content = tkinter.Frame(card, bg=PANEL_BG_COLOR, padx=18, pady=18)
    content.pack(fill="both", expand=True)

    body = tkinter.Frame(content, bg=PANEL_BG_COLOR)
    body.pack(fill="both", expand=True)

    icon_label = None
    if show_icon:
        icon_column = 1 if direction["start_side"] == "right" else 0
        text_column = 0 if direction["start_side"] == "right" else 1
        icon_sticky = "ne" if direction["start_side"] == "right" else "nw"
        icon_padx = (14, 0) if direction["start_side"] == "right" else (0, 14)
        body.grid_columnconfigure(text_column, weight=1)

        icon_label = tkinter.Label(
            body,
            text=style["icon"],
            bg=PANEL_BG_COLOR,
            fg=style["icon_color"],
            font=(ui_font, 26),
            anchor="n",
            justify="center",
        )
        icon_label.grid(
            row=0,
            column=icon_column,
            rowspan=2,
            sticky=icon_sticky,
            padx=icon_padx,
        )

        text_wrap = tkinter.Frame(body, bg=PANEL_BG_COLOR)
        text_wrap.grid(row=0, column=text_column, sticky="nsew")
    else:
        body.grid_columnconfigure(0, weight=1)
        text_wrap = tkinter.Frame(body, bg=PANEL_BG_COLOR)
        text_wrap.grid(row=0, column=0, sticky="nsew")

    title_label = tkinter.Label(
        text_wrap,
        text="",
        bg=PANEL_BG_COLOR,
        fg=TEXT_PRIMARY_COLOR,
        font=(ui_font, 14, "bold"),
        anchor=direction["anchor"],
        justify=direction["justify"],
    )
    title_label.pack(anchor=direction["anchor"])

    message_label = tkinter.Message(
        text_wrap,
        text="",
        width=430,
        bg=PANEL_BG_COLOR,
        fg=TEXT_SECONDARY_COLOR,
        font=(ui_font, 11),
        justify=direction["justify"],
    )
    message_label.pack(anchor=direction["anchor"], pady=(10, 0))

    custom_content_state = {}
    button_widgets = []
    button_border_colors = {}
    button_border_frames = {}
    keyboard_focus_visible = False
    primary_button = None

    def resolve_text(value):
        return value() if callable(value) else value

    def fit_dialog_to_content(expand_only=True):
        dialog.update_idletasks()
        req_w = dialog.winfo_reqwidth()
        req_h = dialog.winfo_reqheight()
        if expand_only:
            cur_w = dialog.winfo_width() or req_w
            cur_h = dialog.winfo_height() or req_h
            req_w = max(req_w, cur_w)
            req_h = max(req_h, cur_h)
        dialog.geometry(f"{req_w}x{req_h}")

    def refresh_dialog_texts():
        current_direction = tk_direction_options()
        dialog_title = resolve_text(title) or "Histolauncher"
        message_text = resolve_text(message) or ""
        dialog.title(dialog_title)
        topbar_title.configure(
            text=dialog_title,
            anchor=current_direction["anchor"],
            justify=current_direction["justify"],
        )
        title_label.configure(
            text=dialog_title,
            anchor=current_direction["anchor"],
            justify=current_direction["justify"],
        )
        title_label.pack_configure(anchor=current_direction["anchor"])
        message_label.configure(
            text=message_text,
            justify=current_direction["justify"],
        )
        message_label.pack_configure(anchor=current_direction["anchor"])
        if callable(content_builder) and custom_content_state.get("refresh"):
            custom_content_state["refresh"](current_direction)
        for index, btn in enumerate(button_widgets):
            btn.configure(text=resolve_text(buttons[index].get("label", t("common.ok"))))
        fit_dialog_to_content(expand_only=False)

    if callable(content_builder):
        custom_content_state = content_builder(
            {
                "dialog": dialog,
                "content": content,
                "body": body,
                "text_wrap": text_wrap,
                "ui_font": ui_font,
                "direction": direction,
                "refresh_dialog": refresh_dialog_texts,
            }
        ) or {}

    refresh_dialog_texts()

    buttons_row = tkinter.Frame(content, bg=PANEL_BG_COLOR)
    buttons_row.pack(fill="x", pady=(16, 0))

    buttons_wrap = tkinter.Frame(buttons_row, bg=PANEL_BG_COLOR)
    buttons_wrap.pack(anchor="center")

    def update_button_borders():
        focused_widget = dialog.focus_get()
        for btn in button_widgets:
            border_frame = button_border_frames.get(btn)
            if border_frame is None:
                continue
            border = button_border_colors.get(btn, PANEL_BORDER_COLOR)
            border_frame.configure(
                bg=FOCUS_COLOR
                if keyboard_focus_visible and focused_widget is btn
                else border
            )

    def finish(value):
        result["value"] = value
        try:
            close_custom = custom_content_state.get("close")
            if callable(close_custom):
                close_custom()
        except Exception:
            pass
        try:
            dialog.grab_release()
        except Exception:
            pass
        try:
            dialog.destroy()
        except Exception:
            pass

    for button_spec in buttons:
        style_name = button_spec.get("style") or (
            "primary" if button_spec.get("primary") else style["button_style"]
        )
        button_style = BUTTON_STYLE_MAP.get(style_name, BUTTON_STYLE_MAP["default"])

        button_border = tkinter.Frame(
            buttons_wrap,
            bg=button_style["border"],
            padx=4,
            pady=4,
            bd=0,
            highlightthickness=0,
        )
        button = tkinter.Button(
            button_border,
            text=resolve_text(button_spec.get("label", t("common.ok"))),
            command=lambda value=button_spec.get("value"): finish(resolve_text(value)),
            bg=button_style["bg"],
            fg=button_style["fg"],
            activebackground=button_style["active_bg"],
            activeforeground=button_style["fg"],
            highlightthickness=0,
            bd=0,
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            takefocus=True,
            font=(ui_font, 10, "bold" if button_spec.get("primary") else "normal"),
            default="active" if button_spec.get("primary") else "normal",
        )
        button.pack(fill="both", expand=True)
        button_border_colors[button] = button_style["border"]
        button_border_frames[button] = button_border
        button_border.pack(side=direction["start_side"], padx=6)
        button.bind(
            "<Return>", lambda _event, btn=button: (btn.invoke(), "break")[1]
        )
        button.bind(
            "<KP_Enter>", lambda _event, btn=button: (btn.invoke(), "break")[1]
        )
        button.bind(
            "<space>", lambda _event, btn=button: (btn.invoke(), "break")[1]
        )
        button.bind(
            "<Enter>",
            lambda _event, btn=button, hover=button_style["active_bg"]: btn.configure(
                bg=hover
            ),
        )
        button.bind(
            "<Leave>",
            lambda _event, btn=button, bg=button_style["bg"]: btn.configure(
                bg=bg
            ),
        )
        button.bind("<FocusIn>", lambda _event: update_button_borders())
        button.bind(
            "<FocusOut>", lambda _event: dialog.after_idle(update_button_borders)
        )
        button_widgets.append(button)
        if primary_button is None and button_spec.get("primary"):
            primary_button = button

    if primary_button is None and button_widgets:
        primary_button = button_widgets[0]

    fit_dialog_to_content(expand_only=True)

    def set_button_focus_visible(visible):
        nonlocal keyboard_focus_visible
        keyboard_focus_visible = visible
        dialog.after_idle(update_button_borders)

    def handle_keyboard_focus_navigation(_event=None):
        if not keyboard_focus_visible:
            set_button_focus_visible(True)
        return None

    def handle_pointer_focus_navigation(_event=None):
        if keyboard_focus_visible:
            set_button_focus_visible(False)
        return None

    def move_button_focus(delta):
        if not button_widgets:
            return "break"

        focused_widget = dialog.focus_get()
        try:
            current_index = button_widgets.index(focused_widget)
        except ValueError:
            if primary_button in button_widgets:
                current_index = button_widgets.index(primary_button)
            else:
                current_index = 0

        next_index = (current_index + delta) % len(button_widgets)
        next_button = button_widgets[next_index]
        try:
            next_button.focus_force()
        except Exception:
            try:
                next_button.focus_set()
            except Exception:
                pass
        dialog.after_idle(update_button_borders)

        return "break"

    def handle_tab_navigation(delta):
        set_button_focus_visible(True)
        return move_button_focus(delta)

    def handle_arrow_navigation(delta):
        handle_keyboard_focus_navigation()
        return move_button_focus(delta)

    for btn in button_widgets:
        btn.bind("<Tab>", lambda _event, d=1: handle_tab_navigation(d))
        btn.bind("<Shift-Tab>", lambda _event, d=-1: handle_tab_navigation(d))
        btn.bind("<ISO_Left_Tab>", lambda _event, d=-1: handle_tab_navigation(d))
        btn.bind("<Left>", lambda _event, d=-1: handle_arrow_navigation(d))
        btn.bind("<Right>", lambda _event, d=1: handle_arrow_navigation(d))
        btn.bind("<Up>", lambda _event, d=-1: handle_arrow_navigation(d))
        btn.bind("<Down>", lambda _event, d=1: handle_arrow_navigation(d))
        btn.bind("<ButtonPress-1>", handle_pointer_focus_navigation, add="+")

    def trigger_focused_button(prefer_primary=False):
        focused_widget = dialog.focus_get()
        if focused_widget in button_widgets:
            focused_widget.invoke()
        elif primary_button is not None:
            if prefer_primary or focused_widget in (
                None,
                dialog,
                card,
                content,
                body,
                text_wrap,
                title_label,
                message_label,
                icon_label,
            ):
                primary_button.invoke()
        return "break"

    def handle_return(_event=None):
        return trigger_focused_button(prefer_primary=True)

    def handle_space(_event=None):
        return trigger_focused_button(prefer_primary=False)

    def ensure_primary_focus():
        if primary_button is None:
            return
        if dialog.focus_get() in button_widgets:
            update_button_borders()
            return "break"
        try:
            dialog.focus_force()
        except Exception:
            try:
                dialog.focus_set()
            except Exception:
                pass
        try:
            primary_button.focus_force()
        except Exception:
            try:
                primary_button.focus_set()
            except Exception:
                pass
        dialog.after_idle(update_button_borders)
        return "break"

    dialog.protocol("WM_DELETE_WINDOW", invoke_cancel)
    dialog.bind("<Return>", handle_return)
    dialog.bind("<KP_Enter>", handle_return)
    dialog.bind("<space>", handle_space)
    dialog.bind("<Escape>", lambda _event: (invoke_cancel(), "break")[1])

    center_dialog_window(dialog, owner if not owns_owner else None)
    dialog.deiconify()
    dialog.lift()
    try:
        dialog.wait_visibility()
    except Exception:
        pass
    dialog.grab_set()
    dialog.after_idle(
        lambda: play_dialog_sound(style.get("sound", kind), dialog)
    )
    initial_focus = custom_content_state.get("initial_focus")
    if initial_focus is not None:
        def ensure_custom_focus():
            target = initial_focus() if callable(initial_focus) else initial_focus
            if target is None:
                return
            try:
                target.focus_force()
            except Exception:
                try:
                    target.focus_set()
                except Exception:
                    pass

        dialog.after_idle(ensure_custom_focus)
        dialog.after(25, ensure_custom_focus)
        dialog.after(100, ensure_custom_focus)
    elif primary_button is not None:
        dialog.after_idle(ensure_primary_focus)
        dialog.after(25, ensure_primary_focus)
        dialog.after(100, ensure_primary_focus)

    dialog.wait_window()

    if owns_owner:
        try:
            owner.destroy()
        except Exception:
            pass

    return result["value"]


def show_custom_info(title, message, parent=None):
    return show_custom_dialog(
        title,
        message,
        kind="info",
        parent=parent,
        buttons=[
            {
                "label": t("common.ok"),
                "value": True,
                "style": "important",
                "primary": True,
                "cancel": True,
            }
        ],
    )


def show_custom_warning(title, message, parent=None):
    return show_custom_dialog(
        title,
        message,
        kind="warning",
        parent=parent,
        buttons=[
            {
                "label": t("common.ok"),
                "value": True,
                "style": "mild",
                "primary": True,
                "cancel": True,
            }
        ],
    )


def show_custom_error(title, message, parent=None):
    return show_custom_dialog(
        title,
        message,
        kind="error",
        parent=parent,
        buttons=[
            {
                "label": t("common.ok"),
                "value": True,
                "style": "danger",
                "primary": True,
                "cancel": True,
            }
        ],
    )


def ask_custom_okcancel(
    title, message, parent=None, kind="question", ok_style="primary"
):
    return bool(
        show_custom_dialog(
            title,
            message,
            kind=kind,
            parent=parent,
            buttons=[
                {
                    "label": t("common.ok"),
                    "value": True,
                    "style": ok_style,
                    "primary": True,
                },
                {
                    "label": t("common.cancel"),
                    "value": False,
                    "style": "default",
                    "cancel": True,
                },
            ],
        )
    )


def ask_custom_yesno(
    title, message, parent=None, kind="question", yes_style="primary"
):
    return bool(
        show_custom_dialog(
            title,
            message,
            kind=kind,
            parent=parent,
            buttons=[
                {
                    "label": t("common.yes"),
                    "value": True,
                    "style": yes_style,
                    "primary": True,
                },
                {
                    "label": t("common.no"),
                    "value": False,
                    "style": "default",
                    "cancel": True,
                },
            ],
        )
    )
