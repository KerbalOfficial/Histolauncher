from __future__ import annotations

import contextlib
import logging
import os
import re
import sys
import threading
from datetime import datetime
from typing import Final


class Colors:
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"


TAG_COLORS: Final[dict[str, str]] = {
    "launcher": Colors.BRIGHT_BLUE,
    "startup": Colors.BRIGHT_CYAN,
    "discord_rpc": Colors.BRIGHT_MAGENTA,
    "api": Colors.BRIGHT_GREEN,
    "api_launch_status": Colors.GREEN,
    "api_open_crash_log": Colors.GREEN,
    "api_clear_logs": Colors.GREEN,
    "api_settings": Colors.GREEN,
    "http_server": Colors.BRIGHT_YELLOW,
    "yggdrasil": Colors.BRIGHT_MAGENTA,
    "version_manager": Colors.CYAN,
    "downloader": Colors.MAGENTA,
    "modloaders": Colors.BLUE,
    "addons": Colors.GREEN,
    "progress": Colors.BRIGHT_MAGENTA,
    "microsoft_auth": Colors.RED,
}


class SafeStreamHandler(logging.StreamHandler):
    def emit(self, record: logging.LogRecord) -> None:
        if _console_quiet.is_set():
            return
        try:
            super().emit(record)
        except UnicodeEncodeError:
            try:
                msg = self.format(record)
                safe_msg = msg.encode("utf-8", errors="replace").decode("utf-8")
                self.stream.write(safe_msg + self.terminator)
                self.flush()
            except Exception:
                self.handleError(record)


def safe_print(*args: object, **kwargs: object) -> None:
    sep = str(kwargs.get("sep", " ")) if kwargs.get("sep") is not None else " "
    plain = sep.join(str(a) for a in args)
    _append_safe_print_log(plain)

    if _console_quiet.is_set():
        return

    prev = getattr(_safe_print_local, "active", False)
    _safe_print_local.active = True
    try:
        try:
            if len(args) == 1:
                print(colorize_log(args[0]), **kwargs)  # type: ignore[arg-type]
            else:
                print(*args, **kwargs)  # type: ignore[arg-type]
        except UnicodeEncodeError:
            stream = kwargs.get("file") or getattr(sys, "stdout", None)
            if stream is None:
                return
            end = str(kwargs.get("end", "\n"))
            safe_message = plain.encode("utf-8", errors="replace").decode("utf-8")
            try:
                stream.write(safe_message + end)
                if kwargs.get("flush"):
                    stream.flush()
            except Exception:
                pass
    finally:
        _safe_print_local.active = prev


_safe_print_local = threading.local()
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_safe_print_log_path: str | None = None
_safe_print_log_resolved = False
_safe_print_log_lock = threading.Lock()
_console_quiet = threading.Event()


def set_console_quiet(quiet: bool) -> None:
    if quiet:
        _console_quiet.set()
    else:
        _console_quiet.clear()


def is_console_quiet() -> bool:
    return _console_quiet.is_set()


def is_in_safe_print() -> bool:
    return bool(getattr(_safe_print_local, "active", False))


@contextlib.contextmanager
def safe_print_context():
    prev = getattr(_safe_print_local, "active", False)
    _safe_print_local.active = True
    try:
        yield
    finally:
        _safe_print_local.active = prev


def _append_safe_print_log(message: str) -> None:
    global _safe_print_log_path, _safe_print_log_resolved
    if not _safe_print_log_resolved:
        with _safe_print_log_lock:
            if not _safe_print_log_resolved:
                _safe_print_log_path = _resolve_log_file()
                _safe_print_log_resolved = True
    path = _safe_print_log_path
    if not path:
        return
    try:
        plain = _ANSI_RE.sub("", message)
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {plain}\n"
        with _safe_print_log_lock:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8", errors="replace") as f:
                f.write(line)
    except Exception:
        pass


def _resolve_log_file() -> str | None:
    session_log_file = os.environ.get("HISTOLAUNCHER_LAUNCHER_LOG_FILE")
    if session_log_file:
        return session_log_file
    try:
        from core.settings import get_base_dir  # noqa: PLC0415

        return os.path.join(
            get_base_dir(),
            "logs",
            "launcher",
            f"histolauncher_{datetime.now().strftime('%Y-%m-%d')}.log",
        )
    except Exception:
        return None


def _ensure_file_handler(logger: logging.Logger, log_file: str | None) -> None:
    if not log_file:
        return
    desired_path = os.path.abspath(log_file)
    for handler in logger.handlers:
        if (
            getattr(handler, "_histolauncher_file_handler", False)
            and os.path.abspath(getattr(handler, "baseFilename", "")) == desired_path
        ):
            return

    for handler in list(logger.handlers):
        if getattr(handler, "_histolauncher_file_handler", False):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    try:
        logs_dir = os.path.dirname(desired_path)
        if logs_dir:
            os.makedirs(logs_dir, exist_ok=True)
        file_handler = logging.FileHandler(desired_path, encoding="utf-8")
        file_handler._histolauncher_file_handler = True
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(file_handler)
    except Exception:
        pass


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("histolauncher")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not any(getattr(handler, "_histolauncher_console_handler", False) for handler in logger.handlers):
        console_handler = SafeStreamHandler()
        console_handler._histolauncher_console_handler = True
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
        logger.addHandler(console_handler)

    _ensure_file_handler(logger, _resolve_log_file())

    return logger


_logger: logging.Logger | None = None


def get_logger() -> logging.Logger:
    global _logger
    _logger = _setup_logging()
    return _logger


def get_tag_color(tag: str) -> str:
    return TAG_COLORS.get(tag, Colors.WHITE)


def colorize_log(message: str) -> str:
    if message.startswith("[") and "]" in message:
        end_bracket = message.index("]")
        tag = message[1:end_bracket]
        color = get_tag_color(tag)
        return f"{color}[{tag}]{Colors.RESET} {message[end_bracket + 1:].lstrip()}"
    return message


def log_success(message: str) -> None:
    safe_print(f"{Colors.BRIGHT_GREEN}[OK] {message}{Colors.RESET}")


def log_error(message: str) -> None:
    safe_print(f"{Colors.BRIGHT_RED}[ERR] {message}{Colors.RESET}")


def log_warning(message: str) -> None:
    safe_print(f"{Colors.BRIGHT_YELLOW}[WARN] {message}{Colors.RESET}")


def log_info(message: str) -> None:
    safe_print(f"{Colors.BRIGHT_CYAN}[INFO] {message}{Colors.RESET}")


def dim_line(message: str) -> str:
    return f"{Colors.DIM}{message}{Colors.RESET}"


def is_unimportant_line(line: str) -> bool:
    line = line.strip()
    if not line:
        return True
    if all(c in "-=" for c in line) and len(line) > 3:
        return True
    if " - - [" in line and "/" in line:
        return True
    return False
