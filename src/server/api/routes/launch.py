from __future__ import annotations

import os
import re
import time
from typing import Any

from core.discord_rpc import set_game_presence, set_launcher_presence
from core.java import (
    class_file_major_to_java_major,
    detect_client_jar_java_major,
    suggest_java_feature_version,
)
from core.launch.paths import _resolve_version_dir
from core.logger import colorize_log
from core.settings import get_base_dir
from core.version_manager import get_clients_dir

from server.api._constants import MAX_LOADER_VERSION_LENGTH, MAX_USERNAME_LENGTH
from server.api._helpers import (
    _is_path_within,
    _is_non_crash_exit,
    _loader_display_name,
)
from server.api._validation import (
    _validate_category_string,
    _validate_loader_type,
    _validate_version_string,
)


__all__ = [
    "api_launch",
    "api_launch_status",
    "api_game_window_visible",
    "_analyze_crash_log",
    "api_crash_log",
    "api_open_crash_log",
    "api_clear_logs",
]


def api_launch(data):
    from core.launch import (
        _get_loader_version,
        _has_modloader_runtime,
        _legacy_forge_requires_modloader,
        check_mod_loader_compatibility,
        consume_last_launch_diagnostic,
        consume_last_launch_error,
        launch_version,
    )

    category = data.get("category")
    folder = data.get("folder")
    username = data.get("username")
    loader = data.get("loader")
    loader_version = data.get("loader_version")

    if not category or not folder:
        return {"ok": False, "message": "Missing category or folder"}

    if not _validate_category_string(category):
        return {"ok": False, "message": "Invalid category format"}

    if not _validate_version_string(folder):
        return {"ok": False, "message": "Invalid folder format"}

    if username and len(str(username)) > MAX_USERNAME_LENGTH:
        return {"ok": False, "message": "Username is too long"}

    if loader and not _validate_loader_type(loader):
        return {"ok": False, "message": "Invalid loader type"}

    if loader_version and not _validate_version_string(loader_version, MAX_LOADER_VERSION_LENGTH):
        return {"ok": False, "message": "Invalid loader version format"}

    clients_dir = get_clients_dir()
    version_identifier = f"{category}/{folder}"
    version_dir = _resolve_version_dir(version_identifier) or os.path.join(
        clients_dir, category, folder
    )
    jar_path = os.path.join(version_dir, "client.jar")

    if not os.path.exists(jar_path):
        return {
            "ok": False,
            "message": "Client not installed. Please download it from Versions first.",
        }

    if loader:
        current_loader = _get_loader_version(version_dir, loader)

        if not current_loader:
            return {
                "ok": False,
                "message": (
                    f"{_loader_display_name(loader)} is not installed for {folder}. "
                    "Install the loader first from Versions -> Modloaders."
                ),
            }

        if loader.lower() == "forge":
            if (
                _legacy_forge_requires_modloader(version_dir, current_loader)
                and not _has_modloader_runtime(version_dir)
            ):
                return {
                    "ok": False,
                    "message": (
                        f"Forge {current_loader} for Minecraft {folder} is a ModLoader-era build. "
                        "It requires ModLoader runtime classes (BaseMod/ModLoader), which are not present in this client. "
                        "Place a matching modloader jar in this version folder (for example: modloader-<mc>.jar), then relaunch Forge."
                    ),
                }

        issues = check_mod_loader_compatibility(version_dir, loader)
        if issues:
            lines = []
            for mod_id, jar_name, req in issues:
                lines.append(
                    f"{mod_id} ({jar_name}) requires loader {req} (current {current_loader})"
                )
            return {"ok": False, "message": "Mod compatibility issue:\n" + "\n".join(lines)}

    process_id = launch_version(
        version_identifier,
        username_override=username,
        loader=loader,
        loader_version=loader_version,
    )

    if process_id:
        set_game_presence(
            version_identifier,
            start_time=time.time(),
            phase="Launching",
            loader_type=loader,
            loader_version=loader_version,
        )
        return {
            "ok": True,
            "process_id": process_id,
            "message": f"Launching {folder} as {username}",
        }

    set_launcher_presence()
    launch_error = consume_last_launch_error(version_identifier)
    launch_diagnostic = consume_last_launch_diagnostic(version_identifier)
    message = launch_error or f"Failed to launch {folder}"
    response = {"ok": False, "message": message}
    if isinstance(launch_diagnostic, dict) and launch_diagnostic:
        response.update(launch_diagnostic)
    if "java" in message.lower():
        target_java_major = detect_client_jar_java_major(version_dir)
        if target_java_major > 0:
            response.update(
                {
                    "java_required_major": target_java_major,
                    "java_download_major": suggest_java_feature_version(target_java_major),
                }
            )
    return response


