from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
import time
from datetime import datetime

from core.java import (
    JAVA_RUNTIME_MODE_AUTO,
    JAVA_RUNTIME_MODE_PATH,
    detect_java_runtimes,
    get_path_java_executable,
)
from core.launch.mods import _cleanup_copied_mods
from core.launch.state import STATE
from core.subprocess_utils import no_window_kwargs
from core.logger import colorize_log
from core.settings import get_base_dir, get_versions_profile_dir

__all__ = [
    "_attach_copied_mods_to_process",
    "_create_version_log_file",
    "_detect_client_jar_java_major",
    "_class_file_major_to_java_major",
    "_finalize_process_exit",
    "_get_game_window_visible",
    "_get_latest_log_path",
    "_get_log_directories",
    "_get_process_status",
    "_is_minecraft_window_visible",
    "_output_reader_thread",
    "_process_monitor_thread",
    "_register_process",
    "_resolve_java_launch_candidates",
    "_set_last_launch_error",
    "_set_last_launch_diagnostic",
    "_spawn_version_process",
    "_wait_for_launch_stability",
    "consume_last_launch_diagnostic",
    "consume_last_launch_error",
]


def _finalize_process_exit(process_id, exit_code=None):
    cleanup_files = []
    snapshot = None

    with STATE.process_lock:
        proc_info = STATE.active_processes.get(process_id)
        if not proc_info:
            return None

        process_obj = proc_info.get("process")
        if exit_code is None and process_obj is not None:
            exit_code = process_obj.poll()

        if exit_code is None:
            return dict(proc_info)

        proc_info["status"] = "exited"
        proc_info["exit_code"] = exit_code
        proc_info.setdefault("end_time", time.time())

        if not proc_info.get("cleanup_started"):
            proc_info["cleanup_started"] = True
            cleanup_files = list(proc_info.get("copied_mods") or [])

        snapshot = dict(proc_info)

    if cleanup_files:
        _cleanup_copied_mods(cleanup_files)

    with STATE.process_lock:
        proc_info = STATE.active_processes.get(process_id)
        if not proc_info:
            return snapshot

        proc_info["status"] = "exited"
        proc_info["exit_code"] = exit_code
        proc_info.setdefault("end_time", time.time())
        proc_info["cleanup_started"] = True
        proc_info["cleanup_done"] = True
        if cleanup_files:
            proc_info["copied_mods"] = []
        snapshot = dict(proc_info)

    return snapshot


