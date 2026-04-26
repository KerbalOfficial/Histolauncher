from __future__ import annotations

import re
import sys
import tkinter

from launcher._constants import (
    BUTTON_STYLE_MAP,
    DIALOG_KIND_STYLES,
    FOCUS_COLOR,
    ICO_PATH,
    PANEL_BG_COLOR,
    PANEL_BORDER_COLOR,
    TEXT_PRIMARY_COLOR,
    TEXT_SECONDARY_COLOR,
    TOPBAR_ACTIVE_COLOR,
    TOPBAR_BG_COLOR,
)
from launcher.fonts import get_native_ui_font_family


__all__ = [
    "resolve_dialog_owner",
    "center_dialog_window",
    "play_dialog_sound",
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


def show_custom_dialog(title, message, kind="info", buttons=None, parent=None):
    style = DIALOG_KIND_STYLES.get(kind, DIALOG_KIND_STYLES["info"])
    buttons = list(buttons or [])
    if not buttons:
        buttons = [
            {
                "label": "OK",
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
        anchor="w",
        padx=12,
    )
    topbar_title.pack(side="left", fill="y")

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
    close_button.pack(side="right", fill="y")

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
    body.grid_columnconfigure(1, weight=1)

    icon_label = tkinter.Label(
        body,
        text=style["icon"],
        bg=PANEL_BG_COLOR,
        fg=style["icon_color"],
        font=(ui_font, 26),
        anchor="n",
        justify="center",
    )
    icon_label.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 14))

    text_wrap = tkinter.Frame(body, bg=PANEL_BG_COLOR)
    text_wrap.grid(row=0, column=1, sticky="nsew")

    title_label = tkinter.Label(
        text_wrap,
        text=title,
        bg=PANEL_BG_COLOR,
        fg=TEXT_PRIMARY_COLOR,
        font=(ui_font, 14, "bold"),
        anchor="w",
        justify="left",
    )
    title_label.pack(anchor="w")

    message_label = tkinter.Message(
        text_wrap,
        text=message,
        width=430,
        bg=PANEL_BG_COLOR,
        fg=TEXT_SECONDARY_COLOR,
        font=(ui_font, 11),
        justify="left",
    )
    message_label.pack(anchor="w", pady=(10, 0))

    buttons_row = tkinter.Frame(content, bg=PANEL_BG_COLOR)
    buttons_row.pack(fill="x", pady=(16, 0))

    buttons_wrap = tkinter.Frame(buttons_row, bg=PANEL_BG_COLOR)
    buttons_wrap.pack(anchor="center")

    button_widgets = []
    primary_button = None
    button_border_colors = {}
    button_border_frames = {}
    keyboard_focus_visible = False

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
            text=button_spec.get("label", "OK"),
            command=lambda value=button_spec.get("value"): finish(value),
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
        button_border.pack(side="left", padx=6)
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
    if primary_button is not None:
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
                "label": "OK",
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
                "label": "OK",
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
                "label": "OK",
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
                    "label": "OK",
                    "value": True,
                    "style": ok_style,
                    "primary": True,
                },
                {
                    "label": "Cancel",
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
                    "label": "Yes",
                    "value": True,
                    "style": yes_style,
                    "primary": True,
                },
                {
                    "label": "No",
                    "value": False,
                    "style": "default",
                    "cancel": True,
                },
            ],
        )
    )