def api_launch_status(process_id):
    from core.launch import _get_process_status

    if not process_id:
        set_launcher_presence()
        return {"ok": False, "error": "Invalid process ID"}

    status_info = _get_process_status(process_id)

    if status_info is None:
        set_launcher_presence()
        return {"ok": False, "error": "Process not found", "status": "unknown"}

    if status_info["status"] == "running":
        return {
            "ok": True,
            "status": "running",
            "elapsed": status_info.get("elapsed", 0),
        }

    exit_code = status_info.get("exit_code", -1)
    version_id = status_info.get("version", "")
    category = (
        version_id.split("/", 1)[0].lower() if "/" in version_id else version_id.lower()
    )

    is_crash = not _is_non_crash_exit(version_id, exit_code)
    log_path = status_info.get("log_path")

    print(colorize_log(
        f"[api_launch_status] exit_code={exit_code}, category={category}, "
        f"is_crash={is_crash}, log_path={log_path}"
    ))
    set_launcher_presence()

    return {
        "ok": not is_crash,
        "status": "crashed" if is_crash else "exited",
        "exit_code": exit_code,
        "log_path": log_path,
    }


def api_game_window_visible(process_id):
    from core.launch import _get_game_window_visible

    if not process_id:
        set_launcher_presence()
        return {"ok": False, "error": "Invalid process ID"}

    result = _get_game_window_visible(process_id)

    if result.get("ok"):
        set_game_presence(
            result.get("version"),
            start_time=result.get("start_time"),
            phase="Playing" if result.get("visible") else "Launching",
        )
    else:
        set_launcher_presence()

    return result


def _resolve_allowed_crash_log_path(log_path: str) -> tuple[bool, str, str]:
    raw_path = str(log_path or "").strip()
    if not raw_path or "\x00" in raw_path:
        return False, "Invalid log path", ""

    resolved_path = os.path.realpath(os.path.abspath(raw_path))
    if os.path.splitext(resolved_path)[1].lower() not in {".log", ".txt"}:
        return False, "Unsupported log file type", ""

    base_logs_dir = os.path.join(get_base_dir(), "logs")
    if _is_path_within(base_logs_dir, resolved_path):
        return True, "", resolved_path

    clients_dir = get_clients_dir()
    if _is_path_within(clients_dir, resolved_path):
        try:
            rel_path = os.path.relpath(resolved_path, clients_dir).replace("\\", "/")
        except ValueError:
            rel_path = ""
        parts = {part.lower() for part in rel_path.split("/") if part}
        if "logs" in parts or "crash-reports" in parts:
            return True, "", resolved_path

    return False, "Log path is outside launcher log directories", ""


def _analyze_crash_log(log_content: str) -> dict:
    match = re.search(
        r"UnsupportedClassVersionError:.*?class file version (\d+\.0)"
        r".*?version of the Java Runtime only recognizes class file versions up to (\d+\.0)",
        log_content,
        re.DOTALL,
    )
    if match:
        required_version_str = match.group(1).split(".")[0]
        current_version_str = match.group(2).split(".")[0]

        try:
            required_major = int(required_version_str)
            current_major = int(current_version_str)
            required_java_major = class_file_major_to_java_major(required_major)
            current_java_major = class_file_major_to_java_major(current_major)
            download_java_major = suggest_java_feature_version(required_java_major)

            required_java = (
                f"Java {required_java_major}"
                if required_java_major > 0
                else f"Java with class version {required_major}"
            )
            current_java = (
                f"Java {current_java_major}"
                if current_java_major > 0
                else f"Java with class version {current_major}"
            )
            if download_java_major != required_java_major and download_java_major > 0:
                suggestion = (
                    f"Please install Java {download_java_major} or newer and try launching again."
                )
            else:
                suggestion = f"Please install {required_java} and try launching again."

            return {
                "has_error": True,
                "error_type": "JavaVersionMismatch",
                "message": "Java version mismatch detected!",
                "details": (
                    f"You are using an older version of Java! ({current_java}). "
                    f"This version requires {required_java}."
                ),
                "suggestion": suggestion,
                "required_class_version": required_major,
                "current_max_class_version": current_major,
                "required_java_major": required_java_major,
                "current_java_major": current_java_major,
                "download_java_major": download_java_major,
            }
        except (ValueError, IndexError):
            pass

    if "OutOfMemoryError" in log_content:
        return {
            "has_error": True,
            "error_type": "OutOfMemory",
            "message": "Out of Memory Error",
            "details": "The game ran out of allocated RAM.",
            "suggestion": "Try increasing the maximum RAM allocation in the launcher settings.",
        }

    if "Could not reserve enough space for object heap" in log_content:
        return {
            "has_error": True,
            "error_type": "HeapAllocationFailure",
            "message": "Heap Allocation Failure",
            "details": "The Java Virtual Machine could not reserve enough memory for the heap.",
            "suggestion": (
                "Try reducing the maximum RAM allocation in the launcher settings or "
                "closing other applications to free up memory."
            ),
        }

    if (
        "ModNotFoundException" in log_content
        or "net.minecraftforge.fml.ModLoadingException" in log_content
    ):
        return {
            "has_error": True,
            "error_type": "ModError",
            "message": "Mod Loading Error",
            "details": "A required mod could not be found or loaded.",
            "suggestion": "Check that all required mods are installed correctly.",
        }

    if re.search(r"(missing texture|Unable to load resource)", log_content, re.IGNORECASE):
        return {
            "has_error": True,
            "error_type": "ResourceError",
            "message": "Missing Resource",
            "details": "The game encountered missing textures or resources.",
            "suggestion": "Try verifying game files or reinstalling the version.",
        }

    return {
        "has_error": False,
        "error_type": None,
        "message": None,
        "details": None,
        "suggestion": None,
    }


