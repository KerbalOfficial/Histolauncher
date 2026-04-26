from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime

from core.logger import colorize_log


__all__ = ["TeeOutput", "setup_launcher_logging"]


_ANSI_ESCAPE = re.compile(r"\033\[[0-9;]*m|\u001b\[[0-9;]*m")


class TeeOutput:
    def __init__(self, file_obj, original_stream):
        self.file_obj = file_obj
        self.original_stream = original_stream

    @staticmethod
    def _strip_ansi_codes(text):
        return _ANSI_ESCAPE.sub("", text)

    def write(self, message):
        clean_message = self._strip_ansi_codes(message)
        try:
            self.file_obj.write(clean_message)
            self.file_obj.flush()
        except UnicodeEncodeError:
            self.file_obj.write(
                clean_message.encode("utf-8", errors="replace").decode("utf-8")
            )
            self.file_obj.flush()

        if self.original_stream is None:
            return
        try:
            self.original_stream.write(message)
        except UnicodeEncodeError:
            safe_message = message.encode("utf-8", errors="replace").decode("utf-8")
            self.original_stream.write(safe_message)
        try:
            self.original_stream.flush()
        except Exception:
            pass

    def flush(self):
        self.file_obj.flush()
        if self.original_stream is None:
            return
        try:
            self.original_stream.flush()
        except Exception:
            pass

    def isatty(self):
        if self.original_stream is None:
            return False
        try:
            return self.original_stream.isatty()
        except Exception:
            return False


def setup_launcher_logging():
    try:
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        base_dir = os.path.expanduser("~/.histolauncher")
        logs_dir = os.path.join(base_dir, "logs", "launcher")
        os.makedirs(logs_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_file = os.path.join(logs_dir, f"{timestamp}.log")

        log_handle = open(
            log_file, "w", buffering=1, encoding="utf-8", errors="replace"
        )

        timestamp_display = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_handle.write(f"{'=' * 60}\n")
        log_handle.write(f"Histolauncher started at {timestamp_display}\n")
        log_handle.write(f"{'=' * 60}\n\n")
        log_handle.flush()

        sys.stdout = TeeOutput(log_handle, original_stdout)
        sys.stderr = TeeOutput(log_handle, original_stderr)

        print(colorize_log(f"[launcher] Logging to: {log_file}"))
        return log_handle
    except Exception as e:
        print(colorize_log(f"[launcher] ERROR: Could not set up logging: {e}"))
        return None