def _is_minecraft_window_visible(process_pid):
    system = platform.system().lower()

    if "windows" in system:
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            TH32CS_SNAPPROCESS = 0x00000002
            INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

            class PROCESSENTRY32W(ctypes.Structure):
                _fields_ = [
                    ("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260),
                ]

            candidate_pids = {int(process_pid)}
            snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if snapshot and snapshot != INVALID_HANDLE_VALUE:
                try:
                    entry = PROCESSENTRY32W()
                    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)

                    parent_map = {}
                    if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                        while True:
                            parent_map[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                                break

                    changed = True
                    while changed:
                        changed = False
                        for child_pid, parent_pid in parent_map.items():
                            if parent_pid in candidate_pids and child_pid not in candidate_pids:
                                candidate_pids.add(child_pid)
                                changed = True
                finally:
                    kernel32.CloseHandle(snapshot)

            class WindowInfo:
                found = False

            def enum_windows_callback(hwnd, lparam):
                if WindowInfo.found:
                    return False
                try:
                    if not user32.IsWindowVisible(hwnd):
                        return True

                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if int(pid.value) not in candidate_pids:
                        return True

                    title_buf = ctypes.create_unicode_buffer(512)
                    user32.GetWindowTextW(hwnd, title_buf, len(title_buf))
                    title = title_buf.value.strip().lower()

                    class_buf = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, class_buf, len(class_buf))
                    class_name = class_buf.value.strip().lower()

                    looks_like_game_window = (
                        "minecraft" in title
                        or class_name.startswith("glfw")
                        or class_name.startswith("lwjgl")
                    )

                    if looks_like_game_window or title:
                        WindowInfo.found = True
                        return False
                except Exception:
                    pass
                return True

            enum_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            callback_ref = enum_callback(enum_windows_callback)
            user32.EnumWindows(callback_ref, 0)

            return WindowInfo.found
        except Exception:
            pass

    elif "linux" in system:
        import shutil as _shutil

        if os.environ.get("WAYLAND_DISPLAY"):
            try:
                os.kill(int(process_pid), 0)
                return True
            except OSError:
                return False
            except Exception:
                return True

        if _shutil.which("xdotool"):
            try:
                result = subprocess.run(
                    ["xdotool", "search", "--pid", str(process_pid)],
                    capture_output=True,
                    timeout=2,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return True
            except Exception:
                pass

        if _shutil.which("wmctrl"):
            try:
                result = subprocess.run(
                    ["wmctrl", "-lp"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode == 0 and result.stdout:
                    pid_str = str(int(process_pid))
                    for line in result.stdout.splitlines():
                        cols = line.split(None, 4)
                        # Format: <id> <desk> <pid> <host> <title>
                        if len(cols) >= 3 and cols[2] == pid_str:
                            return True
            except Exception:
                pass

        return False

    elif "darwin" in system or "mac" in system:
        try:
            result = subprocess.run(
                ["osascript", "-e", f'tell application "System Events" to get windows of process "java" where unix id is {process_pid}'],
                capture_output=True,
                timeout=2
            )
            return result.returncode == 0 and "missing value" not in result.stdout.decode()
        except Exception:
            pass

    return False


def _set_last_launch_error(version_identifier, message):
    key = str(version_identifier or "").strip()
    if not key:
        return
    with STATE.last_launch_error_lock:
        STATE.last_launch_errors[key] = str(message or "").strip()


def _set_last_launch_diagnostic(version_identifier, diagnostic):
    key = str(version_identifier or "").strip()
    if not key or not isinstance(diagnostic, dict):
        return
    with STATE.last_launch_error_lock:
        STATE.last_launch_diagnostics[key] = dict(diagnostic)


def consume_last_launch_error(version_identifier):
    key = str(version_identifier or "").strip()
    if not key:
        return ""
    with STATE.last_launch_error_lock:
        return STATE.last_launch_errors.pop(key, "")


def consume_last_launch_diagnostic(version_identifier):
    key = str(version_identifier or "").strip()
    if not key:
        return {}
    with STATE.last_launch_error_lock:
        return STATE.last_launch_diagnostics.pop(key, {})


def _create_version_log_file(version_identifier):
    try:
        base_dir = get_base_dir()

        if "/" in version_identifier:
            version_name = version_identifier.split("/", 1)[1]
        else:
            version_name = version_identifier

        logs_dir = os.path.join(base_dir, "logs", "versions", version_name)
        os.makedirs(logs_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_file_path = os.path.join(logs_dir, f"{timestamp}.log")
        log_file = open(log_file_path, "w", buffering=1, encoding="utf-8")

        print(colorize_log(f"[launcher] Created log file: {log_file_path}"))

        return log_file_path, log_file
    except Exception as e:
        print(colorize_log(f"[launcher] ERROR creating log file: {e}"))
        return None, None


def _get_log_directories(version_dir):
    return [
        os.path.join(version_dir, "data", "logs"),
        os.path.join(version_dir, "logs"),
    ]


def _get_latest_log_path(version_dir):
    try:
        log_dirs = _get_log_directories(version_dir)

        latest_log = None
        found_files = {}

        for log_dir in log_dirs:
            if not os.path.isdir(log_dir):
                continue
            try:
                for filename in os.listdir(log_dir):
                    is_log = filename.endswith(".log") or filename.endswith(".txt")
                    if not is_log:
                        continue

                    filepath = os.path.join(log_dir, filename)
                    mtime = os.path.getmtime(filepath)

                    if filename == "latest.log":
                        priority = 3
                    elif filename.startswith("crash-"):
                        priority = 2
                    elif filename.endswith(".log"):
                        priority = 1
                    else:
                        priority = 0

                    if (
                        filename not in found_files
                        or found_files[filename][0] < priority
                        or (found_files[filename][0] == priority and mtime > found_files[filename][1])
                    ):
                        found_files[filename] = (priority, mtime, filepath)
            except Exception:
                pass

        if found_files:
            best_file = max(found_files.items(), key=lambda x: (x[1][0], x[1][1]))
            latest_log = best_file[1][2]
            print(colorize_log(f"[_get_latest_log_path] Best log file found: {latest_log}"))
            print(colorize_log(f"[_get_latest_log_path] All found files: {list(found_files.keys())}"))
        else:
            print(colorize_log(f"[_get_latest_log_path] No log files found in: {log_dirs}"))

        return latest_log
    except Exception as e:
        print(colorize_log(f"[_get_latest_log_path] Exception: {e}"))
        return None


def _output_reader_thread(process, log_file, version_name):
    try:
        if not process.stdout:
            return

        for line in iter(process.stdout.readline, ''):
            if not line:
                break

            try:
                log_file.write(line)
                log_file.flush()
            except (ValueError, OSError):
                pass

            msg = f"[{version_name}] {line.rstrip()}"
            try:
                print(msg, flush=True)
            except UnicodeEncodeError:
                try:
                    out_enc = sys.stdout.encoding or "utf-8"
                    safe_msg = msg.encode(out_enc, errors="replace").decode(out_enc, errors="replace")
                    print(safe_msg, flush=True)
                except Exception:
                    try:
                        sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))
                        sys.stdout.flush()
                    except Exception:
                        pass
    except Exception as e:
        print(colorize_log(f"[_output_reader_thread] Error: {e}"))
    finally:
        try:
            if log_file:
                log_file.close()
        except Exception:
            pass


def _process_monitor_thread(process_id, process_obj):
    try:
        exit_code = process_obj.wait()
    except Exception:
        exit_code = process_obj.poll()

    _finalize_process_exit(process_id, exit_code)


def _register_process(process_id, process_obj, version_identifier, log_file_path=None,
                      copied_mods=None, start_time=None):
    with STATE.process_lock:
        STATE.active_processes[process_id] = {
            "pid": process_obj.pid,
            "version": version_identifier,
            "start_time": float(start_time if start_time is not None else time.time()),
            "process": process_obj,
            "log_path": log_file_path,
            "copied_mods": copied_mods or [],
            "status": "running",
            "exit_code": None,
            "cleanup_started": False,
            "cleanup_done": False,
            "end_time": None,
        }

    monitor = threading.Thread(
        target=_process_monitor_thread,
        args=(process_id, process_obj),
        daemon=True
    )
    monitor.start()


def _get_process_status(process_id):
    with STATE.process_lock:
        if process_id not in STATE.active_processes:
            return None

        proc_info = STATE.active_processes[process_id]
        process_obj = proc_info["process"]
        version = proc_info["version"]
        elapsed = time.time() - proc_info["start_time"]
        status = proc_info.get("status", "running")

        poll_result = process_obj.poll()

        if poll_result is None and status != "exited":
            return {
                "ok": True,
                "status": "running",
                "process_id": process_id,
                "version": version,
                "elapsed": elapsed,
                "start_time": proc_info["start_time"],
            }

    proc_info = _finalize_process_exit(process_id, poll_result)
    if not proc_info:
        return None

    log_path = proc_info.get("log_path")

    if log_path:
        print(colorize_log(f"[_get_process_status] Using stored log path: {log_path}"))
    else:
        clients_dir = get_versions_profile_dir()

        version_dir = None
        if "/" in version:
            parts = version.replace("\\", "/").split("/", 1)
            category, folder = parts[0], parts[1]
            for cat in os.listdir(clients_dir):
                if cat.lower() == category.lower():
                    candidate = os.path.join(clients_dir, cat, folder)
                    if os.path.isdir(candidate):
                        version_dir = candidate
                        break
            if not version_dir:
                version_dir = os.path.join(clients_dir, category, folder)
            print(colorize_log(f"[_get_process_status] Reconstructed version_dir from '/' split: {version_dir}"))
        else:
            for cat in os.listdir(clients_dir):
                p = os.path.join(clients_dir, cat, version)
                if os.path.isdir(p):
                    version_dir = p
                    print(colorize_log(f"[_get_process_status] Found version_dir from directory scan: {version_dir}"))
                    break

        log_path = _get_latest_log_path(version_dir) if version_dir else None
        print(colorize_log(
            f"[_get_process_status] Fallback log search - version_dir: {version_dir}, log_path: {log_path}"
        ))

    with STATE.process_lock:
        STATE.active_processes.pop(process_id, None)

    return {
        "ok": True,
        "status": "exited",
        "process_id": process_id,
        "version": version,
        "exit_code": proc_info.get("exit_code", poll_result),
        "elapsed": elapsed,
        "start_time": proc_info["start_time"],
        "log_path": log_path,
    }


def _get_game_window_visible(process_id):
    with STATE.process_lock:
        if process_id not in STATE.active_processes:
            return {"ok": False, "error": "Process not found"}

        proc_info = STATE.active_processes[process_id]
        process_obj = proc_info["process"]
        elapsed = time.time() - proc_info["start_time"]

        poll_result = process_obj.poll()
        if poll_result is not None:
            return {"ok": False, "error": "Process has exited"}

        pid = process_obj.pid
        is_visible = _is_minecraft_window_visible(pid)

        return {
            "ok": True,
            "visible": is_visible,
            "version": proc_info["version"],
            "start_time": proc_info["start_time"],
            "elapsed": elapsed,
        }


def _attach_copied_mods_to_process(process_id, copied_mods):
    with STATE.process_lock:
        proc_info = STATE.active_processes.get(process_id)
        if not proc_info:
            return
        proc_info["copied_mods"] = list(copied_mods or [])


def _class_file_major_to_java_major(class_major: int) -> int:
    try:
        major = int(class_major or 0)
    except Exception:
        return 0
    if major < 45:
        return 0
    return major - 44


def _detect_client_jar_java_major(version_dir: str) -> int:
    import zipfile

    client_jar = os.path.join(version_dir, "client.jar")
    if not os.path.isfile(client_jar):
        return 0

    highest_class_major = 0
    try:
        with zipfile.ZipFile(client_jar, "r") as jar:
            for info in jar.infolist():
                if info.is_dir() or not str(info.filename or "").endswith(".class"):
                    continue
                try:
                    with jar.open(info, "r") as class_fp:
                        header = class_fp.read(8)
                    if len(header) < 8 or header[:4] != b"\xca\xfe\xba\xbe":
                        continue
                    class_major = int.from_bytes(header[6:8], "big")
                    if class_major > highest_class_major:
                        highest_class_major = class_major
                except Exception:
                    continue
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: Could not inspect client.jar Java target: {e}"))
        return 0

    return _class_file_major_to_java_major(highest_class_major)


def _resolve_java_launch_candidates(selected_java_setting: str, version_dir: str):
    raw = str(selected_java_setting or "").strip()
    target_java_major = _detect_client_jar_java_major(version_dir)
    path_java = get_path_java_executable()

    force_runtime_refresh = raw == JAVA_RUNTIME_MODE_AUTO
    detected = detect_java_runtimes(force_refresh=force_runtime_refresh)
    runtimes_by_path = {}
    ordered_runtimes = []
    for rt in sorted(
        detected,
        key=lambda item: (int(item.get("major") or 0), str(item.get("path") or "").lower()),
    ):
        path = str(rt.get("path") or "").strip()
        if not path:
            continue
        norm = os.path.normcase(os.path.normpath(path))
        if norm in runtimes_by_path:
            continue
        entry = {
            "path": path,
            "label": str(rt.get("label") or "Java"),
            "major": int(rt.get("major") or 0),
            "version": str(rt.get("version") or "unknown"),
        }
        runtimes_by_path[norm] = entry
        ordered_runtimes.append(entry)

    if raw == JAVA_RUNTIME_MODE_AUTO:
        if target_java_major > 0:
            exact = [rt for rt in ordered_runtimes if rt.get("major") == target_java_major]
            higher = [rt for rt in ordered_runtimes if rt.get("major", 0) > target_java_major]
            compatible = exact + higher
            if compatible:
                return compatible, target_java_major
            return [], target_java_major
        if ordered_runtimes:
            return list(ordered_runtimes), target_java_major
        return [{
            "path": path_java,
            "label": "Default (Java PATH)",
            "major": 0,
            "version": "unknown",
        }], target_java_major

    if raw == "" or raw == JAVA_RUNTIME_MODE_PATH:
        return [{
            "path": path_java,
            "label": "Default (Java PATH)",
            "major": 0,
            "version": "unknown",
        }], target_java_major

    explicit_norm = os.path.normcase(os.path.normpath(raw))
    if explicit_norm in runtimes_by_path:
        return [runtimes_by_path[explicit_norm]], target_java_major

    if os.path.isfile(raw):
        return [{
            "path": raw,
            "label": "Custom Java",
            "major": 0,
            "version": "unknown",
        }], target_java_major

    print(colorize_log(f"[launcher] Warning: configured Java runtime not found, falling back to PATH: {raw}"))
    return [{
        "path": path_java,
        "label": "Default (Java PATH)",
        "major": 0,
        "version": "unknown",
    }], target_java_major


def _wait_for_launch_stability(process_obj, timeout_seconds: float = 8.0):
    deadline = time.time() + max(1.0, float(timeout_seconds or 0))
    while time.time() < deadline:
        exit_code = process_obj.poll()
        if exit_code is not None:
            return False, exit_code

        try:
            if _is_minecraft_window_visible(process_obj.pid):
                return True, None
        except Exception:
            pass

        time.sleep(0.5)

    exit_code = process_obj.poll()
    if exit_code is not None:
        return False, exit_code
    return True, None


def _spawn_version_process(cmd, launch_cwd, version_identifier):
    log_file_path = None
    log_file = None
    version_name = version_identifier.split("/", 1)[1] if "/" in version_identifier else version_identifier

    print("Launching version:", version_identifier)
    print("Working dir:", launch_cwd)
    print("Command:", " ".join(cmd))

    _popen_kwargs = no_window_kwargs()

    try:
        log_file_path, log_file = _create_version_log_file(version_identifier)

        if log_file:
            process = subprocess.Popen(
                cmd,
                cwd=launch_cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **_popen_kwargs,
            )
        else:
            process = subprocess.Popen(cmd, cwd=launch_cwd, **_popen_kwargs)

        if log_file and process.stdout:
            reader_thread = threading.Thread(
                target=_output_reader_thread,
                args=(process, log_file, version_name),
                daemon=True
            )
            reader_thread.start()
            print(colorize_log(f"[launcher] Output reader thread started"))

        return {
            "ok": True,
            "process": process,
            "log_path": log_file_path,
            "start_time": time.time(),
        }
    except Exception as e:
        try:
            if log_file:
                log_file.close()
        except Exception:
            pass
        return {
            "ok": False,
            "error": str(e),
            "log_path": log_file_path,
        }