def api_crash_log(data: Any):
    if not isinstance(data, dict):
        return {"ok": False, "error": "Invalid request", "content": ""}

    log_path = (data.get("log_path") or "").strip()
    if not log_path:
        return {"ok": False, "error": "Missing log_path", "content": ""}

    try:
        allowed, error, resolved_path = _resolve_allowed_crash_log_path(log_path)
        if not allowed:
            return {"ok": False, "error": error, "content": ""}

        log_path = resolved_path
        if not os.path.isfile(log_path):
            return {
                "ok": False,
                "error": f"Log file not found: {log_path}",
                "content": "",
            }

        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        error_analysis = _analyze_crash_log(content)

        if len(content) > 102400:
            content = "... (content truncated) ...\n" + content[-102400:]

        return {
            "ok": True,
            "filename": os.path.basename(log_path),
            "filepath": log_path,
            "content": content,
            "error_analysis": error_analysis,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"Could not read log file: {str(e)}",
            "content": "",
        }


def api_open_crash_log(data: Any):
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid request"}

    log_path = (data.get("log_path") or "").strip()
    if not log_path:
        return {"ok": False, "error": "missing log_path"}

    allowed, error, resolved_path = _resolve_allowed_crash_log_path(log_path)
    if not allowed:
        return {"ok": False, "error": error}

    log_path = resolved_path
    if not os.path.exists(log_path):
        return {"ok": False, "error": f"Log file not found: {log_path}"}

    try:
        import platform
        import subprocess

        print(colorize_log(f"[api_open_crash_log] Opening file: {log_path}"))
        print(colorize_log(f"[api_open_crash_log] File exists: {os.path.isfile(log_path)}"))
        if os.path.isfile(log_path):
            file_size = os.path.getsize(log_path)
            print(colorize_log(f"[api_open_crash_log] File size: {file_size} bytes"))

        system = platform.system()

        if system == "Windows":
            os.startfile(log_path)
        elif system == "Darwin":
            subprocess.run(["open", log_path])
        else:
            subprocess.run(["xdg-open", log_path])

        return {"ok": True, "message": f"Opening {os.path.basename(log_path)}..."}
    except Exception as e:
        print(colorize_log(f"[api] Error opening crash log: {e}"))
        return {"ok": False, "error": f"Failed to open log file: {str(e)}"}


def api_clear_logs():
    try:
        base_dir = get_base_dir()
        logs_dir = os.path.join(base_dir, "logs")

        if not os.path.exists(logs_dir):
            return {"ok": True, "message": "No logs directory found"}

        skipped_files = []
        deleted_count = 0

        for root, dirs, files in os.walk(logs_dir, topdown=False):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except (OSError, PermissionError):
                    skipped_files.append(os.path.basename(file_path))
                    print(colorize_log(f"[api_clear_logs] Skipped (in use): {file_path}"))

            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                try:
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                except (OSError, PermissionError):
                    pass

        try:
            if os.path.exists(logs_dir) and not os.listdir(logs_dir):
                os.rmdir(logs_dir)
        except (OSError, PermissionError):
            pass

        print(colorize_log(
            f"[api_clear_logs] Cleared logs: {deleted_count} files deleted, "
            f"{len(skipped_files)} files skipped"
        ))

        message = f"Deleted {deleted_count} log files."
        if skipped_files:
            message += (
                f" {len(skipped_files)} active log file(s) are still in use and "
                "will be cleared next time."
            )

        return {
            "ok": True,
            "message": message,
            "deleted": deleted_count,
            "skipped": len(skipped_files),
        }
    except Exception as e:
        print(colorize_log(f"[api_clear_logs] Error clearing logs: {e}"))
        return {"ok": False, "error": f"Failed to clear logs: {str(e)}"}
