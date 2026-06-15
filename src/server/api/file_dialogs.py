from __future__ import annotations

import contextlib
import os
import secrets
import threading
import time
from typing import Any, Callable

from core.logger import safe_print
from launcher._constants import ICO_PATH, PNG_ICON_PATH

from server.api._state import STATE


__all__ = [
    "create_native_dialog_root",
    "open_native_file_picker",
    "save_native_file_picker",
    "open_native_directory_picker",
    "validate_selected_file",
    "remember_pending_import_file",
    "take_pending_import_file",
    "dialog_path_override",
]


_dialog_local = threading.local()


@contextlib.contextmanager
def dialog_path_override(path: str):
    prev_active = getattr(_dialog_local, "active", False)
    prev_path = getattr(_dialog_local, "path", "")
    _dialog_local.active = True
    _dialog_local.path = str(path or "")
    try:
        yield
    finally:
        _dialog_local.active = prev_active
        _dialog_local.path = prev_path


def _active_dialog_override() -> str | None:
    if getattr(_dialog_local, "active", False):
        return str(getattr(_dialog_local, "path", "") or "")
    return None


_PENDING_IMPORT_TTL_SECONDS = 60 * 60


def _apply_native_dialog_icon(root: Any) -> None:
    import sys

    if ICO_PATH and os.path.isfile(ICO_PATH):
        try:
            root.iconbitmap(ICO_PATH)
        except Exception:
            pass
        try:
            root.iconbitmap(default=ICO_PATH)
        except Exception:
            pass

    if sys.platform.startswith("win"):
        try:
            hwnd = root.winfo_id()
            if hwnd:
                from launcher.win32_icon import apply_hwnd_icon
                apply_hwnd_icon(hwnd)
        except Exception:
            pass

    if not sys.platform.startswith("win") and PNG_ICON_PATH and os.path.isfile(PNG_ICON_PATH):
        try:
            from tkinter import PhotoImage

            icon_image = PhotoImage(file=PNG_ICON_PATH)
            root._histolauncher_icon_image = icon_image
            root.iconphoto(True, icon_image)
        except Exception:
            pass


def create_native_dialog_root() -> Any:
    from tkinter import Tk

    root = Tk()
    try:
        root.title("Histolauncher")
    except Exception:
        pass
    _apply_native_dialog_icon(root)
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    return root


def _resolve_start_dir(initialdir: str) -> str:
    return initialdir if initialdir and os.path.isdir(initialdir) else os.path.expanduser("~")


def _run_native_dialog(
    dialog_action: Callable[[Any], str],
    *,
    failure_message: str,
) -> str:
    root = None
    try:
        root = create_native_dialog_root()
        return str(dialog_action(root) or "").strip()
    except Exception as exc:
        safe_print(f"[api] {failure_message}: {exc}")
        raise
    finally:
        try:
            if root is not None:
                root.destroy()
        except Exception:
            pass


def open_native_file_picker(
    *,
    title: str,
    filetypes: list[tuple[str, str]],
    initialdir: str = "",
) -> str:
    override = _active_dialog_override()
    if override is not None:
        return override

    def _open(root: Any) -> str:
        from tkinter.filedialog import askopenfilename

        return askopenfilename(
            parent=root,
            initialdir=_resolve_start_dir(initialdir),
            title=title,
            filetypes=filetypes,
        )

    return _run_native_dialog(
        _open,
        failure_message="Failed to open file picker",
    )


def save_native_file_picker(
    *,
    title: str,
    filetypes: list[tuple[str, str]],
    initialfile: str = "",
    initialdir: str = "",
    defaultextension: str = "",
) -> str:
    override = _active_dialog_override()
    if override is not None:
        return override

    def _save(root: Any) -> str:
        from tkinter.filedialog import asksaveasfilename

        return asksaveasfilename(
            parent=root,
            initialfile=initialfile,
            defaultextension=defaultextension,
            filetypes=filetypes,
            initialdir=_resolve_start_dir(initialdir),
            title=title,
        )

    return _run_native_dialog(
        _save,
        failure_message="Failed to open save dialog",
    )


def open_native_directory_picker(
    *,
    title: str,
    initialdir: str = "",
    mustexist: bool = True,
) -> str:
    override = _active_dialog_override()
    if override is not None:
        return override

    def _select(root: Any) -> str:
        from tkinter.filedialog import askdirectory

        return askdirectory(
            parent=root,
            initialdir=_resolve_start_dir(initialdir),
            title=title,
            mustexist=mustexist,
        )

    return _run_native_dialog(
        _select,
        failure_message="Failed to open directory picker",
    )


def validate_selected_file(
    selected_path: str,
    *,
    allowed_extensions: set[str],
    max_size: int,
    label: str,
) -> dict[str, Any]:
    path = str(selected_path or "").strip()
    if not path:
        return {"ok": False, "cancelled": True, "error": "File selection cancelled"}

    if not os.path.isfile(path):
        return {"ok": False, "error": f"Selected {label} file does not exist."}

    extension = os.path.splitext(os.path.basename(path))[1].lower()
    if extension not in allowed_extensions:
        expected = ", ".join(sorted(allowed_extensions))
        return {"ok": False, "error": f"Selected {label} must use one of: {expected}"}

    try:
        size_bytes = os.path.getsize(path)
    except OSError as exc:
        return {"ok": False, "error": f"Failed to inspect selected {label}: {exc}"}

    if size_bytes <= 0:
        return {"ok": False, "error": f"Selected {label} file is empty."}
    if size_bytes > max_size:
        return {
            "ok": False,
            "error": f"Selected {label} exceeds max size ({max_size} bytes).",
        }

    return {
        "ok": True,
        "path": path,
        "file_name": os.path.basename(path),
        "size_bytes": size_bytes,
    }


def _purge_expired_pending_imports(now: float) -> None:
    expired = []
    for token, entry in STATE.pending_file_imports.items():
        created_at = float(entry.get("created_at") or 0.0)
        if now - created_at > _PENDING_IMPORT_TTL_SECONDS:
            expired.append(token)
    for token in expired:
        STATE.pending_file_imports.pop(token, None)


def remember_pending_import_file(kind: str, path: str) -> str:
    token = secrets.token_urlsafe(24)
    now = time.time()
    with STATE.file_import_lock:
        _purge_expired_pending_imports(now)
        STATE.pending_file_imports[token] = {
            "kind": str(kind or ""),
            "path": str(path or ""),
            "created_at": now,
        }
    return token


def take_pending_import_file(kind: str, token: str) -> str:
    clean_token = str(token or "").strip()
    if not clean_token:
        return ""
    now = time.time()
    with STATE.file_import_lock:
        _purge_expired_pending_imports(now)
        entry = STATE.pending_file_imports.pop(clean_token, None)
    if not isinstance(entry, dict):
        return ""
    if str(entry.get("kind") or "") != str(kind or ""):
        return ""
    path = str(entry.get("path") or "").strip()
    return path if path and os.path.isfile(path) else ""