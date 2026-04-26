#!/usr/bin/env python3
# shortcut.pyw

from __future__ import annotations

import os
import sys
import traceback


def _show_fatal(message: str) -> None:
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, "Histolauncher", 0x40010)
            return
        except Exception:
            pass
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("Histolauncher", message)
        root.destroy()
    except Exception:
        pass


def _prepare_shortcut_ui() -> None:
    if not sys.platform.startswith("linux"):
        return
    try:
        from launcher.fonts import preinstall_linux_font

        preinstall_linux_font()
    except Exception:
        pass


def _icon_path(project_root: str) -> str:
    from core.shortcut_manager import get_shortcut_icon_path

    return get_shortcut_icon_path(project_root)


def _install_shortcut(project_root: str) -> bool:
    from core.shortcut_manager import install_platform_shortcut

    return install_platform_shortcut(project_root)


def _delete_shortcut() -> bool:
    from core.shortcut_manager import delete_platform_shortcut

    return delete_platform_shortcut()


def _shortcut_exists() -> bool:
    from core.shortcut_manager import platform_shortcut_exists

    return platform_shortcut_exists()


def _main() -> int:
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    _prepare_shortcut_ui()

    try:
        from launcher.dialogs import (
            show_custom_dialog,
            show_custom_error,
            show_custom_info,
            show_custom_warning,
        )
    except Exception:
        _show_fatal(
            "Histolauncher shortcut manager failed to start.\n\n"
            + traceback.format_exc()
        )
        return 1

    if not (sys.platform.startswith("win") or sys.platform.startswith("linux")):
        show_custom_warning(
            "Shortcut Manager",
            "Shortcut management is available on Windows and Linux.",
        )
        return 0

    shortcut_exists = _shortcut_exists()
    buttons = [
        {
            "label": "Create or Repair" if shortcut_exists else "Create",
            "value": "install",
            "style": "primary",
            "primary": True,
        },
    ]
    if shortcut_exists:
        buttons.append({
            "label": "Delete",
            "value": "delete",
            "style": "danger",
        })
    buttons.append({
        "label": "Cancel",
        "value": None,
        "style": "default",
        "cancel": True,
    })

    message = (
        "Would you like to create the Histolauncher shortcut?"
        if not shortcut_exists
        else "Create, repair, or delete the Histolauncher shortcut.\n\n"
             "'Create or Repair' updates the shortcut to this Histolauncher folder, "
             "so run this again if you move the folder somewhere else."
    )

    choice = show_custom_dialog(
        "Histolauncher Shortcut",
        message,
        kind="question",
        buttons=buttons,
    )

    try:
        if choice == "install":
            if _install_shortcut(project_root):
                show_custom_info(
                    "Shortcut Created",
                    f"The Histolauncher shortcut is ready.",
                )
                return 0
            show_custom_error(
                "Shortcut Error",
                "Histolauncher could not create or repair the shortcut.",
            )
            return 1

        if choice == "delete":
            if _delete_shortcut():
                show_custom_info(
                    "Shortcut Deleted",
                    f"The Histolauncher shortcut has been removed.",
                )
                return 0
            show_custom_error(
                "Shortcut Error",
                "Histolauncher could not delete the shortcut.",
            )
            return 1
    except Exception:
        show_custom_error(
            "Shortcut Error",
            "Histolauncher shortcut manager failed.\n\n"
            + traceback.format_exc(),
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(_main())