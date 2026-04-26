from __future__ import annotations

import queue
import tkinter

from core.logger import colorize_log


__all__ = ["create_tk_ui_dispatcher"]


def create_tk_ui_dispatcher(root, interval_ms: int = 25):
    callbacks: queue.Queue = queue.Queue()
    state = {"closed": False, "job": None}

    def flush_callbacks():
        state["job"] = None

        while True:
            try:
                callback = callbacks.get_nowait()
            except queue.Empty:
                break

            try:
                callback()
            except Exception as e:
                print(colorize_log(f"[launcher] UI callback failed: {e}"))

        if state["closed"]:
            return

        try:
            state["job"] = root.after(interval_ms, flush_callbacks)
        except tkinter.TclError:
            state["closed"] = True

    def dispatch(callback):
        if state["closed"]:
            return
        callbacks.put(callback)

    def start():
        if state["closed"] or state["job"] is not None:
            return
        try:
            state["job"] = root.after(interval_ms, flush_callbacks)
        except tkinter.TclError:
            state["closed"] = True

    def stop():
        state["closed"] = True
        if state["job"] is not None:
            try:
                root.after_cancel(state["job"])
            except Exception:
                pass
            state["job"] = None

    return dispatch, start, stop
