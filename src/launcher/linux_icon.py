from __future__ import annotations

import os
import sys

from core.logger import colorize_log


__all__ = [
    "WM_CLASS_NAME",
    "set_gtk_program_class",
    "set_gtk_default_icon",
    "apply_gtk_window_icon",
    "ensure_desktop_file",
    "install_linux_window_icon",
]


WM_CLASS_NAME = "Histolauncher"


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def set_gtk_program_class(name: str = WM_CLASS_NAME) -> bool:
    if not _is_linux():
        return False
    try:
        import gi
        gi.require_version("Gdk", "3.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gdk, GLib

        try:
            Gdk.set_program_class(name)
        except Exception:
            pass
        try:
            GLib.set_prgname(name)
        except Exception:
            pass
        try:
            GLib.set_application_name(name)
        except Exception:
            pass
        return True
    except Exception as exc:
        print(colorize_log(
            f"[launcher] Could not set GTK program class: {exc}"
        ))
        return False


def set_gtk_default_icon(icon_path: str) -> bool:
    if not _is_linux():
        return False
    if not icon_path or not os.path.isfile(icon_path):
        return False
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        if hasattr(Gtk.Window, "set_default_icon_from_file"):
            try:
                Gtk.Window.set_default_icon_from_file(icon_path)
                return True
            except Exception:
                pass

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(icon_path)
        if hasattr(Gtk.Window, "set_default_icon"):
            Gtk.Window.set_default_icon(pixbuf)
            return True
        return False
    except Exception as exc:
        print(colorize_log(
            f"[launcher] Could not set GTK default icon: {exc}"
        ))
        return False


def apply_gtk_window_icon(native_window, icon_path: str) -> bool:
    if not _is_linux() or native_window is None:
        return False
    if not icon_path or not os.path.isfile(icon_path):
        return False
    try:
        if hasattr(native_window, "set_icon_from_file"):
            try:
                native_window.set_icon_from_file(icon_path)
                return True
            except Exception:
                pass

        try:
            import gi
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(icon_path)
            if hasattr(native_window, "set_icon"):
                native_window.set_icon(pixbuf)
                return True
        except Exception as exc:
            print(colorize_log(
                f"[launcher] GdkPixbuf icon fallback failed: {exc}"
            ))
        return False
    except Exception as exc:
        print(colorize_log(
            f"[launcher] Could not set GTK window icon: {exc}"
        ))
        return False


def ensure_desktop_file(icon_path: str) -> bool:
    if not _is_linux():
        return False
    if not icon_path or not os.path.isfile(icon_path):
        return False
    try:
        from core.shortcut_manager import (
            install_linux_desktop_shortcut,
            linux_shortcut_target_for_project,
        )
        from launcher._constants import PROJECT_ROOT

        target_path, arguments = linux_shortcut_target_for_project(PROJECT_ROOT)
        if not target_path:
            return False

        ok = install_linux_desktop_shortcut(
            target_path=target_path,
            arguments=arguments,
            icon_path=icon_path,
            working_dir=PROJECT_ROOT,
        )
        if not ok:
            return False
        return True
    except Exception as exc:
        print(colorize_log(
            f"[launcher] Could not install desktop entry: {exc}"
        ))
        return False


def install_linux_window_icon(icon_path: str) -> None:
    if not _is_linux():
        return
    # If using Qt Backend, steer clear from mixing Gtk on Wayland
    if os.environ.get("PYWEBVIEW_GUI", "").lower() != "qt":
        set_gtk_program_class(WM_CLASS_NAME)
        set_gtk_default_icon(icon_path)
    ensure_desktop_file(icon_path)
