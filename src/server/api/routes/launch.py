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
from core.logger import safe_print
from core.settings import get_base_dir
from core.version_manager import get_clients_dir

from server.api._constants import MAX_LOADER_VERSION_LENGTH, MAX_USERNAME_LENGTH
from server.api._helpers import (
    _is_path_within,
    _is_legacy_family_category,
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
    "api_crash_autofix",
    "api_open_crash_log",
    "api_clear_logs",
]


_LEGACY_NORMAL_EXIT_MIN_SECONDS = 20.0
_LEGACY_CRASH_LOG_MARKERS = (
    "exception in thread",
    "java.lang.",
    "traceback",
    "fatal error",
    "hs_err_pid",
    "minecraft has crashed",
    "unexpected error",
    "at net.minecraft.",
)


def _log_has_crash_markers(log_path: str) -> bool:
    path = str(log_path or "").strip()
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 64 * 1024), os.SEEK_SET)
            tail = f.read().decode("utf-8", "replace").lower()
    except Exception:
        return False
    return any(marker in tail for marker in _LEGACY_CRASH_LOG_MARKERS)


def _is_legacy_non_crash_exit_by_context(version_id: str, exit_code: int, elapsed: Any, log_path: str) -> bool:
    category = version_id.split("/", 1)[0].lower() if "/" in version_id else version_id.lower()
    if not _is_legacy_family_category(category):
        return False
    if _is_non_crash_exit(version_id, exit_code):
        return True
    try:
        elapsed_seconds = float(elapsed or 0)
    except Exception:
        elapsed_seconds = 0.0
    return elapsed_seconds >= _LEGACY_NORMAL_EXIT_MIN_SECONDS and not _log_has_crash_markers(log_path)


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
    server_address_raw = str(data.get("server_address") or "").strip()
    server_port_raw = data.get("server_port")
    server_mppass_raw = str(data.get("server_mppass") or "").strip()

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

    server_address = None
    server_port = 25565
    server_mppass = None
    if server_address_raw:
        _SERVER_RE = re.compile(
            r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*'
            r'[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?'
            r'$|^(?:\d{1,3}\.){3}\d{1,3}$'
        )
        if len(server_address_raw) > 253:
            return {"ok": False, "message": "Server address is too long"}
        if not _SERVER_RE.match(server_address_raw):
            return {"ok": False, "message": "Invalid server address format"}
        server_address = server_address_raw
        try:
            port_val = int(server_port_raw or 25565)
            if not (1 <= port_val <= 65535):
                raise ValueError
            server_port = port_val
        except (TypeError, ValueError):
            return {"ok": False, "message": "Invalid server port"}
        if server_mppass_raw:
            if len(server_mppass_raw) > 256 or not re.match(r"^[A-Za-z0-9._~\-]+$", server_mppass_raw):
                return {"ok": False, "message": "Invalid Classic mppass format"}
            server_mppass = server_mppass_raw

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
        server_address=server_address,
        server_port=server_port,
        server_mppass=server_mppass,
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

    log_path = status_info.get("log_path")
    is_crash = not _is_non_crash_exit(version_id, exit_code)
    if is_crash and _is_legacy_non_crash_exit_by_context(
        version_id,
        exit_code,
        status_info.get("elapsed", 0),
        log_path,
    ):
        is_crash = False

    safe_print(
        f"[api_launch_status] exit_code={exit_code}, category={category}, "
        f"is_crash={is_crash}, log_path={log_path}"
    )
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
    def _err(error_type, message, details=None, suggestion=None, auto_fix=None, auto_fix_options=None, **extra):
        result = {
            "has_error": True,
            "error_type": error_type,
            "message": message,
            "details": details,
            "suggestion": suggestion,
            **extra,
        }
        if auto_fix:
            result["auto_fix"] = auto_fix
        if auto_fix_options:
            result["auto_fix_options"] = auto_fix_options
        return result

    _ucve_match = re.search(
        r"UnsupportedClassVersionError:.*?class file version (\d+\.0)"
        r".*?version of the Java Runtime only recognizes class file versions up to (\d+\.0)",
        log_content,
        re.DOTALL,
    )
    if _ucve_match:
        required_version_str = _ucve_match.group(1).split(".")[0]
        current_version_str = _ucve_match.group(2).split(".")[0]
        try:
            required_major = int(required_version_str)
            current_major = int(current_version_str)
            required_java_major = class_file_major_to_java_major(required_major)
            current_java_major = class_file_major_to_java_major(current_major)
            download_java_major = suggest_java_feature_version(required_java_major)
            required_java = (
                f"Java {required_java_major}"
                if required_java_major > 0
                else f"class version {required_major}"
            )
            current_java = (
                f"Java {current_java_major}"
                if current_java_major > 0
                else f"class version {current_major}"
            )
            if download_java_major != required_java_major and download_java_major > 0:
                _ucve_suggestion = (
                    f"Download and install Java {download_java_major} or newer, then try launching again."
                )
            else:
                _ucve_suggestion = f"Download and install {required_java}, then try launching again."
            return {
                "has_error": True,
                "error_type": "JavaVersionMismatch",
                "message": "Java needs to be updated",
                "details": (
                    f"The game requires {required_java}, but you only have {current_java} installed. "
                    "Java is the program that runs Minecraft."
                ),
                "suggestion": _ucve_suggestion,
                "required_class_version": required_major,
                "current_max_class_version": current_major,
                "required_java_major": required_java_major,
                "current_java_major": current_java_major,
                "download_java_major": download_java_major,
            }
        except (ValueError, IndexError):
            pass

    if (
        "paging file is too small" in log_content.lower()
        or re.search(
            r"os::commit_memory\(.*\) failed",
            log_content,
        )
        or re.search(
            r"[Nn]ative memory allocation \((?:mmap|malloc|VirtualAlloc)\) failed",
            log_content,
        )
        or (
            "There is insufficient memory for the Java Runtime Environment to continue" in log_content
            and "hs_err_pid" in log_content
        )
    ):
        return _err(
            "OutOfNativeMemory",
            "Not enough memory",
            details=(
                "The game failed to reserve the system memory it needed. "
                "This is often caused by a very large thread stack size (-Xss) or maximum memory (-Xmx) "
                "setting that exceeds what your system can actually provide."
            ),
            suggestion=(
                "Use the Auto-fix button to enable Auto-Optimize, which will automatically choose "
                "memory settings that work on your device."
            ),
            auto_fix={"action": "enable_auto_optimize", "label": "Enable Auto-Optimize"},
        )

    if (
        "A fatal error has been detected by the Java Runtime Environment" in log_content
        or re.search(r"hs_err_pid\d+\.log", log_content)
    ):
        return _err(
            "JvmFatalCrash",
            "The game crashed unexpectedly",
            details=(
                "The game crashed in a way that's usually related to graphics drivers or hardware. "
                "This is not caused by your settings."
            ),
            suggestion=(
                "Try updating your graphics drivers. "
                "If the problem keeps happening, try using a different Java version in the launcher settings."
            ),
        )

    if "initial heap size set to a larger value than the maximum heap size" in log_content.lower():
        return _err(
            "InvalidJvmArgument",
            "Memory settings are conflicting",
            details=(
                "The minimum memory setting is higher than the maximum memory setting. "
                "Min RAM was left higher, or when an Extra Launch Option like -Xms is set "
                "above the Max RAM."
            ),
            suggestion=(
                "Use the Auto-fix button to enable Auto-Optimize, which will "
                "automatically choose compatible memory settings."
            ),
            auto_fix={"action": "enable_auto_optimize", "label": "Enable Auto-Optimize"},
        )

    _jvm_bad_arg = re.search(
        r"(?:Unrecognized VM option|Unrecognized option:|Invalid maximum heap size"
        r"|Too small initial heap|invalid initial heap size)[:\s]*'?([^\n\r'\"]{0,80})",
        log_content,
        re.IGNORECASE,
    )
    if _jvm_bad_arg or (
        "Could not create the Java Virtual Machine" in log_content
        and "Could not reserve enough space" not in log_content
        and "OutOfMemoryError" not in log_content
    ):
        bad_arg = (_jvm_bad_arg.group(1).strip() if _jvm_bad_arg else "").rstrip(".,")
        details = (
            f"The game couldn't start because of an unrecognized launch option: \"{bad_arg}\"."
            if bad_arg
            else "The game couldn't start because one of the launch options in Settings is not recognized."
        )
        return _err(
            "InvalidJvmArgument",
            "A launch setting is not valid",
            details=details,
            suggestion=(
                "You can enable Auto-Optimize to let the launcher manage launch settings automatically, "
                "or remove just the bad argument if you want to keep your other settings."
            ),
            auto_fix_options=[
                {"action": "enable_auto_optimize", "label": "Enable Auto-Optimize"},
                {"action": "clear_jvm_args", "label": "Remove Bad Argument", "bad_arg": bad_arg},
            ],
        )

    if "GL_OUT_OF_MEMORY" in log_content or re.search(
        r"out of (?:video|graphics) memory", log_content, re.IGNORECASE
    ):
        return _err(
            "OutOfVideoMemory",
            "Your graphics card ran out of memory",
            details=(
                "The game used up all the memory on your graphics card. "
                "This is separate from regular RAM."
            ),
            suggestion=(
                "Try lowering the render distance or turning off shaders in the game's video settings. "
                "Closing other programs that use graphics may also help."
            ),
        )

    if "OutOfMemoryError" in log_content:
        if re.search(
            r"OutOfMemoryError: (?:Direct buffer memory|unable to create.*?thread)",
            log_content,
            re.IGNORECASE,
        ):
            return _err(
                "OutOfNativeMemory",
                "The game ran out of memory",
                details=(
                    "The game ran out of background system memory. "
                    "This can happen when the memory setting is set too high, "
                    "leaving less room for other parts of the game."
                ),
                suggestion=(
                    "Try reducing the maximum memory in Settings. "
                    "Using the Auto-fix button will enable Auto-Optimize to handle this automatically."
                ),
                auto_fix={"action": "enable_auto_optimize", "label": "Enable Auto-Optimize"},
            )
        return _err(
            "OutOfMemory",
            "The game ran out of memory",
            details=(
                "The game used up all the memory it was given. "
                "Try giving it more memory in the launcher settings."
            ),
            suggestion=(
                "Open Settings and increase the Maximum Memory. "
                "Closing other programs before launching can also help."
            ),
        )

    if "Could not reserve enough space for object heap" in log_content:
        return _err(
            "HeapAllocationFailure",
            "Not enough memory",
            details=(
                "The game couldn't reserve the amount of memory it was given. "
                "Your computer may not have enough free memory right now, "
                "or the amount set is too high for your system."
            ),
            suggestion=(
                "Use the Auto-fix button to enable Auto-Optimize, which will "
                "automatically choose the right memory amount for your device."
            ),
            auto_fix={"action": "enable_auto_optimize", "label": "Enable Auto-Optimize"},
        )

    if "StackOverflowError" in log_content:
        return _err(
            "StackOverflow",
            "A mod crashed the game in a loop",
            details=(
                "One of your mods got stuck in an infinite loop and crashed the game. "
                "This can also happen with a corrupted world."
            ),
            suggestion=(
                "If you recently added a mod, try removing it and launching again. "
                "Otherwise, open the crash log to identify which mod caused this."
            ),
        )

    if re.search(
        r"ZipException.*?(?:invalid LOC header|bad signature|invalid entry|zip END header)"
        r"|ClassFormatError",
        log_content,
        re.IGNORECASE,
    ):
        return _err(
            "CorruptedFile",
            "A game file is broken",
            details=(
                "One of the game's files is damaged or was not downloaded correctly. "
                "This is not your fault and can happen with any download."
            ),
            suggestion=(
                "Try re-downloading or reinstalling this Minecraft version. "
                "If a mod file is causing this, try re-downloading that mod."
            ),
        )

    if re.search(
        r"ModResolutionException|Incompatible mods found",
        log_content,
        re.IGNORECASE,
    ):
        _dep_detail_match = re.search(
            r"(?:requires|needs)(?: version| mod)? (.{0,120}?)(?:\n|$)",
            log_content,
            re.IGNORECASE,
        )
        details = "Two or more of your mods don't work together or are the wrong version."
        if _dep_detail_match:
            details += f" The game said: {_dep_detail_match.group(0).strip()}"
        return _err(
            "ModDependencyConflict",
            "Mods are incompatible with each other",
            details=details,
            suggestion=(
                "Open the crash log to see which mods are conflicting. "
                "Try removing recently added mods one by one until the game starts."
            ),
        )

    _dup_mod_match = re.search(
        r"[Dd]uplicate mod(?: id)?[:\s]+['\"]?([A-Za-z0-9_\-]+)",
        log_content,
    )
    if _dup_mod_match:
        mod_id = _dup_mod_match.group(1).strip(".,!\"' ")
        return _err(
            "DuplicateModId",
            "You have two copies of the same mod",
            details=f"The mod '{mod_id}' appears to be installed twice in your mods folder.",
            suggestion=f"Open your mods folder and remove one copy of '{mod_id}', then relaunch.",
        )

    _mixin_match = re.search(r"MixinApplyError[:\s]+Mixin \[([^\]]+)\]", log_content)
    if _mixin_match or "MixinApplyError" in log_content:
        mod_name = _mixin_match.group(1).split(".")[0] if _mixin_match else ""
        details = (
            f"The mod '{mod_name}' tried to modify the game in a way that didn't work."
            if mod_name
            else "A mod tried to modify the game in a way that didn't work."
        )
        return _err(
            "MixinError",
            "A mod is not compatible with this version",
            details=(
                details
                + " This usually means the mod was not made for this version of Minecraft."
            ),
            suggestion=(
                "Try removing recently added mods one by one to find the problem, "
                "or check if there's an updated version of the mod for this Minecraft version."
            ),
        )

    if re.search(
        r"net\.(?:minecraftforge|neoforged)\.fml\.(?:ModLoadingException|loading\.ModLoadingWorker)"
        r"|ModLoadingException",
        log_content,
    ):
        _fml_mod_match = re.search(
            r"Mod (?:ID: |id: |')?([A-Za-z0-9_\-]+)'?\s+.*?(?:requires|failed|error)",
            log_content,
            re.IGNORECASE,
        )
        details = "Forge couldn't load one or more of your mods."
        if _fml_mod_match:
            details += f" The problem seems to be with the mod '{_fml_mod_match.group(1)}'."
        return _err(
            "ForgeModLoadingError",
            "Forge couldn't load one of your mods",
            details=details,
            suggestion=(
                "Make sure all your mods are made for this exact Minecraft and Forge version. "
                "Open the crash log to see the full list of errors."
            ),
        )

    if re.search(
        r"Missing or unsupported mandatory (?:dependencies|mods)"
        r"|requires mod[:\s]"
        r"|Could not find required mod",
        log_content,
        re.IGNORECASE,
    ):
        return _err(
            "MissingDependency",
            "A required mod is missing",
            details=(
                "One or more mods need another mod to be installed in order to work, "
                "but that mod is not in your mods folder."
            ),
            suggestion=(
                "Open the crash log to see which mods are missing, then install them. "
                "Make sure all required mods are in your mods folder before launching."
            ),
        )

    if re.search(
        r"GLFW error|Failed to initialize GLFW|Couldn.t initialize GLFW"
        r"|GLFW library is not initialized",
        log_content,
        re.IGNORECASE,
    ):
        _glfw_desc = re.search(
            r"Description:\s*([^\n\r]{1,120})", log_content, re.IGNORECASE
        )
        details = "The game couldn't open a window on your screen."
        if _glfw_desc:
            details += f" The error message was: \"{_glfw_desc.group(1).strip()}\""
        return _err(
            "GlfwError",
            "Couldn't open the game window",
            details=details,
            suggestion=(
                "Try updating your graphics drivers. "
                "On Linux, make sure your desktop environment is running before launching."
            ),
        )

    if re.search(
        r"does not support OpenGL|minimum required opengl version"
        r"|OpenGL.{0,30}not supported|Pixel format not accelerated"
        r"|Your graphics card does not support",
        log_content,
        re.IGNORECASE,
    ):
        return _err(
            "OpenGlTooOld",
            "Your graphics card may not support this version",
            details=(
                "This version of Minecraft requires graphics features that your graphics card "
                "or its driver doesn't support."
            ),
            suggestion=(
                "Try updating your graphics drivers to the latest version available. "
                "If your hardware is very old, you may need to use an older version of Minecraft."
            ),
        )

    _nsme_match = re.search(
        r"java\.lang\.(NoSuchMethodError|NoSuchFieldError):\s*['\"]?([^\n\r'\"]{1,120})",
        log_content,
    )
    if _nsme_match:
        return _err(
            "ClassMemberNotFound",
            "A mod is incompatible with this Minecraft version",
            details=(
                "One of your mods was made for a different version of Minecraft or a different "
                "mod loader version, and it's not working correctly with the one you're using."
            ),
            suggestion=(
                "Check that all your mods are made for this exact Minecraft version. "
                "Try removing recently added mods to find which one is causing this."
            ),
        )

    _cnfe_match = re.search(
        r"java\.lang\.(?:ClassNotFoundException|NoClassDefFoundError):\s*([^\n\r]{1,120})",
        log_content,
    )
    if _cnfe_match:
        return _err(
            "ClassNotFound",
            "A mod or game file could not be found",
            details=(
                "The game tried to load something that wasn't there. "
                "This is usually caused by a missing mod, an incompatible mod, or a damaged installation."
            ),
            suggestion=(
                "Try removing recently added mods, or try re-downloading this Minecraft version."
            ),
        )

    if re.search(
        r"-- Ticking (?:entity|block entity|tile entity) --",
        log_content,
        re.IGNORECASE,
    ):
        return _err(
            "TickingEntityCrash",
            "Something in your world crashed the game",
            details=(
                "An object or creature in your world caused the game to crash. "
                "This is usually caused by a corrupted item, mob, or tile in the world."
            ),
            suggestion=(
                "Open the crash log to find the name of what crashed. "
                "You may need to remove that object from your world using a world editor, "
                "or disable the mod that added it."
            ),
        )

    if re.search(
        r"Invalid session.*?restarting|Failed to verify username"
        r"|authentication servers are down",
        log_content,
        re.IGNORECASE,
    ):
        return _err(
            "AuthenticationError",
            "Couldn't verify your account",
            details=(
                "The game couldn't confirm your identity with the Minecraft servers. "
                "This is usually a temporary issue."
            ),
            suggestion=(
                "Try closing and relaunching the game. "
                "If this keeps happening, check your internet connection."
            ),
        )

    if re.search(
        r"No space left on device|not enough space on the disk|DiskSpaceException",
        log_content,
        re.IGNORECASE,
    ):
        return _err(
            "NoDiskSpace",
            "Your storage is full",
            details="The game couldn't save files because your disk is completely full.",
            suggestion=(
                "Free up some space by deleting files you no longer need, "
                "then try launching again."
            ),
        )

    if (
        "ModNotFoundException" in log_content
        or "net.minecraftforge.fml.ModLoadingException" in log_content
    ):
        return _err(
            "ModError",
            "A mod couldn't be loaded",
            details="A required mod could not be found or loaded.",
            suggestion="Check that all required mods are installed correctly.",
        )

    if re.search(r"missing texture|Unable to load resource", log_content, re.IGNORECASE):
        return _err(
            "ResourceError",
            "A game resource is missing",
            details="The game couldn't find a texture or file it needed.",
            suggestion=(
                "Try re-downloading or reinstalling this Minecraft version. "
                "If you are using a resource pack, try disabling it."
            ),
        )

    return {
        "has_error": False,
        "error_type": None,
        "message": None,
        "details": None,
        "suggestion": None,
        "auto_fix": None,
    }




