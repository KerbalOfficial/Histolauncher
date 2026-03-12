# core/logger.py

import logging
import os

from datetime import datetime

class Colors:
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'


TAG_COLORS = {
    'launcher': Colors.BRIGHT_BLUE,
    'startup': Colors.BRIGHT_CYAN,
    'discord_rpc': Colors.BRIGHT_MAGENTA,
    'api': Colors.BRIGHT_GREEN,
    'api_launch_status': Colors.GREEN,
    'api_open_crash_log': Colors.GREEN,
    'api_clear_logs': Colors.GREEN,
    'api_settings': Colors.GREEN,
    'http_server': Colors.BRIGHT_YELLOW,
    'yggdrasil': Colors.BRIGHT_MAGENTA,
    'version_manager': Colors.CYAN,
    'downloader': Colors.MAGENTA,
    'modloaders': Colors.BLUE,
    'progress': Colors.BRIGHT_MAGENTA,
}


def _setup_logging():
    logger = logging.getLogger('histolauncher')
    
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.DEBUG)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '[%(name)s] %(levelname)s: %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    try:
        from core.settings import get_base_dir
        logs_dir = os.path.join(get_base_dir(), 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        
        log_file = os.path.join(logs_dir, f'histolauncher_{datetime.now().strftime("%Y-%m-%d")}.log')
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except Exception: pass
    
    return logger


_logger = None
def get_logger():
    global _logger
    if _logger is None:
        _logger = _setup_logging()
    return _logger


def get_tag_color(tag):
    return TAG_COLORS.get(tag, Colors.WHITE)


def colorize_log(message):
    if message.startswith('[') and ']' in message:
        end_bracket = message.index(']')
        tag = message[1:end_bracket]
        color = get_tag_color(tag)
        
        colored_message = f"{color}[{tag}]{Colors.RESET} {message[end_bracket+1:].lstrip()}"
        return colored_message
    
    return message


def log_success(message):
    print(f"{Colors.BRIGHT_GREEN}✓ {message}{Colors.RESET}")


def log_error(message):
    print(f"{Colors.BRIGHT_RED}✗ {message}{Colors.RESET}")


def log_warning(message):
    print(f"{Colors.BRIGHT_YELLOW}⚠ {message}{Colors.RESET}")


def log_info(message):
    print(f"{Colors.BRIGHT_CYAN}ℹ {message}{Colors.RESET}")


def dim_line(message):
    return f"{Colors.DIM}{message}{Colors.RESET}"


def is_unimportant_line(line):
    line = line.strip()
    
    if all(c in '-=' for c in line) and len(line) > 3:
        return True
    
    if ' - - [' in line and '/' in line:
        return True
    
    if not line:
        return True
    
    return False