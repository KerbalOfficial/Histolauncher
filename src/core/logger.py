from __future__ import annotations

import logging
import os
import sys
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
    "mods": Colors.GREEN,
    "progress": Colors.BRIGHT_MAGENTA,
}


class SafeStreamHandler(logging.StreamHandler):
    def emit(self, record: logging.LogRecord) -> None:
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


def _safe_print(message: object) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        stream = getattr(sys, "stdout", None)
        if stream is None:
            return
        safe_message = str(message).encode("utf-8", errors="replace").decode("utf-8")
        stream.write(safe_message + "\n")
        stream.flush()


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("histolauncher")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    console_handler = SafeStreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
    logger.addHandler(console_handler)

    try:
        from core.settings import get_base_dir  # noqa: PLC0415

        logs_dir = os.path.join(get_base_dir(), "logs")
        os.makedirs(logs_dir, exist_ok=True)

        log_file = os.path.join(
            logs_dir, f"histolauncher_{datetime.now().strftime('%Y-%m-%d')}.log"
        )
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
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

    return logger


_logger: logging.Logger | None = None


def get_logger() -> logging.Logger:
    global _logger
    if _logger is None:
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
    _safe_print(f"{Colors.BRIGHT_GREEN}[OK] {message}{Colors.RESET}")


def log_error(message: str) -> None:
    _safe_print(f"{Colors.BRIGHT_RED}[ERR] {message}{Colors.RESET}")


def log_warning(message: str) -> None:
    _safe_print(f"{Colors.BRIGHT_YELLOW}[WARN] {message}{Colors.RESET}")


def log_info(message: str) -> None:
    _safe_print(f"{Colors.BRIGHT_CYAN}[INFO] {message}{Colors.RESET}")


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