def _strip_heap_flags_from_args(args: str) -> str:
    return " ".join(
        p for p in args.split()
        if not re.match(r"^-Xm[sx]\d", p, re.IGNORECASE)
    ).strip()


def _remove_bad_jvm_arg(args: str, bad_arg: str) -> str:
    if not bad_arg or not args.strip():
        return args
    bad = bad_arg.strip()
    bad_lower = bad.lower()

    def _core(s: str) -> str:
        s = s.lstrip('-+')
        if s.startswith('xx:'):
            s = s[3:].lstrip('-+')
        return s

    bad_core = _core(bad_lower)

    def _matches(token: str) -> bool:
        t = token.strip()
        t_lower = t.lower()
        if t_lower == bad_lower:
            return True
        if t_lower.lstrip('-') == bad_lower.lstrip('-'):
            return True
        if t_lower.endswith(':' + bad_lower):
            return True
        if t_lower in (f'-{bad_lower}', f'--{bad_lower}'):
            return True
        t_core = _core(t_lower)
        if bad_core and t_core == bad_core:
            return True
        return False

    return " ".join(t for t in args.split() if not _matches(t)).strip()


def _parse_ram_mb(value: str) -> int:
    raw = str(value or "").strip().upper()
    m = re.match(r"^(\d+)([KMGT]?)$", raw)
    if not m:
        return 0
    num = int(m.group(1))
    suffix = m.group(2)
    if suffix == "K":
        return max(1, num // 1024)
    if suffix == "G":
        return num * 1024
    if suffix == "T":
        return num * 1024 * 1024
    return num


def api_crash_autofix(data: Any):
    if not isinstance(data, dict):
        return {"ok": False, "error": "Invalid request"}

    action = str(data.get("action") or "").strip().lower()
    if action not in {"reduce_ram", "enable_auto_optimize", "clear_jvm_args"}:
        return {"ok": False, "error": "Unknown action"}

    from server.api._helpers import _read_data_ini_file, _resolve_version_dir_secure, _write_data_ini_file
    from core.settings import load_global_settings, save_global_settings

    category = str(data.get("category") or "").strip()
    folder = str(data.get("folder") or "").strip()
    use_version = bool(category and folder)

    try:
        if action in {"reduce_ram", "enable_auto_optimize"}:
            if use_version:
                resolved = _resolve_version_dir_secure(category, folder)
                if not resolved.get("ok"):
                    return {"ok": False, "error": "Version not found"}
                version_dir = resolved["path"]
                data_ini_path = os.path.join(version_dir, "data.ini")
                ini_data = _read_data_ini_file(data_ini_path)
                ini_data.pop("launch_min_ram", None)
                ini_data.pop("launch_max_ram", None)
                _write_data_ini_file(data_ini_path, ini_data)
            save_global_settings({"auto_optimize_launch_settings": "1"})
            safe_print(
                f"[api_crash_autofix] enable_auto_optimize "
                f"(version={category}/{folder} if set)"
            )
            return {
                "ok": True,
                "message": (
                    "Auto-Optimize has been enabled. It will automatically choose the best "
                    "memory settings when you next launch the game."
                ),
            }

        if action == "clear_jvm_args":
            bad_arg_token = str(data.get("bad_arg") or "").strip()

            def _apply_removal(current: str) -> str:
                if bad_arg_token:
                    return _remove_bad_jvm_arg(current, bad_arg_token)
                return ""

            old_args_global = ""
            old_args_version = ""
            global_cfg = load_global_settings()
            old_args_global = str(global_cfg.get("extra_jvm_args") or "")
            save_global_settings({"extra_jvm_args": _apply_removal(old_args_global)})
            if use_version:
                resolved = _resolve_version_dir_secure(category, folder)
                if not resolved.get("ok"):
                    return {"ok": False, "error": "Version not found"}
                version_dir = resolved["path"]
                data_ini_path = os.path.join(version_dir, "data.ini")
                ini_data = _read_data_ini_file(data_ini_path)
                old_args_version = str(ini_data.get("launch_extra_jvm_args") or "")
                ini_data["launch_extra_jvm_args"] = _apply_removal(old_args_version)
                _write_data_ini_file(data_ini_path, ini_data)
            old_args = old_args_global or old_args_version
            safe_print(
                f"[api_crash_autofix] clear_jvm_args: removed '{bad_arg_token or 'all'}' from '{old_args}' "
                f"(version={category}/{folder} if set)"
            )
            action_desc = f'"{bad_arg_token}"' if bad_arg_token else "all extra launch options"
            return {
                "ok": True,
                "message": f"Removed {action_desc} from your launch options. Relaunch the game to apply.",
            }
    except Exception as exc:
        return {"ok": False, "error": f"Auto-fix failed: {exc}"}

    return {"ok": False, "error": "Unknown action"}


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

        safe_print(f"[api_open_crash_log] Opening file: {log_path}")
        safe_print(f"[api_open_crash_log] File exists: {os.path.isfile(log_path)}")
        if os.path.isfile(log_path):
            file_size = os.path.getsize(log_path)
            safe_print(f"[api_open_crash_log] File size: {file_size} bytes")

        system = platform.system()

        if system == "Windows":
            os.startfile(log_path)
        elif system == "Darwin":
            subprocess.run(["open", log_path])
        else:
            subprocess.run(["xdg-open", log_path])

        return {"ok": True, "message": f"Opening {os.path.basename(log_path)}..."}
    except Exception as e:
        safe_print(f"[api] Error opening crash log: {e}")
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
                    safe_print(f"[api_clear_logs] Skipped (in use): {file_path}")

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

        safe_print(
            f"[api_clear_logs] Cleared logs: {deleted_count} files deleted, "
            f"{len(skipped_files)} files skipped"
        )

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
        safe_print(f"[api_clear_logs] Error clearing logs: {e}")
        return {"ok": False, "error": f"Failed to clear logs: {str(e)}"}
