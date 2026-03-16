# core/java_launcher.py

import os
import sys
import subprocess
import platform
import zipfile
import re
import time
import threading
import json
import hashlib
import shutil
import tempfile
import urllib.request
import shlex

from datetime import datetime
from uuid import uuid3, NAMESPACE_DNS

from core.settings import load_global_settings, get_base_dir, get_versions_profile_dir
from core.logger import colorize_log
from server.yggdrasil import _get_username_and_uuid

# ========== MOD MANAGEMENT ==========
def _copy_mods_for_launch(game_dir, mod_loader):
    """Copy mods from storage to game mods folder before launch.
    
    Scans ~/.histolauncher/mods/{loader}/{slug}/ directories. For each mod:
    - Reads mod_meta.json for disabled flag and active_version
    - Gets the active version's version_meta.json to check mod_loader matches
    - Copies .jar files from the active version directory
    
    Args:
        game_dir: The game data directory
        mod_loader: The mod loader type (fabric/forge)
        
    Returns:
        List of file paths that were copied (for cleanup later)
    """
    if not game_dir or not mod_loader:
        return []
    
    try:
        from core import mod_manager
        
        mods_storage = mod_manager.get_mods_storage_dir()
        
        if not os.path.isdir(mods_storage):
            return []
        
        target_mods_dir = os.path.join(game_dir, "mods")
        os.makedirs(target_mods_dir, exist_ok=True)
        
        copied_files = []
        
        existing_files = set()
        if os.path.isdir(target_mods_dir):
            existing_files = {f.lower() for f in os.listdir(target_mods_dir) if f.endswith(".jar")}

        # New layout: mods/{loader}/{slug}/
        for loader_name in os.listdir(mods_storage):
            loader_dir = os.path.join(mods_storage, loader_name)
            if not os.path.isdir(loader_dir):
                continue

            for mod_slug in os.listdir(loader_dir):
                mod_dir = os.path.join(loader_dir, mod_slug)
                if not os.path.isdir(mod_dir):
                    continue
            
                # Read mod-level metadata
                meta_file = os.path.join(mod_dir, "mod_meta.json")
                if not os.path.isfile(meta_file):
                    continue
                
                try:
                    with open(meta_file, "r", encoding="utf-8") as mf:
                        meta = json.load(mf)
                except Exception:
                    continue
                
                if meta.get("disabled", False):
                    print(colorize_log(f"[mods] Skipping disabled mod: {mod_slug}"))
                    continue
                
                active_version = meta.get("active_version")
                if not active_version:
                    continue
                
                version_dir = os.path.join(mod_dir, active_version)
                if not os.path.isdir(version_dir):
                    continue
                
                # Check version's mod_loader matches the launch loader
                ver_meta_file = os.path.join(version_dir, "version_meta.json")
                if os.path.isfile(ver_meta_file):
                    try:
                        with open(ver_meta_file, "r", encoding="utf-8") as vf:
                            ver_meta = json.load(vf)
                        if ver_meta.get("mod_loader", "").lower() != mod_loader.lower():
                            print(colorize_log(f"[mods] Skipping {mod_slug} v{active_version} (loader mismatch: {ver_meta.get('mod_loader')} != {mod_loader})"))
                            continue
                    except Exception:
                        pass
                
                # Copy .jar files from the active version directory
                for filename in os.listdir(version_dir):
                    if not filename.endswith(".jar"):
                        continue
                    
                    if filename.lower() in existing_files:
                        print(colorize_log(f"[mods] Skipping {filename} (already exists)"))
                        continue
                    
                    src = os.path.join(version_dir, filename)
                    dst = os.path.join(target_mods_dir, filename)
                    
                    try:
                        shutil.copy2(src, dst)
                        copied_files.append(dst)
                        print(colorize_log(f"[mods] Copied: {filename}"))
                    except Exception as e:
                        print(colorize_log(f"[mods] Warning: Failed to copy {filename}: {e}"))
        
        if copied_files:
            print(colorize_log(f"[mods] Total mods copied: {len(copied_files)}"))
        
        # --- Copy modpack mods ---
        try:
            modpacks_dir = mod_manager.get_modpacks_storage_dir()
            if os.path.isdir(modpacks_dir):
                for pack_slug in os.listdir(modpacks_dir):
                    pack_dir = os.path.join(modpacks_dir, pack_slug)
                    if not os.path.isdir(pack_dir):
                        continue
                    data_file = os.path.join(pack_dir, "data.json")
                    if not os.path.isfile(data_file):
                        continue
                    try:
                        with open(data_file, "r", encoding="utf-8") as df:
                            pack_data = json.load(df)
                    except Exception:
                        continue
                    if pack_data.get("disabled", False):
                        print(colorize_log(f"[mods] Skipping disabled modpack: {pack_slug}"))
                        continue
                    pack_loader = (pack_data.get("mod_loader") or "").lower()
                    if pack_loader != mod_loader.lower():
                        print(colorize_log(f"[mods] Skipping modpack {pack_slug} (loader mismatch: {pack_loader} != {mod_loader})"))
                        continue

                    pack_mod_entries = pack_data.get("mods") if isinstance(pack_data.get("mods"), list) else []

                    # Prefer metadata-driven iteration so we can respect per-mod disabled state
                    # and support both new and legacy on-disk layouts.
                    for pm in pack_mod_entries:
                        if not isinstance(pm, dict):
                            continue
                        if pm.get("disabled", False):
                            continue

                        pm_slug = str(pm.get("mod_slug") or "").strip()
                        ver_name = str(pm.get("version_label") or "").strip()
                        if not pm_slug:
                            continue

                        ver_candidates = []
                        if ver_name:
                            # New layout: modpacks/{slug}/mods/{mod_slug}/{ver}/
                            ver_candidates.append(os.path.join(pack_dir, "mods", pm_slug, ver_name))
                            # Legacy layout: modpacks/{slug}/mods/{loader}/{mod_slug}/{ver}/
                            ver_candidates.append(os.path.join(pack_dir, "mods", pack_loader, pm_slug, ver_name))

                        # Fallback when version label is missing/outdated.
                        if not ver_candidates:
                            base_new = os.path.join(pack_dir, "mods", pm_slug)
                            if os.path.isdir(base_new):
                                ver_candidates.extend(
                                    [
                                        os.path.join(base_new, d)
                                        for d in os.listdir(base_new)
                                        if os.path.isdir(os.path.join(base_new, d))
                                    ]
                                )
                            base_old = os.path.join(pack_dir, "mods", pack_loader, pm_slug)
                            if os.path.isdir(base_old):
                                ver_candidates.extend(
                                    [
                                        os.path.join(base_old, d)
                                        for d in os.listdir(base_old)
                                        if os.path.isdir(os.path.join(base_old, d))
                                    ]
                                )

                        for ver_dir in ver_candidates:
                            if not os.path.isdir(ver_dir):
                                continue
                            for filename in os.listdir(ver_dir):
                                if not filename.endswith(".jar"):
                                    continue
                                if filename.lower() in existing_files:
                                    continue
                                src = os.path.join(ver_dir, filename)
                                dst = os.path.join(target_mods_dir, filename)
                                try:
                                    shutil.copy2(src, dst)
                                    copied_files.append(dst)
                                    existing_files.add(filename.lower())
                                    print(colorize_log(f"[mods] Copied (modpack {pack_slug}): {filename}"))
                                except Exception as e:
                                    print(colorize_log(f"[mods] Warning: Failed to copy modpack file {filename}: {e}"))

                    # Legacy fallback for packs that do not have usable mods metadata.
                    if not pack_mod_entries:
                        pack_mods_dir = os.path.join(pack_dir, "mods", pack_loader)
                        if os.path.isdir(pack_mods_dir):
                            for pm_slug in os.listdir(pack_mods_dir):
                                pm_dir = os.path.join(pack_mods_dir, pm_slug)
                                if not os.path.isdir(pm_dir):
                                    continue
                                for ver_name in os.listdir(pm_dir):
                                    ver_dir = os.path.join(pm_dir, ver_name)
                                    if not os.path.isdir(ver_dir):
                                        continue
                                    for filename in os.listdir(ver_dir):
                                        if not filename.endswith(".jar"):
                                            continue
                                        if filename.lower() in existing_files:
                                            continue
                                        src = os.path.join(ver_dir, filename)
                                        dst = os.path.join(target_mods_dir, filename)
                                        try:
                                            shutil.copy2(src, dst)
                                            copied_files.append(dst)
                                            existing_files.add(filename.lower())
                                            print(colorize_log(f"[mods] Copied (legacy modpack {pack_slug}): {filename}"))
                                        except Exception as e:
                                            print(colorize_log(f"[mods] Warning: Failed to copy legacy modpack file {filename}: {e}"))
        except Exception as e:
            print(colorize_log(f"[mods] Error copying modpack mods: {e}"))

        if copied_files:
            print(colorize_log(f"[mods] Total files copied (mods + modpacks): {len(copied_files)}"))

        return copied_files
    except Exception as e:
        print(colorize_log(f"[mods] Error copying mods: {e}"))
        return []


def _cleanup_copied_mods(copied_files):
    """Remove mods that were copied during launch.

    Only the files tracked in copied_files (placed by Histolauncher) are
    removed — any pre-existing mods in the game mods folder are left alone.

    Because Minecraft (or its JVM) can still hold file locks for a short time
    after the process exits, removal is retried up to 10 times with a 2-second
    delay between attempts.

    Args:
        copied_files: List of file paths that were copied during launch
    """
    if not copied_files:
        return

    try:
        MAX_ATTEMPTS = 10
        RETRY_DELAY = 2  # seconds

        remaining = [p for p in copied_files if os.path.isfile(p)]
        removed_count = 0

        for attempt in range(1, MAX_ATTEMPTS + 1):
            if not remaining:
                break

            still_locked = []
            for file_path in remaining:
                try:
                    os.remove(file_path)
                    removed_count += 1
                except Exception as e:
                    still_locked.append(file_path)
                    if attempt == 1:
                        print(colorize_log(f"[mods] File locked, will retry: {os.path.basename(file_path)} ({e})"))

            remaining = still_locked

            if remaining and attempt < MAX_ATTEMPTS:
                print(colorize_log(f"[mods] {len(remaining)} mod file(s) still locked, retrying in {RETRY_DELAY}s (attempt {attempt}/{MAX_ATTEMPTS})..."))
                time.sleep(RETRY_DELAY)

        if removed_count > 0:
            print(colorize_log(f"[mods] Cleaned up {removed_count} copied mod(s)"))

        if remaining:
            print(colorize_log(f"[mods] Warning: {len(remaining)} mod file(s) could not be removed after {MAX_ATTEMPTS} attempts:"))
            for p in remaining:
                print(colorize_log(f"[mods]   - {p}"))
    except Exception as e:
        print(colorize_log(f"[mods] Error during cleanup: {e}"))


def _finalize_process_exit(process_id, exit_code=None):
    cleanup_files = []
    snapshot = None

    with _process_lock:
        proc_info = _active_processes.get(process_id)
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

    with _process_lock:
        proc_info = _active_processes.get(process_id)
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

# ========== WINDOW DETECTION ==========
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
        try:
            result = subprocess.run(
                ["xdotool", "search", "--name", "Minecraft", "--pid", str(process_pid)],
                capture_output=True,
                timeout=2
            )
            return result.returncode == 0 and result.stdout.strip() != b""
        except Exception:
            pass
    
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


# ========== PROCESS TRACKING SYSTEM ==========

_active_processes = {}
_process_lock = threading.Lock()


def _create_client_log_file(version_identifier):
    try:
        base_dir = get_base_dir()
        
        if "/" in version_identifier:
            version_name = version_identifier.split("/", 1)[1]
        else:
            version_name = version_identifier
        
        logs_dir = os.path.join(base_dir, "logs", "clients", version_name)
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
        latest_mtime = 0
        
        priority_files = {
            "latest.log": 2,
            "crash-": 2,
            ".log": 1,
            ".txt": 0,
        }
        
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
                    
                    if filename not in found_files or found_files[filename][0] < priority or (found_files[filename][0] == priority and mtime > found_files[filename][1]):
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
                # Some Windows consoles use legacy code pages that cannot encode
                # all Minecraft/Forge log characters.
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


def _register_process(process_id, process_obj, version_identifier, log_file_path=None, copied_mods=None):
    with _process_lock:
        _active_processes[process_id] = {
            "pid": process_obj.pid,
            "version": version_identifier,
            "start_time": time.time(),
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
    with _process_lock:
        if process_id not in _active_processes:
            return None

        proc_info = _active_processes[process_id]
        process_obj = proc_info["process"]
        version = proc_info["version"]
        elapsed = time.time() - proc_info["start_time"]
        status = proc_info.get("status", "running")

        poll_result = process_obj.poll()

        if poll_result is None and status != "exited":
            # Process is still running
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

    log_path = proc_info.get("log_path")  # Use the log file we created during launch

    # If we stored a log path, use that (it has all the stdout/stderr)
    if log_path:
        print(colorize_log(f"[_get_process_status] Using stored log path: {log_path}"))
    else:
        # Fallback: try to find log file in version directory
        clients_dir = get_versions_profile_dir()

        # Reconstruct version_dir from version identifier
        version_dir = None
        if "/" in version:
            parts = version.replace("\\", "/").split("/", 1)
            category, folder = parts[0], parts[1]
            # Case-insensitive directory lookup
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
        print(colorize_log(f"[_get_process_status] Fallback log search - version_dir: {version_dir}, log_path: {log_path}"))

    with _process_lock:
        _active_processes.pop(process_id, None)

    return {
        "ok": True,
        "status": "exited",
        "process_id": process_id,
        "version": version,
        "exit_code": proc_info.get("exit_code", poll_result),
        "elapsed": elapsed,
        "start_time": proc_info["start_time"],
        "log_path": log_path
    }


def _get_game_window_visible(process_id):
    with _process_lock:
        if process_id not in _active_processes:
            return {"ok": False, "error": "Process not found"}
        
        proc_info = _active_processes[process_id]
        process_obj = proc_info["process"]
        elapsed = time.time() - proc_info["start_time"]
        
        # Check if process is still running
        poll_result = process_obj.poll()
        if poll_result is not None:
            # Process has exited
            return {"ok": False, "error": "Process has exited"}
        
        # Process is running, check if window is visible
        pid = process_obj.pid
        is_visible = _is_minecraft_window_visible(pid)
        
        return {
            "ok": True,
            "visible": is_visible,
            "version": proc_info["version"],
            "start_time": proc_info["start_time"],
            "elapsed": elapsed,
        }


def _extract_mc_version_string(version_identifier):
    if "/" in version_identifier:
        _, base = version_identifier.split("/", 1)
    else:
        base = version_identifier
    # Remove loader suffix if present (e.g. "1.16.5-fabric" -> "1.16.5")
    return base.split("-", 1)[0]



def _native_subfolder_for_platform():
    system = platform.system().lower()
    if "windows" in system:
        return os.path.join("native", "windows")
    if "linux" in system:
        return os.path.join("native", "linux")
    if "darwin" in system or "mac" in system:
        return os.path.join("native", "mac")
    return os.path.join("native", "windows")


def _join_classpath(base_dir, entries):
    sep = os.pathsep
    # Normalize all paths to use proper OS separators (critical for Windows with mixed slashes)
    abs_entries = [os.path.normpath(os.path.join(base_dir, e)) for e in entries]
    return sep.join(abs_entries)


def _load_data_ini(version_dir):
    data_ini = os.path.join(version_dir, "data.ini")
    if not os.path.exists(data_ini):
        return {}
    meta = {}
    with open(data_ini, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                meta[k.strip()] = v.strip()
    return meta


def _parse_mc_version(version_identifier):
    if "/" in version_identifier:
        _, base = version_identifier.split("/", 1)
    else:
        base = version_identifier
    base = base.split("-", 1)[0]
    parts = base.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return major, minor
    except Exception:
        return None, None


def _is_authlib_injector_needed(version_identifier):
    major, minor = _parse_mc_version(version_identifier)
    if major is None:
        return False
    if major > 1:
        return True
    # Authlib-based profile/session skin handling is used by 1.7+.
    # Enabling this for legacy modern versions keeps custom skins working
    # for 1.12.2 and below while avoiding very old classic-era clients.
    if major == 1 and minor >= 7:
        return True
    return False


def username_to_uuid(username: str) -> str:
    offline_uuid = uuid3(NAMESPACE_DNS, "OfflinePlayer:" + username)
    return str(offline_uuid).replace("-", "")


def _expand_placeholders(args_str, version_identifier, game_dir, version_dir, global_settings, meta, assets_root_override=None):
    username, auth_uuid_raw = _get_username_and_uuid()
    base_dir = get_base_dir()
    assets_root = assets_root_override or os.path.join(base_dir, "assets")
    asset_index_name = meta.get("asset_index") or ""
    version_type = meta.get("version_type") or ""
    auth_uuid = (
        f"{auth_uuid_raw[0:8]}-{auth_uuid_raw[8:12]}-{auth_uuid_raw[12:16]}-"
        f"{auth_uuid_raw[16:20]}-{auth_uuid_raw[20:]}"
    )
    auth_access_token = "0"
    user_type = "legacy"
    user_properties = "{}"
    game_dir = game_dir or ""
    
    # Extract just the MC version from version_identifier (e.g., "Release/1.21.11" -> "1.21.11")
    mc_version = version_identifier.split("/")[-1] if "/" in version_identifier else version_identifier
    
    replacements = {
        "${auth_player_name}": username,
        "${auth_uuid}": auth_uuid,
        "${auth_access_token}": auth_access_token,
        "${user_type}": user_type,
        "${user_properties}": user_properties,
        "${version_name}": mc_version,
        "${game_directory}": game_dir,
        "${gameDir}": game_dir,
        "${assets_root}": assets_root,
        "${game_assets}": assets_root,  # Legacy name for assets_root (pre-1.6)
        "${assets_index_name}": asset_index_name,
        "${version_type}": version_type,
        "${resolution_width}": "854",
        "${resolution_height}": "480",
        # Legacy authentication tokens (very old versions)
        "${auth_session}": "0",  # Legacy session token (pre-1.6)
        "${auth_player_type}": "legacy",  # Alternative name for user_type
    }
    
    # Log asset_index for debugging old version issues
    if not asset_index_name:
        print(colorize_log(f"[launcher] DEBUG: asset_index not in metadata for {version_identifier}"))
    print(colorize_log(f"[launcher] DEBUG: Expanding placeholders - assets_root={assets_root}, asset_index={asset_index_name}"))
    
    # First pass: filter out launcher-specific arguments before placeholder expansion
    # These are arguments from Minecraft Launcher that shouldn't be passed to the game
    args_before_expand = args_str.split()
    launcher_only_args = set()
    filtered_before_expand = []
    skip_next = False
    
    for i, arg in enumerate(args_before_expand):
        if skip_next:
            skip_next = False
            continue
        # Launcher-specific arguments that should never reach the game
        if arg in ("--clientId", "--xuid") or arg.startswith("--quickPlay"):
            # Skip this arg and its value (if it has one)
            if "=" not in arg and i + 1 < len(args_before_expand) and not args_before_expand[i + 1].startswith("--"):
                skip_next = True
            continue
        filtered_before_expand.append(arg)
    
    args_str_filtered = " ".join(filtered_before_expand)
    
    # Now do placeholder expansion on the pre-filtered args
    out = args_str_filtered
    for k, v in replacements.items():
        if k in out:
            out = out.replace(k, v)
    args = out.split()
    
    # Debug: Log if any problematic placeholders remain
    unresolved = [arg for arg in args if "${" in arg and "}" in arg]
    if unresolved:
        print(colorize_log(f"[launcher] DEBUG: Unresolved placeholders found: {unresolved}"))
    
    # Second pass: filter out remaining problematic arguments and handle special cases
    filtered = []
    skip_next = False
    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        # Skip arguments with unresolved placeholders (e.g., ${clientid}, ${auth_xuid})
        if "${" in arg and "}" in arg:
            print(colorize_log(f"[launcher] DEBUG: Filtering out unresolved placeholder: {arg}"))
            continue
        if arg.startswith("--gameDir"):
            # Skip --gameDir and its value (next arg if --gameDir doesn't have =)
            if "=" not in arg:  # If not in form --gameDir=path
                skip_next = True  # Skip the next argument (the path)
            continue
        if arg.startswith("--demo") or arg.startswith("--width") or arg.startswith("--height"):
            continue
        filtered.append(arg)
    
    # Preserve legacy positional arguments (e.g. username/session in very old versions)
    # before processing flag/value pairs.
    final = []
    i = 0
    while i < len(filtered) and not filtered[i].startswith("--"):
        final.append(filtered[i])
        i += 1

    # Final pass: remove orphaned bare values (like "854 480" from resolution placeholders)
    # while preserving required arguments for flags that need them.
    while i < len(filtered):
        arg = filtered[i]
        
        # If this is a flag, keep it
        if arg.startswith("--"):
            # Check if this flag requires an argument
            needs_arg = arg in {
                '--username', '--version', '--gameDir', '--gameDirectory',
                '--assetsDir', '--assetIndex', '--uuid', '--accessToken',
                '--userType', '--versionType', '--userProperties', '--tweakClass'
            } or arg.split('=', 1)[0] in {
                '--username', '--version', '--gameDir', '--gameDirectory',
                '--assetsDir', '--assetIndex', '--uuid', '--accessToken',
                '--userType', '--versionType', '--userProperties', '--tweakClass'
            }
            
            # For flags that use = notation (like --gameDir=/path), they already have their value
            has_value_inline = "=" in arg
            
            final.append(arg)
            i += 1
            
            # If flag needs argument and doesn't have it inline, grab the next value if available
            if needs_arg and not has_value_inline and i < len(filtered) and not filtered[i].startswith("--"):
                final.append(filtered[i])
                i += 1
        else:
            # This is a bare value - only keep it if it immediately followed a flag
            if final and final[-1].startswith("--") and "=" not in final[-1]:
                final.append(arg)
            # Otherwise skip orphaned values
            i += 1
    
    return " ".join(final)


def _filter_conflicting_classpath_entries(
    classpath_entries: list,
    loader_jars: list,
    preserve_forge_client: bool = True,
) -> list:
    def jar_artifact_name(filename: str) -> str:
        stem = filename[:-4] if filename.endswith(".jar") else filename
        parts = stem.split("-")
        name_parts = []
        for part in parts:
            if part and part[0].isdigit():
                break
            name_parts.append(part)
        return "-".join(name_parts) if name_parts else stem

    loader_artifact_names = set()
    for jar_path in loader_jars:
        name = jar_artifact_name(os.path.basename(jar_path))
        if name:
            loader_artifact_names.add(name)

    if not loader_artifact_names:
        return classpath_entries

    def _is_forge_loader_path(path_str: str) -> bool:
        normalized = path_str.replace("\\", "/").lower().lstrip("./")
        return "loaders/forge/" in normalized

    is_forge_loader = any(_is_forge_loader_path(p) for p in loader_jars)

    filtered = []
    preserved_client = False
    for entry in classpath_entries:
        filename = os.path.basename(entry)
        name = jar_artifact_name(filename)

        if is_forge_loader and preserve_forge_client and filename.lower() == "client.jar":
            if not preserved_client:
                print(colorize_log("[launcher] Preserving vanilla client.jar in classpath for Forge"))
                preserved_client = True
            filtered.append(entry)
            continue

        if name in loader_artifact_names:
            print(colorize_log(f"[launcher] Filtering out conflicting classpath entry: {filename} (loader provides {name})"))
        else:
            filtered.append(entry)

    return filtered


def _get_loader_jars(version_dir: str, loader_type: str, loader_version: str = None) -> list:
    loaders_dir = os.path.join(version_dir, "loaders", loader_type.lower())
    jar_paths = []
    
    if not os.path.isdir(loaders_dir):
        return jar_paths
    
    try:
        version_path = None
        if loader_version:
            version_path = os.path.join(loaders_dir, loader_version)
            if not os.path.isdir(version_path):
                return jar_paths
        else:
            versions = [d for d in sorted(os.listdir(loaders_dir)) if os.path.isdir(os.path.join(loaders_dir, d))]
            if not versions:
                return jar_paths
            version_path = os.path.join(loaders_dir, versions[-1])

        if loader_type.lower() == "forge":
            try:
                metadata_dir = os.path.join(version_path, ".metadata")
                version_json_path = os.path.join(metadata_dir, "version.json")
                if os.path.exists(version_json_path):
                    with open(version_json_path, "r", encoding="utf-8") as f:
                        version_data = json.load(f)

                    libraries = version_data.get("libraries", []) or []
                    metadata_main_class = (version_data.get("mainClass") or "").strip().lower()
                    has_modlauncher_lib = any(
                        isinstance(lib, dict) and ":modlauncher:" in (lib.get("name") or "")
                        for lib in libraries
                    )
                    has_bootstrap_main = (
                        metadata_main_class.startswith("cpw.mods.bootstraplauncher")
                        or metadata_main_class.startswith("net.minecraftforge.bootstrap")
                    )

                    if has_modlauncher_lib or has_bootstrap_main:
                        ordered_paths = []
                        seen_paths = set()
                        forge_loader_version = os.path.basename(version_path)
                        libraries_root_rel = os.path.join(
                            "loaders", "forge", forge_loader_version, "libraries"
                        )

                        def _add_rel_if_exists(rel_path: str):
                            rel_norm = rel_path.replace("\\", "/")
                            if rel_norm in seen_paths:
                                return
                            abs_path = os.path.join(version_dir, rel_path)
                            if os.path.isfile(abs_path):
                                seen_paths.add(rel_norm)
                                ordered_paths.append(rel_norm)

                        for lib in libraries:
                            if not isinstance(lib, dict):
                                continue

                            downloads = lib.get("downloads") or {}
                            artifact = downloads.get("artifact") or {}
                            artifact_path = artifact.get("path")
                            if artifact_path:
                                _add_rel_if_exists(os.path.join(libraries_root_rel, artifact_path))
                                continue

                            lib_name = lib.get("name", "")
                            parts = lib_name.split(":")
                            if len(parts) < 3:
                                continue
                            group, artifact_name, artifact_version = parts[0], parts[1], parts[2]
                            classifier = ""
                            if len(parts) >= 4:
                                classifier = parts[3].split("@", 1)[0]
                            artifact_dir = os.path.join(
                                libraries_root_rel,
                                group.replace(".", os.sep),
                                artifact_name,
                                artifact_version
                            )
                            artifact_dir_abs = os.path.join(version_dir, artifact_dir)
                            if not os.path.isdir(artifact_dir_abs):
                                continue

                            jar_files = [
                                n for n in os.listdir(artifact_dir_abs)
                                if n.endswith(".jar")
                            ]
                            if not jar_files:
                                continue

                            # Prefer exact classifier match when provided (e.g. forge:...:universal/client).
                            if classifier:
                                expected_name = f"{artifact_name}-{artifact_version}-{classifier}.jar"
                                if expected_name in jar_files:
                                    _add_rel_if_exists(os.path.join(artifact_dir, expected_name))
                                    continue

                            # If no classifier (or exact file not found), choose standard artifact jar first.
                            base_name = f"{artifact_name}-{artifact_version}.jar"
                            if base_name in jar_files:
                                _add_rel_if_exists(os.path.join(artifact_dir, base_name))
                                continue

                            # Last resort: deterministic fallback.
                            jar_files.sort()
                            _add_rel_if_exists(os.path.join(artifact_dir, jar_files[0]))

                        if ordered_paths:
                            print(colorize_log(
                                f"[launcher] Using {len(ordered_paths)} Forge ModLauncher libraries from metadata order"
                            ))
                            return ordered_paths
            except Exception as e:
                print(colorize_log(f"[launcher] Warning: Could not build Forge metadata classpath, falling back to scan: {e}"))
        
        # For Forge loaders, validate against bootstrap-shim.list
        bootstrap_shim_path = os.path.join(version_path, "bootstrap-shim.list")
        bootstrap_libs = set()
        
        if loader_type.lower() == "forge" and os.path.exists(bootstrap_shim_path):
            try:
                with open(bootstrap_shim_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        # Each line format: path#hash
                        # Example: net/minecraftforge/fmlcore/1.0.0/fmlcore-1.0.0.jar#abc123...
                        if "#" in line:
                            lib_path = line.split("#")[0]
                            # Extract just the filename from Maven path
                            lib_name = os.path.basename(lib_path)
                            bootstrap_libs.add(lib_name)
                
                if bootstrap_libs:
                    print(colorize_log(f"[launcher] Loaded bootstrap-shim.list with {len(bootstrap_libs)} libraries"))
            except Exception as e:
                print(colorize_log(f"[launcher] Warning: Could not parse bootstrap-shim.list: {e}"))
        
        # Find all JAR files in this loader version folder (recursively)
        found_jars = []
        missing_libs = []

        for root, dirs, files in os.walk(version_path):
            for filename in sorted(files):
                if not filename.endswith('.jar'):
                    continue
                fullpath = os.path.join(root, filename)
                # Compute relative path from the version_dir so _join_classpath can resolve it
                rel_from_version = os.path.relpath(fullpath, version_dir)
                # Track discovery by basename for bootstrap checks
                found_jars.append(filename)

                # Normalize to forward slashes for consistency
                rel_path = rel_from_version.replace('\\', '/')
                jar_paths.append(rel_path)

        # Diagnostic logging for JAR discovery (especially for troubleshooting old Forge versions)
        if loader_type.lower() == "forge" and len(found_jars) < 5:
            print(colorize_log(f"[launcher] Debug: Found {len(found_jars)} JAR files in {os.path.basename(version_path)}:"))
            for jar in found_jars[:10]:
                print(f"  [launcher]   - {jar}")

        # Check for missing bootstrap libraries
        if bootstrap_libs:
            for expected_lib in sorted(bootstrap_libs):
                if expected_lib not in found_jars:
                    missing_libs.append(expected_lib)

            if missing_libs:
                print(colorize_log(f"[launcher] Warning: {len(missing_libs)} libraries from bootstrap-shim.list are missing:"))
                for lib in missing_libs[:5]:  # Show first 5
                    print(f"  [launcher] Missing: {lib}")
                if len(missing_libs) > 5:
                    print(f"  [launcher] ... and {len(missing_libs)-5} more")
            else:
                print(colorize_log(f"[launcher] All {len(bootstrap_libs)} bootstrap libraries found"))
        
        # For Forge, also include Maven-structured libraries from version_dir/libraries/
        # These were downloaded and placed there by the installer
        if loader_type.lower() == "forge":
            maven_libs_path = os.path.join(version_path, "libraries")
            maven_libs_count = 0
            if os.path.isdir(maven_libs_path):
                for root, dirs, files in os.walk(maven_libs_path):
                    for filename in sorted(files):
                        if filename.endswith('.jar'):
                            fullpath = os.path.join(root, filename)
                            # Compute relative path from version_dir (need to go through loader directory)
                            rel_from_version = os.path.relpath(fullpath, version_dir)
                            # Normalize to forward slashes
                            rel_path = rel_from_version.replace('\\', '/')
                            if rel_path not in jar_paths:
                                jar_paths.append(rel_path)
                                maven_libs_count += 1
            
            if maven_libs_count > 0:
                print(colorize_log(f"[launcher] Added {maven_libs_count} Maven libraries from loader/libraries/"))

        print(colorize_log(f"[launcher] Using {len(jar_paths)} {loader_type} libraries for classpath"))
        
    except Exception as e:
        print(colorize_log(f"[launcher] Error scanning loader JARs: {e}"))
    
    return jar_paths


# new helpers for version & compatibility checking -------------------------------------------------

def _parse_version(version_str: str) -> tuple:
    parts = re.split(r'[.\-+]', version_str)
    result = []
    for part in parts:
        # Try to convert to int, otherwise keep as string
        try:
            result.append(int(part))
        except ValueError:
            result.append(part)
    return tuple(result)


def _get_loader_version(version_dir: str, loader_type: str) -> str:
    loaders_dir = os.path.join(version_dir, "loaders", loader_type.lower())
    if not os.path.isdir(loaders_dir):
        return ""
    versions = [d for d in os.listdir(loaders_dir) if os.path.isdir(os.path.join(loaders_dir, d))]
    if not versions:
        return ""
    versions.sort(key=_parse_version)
    return versions[-1]


def _get_mods_dir(version_dir: str) -> str:
    global_settings = load_global_settings()
    storage_mode = global_settings.get("storage_directory", "global").lower()
    if storage_mode == "version":
        return os.path.join(version_dir, "data", "mods")
    system = platform.system().lower()
    if "windows" in system:
        user_profile = os.environ.get("APPDATA")
        return os.path.join(user_profile, ".minecraft", "mods")
    else:
        return os.path.expanduser(os.path.join("~", ".minecraft", "mods"))


def _version_satisfies(loader_ver: str, requirement: str) -> bool:
    if not requirement or requirement.strip() == "*":
        return True

    for part in requirement.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^([<>!=]+)\s*(.+)$", part)
        if m:
            op, ver = m.groups()
        else:
            op, ver = "==", part
        try:
            left = _parse_version(loader_ver)
            right = _parse_version(ver)
        except Exception:
            # if parsing fails, be permissive
            continue
        if op in ("==", "=") and not (left == right):
            return False
        if op == ">=" and not (left >= right):
            return False
        if op == "<=" and not (left <= right):
            return False
        if op == ">" and not (left > right):
            return False
        if op == "<" and not (left < right):
            return False
        if op == "!=" and not (left != right):
            return False
    return True


def check_mod_loader_compatibility(version_dir: str, loader_type: str) -> list:
    issues = []
    loader_ver = _get_loader_version(version_dir, loader_type)
    if not loader_ver:
        return issues

    mods_dir = _get_mods_dir(version_dir)
    if not os.path.isdir(mods_dir):
        return issues

    for fname in os.listdir(mods_dir):
        if not fname.endswith(".jar"):
            continue
        path = os.path.join(mods_dir, fname)
        try:
            with zipfile.ZipFile(path, 'r') as jar:
                if 'fabric.mod.json' not in jar.namelist():
                    continue
                data = jar.read('fabric.mod.json').decode('utf-8')
                modinfo = json.loads(data)
        except Exception:
            continue
        deps = modinfo.get('depends', {}) or {}
        req = deps.get('fabricloader') or deps.get('fabric-loader') or deps.get('fabricloader')
        if req and not _version_satisfies(loader_ver, req):
            mod_id = modinfo.get('id', '<unknown>')
            issues.append((mod_id, fname, req))
            print(colorize_log(f"[launcher] compatibility issue: mod {mod_id} ({fname}) requires loader {req}, current is {loader_ver}"))
    return issues


def _get_jar_main_class(jar_path: str) -> str:
    try:
        with zipfile.ZipFile(jar_path, 'r') as jar:
            # Try to read the manifest
            manifest_data = jar.read('META-INF/MANIFEST.MF').decode('utf-8')
            # Look for Main-Class line (handles line continuations)
            lines = manifest_data.split('\n')
            for i, line in enumerate(lines):
                if line.startswith('Main-Class:'):
                    main_class = line[len('Main-Class:'):].strip()
                    # Handle multi-line values (continuation lines start with space)
                    while i + 1 < len(lines) and lines[i + 1].startswith(' '):
                        main_class += lines[i + 1].strip()
                        i += 1
                    return main_class
    except Exception as e:
        pass
    
    return ""


def _compare_mc_versions(version_a: str, version_b: str) -> int:
    try:
        def parse_version(v):
            return tuple(map(int, v.split('.')))
        
        a_parts = parse_version(version_a)
        b_parts = parse_version(version_b)
        
        if a_parts < b_parts:
            return -1
        elif a_parts > b_parts:
            return 1
        else:
            return 0
    except Exception:
        # If parsing fails, do string comparison
        if version_a < version_b:
            return -1
        elif version_a > version_b:
            return 1
        else:
            return 0


def _normalize_forge_mc_version(mc_version: str) -> str:
    value = (mc_version or "").strip().strip("'\"")
    if not value:
        return ""

    # Common format in Forge metadata: "1.13.2-forge-25.0.223"
    if "-forge-" in value:
        return value.split("-forge-", 1)[0]

    # Fallback for "1.13.2-25.0.223" style composite versions.
    if "-" in value:
        candidate = value.split("-", 1)[0]
        if re.match(r"^\d+\.\d+(?:\.\d+)?$", candidate):
            return candidate

    return value


def _normalize_forge_mcp_version(mcp_version: str, mc_version: str = "") -> str:
    value = (mcp_version or "").strip().strip("'\"")
    if not value:
        return ""

    mc_ver = _normalize_forge_mc_version(mc_version)
    if mc_ver and value.startswith(mc_ver + "-"):
        value = value[len(mc_ver) + 1:]

    return value


def _set_or_append_cli_arg(args: list, flag: str, value: str) -> None:
    for i, arg in enumerate(args):
        if arg == flag and i + 1 < len(args):
            args[i + 1] = value
            return
        if arg.startswith(flag + "="):
            args[i] = f"{flag}={value}"
            return
    args.extend([flag, value])


def _prune_forge_root_jars_for_modlauncher(classpath_entries: list) -> list:
    pruned = []
    removed = []

    for entry in classpath_entries:
        norm = entry.replace("\\", "/").lower().lstrip("./")
        base = os.path.basename(norm)
        is_root_forge_loader_jar = (
            norm.startswith("loaders/forge/")
            and "/libraries/" not in norm
            and base.startswith("forge-")
            and base.endswith(".jar")
        )
        if is_root_forge_loader_jar:
            removed.append(entry)
            continue
        pruned.append(entry)

    if removed:
        print(colorize_log(f"[launcher] Removed {len(removed)} root Forge loader JAR(s) for ModLauncher classpath hygiene"))

    return pruned


def _prune_vanilla_client_jar(classpath_entries: list) -> list:
    pruned = []
    removed = 0
    for entry in classpath_entries:
        norm = entry.replace("\\", "/").lower().lstrip("./")
        if norm == "client.jar":
            removed += 1
            continue
        pruned.append(entry)
    if removed:
        print(colorize_log(f"[launcher] Removed vanilla client.jar from classpath for Forge bootstrap launch"))
    return pruned


def _get_loader_main_class(version_dir: str, loader_type: str, loader_version: str = None) -> str:
    loader_type_lower = loader_type.lower()
    
    if loader_type_lower == "forge":
        # Determine loader version path
        loaders_dir = os.path.join(version_dir, "loaders", "forge")
        version_path = None
        if loader_version:
            version_path = os.path.join(loaders_dir, loader_version)
        else:
            # pick latest
            try:
                versions = [d for d in sorted(os.listdir(loaders_dir)) if os.path.isdir(os.path.join(loaders_dir, d))]
                if versions:
                    version_path = os.path.join(loaders_dir, versions[-1])
            except Exception:
                version_path = None

        # Newer Forge declares the intended entrypoint in .metadata/version.json.
        try:
            if version_path and os.path.isdir(version_path):
                version_json_path = os.path.join(version_path, ".metadata", "version.json")
                if os.path.exists(version_json_path):
                    with open(version_json_path, "r", encoding="utf-8") as f:
                        metadata_version = json.load(f)
                    declared_main = (metadata_version.get("mainClass") or "").strip()
                    if declared_main:
                        print(f"[launcher] Using Forge mainClass from metadata: {declared_main}")
                        return declared_main
        except Exception as e:
            print(f"[launcher] Warning: Could not read Forge metadata mainClass: {e}")

        version_dir_name = os.path.basename(version_dir.rstrip(os.sep))
        legacy_launchwrapper_only = False
        try:
            vparts = version_dir_name.split('.')
            vmajor = int(vparts[0]) if len(vparts) > 0 else 0
            vminor = int(vparts[1]) if len(vparts) > 1 else 0
            legacy_launchwrapper_only = (vmajor == 1 and vminor < 13)
        except Exception:
            legacy_launchwrapper_only = False

        # Helper: check whether any JAR contains the given class path
        def _jar_contains_class(search_class_path: str) -> bool:
            try:
                if not (version_path and os.path.isdir(version_path)):
                    return False
                for root, dirs, files in os.walk(version_path):
                    for fname in files:
                        if not fname.endswith('.jar'):
                            continue
                        jarp = os.path.join(root, fname)
                        try:
                            with zipfile.ZipFile(jarp, 'r') as jar:
                                if search_class_path in jar.namelist():
                                    return True
                        except Exception:
                            continue
            except Exception:
                return False
            return False

        # If we can inspect the JARs, look for a Tweak-Class entry in any manifest.
        # Presence of a Tweak-Class typically indicates a LaunchWrapper-based bootstrap (pre-1.13).
        if version_path and os.path.isdir(version_path):
            try:
                for root, dirs, files in os.walk(version_path):
                    for fname in files:
                        if not fname.endswith('.jar'):
                            continue
                        jarp = os.path.join(root, fname)
                        try:
                            with zipfile.ZipFile(jarp, 'r') as jar:
                                try:
                                    mf = jar.read('META-INF/MANIFEST.MF').decode('utf-8')
                                except Exception:
                                    mf = ''
                                if 'Tweak-Class:' in mf:
                                    # If Tweak-Class found, prefer LaunchWrapper main (pre-1.13)
                                    if _jar_contains_class('net/minecraft/launchwrapper/Launch.class'):
                                        return 'net.minecraft.launchwrapper.Launch'
                                    else:
                                        print('[launcher] Detected Tweak-Class but LaunchWrapper class not found in extracted JARs')
                        except Exception:
                            continue
            except Exception:
                pass

        if legacy_launchwrapper_only:
            if not _legacy_forge_has_fml(version_dir, loader_version):
                print('[launcher] Pre-FML Forge detected (no cpw/mods/fml/ classes) — launching directly')
                return 'net.minecraft.client.Minecraft'

            if _jar_contains_class('net/minecraft/launchwrapper/Launch.class'):
                print('[launcher] Legacy Forge version detected - forcing LaunchWrapper main class')
                return 'net.minecraft.launchwrapper.Launch'
            # Even when launchwrapper isn't directly detected (incomplete extraction
            # or transformed jars), legacy Forge should not route to ModLauncher.
            print('[launcher] Legacy Forge version detected - using LaunchWrapper fallback')
            return 'net.minecraft.launchwrapper.Launch'

        # Detect ModLauncher (used by Forge 1.13+) by looking for a ModLauncher main-class
        if version_path and os.path.isdir(version_path):
            # For Forge 1.17+, check the shim JAR manifest for the main class
            shim_main = None
            for fname in os.listdir(version_path):
                if fname.endswith('-shim.jar'):
                    try:
                        shim_path = os.path.join(version_path, fname)
                        with zipfile.ZipFile(shim_path, 'r') as jar:
                            try:
                                mf = jar.read('META-INF/MANIFEST.MF').decode('utf-8')
                                # Look for Main-Class in manifest
                                for line in mf.split('\n'):
                                    if 'Main-Class:' in line:
                                        shim_main = line.split('Main-Class:')[1].strip()
                                        print(f'[launcher] Found Forge shim Main-Class: {shim_main}')
                                        return shim_main
                            except Exception:
                                pass
                    except Exception:
                        pass
            
            # If shim doesn't have manifest, check if ModLauncher class exists
            if _jar_contains_class('cpw/mods/modlauncher/Launcher.class'):
                print(f'[launcher] Found ModLauncher class, using ModLauncher')
                return 'cpw.mods.modlauncher.Launcher'
            
            # Fallback: search in manifests for ModLauncher indicators
            try:
                for root, dirs, files in os.walk(version_path):
                    for fname in files:
                        if not fname.endswith('.jar'):
                            continue
                        jarp = os.path.join(root, fname)
                        try:
                            with zipfile.ZipFile(jarp, 'r') as jar:
                                try:
                                    mf = jar.read('META-INF/MANIFEST.MF').decode('utf-8')
                                except Exception:
                                    mf = ''
                                if 'cpw.mods.modlauncher.Launcher' in mf or 'ModLauncher' in mf or 'modlauncher' in mf.lower():
                                    if _jar_contains_class('cpw/mods/modlauncher/Launcher.class'):
                                        return 'cpw.mods.modlauncher.Launcher'
                        except Exception:
                            continue
            except Exception:
                pass

        # Fallback: check extracted service providers for modlauncher service indicators
        try:
            services_dir = os.path.join(version_path, 'META-INF', 'services') if version_path else None
            if services_dir and os.path.isdir(services_dir):
                for svc in os.listdir(services_dir):
                    svc_path = os.path.join(services_dir, svc)
                    try:
                        with open(svc_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            if 'cpw.mods.modlauncher' in content or 'ILaunchHandlerService' in svc or 'ITransformerDiscoveryService' in svc:
                                if _jar_contains_class('cpw/mods/modlauncher/Launcher.class'):
                                    return 'cpw.mods.modlauncher.Launcher'
                    except Exception:
                        continue
        except Exception:
            pass

        try:
            if version_path and os.path.isdir(version_path):
                jars_in_loader = []
                for root, dirs, files in os.walk(version_path):
                    for f in files:
                        if f.endswith('.jar'):
                            jars_in_loader.append(f)
                
                if jars_in_loader and any('forge' in j.lower() for j in jars_in_loader):
                    try:
                        parts = version_dir.split(os.sep)
                        mc_version_str = parts[-1] if len(parts) >= 1 else ""
                        
                        if mc_version_str and mc_version_str[0].isdigit():
                            version_parts = mc_version_str.split('.')
                            major = int(version_parts[0]) if len(version_parts) > 0 else 0
                            minor = int(version_parts[1]) if len(version_parts) > 1 else 0
                            
                            if major > 1 or (major == 1 and minor >= 13):
                                print(f'[launcher] MC version {mc_version_str} detected - using ModLauncher')
                                return 'cpw.mods.modlauncher.Launcher'
                            else:
                                print(f'[launcher] MC version {mc_version_str} detected - using LaunchWrapper')
                                return 'net.minecraft.launchwrapper.Launch'
                    except Exception as e:
                        print(f'[launcher] Could not parse MC version for version detection: {e}')
                    
                    print(f'[launcher] Warning: ModLauncher class not found, but found {len(jars_in_loader)} Forge JARs')
                    print(f'[launcher] Attempting ModLauncher as fallback')
                    return 'cpw.mods.modlauncher.Launcher'
        except Exception:
            pass
        
        return ""
    
    elif loader_type_lower == "fabric":
        return "net.fabricmc.loader.launch.knot.KnotClient"
    
    return ""



def _get_forge_fml_metadata(version_dir: str, loader_version: str = None) -> dict:
    try:
        actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
        if not actual_loader_version:
            return {}
        
        forge_loader_dir = os.path.join(version_dir, "loaders", "forge", actual_loader_version)
        metadata_dir = os.path.join(forge_loader_dir, ".metadata")
        
        metadata = {}
        
        forge_metadata_path = os.path.join(forge_loader_dir, "forge_metadata.json")
        if os.path.exists(forge_metadata_path):
            try:
                with open(forge_metadata_path, 'r', encoding='utf-8') as f:
                    forge_meta = json.load(f)
                if forge_meta.get("mc_version"):
                    metadata["mc_version"] = forge_meta["mc_version"]
                if forge_meta.get("forge_version"):
                    metadata["forge_version"] = forge_meta["forge_version"]
                if forge_meta.get("mcp_version"):
                    mcp_ver = forge_meta["mcp_version"]
                    mc_ver = forge_meta.get("mc_version", "")
                    if mc_ver and mcp_ver.startswith(mc_ver + "-"):
                        mcp_ver = mcp_ver[len(mc_ver) + 1:]
                    metadata["mcp_version"] = mcp_ver
                    print(colorize_log(f"[launcher] Read MCP version from forge_metadata.json: {mcp_ver}"))
            except Exception as e:
                print(colorize_log(f"[launcher] Warning: Could not read forge_metadata.json: {e}"))
        
        version_json_path = os.path.join(metadata_dir, "version.json")
        if os.path.exists(version_json_path):
            try:
                with open(version_json_path, 'r', encoding='utf-8') as f:
                    version_data = json.load(f)
                
                mc_version = version_data.get("id")
                
                if mc_version:
                    metadata["mc_version"] = mc_version
                    if "-forge-" in mc_version:
                        mc_v, forge_v = mc_version.split("-forge-", 1)
                        metadata["mc_version"] = mc_v
                        if forge_v and "forge_version" not in metadata:
                            metadata["forge_version"] = forge_v
                
                if "time" in version_data:
                    pass
                
                libraries = version_data.get("libraries", [])
                for lib in libraries:
                    lib_name = lib.get("name", "")
                    if "net.minecraftforge:forge:" in lib_name or "net.minecraftforge:fmlcore:" in lib_name:
                        parts = lib_name.split(':')
                        if len(parts) >= 3:
                            metadata["forge_group"] = parts[0] or "net.minecraftforge"
                            version_str = parts[2]
                            if "-" in version_str:
                                mc_v, forge_v = version_str.rsplit("-", 1)
                                metadata["mc_version"] = mc_v
                                metadata["forge_version"] = forge_v
                    elif "de.oceanlabs.mcp:mcp_config:" in lib_name or "de.oceanlabs.mcp:mcp_mappings:" in lib_name:
                        parts = lib_name.split(':')
                        if len(parts) >= 3:
                            mcp_ver = parts[2]
                            metadata["mcp_version"] = mcp_ver
                            print(colorize_log(f"[launcher] Extracted MCP Config version: {mcp_ver}"))
                    if "mc_version" in metadata and "forge_version" in metadata and "mcp_version" in metadata:
                        break
                
            except Exception as e:
                print(colorize_log(f"[launcher] Warning: Could not parse version.json: {e}"))
        
        profile_json_path = os.path.join(metadata_dir, "install_profile.json")
        if os.path.exists(profile_json_path) and ("mc_version" not in metadata or "mcp_version" not in metadata):
            try:
                with open(profile_json_path, 'r', encoding='utf-8') as f:
                    profile_data = json.load(f)
                
                raw_version = profile_data.get("version", "")
                if isinstance(raw_version, dict):
                    raw_version = raw_version.get("id", "")
                
                mc_version = profile_data.get("minecraft")
                profile_path = profile_data.get("path", "")
                if isinstance(profile_path, str):
                    parts = profile_path.split(":")
                    if len(parts) >= 2 and parts[0]:
                        metadata["forge_group"] = parts[0]

                forge_version = ""
                if raw_version:
                    if "-forge-" in raw_version:
                        forge_version = raw_version.split("-forge-", 1)[1]
                    elif "-" in raw_version:
                        forge_version = raw_version.split("-", 1)[1]
                
                if mc_version and "mc_version" not in metadata:
                    metadata["mc_version"] = mc_version
                if forge_version and "forge_version" not in metadata:
                    metadata["forge_version"] = forge_version
                
                if "mcp_version" not in metadata:
                    profile_data_section = profile_data.get("data", {})
                    mcp_ver = ""

                    raw_mcp = (profile_data_section.get("MCP_VERSION") or {}).get("client", "")
                    if raw_mcp:
                        mcp_ver = raw_mcp.strip("'")

                    if not mcp_ver:
                        raw_srg = (profile_data_section.get("MC_SRG") or {}).get("client", "")
                        if raw_srg:
                            inner = raw_srg.strip("[]")
                            srg_parts = inner.split(":")
                            if len(srg_parts) >= 3:
                                mcp_ver = srg_parts[2]

                    if not mcp_ver:
                        raw_mappings = (profile_data_section.get("MAPPINGS") or {}).get("client", "")
                        if raw_mappings:
                            inner = raw_mappings.strip("[]").split("@")[0]
                            map_parts = inner.split(":")
                            if len(map_parts) >= 3:
                                mcp_ver = map_parts[2]

                    fallback_mc = metadata.get("mc_version") or profile_data.get("minecraft", "")
                    if mcp_ver and fallback_mc and mcp_ver.startswith(fallback_mc + "-"):
                        mcp_ver = mcp_ver[len(fallback_mc) + 1:]

                    if mcp_ver:
                        metadata["mcp_version"] = mcp_ver
                        print(colorize_log(f"[launcher] Read MCP version from install_profile.json: {mcp_ver}"))
                
            except Exception as e:
                print(colorize_log(f"[launcher] Warning: Could not parse install_profile.json: {e}"))
        
        if "forge_version" not in metadata and actual_loader_version:
            metadata["forge_version"] = actual_loader_version
        
        if "forge_group" not in metadata:
            metadata["forge_group"] = "net.minecraftforge"
        
        if "mc_version" not in metadata:
            try:
                parts = version_dir.split(os.sep)
                if len(parts) >= 2:
                    potential_mc_version = parts[-1]
                    if potential_mc_version and potential_mc_version[0].isdigit() and "." in potential_mc_version:
                        metadata["mc_version"] = potential_mc_version
            except Exception:
                pass
        
        if "mc_version" in metadata:
            metadata["mc_version"] = _normalize_forge_mc_version(metadata["mc_version"])

        if "mcp_version" in metadata:
            metadata["mcp_version"] = _normalize_forge_mcp_version(
                metadata["mcp_version"],
                metadata.get("mc_version", "")
            )
        
        return metadata
    
    except Exception as e:
        print(colorize_log(f"[launcher] ERROR extracting Forge FML metadata: {e}"))
        return {}


def _get_forge_metadata_args(version_dir: str, loader_version: str = None, key: str = "game") -> list:
    try:
        actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
        if not actual_loader_version:
            return []

        version_json_path = os.path.join(
            version_dir, "loaders", "forge", actual_loader_version, ".metadata", "version.json"
        )
        if not os.path.exists(version_json_path):
            return []

        with open(version_json_path, "r", encoding="utf-8") as f:
            version_data = json.load(f)

        arg_list = ((version_data.get("arguments") or {}).get(key) or [])
        return [arg for arg in arg_list if isinstance(arg, str)]
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: Could not read Forge metadata {key} arguments: {e}"))
        return []


def _expand_forge_metadata_args(args: list, version_dir: str, loader_version: str = None, version_identifier: str = "") -> list:
    actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
    libraries_dir = os.path.join(version_dir, "loaders", "forge", actual_loader_version, "libraries") if actual_loader_version else ""

    forge_profile_version = ""
    try:
        if actual_loader_version:
            version_json_path = os.path.join(
                version_dir, "loaders", "forge", actual_loader_version, ".metadata", "version.json"
            )
            if os.path.exists(version_json_path):
                with open(version_json_path, "r", encoding="utf-8") as f:
                    version_data = json.load(f)
                forge_profile_version = (version_data.get("id") or "").strip()
    except Exception:
        pass

    if not forge_profile_version and version_identifier:
        mc_ver = _extract_mc_version_string(version_identifier)
        if mc_ver and actual_loader_version:
            forge_profile_version = f"{mc_ver}-forge-{actual_loader_version}"

    replacements = {
        "${library_directory}": libraries_dir.replace("\\", "/"),
        "${classpath_separator}": os.pathsep,
        "${version_name}": forge_profile_version,
    }

    expanded = []
    for arg in args:
        out = arg
        for k, v in replacements.items():
            out = out.replace(k, v)
        expanded.append(out)
    return expanded


def _extract_tweak_class_from_arg_string(arg_str: str) -> str:
    if not isinstance(arg_str, str) or not arg_str.strip():
        return ""
    match = re.search(r"(?:^|\s)--tweakClass\s+([^\s]+)", arg_str)
    if match:
        return match.group(1).strip()
    match = re.search(r"(?:^|\s)--tweakClass=([^\s]+)", arg_str)
    if match:
        return match.group(1).strip()
    return ""


def _extract_tweak_class_from_arg_list(arg_list: list) -> str:
    if not isinstance(arg_list, list):
        return ""
    for idx, arg in enumerate(arg_list):
        if isinstance(arg, str):
            if arg == "--tweakClass" and idx + 1 < len(arg_list) and isinstance(arg_list[idx + 1], str):
                return arg_list[idx + 1].strip()
            if arg.startswith("--tweakClass="):
                return arg.split("=", 1)[1].strip()
    return ""


def _get_forge_tweak_class_from_metadata(version_dir: str, loader_version: str = None) -> str:
    actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
    if not actual_loader_version:
        return ""

    forge_loader_dir = os.path.join(version_dir, "loaders", "forge", actual_loader_version)
    candidate_files = [
        os.path.join(forge_loader_dir, ".metadata", "install_profile.json"),
        os.path.join(forge_loader_dir, ".metadata", "version.json"),
        os.path.join(forge_loader_dir, "forge_metadata.json"),
    ]

    for file_path in candidate_files:
        if not os.path.exists(file_path):
            continue
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        arg_strings = []
        arg_lists = []

        root_minecraft_args = data.get("minecraftArguments")
        if isinstance(root_minecraft_args, str):
            arg_strings.append(root_minecraft_args)

        root_args = data.get("arguments")
        if isinstance(root_args, dict):
            game_args = root_args.get("game")
            if isinstance(game_args, list):
                arg_lists.append(game_args)

        version_info = data.get("versionInfo")
        if isinstance(version_info, dict):
            vi_minecraft_args = version_info.get("minecraftArguments")
            if isinstance(vi_minecraft_args, str):
                arg_strings.append(vi_minecraft_args)

            vi_args = version_info.get("arguments")
            if isinstance(vi_args, dict):
                vi_game_args = vi_args.get("game")
                if isinstance(vi_game_args, list):
                    arg_lists.append(vi_game_args)

        for arg_string in arg_strings:
            tweak = _extract_tweak_class_from_arg_string(arg_string)
            if tweak:
                return tweak

        for arg_list in arg_lists:
            tweak = _extract_tweak_class_from_arg_list(arg_list)
            if tweak:
                return tweak

    return ""


def _sha1_file(path: str) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().lower()


def _is_legacy_forge_runtime(version_identifier: str) -> bool:
    major, minor = _parse_mc_version(version_identifier)
    return major == 1 and minor is not None and minor < 6


def _legacy_forge_has_fml(version_dir: str, loader_version: str = None) -> bool:
    actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
    if not actual_loader_version:
        return False

    forge_loader_dir = os.path.join(version_dir, "loaders", "forge", actual_loader_version)
    if not os.path.isdir(forge_loader_dir):
        return False

    try:
        for filename in os.listdir(forge_loader_dir):
            if not filename.endswith(".jar"):
                continue
            lower_name = filename.lower()
            if not (
                lower_name.startswith("forge-")
                or lower_name.startswith("fml-")
                or lower_name.startswith("minecraftforge-")
            ):
                continue
            jar_path = os.path.join(forge_loader_dir, filename)
            try:
                with zipfile.ZipFile(jar_path, "r") as jar:
                    if any(name.startswith("cpw/mods/fml/") for name in jar.namelist()):
                        return True
            except Exception:
                continue
    except Exception:
        return False

    return False


def _legacy_forge_requires_modloader(version_dir: str, loader_version: str = None) -> bool:
    version_name = os.path.basename(version_dir.rstrip(os.sep))
    major, minor = _parse_mc_version(version_name)
    if not (major == 1 and minor is not None and minor < 6):
        return False
    return not _legacy_forge_has_fml(version_dir, loader_version)


def _is_modloader_runtime_jar(jar_path: str) -> bool:
    try:
        with zipfile.ZipFile(jar_path, "r") as jar:
            names = set(jar.namelist())
            return "BaseMod.class" in names and "ModLoader.class" in names
    except Exception:
        return False


def _find_modloader_runtime_jar(version_dir: str) -> str:
    candidates = []

    # Primary location: root version jars (manual drop-in)
    try:
        for filename in os.listdir(version_dir):
            if filename.endswith(".jar") and "modloader" in filename.lower():
                candidates.append(os.path.join(version_dir, filename))
    except Exception:
        pass

    # Optional location: loaders/modloader/<version>/*
    modloader_root = os.path.join(version_dir, "loaders", "modloader")
    if os.path.isdir(modloader_root):
        for root, dirs, files in os.walk(modloader_root):
            for filename in files:
                if filename.endswith(".jar"):
                    candidates.append(os.path.join(root, filename))

    seen = set()
    for jar_path in candidates:
        if jar_path in seen:
            continue
        seen.add(jar_path)
        if _is_modloader_runtime_jar(jar_path):
            return jar_path

    return ""


def _has_modloader_runtime(version_dir: str) -> bool:
    # Either client.jar already has runtime classes merged, or a separate
    # ModLoader runtime jar is available for merge.
    client_jar = os.path.join(version_dir, "client.jar")
    if os.path.isfile(client_jar) and _is_modloader_runtime_jar(client_jar):
        return True
    return bool(_find_modloader_runtime_jar(version_dir))


def _find_forge_core_jar(version_dir: str, loader_version: str = None) -> str:
    actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
    if not actual_loader_version:
        return ""

    forge_loader_dir = os.path.join(version_dir, "loaders", "forge", actual_loader_version)
    if not os.path.isdir(forge_loader_dir):
        return ""

    preferred = []
    fallback = []
    for filename in sorted(os.listdir(forge_loader_dir)):
        if not filename.endswith(".jar"):
            continue
        full_path = os.path.join(forge_loader_dir, filename)
        lower_name = filename.lower()
        if "universal" in lower_name and ("minecraftforge" in lower_name or lower_name.startswith("forge-")):
            preferred.append(full_path)
        elif "minecraftforge" in lower_name or lower_name.startswith("forge-"):
            fallback.append(full_path)

    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    return ""


def _read_fml_version_properties(version_dir: str, loader_version: str = None) -> dict:
    forge_jar = _find_forge_core_jar(version_dir, loader_version)
    if not forge_jar:
        return {}

    try:
        with zipfile.ZipFile(forge_jar, "r") as jar:
            try:
                raw = jar.read("fmlversion.properties").decode("utf-8", errors="replace")
            except KeyError:
                return {}
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: Could not read fmlversion.properties: {e}"))
        return {}

    props = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key.strip()] = value.strip()
    return props


def _legacy_forge_lib_copy_targets(version_dir: str, loader_version: str = None) -> list:
    actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
    if not actual_loader_version:
        return []

    def _fallback_targets_from_filesystem() -> list:
        root = os.path.join(version_dir, "loaders", "forge", actual_loader_version)
        if not os.path.isdir(root):
            return []

        targets = []
        seen = set()
        wanted_prefixes = {
            "argo-": "argo",
            "argo-small-": "argo",
            "guava-": "guava",
            "asm-all-": "asm-all",
            "bcprov-jdk15on-": "bcprov-jdk15on",
            "scala-library-": "scala-library",
            "scala-library.jar": "scala-library",
        }

        for walk_root, _, files in os.walk(root):
            for filename in files:
                if not filename.endswith(".jar"):
                    continue

                lowered = filename.lower()
                matched_kind = None
                for prefix, kind in wanted_prefixes.items():
                    if lowered == prefix or lowered.startswith(prefix):
                        matched_kind = kind
                        break
                if not matched_kind:
                    continue

                src = os.path.join(walk_root, filename)
                if matched_kind == "scala-library":
                    dst = "scala-library.jar"
                else:
                    dst = filename

                key = (matched_kind, os.path.normcase(src))
                if key in seen:
                    continue
                seen.add(key)
                targets.append((src, dst))

        return targets

    profile_path = os.path.join(
        version_dir,
        "loaders",
        "forge",
        actual_loader_version,
        ".metadata",
        "install_profile.json",
    )
    if not os.path.exists(profile_path):
        return _fallback_targets_from_filesystem()

    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile_data = json.load(f)
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: Could not parse legacy Forge install_profile.json: {e}"))
        return _fallback_targets_from_filesystem()

    libraries = ((profile_data.get("versionInfo") or {}).get("libraries") or [])
    targets = []
    wanted = {
        ("net.sourceforge.argo", "argo"),
        ("com.google.guava", "guava"),
        ("org.ow2.asm", "asm-all"),
        ("org.bouncycastle", "bcprov-jdk15on"),
        ("org.scala-lang", "scala-library"),
    }

    for lib in libraries:
        lib_name = lib.get("name", "") if isinstance(lib, dict) else str(lib)
        parts = lib_name.split(":")
        if len(parts) < 3:
            continue

        group, artifact, version = parts[0], parts[1], parts[2]
        if (group, artifact) not in wanted:
            continue

        src_path = os.path.join(
            version_dir,
            "loaders",
            "forge",
            actual_loader_version,
            "libraries",
            group.replace(".", os.sep),
            artifact,
            version,
            f"{artifact}-{version}.jar",
        )
        if not os.path.exists(src_path):
            continue

        if group == "net.sourceforge.argo" and artifact == "argo":
            dst_name = f"argo-small-{version.replace('-small', '')}.jar" if version.endswith("-small") else f"argo-{version}.jar"
        elif group == "org.scala-lang" and artifact == "scala-library":
            dst_name = "scala-library.jar"
        else:
            dst_name = f"{artifact}-{version}.jar"

        targets.append((src_path, dst_name))

    if targets:
        return targets

    return _fallback_targets_from_filesystem()


def _download_legacy_forge_file(dest_path: str, file_name: str, expected_sha1: str) -> bool:
    candidate_urls = [
        f"https://web.archive.org/web/20200830040255if_/http://files.minecraftforge.net/fmllibs/{file_name}",
        f"https://files.minecraftforge.net/fmllibs/{file_name}",
        f"http://files.minecraftforge.net/fmllibs/{file_name}",
    ]

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    for url in candidate_urls:
        tmp_path = None
        try:
            print(colorize_log(f"[launcher] Downloading legacy Forge support file: {url}"))
            fd, tmp_path = tempfile.mkstemp(prefix="legacy_forge_", suffix=".tmp")
            os.close(fd)

            request = urllib.request.Request(
                url,
                headers={"User-Agent": "Histolauncher/1.0"},
            )
            with urllib.request.urlopen(request, timeout=30) as response, open(tmp_path, "wb") as out:
                shutil.copyfileobj(response, out)

            actual_sha1 = _sha1_file(tmp_path)
            if expected_sha1 and actual_sha1.lower() != expected_sha1.lower():
                print(colorize_log(
                    f"[launcher] Warning: Legacy support file checksum mismatch for {file_name}: expected {expected_sha1}, got {actual_sha1}"
                ))
                continue

            shutil.move(tmp_path, dest_path)
            tmp_path = None
            print(colorize_log(f"[launcher] Cached legacy Forge support file: {os.path.basename(dest_path)}"))
            return True
        except Exception as e:
            print(colorize_log(f"[launcher] Warning: Could not download {file_name} from {url}: {e}"))
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    return False


def _prepare_legacy_forge_runtime_files(version_dir: str, game_dir: str, loader_version: str = None) -> None:
    actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
    if not actual_loader_version or not game_dir:
        return

    lib_dir = os.path.join(game_dir, "lib")
    os.makedirs(lib_dir, exist_ok=True)

    for src_path, dst_name in _legacy_forge_lib_copy_targets(version_dir, actual_loader_version):
        dst_path = os.path.join(lib_dir, dst_name)
        try:
            if os.path.exists(dst_path):
                if _sha1_file(dst_path) == _sha1_file(src_path):
                    continue
            shutil.copy2(src_path, dst_path)
            print(colorize_log(f"[launcher] Seeded legacy FML library: {dst_name}"))
        except Exception as e:
            print(colorize_log(f"[launcher] Warning: Could not seed legacy FML library {dst_name}: {e}"))

    fml_props = _read_fml_version_properties(version_dir, actual_loader_version)
    mc_version = fml_props.get("fmlbuild.mcversion", "").strip()
    deobf_hash = fml_props.get("fmlbuild.deobfuscation.hash", "").strip().lower()
    if not mc_version or not deobf_hash:
        return

    deobf_name = f"deobfuscation_data_{mc_version}.zip"
    deobf_dest = os.path.join(lib_dir, deobf_name)
    try:
        if os.path.exists(deobf_dest) and _sha1_file(deobf_dest) == deobf_hash:
            print(colorize_log(f"[launcher] Legacy deobfuscation data already present: {deobf_name}"))
            return
    except Exception:
        pass

    cache_dir = os.path.join(version_dir, "loaders", "forge", actual_loader_version, ".legacy_fml")
    os.makedirs(cache_dir, exist_ok=True)
    cached_deobf = os.path.join(cache_dir, deobf_name)

    cached_valid = False
    if os.path.exists(cached_deobf):
        try:
            cached_valid = _sha1_file(cached_deobf) == deobf_hash
        except Exception:
            cached_valid = False

    if not cached_valid:
        cached_valid = _download_legacy_forge_file(cached_deobf, deobf_name, deobf_hash)

    if cached_valid:
        try:
            shutil.copy2(cached_deobf, deobf_dest)
            print(colorize_log(f"[launcher] Seeded legacy deobfuscation data: {deobf_name}"))
        except Exception as e:
            print(colorize_log(f"[launcher] Warning: Could not place legacy deobfuscation data: {e}"))


def _prepare_legacy_assets_directory(version_identifier: str, game_dir: str, meta: dict) -> str:
    if not game_dir:
        return ""

    asset_index_name = (meta.get("asset_index") or "").strip()
    if not asset_index_name:
        return ""

    major, minor = _parse_mc_version(version_identifier)
    if major != 1 or minor is None or minor >= 6:
        return ""

    base_dir = get_base_dir()
    index_path = os.path.join(base_dir, "assets", "indexes", f"{asset_index_name}.json")
    if not os.path.exists(index_path):
        print(colorize_log(f"[launcher] Warning: Legacy asset index not found: {index_path}"))
        return ""

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            index_data = json.load(f)
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: Could not read legacy asset index {asset_index_name}: {e}"))
        return ""

    objects = index_data.get("objects") or {}
    if not isinstance(objects, dict) or not objects:
        print(colorize_log(f"[launcher] Warning: Legacy asset index {asset_index_name} has no objects"))
        return ""

    staged_assets_dir = os.path.join(game_dir, "resources")
    os.makedirs(staged_assets_dir, exist_ok=True)

    copied_count = 0
    linked_count = 0
    missing_count = 0
    objects_root = os.path.join(base_dir, "assets", "objects")

    for rel_path, obj in objects.items():
        if not isinstance(obj, dict):
            continue

        obj_hash = (obj.get("hash") or "").strip().lower()
        obj_size = int(obj.get("size") or 0)
        if len(obj_hash) < 2:
            continue

        src_path = os.path.join(objects_root, obj_hash[:2], obj_hash)
        if not os.path.exists(src_path):
            missing_count += 1
            continue

        dest_path = os.path.join(staged_assets_dir, rel_path.replace("/", os.sep))
        dest_dir = os.path.dirname(dest_path)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)

        try:
            if os.path.exists(dest_path) and os.path.getsize(dest_path) == obj_size:
                continue
        except OSError:
            pass

        try:
            if os.path.exists(dest_path):
                os.remove(dest_path)
        except OSError:
            pass

        try:
            os.link(src_path, dest_path)
            linked_count += 1
        except OSError:
            try:
                shutil.copy2(src_path, dest_path)
                copied_count += 1
            except Exception:
                missing_count += 1

    print(colorize_log(
        f"[launcher] Prepared legacy assets in {staged_assets_dir} "
        f"(linked {linked_count}, copied {copied_count}, missing {missing_count})"
    ))
    return staged_assets_dir


def _prepare_legacy_client_resources(version_dir: str, staged_assets_dir: str) -> None:
    if not staged_assets_dir:
        return

    client_jar = os.path.join(version_dir, "client.jar")
    if not os.path.exists(client_jar):
        return

    extracted_count = 0
    skipped_count = 0

    try:
        with zipfile.ZipFile(client_jar, "r") as jar:
            for entry in jar.infolist():
                name = entry.filename
                if entry.is_dir():
                    continue
                if name.startswith("META-INF/") or name.endswith(".class"):
                    continue

                dest_path = os.path.join(staged_assets_dir, name.replace("/", os.sep))
                dest_dir = os.path.dirname(dest_path)
                if dest_dir:
                    os.makedirs(dest_dir, exist_ok=True)

                try:
                    if os.path.exists(dest_path) and os.path.getsize(dest_path) == entry.file_size:
                        skipped_count += 1
                        continue
                except OSError:
                    pass

                with jar.open(entry, "r") as src, open(dest_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted_count += 1
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: Could not prepare legacy client resources: {e}"))
        return

    print(colorize_log(
        f"[launcher] Prepared legacy client.jar resources in {staged_assets_dir} "
        f"(extracted {extracted_count}, reused {skipped_count})"
    ))


def _normalize_legacy_language_code(lang_code: str) -> str:
    value = (lang_code or "").strip()
    if not value:
        return "en_US"

    # Legacy Minecraft expects locale-like codes (e.g. en_US), while
    # newer options.txt commonly stores lowercase variants (e.g. en_us).
    value = value.replace("-", "_")
    parts = value.split("_")
    if len(parts) >= 2 and parts[0] and parts[1]:
        return f"{parts[0].lower()}_{parts[1].upper()}"
    return value


def _prepare_legacy_options_file(version_identifier: str, game_dir: str) -> None:
    major, minor = _parse_mc_version(version_identifier)
    if major != 1 or minor is None or minor >= 6:
        return

    if not game_dir:
        return

    options_path = os.path.join(game_dir, "options.txt")
    if not os.path.exists(options_path):
        try:
            os.makedirs(game_dir, exist_ok=True)
            with open(options_path, "w", encoding="utf-8") as f:
                f.write("lang:en_US\n")
            print(colorize_log("[launcher] Created legacy options.txt with lang:en_US"))
        except Exception as e:
            print(colorize_log(f"[launcher] Warning: Could not create legacy options.txt: {e}"))
        return

    try:
        with open(options_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: Could not read options.txt for legacy normalization: {e}"))
        return

    changed = False
    found_lang = False
    normalized_lines = []

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if line.startswith("lang:"):
            found_lang = True
            current = line.split(":", 1)[1]
            normalized = _normalize_legacy_language_code(current)
            if normalized != current:
                changed = True
                print(colorize_log(f"[launcher] Normalized legacy lang option: {current} -> {normalized}"))
            normalized_lines.append(f"lang:{normalized}\n")
        else:
            normalized_lines.append(raw_line if raw_line.endswith("\n") else (raw_line + "\n"))

    if not found_lang:
        normalized_lines.append("lang:en_US\n")
        changed = True
        print(colorize_log("[launcher] Added missing legacy lang option: en_US"))

    if not changed:
        return

    try:
        with open(options_path, "w", encoding="utf-8") as f:
            f.writelines(normalized_lines)
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: Could not write normalized options.txt: {e}"))


def _prepare_legacy_forge_merged_client_jar(version_dir: str, loader_version: str = None) -> str:
    actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
    if not actual_loader_version:
        return ""

    forge_jar = _find_forge_core_jar(version_dir, actual_loader_version)
    client_jar = os.path.join(version_dir, "client.jar")
    if not forge_jar or not os.path.exists(client_jar):
        return ""

    # Discover FML jar (separate artifact in pre-1.6 Forge)
    fml_jar = None
    modloader_jar = ""
    forge_loader_path = os.path.join(version_dir, "loaders", "forge", actual_loader_version)
    if os.path.isdir(forge_loader_path):
        for fname in os.listdir(forge_loader_path):
            if fname.startswith("fml-") and fname.endswith(".jar"):
                fml_jar = os.path.join(forge_loader_path, fname)
                break

    if _legacy_forge_requires_modloader(version_dir, actual_loader_version):
        modloader_jar = _find_modloader_runtime_jar(version_dir)
        if modloader_jar:
            print(colorize_log(f"[launcher] Found ModLoader runtime for legacy Forge: {os.path.basename(modloader_jar)}"))

    merge_dir = os.path.join(version_dir, "loaders", "forge", actual_loader_version, ".legacy_merged")
    os.makedirs(merge_dir, exist_ok=True)

    merged_name = f"forge-{actual_loader_version}-client-merged.jar"
    merged_path = os.path.join(merge_dir, merged_name)

    source_jars = [j for j in [fml_jar, modloader_jar, forge_jar, client_jar] if j and os.path.exists(j)]
    try:
        merged_mtime = os.path.getmtime(merged_path) if os.path.exists(merged_path) else 0
        source_mtime = max(os.path.getmtime(j) for j in source_jars)
        if merged_mtime >= source_mtime:
            return os.path.relpath(merged_path, version_dir).replace("\\", "/")
    except OSError:
        pass

    tmp_path = merged_path + ".tmp"
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    seen_entries = set()
    forge_count = 0
    client_count = 0

    def _copy_jar_entries(src_jar: str, *, skip_existing: bool) -> int:
        copied = 0
        with zipfile.ZipFile(src_jar, "r") as src_zip, zipfile.ZipFile(tmp_path, "a", compression=zipfile.ZIP_DEFLATED) as dst_zip:
            for entry in src_zip.infolist():
                name = entry.filename
                if entry.is_dir():
                    continue
                if name.upper().startswith("META-INF/"):
                    continue
                if skip_existing and name in seen_entries:
                    continue

                with src_zip.open(entry, "r") as src_file:
                    dst_zip.writestr(name, src_file.read())
                seen_entries.add(name)
                copied += 1
        return copied

    fml_count = 0
    modloader_count = 0
    try:
        # Priority: Forge first (its obfuscated classes carry both FML + Forge
        # patches, e.g. the isDefaultTexture field on Item), then FML (adds
        # cpw/mods/fml framework classes Forge doesn't ship), then ModLoader
        # runtime classes for pre-FML Forge, then client.
        forge_count = _copy_jar_entries(forge_jar, skip_existing=False)
        if fml_jar and os.path.exists(fml_jar):
            fml_count = _copy_jar_entries(fml_jar, skip_existing=True)
        if modloader_jar and os.path.exists(modloader_jar):
            modloader_count = _copy_jar_entries(modloader_jar, skip_existing=True)
        client_count = _copy_jar_entries(client_jar, skip_existing=True)
        os.replace(tmp_path, merged_path)
        print(colorize_log(
            f"[launcher] Prepared legacy merged Forge jar: {merged_name} "
            f"(fml entries {fml_count}, modloader entries {modloader_count}, "
            f"forge entries {forge_count}, client fallback entries {client_count})"
        ))

        # Patch CoreFMLLibraries.class to fix dead fmllibs checksums.
        # The FML-specific asm-all-4.0.jar (hash 9830...) is no longer hosted anywhere;
        # Maven Central's standard asm-all-4.0.jar has a different hash (2518...).
        # Binary-replace the 40-char SHA1 hex string in the class constant pool
        # so FML accepts the Maven Central version we pre-stage.
        _patch_fml_library_hashes(merged_path)

    except Exception as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        print(colorize_log(f"[launcher] Warning: Could not prepare legacy merged Forge jar: {e}"))
        return ""

    return os.path.relpath(merged_path, version_dir).replace("\\", "/")


# Mapping of FML library hashes that are no longer downloadable from the original
# files.minecraftforge.net/fmllibs/ URL to their Maven Central equivalents.
_FML_HASH_FIXUPS = {
    # asm-all-4.0.jar: FML-specific build hash → standard Maven Central hash
    b"98308890597acb64047f7e896638e0d98753ae82": b"2518725354c7a6a491a323249b9e86846b00df09",
}


def _patch_fml_library_hashes(merged_jar_path: str) -> None:
    """Binary-patch CoreFMLLibraries.class inside the merged jar to replace
    dead FML library SHA1 hashes with their Maven Central equivalents.
    Both old and new are 40-char hex, so the class file structure is preserved."""
    target_entry = "cpw/mods/fml/relauncher/CoreFMLLibraries.class"
    try:
        with zipfile.ZipFile(merged_jar_path, "r") as zin:
            if target_entry not in zin.namelist():
                return
            data = zin.read(target_entry)

        patched = False
        for old_hash, new_hash in _FML_HASH_FIXUPS.items():
            if old_hash in data:
                data = data.replace(old_hash, new_hash, 1)
                patched = True

        if not patched:
            return

        # Rewrite the merged jar with the patched class
        tmp_path = merged_jar_path + ".patch_tmp"
        with zipfile.ZipFile(merged_jar_path, "r") as zin, \
             zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == target_entry:
                    zout.writestr(item, data)
                else:
                    zout.writestr(item, zin.read(item.filename))
        os.replace(tmp_path, merged_jar_path)
        print(colorize_log(
            "[launcher] Patched CoreFMLLibraries.class in merged jar "
            "(updated dead fmllibs checksums to Maven Central equivalents)"
        ))
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: Could not patch FML library hashes: {e}"))


# FML companion libraries required by pre-1.6 Forge, mapped to Maven Central coords.
_FML_LIBRARIES = [
    {
        "name": "argo-2.25.jar",
        "url": "https://repo1.maven.org/maven2/net/sourceforge/argo/argo/2.25/argo-2.25.jar",
        "sha1": "bb672829fde76cb163004752b86b0484bd0a7f4b",
    },
    {
        "name": "guava-12.0.1.jar",
        "url": "https://repo1.maven.org/maven2/com/google/guava/guava/12.0.1/guava-12.0.1.jar",
        "sha1": "b8e78b9af7bf45900e14c6f958486b6ca682195f",
    },
    {
        "name": "asm-all-4.0.jar",
        "url": "https://repo1.maven.org/maven2/org/ow2/asm/asm-all/4.0/asm-all-4.0.jar",
        "sha1": "2518725354c7a6a491a323249b9e86846b00df09",
    },
    {
        "name": "bcprov-jdk15on-147.jar",
        "url": "https://repo1.maven.org/maven2/org/bouncycastle/bcprov-jdk15on/1.47/bcprov-jdk15on-1.47.jar",
        "sha1": "b6f5d9926b0afbde9f4dbe3db88c5247be7794bb",
    },
]


def _stage_legacy_fml_libraries(game_dir: str) -> None:
    """Pre-download FML companion libraries into {game_dir}/lib/ so FML's
    RelaunchLibraryManager finds them already present and skips the dead
    files.minecraftforge.net download."""
    lib_dir = os.path.join(game_dir, "lib")
    os.makedirs(lib_dir, exist_ok=True)

    for lib in _FML_LIBRARIES:
        dest = os.path.join(lib_dir, lib["name"])
        # Check if already present with correct hash
        if os.path.isfile(dest):
            try:
                with open(dest, "rb") as f:
                    actual = hashlib.sha1(f.read()).hexdigest()
                if actual == lib["sha1"]:
                    continue
            except OSError:
                pass

        # Download from Maven Central
        try:
            print(colorize_log(f"[launcher] Downloading FML library: {lib['name']}"))
            req = urllib.request.Request(lib["url"], headers={"User-Agent": "Histolauncher/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            actual = hashlib.sha1(data).hexdigest()
            if actual != lib["sha1"]:
                print(colorize_log(
                    f"[launcher] Warning: SHA1 mismatch for {lib['name']} "
                    f"(got {actual}, expected {lib['sha1']})"
                ))
                continue
            with open(dest, "wb") as f:
                f.write(data)
            print(colorize_log(f"[launcher] Staged FML library: {lib['name']}"))
        except Exception as e:
            print(colorize_log(f"[launcher] Warning: Could not download {lib['name']}: {e}"))


def launch_version(version_identifier, username_override=None, loader=None, loader_version=None):
    base_dir = get_base_dir()
    clients_dir = get_versions_profile_dir()
    if "/" in version_identifier:
        parts = version_identifier.replace("\\", "/").split("/", 1)
        category, folder = parts[0], parts[1]
        
        version_dir = None
        for cat in os.listdir(clients_dir):
            if cat.lower() == category.lower():
                candidate = os.path.join(clients_dir, cat, folder)
                if os.path.isdir(candidate):
                    version_dir = candidate
                    break
        
        if not version_dir:
            version_dir = os.path.join(clients_dir, category, folder)
    else:
        version_dir = None
        for cat in os.listdir(clients_dir):
            p = os.path.join(clients_dir, cat, version_identifier)
            if os.path.isdir(p):
                version_dir = p
                break
        if not version_dir:
            print("ERROR: Version directory not found for", version_identifier)
            return False
    meta = _load_data_ini(version_dir)
    main_class = meta.get("main_class") or "net.minecraft.client.Minecraft"
    classpath_entries = [p.strip() for p in (meta.get("classpath") or "client.jar").split(",") if p.strip()]
    
    if loader:
        loader_jars = _get_loader_jars(version_dir, loader, loader_version)
        
        if loader.lower() == "forge" and not loader_version:
            actual_version = _get_loader_version(version_dir, loader)
            if actual_version:
                forge_dir = os.path.join(version_dir, "loaders", "forge", actual_version)
                libraries_dir = os.path.join(forge_dir, "libraries")
                
                has_launchwrapper = False
                if os.path.isdir(libraries_dir):
                    for root, dirs, files in os.walk(libraries_dir):
                        if any(f.startswith("launchwrapper") and f.endswith(".jar") for f in files):
                            has_launchwrapper = True
                            break
                else:
                    # No libraries directory - check if the universal JAR itself has launchwrapper
                    for jar in os.listdir(forge_dir) if os.path.isdir(forge_dir) else []:
                        if jar.endswith(".jar"):
                            try:
                                with zipfile.ZipFile(os.path.join(forge_dir, jar), 'r') as z:
                                    if any("launchwrapper" in name.lower() for name in z.namelist()):
                                        has_launchwrapper = True
                                        break
                            except:
                                pass
                
                if not has_launchwrapper and actual_version.startswith("14"):
                    print(colorize_log(f"[launcher] Warning: Forge {actual_version} appears incomplete (missing LaunchWrapper)"))
                    print(colorize_log(f"[launcher] Attempting to use a compatible newer version instead..."))
                    
                    loaders_dir = os.path.join(version_dir, "loaders", "forge")
                    if os.path.isdir(loaders_dir):
                        versions = sorted([d for d in os.listdir(loaders_dir) if os.path.isdir(os.path.join(loaders_dir, d))],
                                         key=lambda x: tuple(map(int, x.split('.')[:3])) if x[0].isdigit() else (0,))
                        fallback_version = None
                        for v in reversed(versions):
                            if v.startswith("14.23.") or v.startswith("14.22.") or v == "14.23.5.2864":
                                fallback_version = v
                                break
                        
                        if fallback_version and fallback_version != actual_version:
                            print(colorize_log(f"[launcher] Trying fallback: Forge {fallback_version}"))
                            loader_jars = _get_loader_jars(version_dir, loader, fallback_version)
                            if loader_jars:
                                print(colorize_log(f"[launcher] Fallback successful - using Forge {fallback_version}"))
                                loader_version = fallback_version
                                actual_version = fallback_version
        
        if loader_jars:
            lookup_version = loader_version or _get_loader_version(version_dir, loader)
            loader_main = _get_loader_main_class(version_dir, loader, lookup_version)
            if loader_main:
                main_class = loader_main
                print(colorize_log(f"[launcher] Using {loader} main class: {main_class}"))

            preserve_forge_client = True
            if loader.lower() == "forge":
                if main_class.startswith("cpw.mods.bootstraplauncher") or main_class.startswith("net.minecraftforge.bootstrap"):
                    preserve_forge_client = False

            classpath_entries = _filter_conflicting_classpath_entries(
                classpath_entries,
                loader_jars,
                preserve_forge_client=preserve_forge_client,
            )
            
            classpath_entries = loader_jars + classpath_entries
            print(colorize_log(f"[launcher] Injected {len(loader_jars)} {loader} JAR(s) into classpath"))
            
            if loader.lower() == "forge":
                actual_loader_version = loader_version or _get_loader_version(version_dir, loader)
                if actual_loader_version:
                    libraries_dir_rel = os.path.join("loaders", loader.lower(), actual_loader_version, "libraries")
                    loader_full_path = os.path.join(version_dir, "loaders", loader.lower(), actual_loader_version)
                    if os.path.isdir(os.path.join(loader_full_path, "libraries")) and libraries_dir_rel not in classpath_entries:
                        classpath_entries.insert(len(loader_jars), libraries_dir_rel)
                        print(colorize_log(f"[launcher] Added Forge libraries/ to classpath (LaunchWrapper compatibility)"))
                if main_class == "cpw.mods.modlauncher.Launcher":
                    classpath_entries = _prune_forge_root_jars_for_modlauncher(classpath_entries)
                if main_class.startswith("cpw.mods.bootstraplauncher"):
                    classpath_entries = _prune_vanilla_client_jar(classpath_entries)

    if loader and loader.lower() == "forge":
        major, minor = _parse_mc_version(version_identifier)
        if major == 1 and minor is not None and minor < 6:
            actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
            merged_jar_rel = _prepare_legacy_forge_merged_client_jar(version_dir, actual_loader_version)
            forge_core_abs = _find_forge_core_jar(version_dir, actual_loader_version) if actual_loader_version else ""
            forge_core_rel = os.path.relpath(forge_core_abs, version_dir).replace("\\", "/") if forge_core_abs else ""
            if merged_jar_rel:
                # Also identify FML jar to remove (it's merged into the combined jar)
                fml_jar_rel = ""
                if actual_loader_version:
                    forge_loader_path = os.path.join(version_dir, "loaders", "forge", actual_loader_version)
                    if os.path.isdir(forge_loader_path):
                        for fname in os.listdir(forge_loader_path):
                            if fname.startswith("fml-") and fname.endswith(".jar"):
                                fml_jar_rel = os.path.relpath(
                                    os.path.join(forge_loader_path, fname), version_dir
                                ).replace("\\", "/")
                                break

                updated_entries = []
                inserted_merged = False
                for entry in classpath_entries:
                    entry_norm = entry.replace("\\", "/")
                    if entry_norm == "client.jar" or (forge_core_rel and entry_norm == forge_core_rel):
                        if not inserted_merged:
                            updated_entries.append(merged_jar_rel)
                            inserted_merged = True
                        continue
                    # Drop standalone FML jar — its contents are now in the merged jar
                    if fml_jar_rel and entry_norm == fml_jar_rel:
                        continue
                    updated_entries.append(entry)

                if not inserted_merged:
                    updated_entries.insert(0, merged_jar_rel)

                classpath_entries = updated_entries
                print(colorize_log(
                    "[launcher] Using merged legacy Forge/client jar for pre-1.6 compatibility"
                ))

    
    classpath = _join_classpath(version_dir, classpath_entries)
    global_settings = load_global_settings()
    username = username_override or global_settings.get("username", "Player")
    min_ram = global_settings.get("min_ram", "64M")
    max_ram = global_settings.get("max_ram", "2048M")
    selected_java_path = (global_settings.get("java_path") or "").strip()
    java_executable = selected_java_path if (selected_java_path and os.path.isfile(selected_java_path)) else "java"
    global_extra_jvm_args_raw = (global_settings.get("extra_jvm_args") or "").strip()
    storage_mode = global_settings.get("storage_directory", "global").lower()
    if storage_mode == "version":
        game_dir = os.path.join(version_dir, "data")
    else:
        system = platform.system().lower()
        if "windows" in system:
            user_profile = os.environ.get("APPDATA")
            game_dir = os.path.join(user_profile, ".minecraft")
        else:
            game_dir = os.path.expanduser(os.path.join("~", ".minecraft"))
    assets_root_override = _prepare_legacy_assets_directory(version_identifier, game_dir, meta)
    if assets_root_override:
        _prepare_legacy_client_resources(version_dir, assets_root_override)

    _prepare_legacy_options_file(version_identifier, game_dir)

    # Pre-stage FML companion libraries for pre-1.6 Forge
    if loader and loader.lower() == "forge":
        major_pre, minor_pre = _parse_mc_version(version_identifier)
        if major_pre == 1 and minor_pre is not None and minor_pre < 6 and _legacy_forge_has_fml(version_dir, loader_version):
            _stage_legacy_fml_libraries(game_dir)

    cmd = [java_executable, f"-Xms{min_ram}", f"-Xmx{max_ram}"]

    if global_extra_jvm_args_raw:
        try:
            parsed_extra_args = shlex.split(global_extra_jvm_args_raw, posix=False)
        except Exception:
            parsed_extra_args = global_extra_jvm_args_raw.split()
        if parsed_extra_args:
            cmd.extend(parsed_extra_args)
            print(colorize_log(f"[launcher] Added {len(parsed_extra_args)} user-configured JVM argument(s)"))
    
    if loader and loader.lower() == "forge":
        mc_version_str = version_identifier.split("/")[-1].split("-")[0]
        
        is_modlauncher = main_class == "cpw.mods.modlauncher.Launcher"
        is_launchwrapper = main_class == "net.minecraft.launchwrapper.Launch"

        if _is_legacy_forge_runtime(version_identifier):
            _prepare_legacy_forge_runtime_files(version_dir, game_dir, loader_version)

        metadata_jvm_args_raw = _get_forge_metadata_args(version_dir, loader_version, "jvm")
        metadata_jvm_args = _expand_forge_metadata_args(
            metadata_jvm_args_raw, version_dir, loader_version, version_identifier
        ) if metadata_jvm_args_raw else []

        if metadata_jvm_args:
            cmd.extend(metadata_jvm_args)
            print(colorize_log(f"[launcher] Added {len(metadata_jvm_args)} Forge metadata JVM argument(s)"))
        else:
            try:
                java_version_output = subprocess.check_output([java_executable, "-version"], stderr=subprocess.STDOUT).decode('utf-8', errors='ignore')
                if "1.8" not in java_version_output:
                    cmd.extend([
                        "--add-exports=java.base/sun.security.util=ALL-UNNAMED",
                        "--add-exports=jdk.naming.dns/com.sun.jndi.dns=java.naming",
                        "--add-opens=java.base/java.util.jar=ALL-UNNAMED",
                        "--add-opens=java.base/java.lang.invoke=ALL-UNNAMED",
                    ])
                    print(colorize_log(f"[launcher] Added Java 9+ Forge compatibility arguments"))
            except Exception:
                pass
        
        forge_fml_metadata = {}
        
        if is_modlauncher:
            print(colorize_log(f"[launcher] Detected ModLauncher-based Forge (1.13+), will add FML properties as command-line arguments"))
            
            forge_fml_metadata = _get_forge_fml_metadata(version_dir, loader_version)
            
            if "mc_version" not in forge_fml_metadata:
                forge_fml_metadata["mc_version"] = mc_version_str
            
            if "forge_version" not in forge_fml_metadata and loader_version:
                forge_fml_metadata["forge_version"] = loader_version
            elif "forge_version" not in forge_fml_metadata:
                forge_fml_metadata["forge_version"] = _get_loader_version(version_dir, "forge")
            
            if "forge_group" not in forge_fml_metadata:
                forge_fml_metadata["forge_group"] = "net.minecraftforge"
        
        elif is_launchwrapper:
            print(colorize_log(f"[launcher] Detected LaunchWrapper-based Forge (1.12.2 and earlier), skipping FML properties"))
    
    if _is_authlib_injector_needed(version_identifier):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        authlib_path = os.path.join(project_root, "assets", "authlib-injector.jar")
        if os.path.exists(authlib_path):
            port_str = os.environ.get("HISTOLAUNCHER_PORT")
            if port_str:
                try:
                    ygg_port = int(port_str)
                except ValueError:
                    ygg_port = 0
            else:
                ygg_port = 0
            if ygg_port > 0:
                ygg_url = f"http://127.0.0.1:{ygg_port}/authserver"
                cmd.append(f"-javaagent:{authlib_path}={ygg_url}")
    native_folder = meta.get("native_subfolder") or _native_subfolder_for_platform()
    native_path = os.path.join(version_dir, native_folder)
    if os.path.isdir(native_path):
        cmd.append(f"-Djava.library.path={native_path}")
    
    if loader and loader.lower() == "fabric":
        from core.downloader import _download_yarn_mappings
        
        mc_version = _extract_mc_version_string(version_identifier)
        
        yarn_mappings = _download_yarn_mappings(version_dir, mc_version, "launch")
        if not yarn_mappings:
            print(colorize_log(f"[launcher] WARNING: Yarn mappings not available for Fabric"))
            print(colorize_log(f"[launcher] Some mods may not work properly without Yarn mappings"))
        classpath_file = os.path.join(version_dir, ".fabric_remap_classpath.txt")
        classpath_entries = []
        try:
            with open(classpath_file, 'w') as f:
                for entry in classpath.split(";"):
                    entry = entry.strip()
                    if entry:
                        abs_path = os.path.abspath(entry)
                        f.write(abs_path + "\n")
                        classpath_entries.append(abs_path)
            print(colorize_log(f"[launcher] Created Fabric remapping classpath file ({len(classpath_entries)} entries)"))
        except Exception as e:
            print(colorize_log(f"[launcher] ERROR creating Fabric remapping classpath file: {e}"))
            return False
        
        cmd.append("-Dfabric.gameMappingNamespace=official")
        cmd.append("-Dfabric.runtimeMappingNamespace=intermediary")
        cmd.append("-Dfabric.defaultModDistributionNamespace=intermediary")
        
        if yarn_mappings:
            cmd.append(f"-Dfabric.mappingPath={yarn_mappings}")
        
        cmd.append(f"-Dfabric.remapClasspathFile={classpath_file}")
        
        cmd.append(f"-Dfabric.gameJarPath={os.path.join(version_dir, 'client.jar')}")
        
        cmd.append("-Dfabric.development=false")
        
        print("[launcher] Fabric 0.18.4 runtime remapping configured:")
        if yarn_mappings:
            print(f"  [OK] Yarn mappings: {os.path.basename(yarn_mappings)}")
        else:
            print(f"  [NO] Yarn mappings: Not available (mods may warn or fail)")
        print(f"  [OK] Remapping classpath: {len(classpath_entries)} JARs")
        print(f"  [OK] Namespace: official -> intermediary")
    
    if loader and loader.lower() == "forge":
        print("[launcher] Configuring Forge environment...")
        
        loader_version = loader_version or _get_loader_version(version_dir, "forge")
        if loader_version:
            forge_loader_dir = os.path.join(version_dir, "loaders", "forge", loader_version)
            
            log4j_config = None
            for config_file in ["log4j2.xml", "log4j.properties", "log4j.xml"]:
                config_path = os.path.join(forge_loader_dir, config_file)
                if os.path.exists(config_path):
                    log4j_config = config_path
                    print(colorize_log(f"[launcher] Found Forge log4j config: {config_file}"))
                    break
            
            if log4j_config:
                if log4j_config.endswith(".xml"):
                    cmd.append(f"-Dlog4j.configurationFile=file:///{log4j_config.replace(chr(92), '/')}")
                else:
                    cmd.append(f"-Dlog4j.configuration=file:///{log4j_config.replace(chr(92), '/')}")
                print(colorize_log(f"[launcher] Set log4j configuration: {log4j_config}"))
            else:
                print(colorize_log(f"[launcher] WARNING: No log4j configuration found in Forge directory"))
                print(colorize_log(f"[launcher] Forge may have startup issues without proper logging configuration"))
        
        if not main_class or main_class == "":
            main_class = "net.minecraft.client.main.Main"
            print(colorize_log(f"[launcher] Using vanilla main class for Forge: {main_class}"))
    
    cmd.extend(["-cp", classpath])
    cmd.append(main_class)
    
    if loader and loader.lower() == "forge" and main_class == "cpw.mods.modlauncher.Launcher":
        cmd.extend(["--launchTarget", "fmlclient"])
        print(colorize_log(f"[launcher] Added launch target: --launchTarget fmlclient"))
        
        if forge_fml_metadata.get("mc_version"):
            mc_ver = _normalize_forge_mc_version(forge_fml_metadata['mc_version'])
            cmd.extend(["--fml.mcVersion", mc_ver])
            print(colorize_log(f"[launcher] Added FML argument: --fml.mcVersion {mc_ver}"))
        
        if forge_fml_metadata.get("forge_version"):
            cmd.extend(["--fml.forgeVersion", forge_fml_metadata['forge_version']])
            print(colorize_log(f"[launcher] Added FML argument: --fml.forgeVersion {forge_fml_metadata['forge_version']}"))

        forge_group = forge_fml_metadata.get("forge_group") or "net.minecraftforge"
        cmd.extend(["--fml.forgeGroup", forge_group])
        print(colorize_log(f"[launcher] Added FML argument: --fml.forgeGroup {forge_group}"))
        
        mcp_version = _normalize_forge_mcp_version(
            forge_fml_metadata.get("mcp_version", ""),
            forge_fml_metadata.get("mc_version", "")
        )
        
        if mcp_version:
            cmd.extend(["--fml.mcpVersion", mcp_version])
            print(colorize_log(f"[launcher] Added FML argument: --fml.mcpVersion {mcp_version}"))
        else:
            print(colorize_log(f"[launcher] WARNING: Forge MCP version metadata is missing; launching without --fml.mcpVersion"))

    if loader and loader.lower() == "forge" and (
        main_class.startswith("cpw.mods.bootstraplauncher")
        or main_class.startswith("net.minecraftforge.bootstrap")
    ):
        metadata_game_args_raw = _get_forge_metadata_args(version_dir, loader_version, "game")
        metadata_game_args = _expand_forge_metadata_args(
            metadata_game_args_raw, version_dir, loader_version, version_identifier
        ) if metadata_game_args_raw else []
        if metadata_game_args:
            has_launch_target = any(arg == "--launchTarget" for arg in cmd)
            if not has_launch_target:
                cmd.extend(metadata_game_args)
                print(colorize_log(
                    f"[launcher] Added {len(metadata_game_args)} Forge metadata game argument(s) for bootstrap launch"
                ))

    if loader and loader.lower() == "forge" and main_class == "net.minecraft.launchwrapper.Launch":
        tweak_class = None

        # Pre-1.6 Forge uses FML's patched Minecraft.class inside the merged jar
        # to bootstrap — there is no ITweaker / FMLTweaker in this era.
        major_mc, minor_mc = _parse_mc_version(version_identifier)
        is_pre_16_forge = (major_mc == 1 and minor_mc is not None and minor_mc < 6)
        if is_pre_16_forge:
            print(colorize_log(
                "[launcher] Pre-1.6 Forge detected — skipping --tweakClass "
                "(FML bootstraps via patched Minecraft class in merged jar)"
            ))
        else:
            try:
                actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
                if actual_loader_version:
                    forge_loader_path = os.path.join(version_dir, "loaders", "forge", actual_loader_version)

                    jars_checked = []
                    for root, dirs, files in os.walk(forge_loader_path):
                        for filename in sorted(files):
                            is_forge_core_jar = (
                                filename.endswith(".jar")
                                and (
                                    filename.startswith("forge-")
                                    or filename.startswith("minecraftforge-")
                                )
                            )
                            if not is_forge_core_jar:
                                continue

                            forge_jar = os.path.join(root, filename)
                            jars_checked.append(filename)
                            print(colorize_log(f"[launcher] Debug: Checking JAR for Tweak-Class: {filename}"))
                            try:
                                with zipfile.ZipFile(forge_jar, 'r') as jar:
                                    try:
                                        manifest_data = jar.read('META-INF/MANIFEST.MF').decode('utf-8')
                                        for line in manifest_data.split('\n'):
                                            line = line.strip()
                                            if line.startswith('Tweak-Class:'):
                                                tweak_class = line.split(':', 1)[1].strip()
                                                print(colorize_log(f"[launcher] Found Tweak-Class in {filename}: {tweak_class}"))
                                                break
                                            elif line.startswith('TweakClass:'):
                                                tweak_class = line.split(':', 1)[1].strip()
                                                print(colorize_log(f"[launcher] Found TweakClass (old format) in {filename}: {tweak_class}"))
                                                break
                                    except KeyError:
                                        print(colorize_log(f"[launcher] Debug: No META-INF/MANIFEST.MF in {filename}"))
                                        pass

                                if tweak_class:
                                    break
                            except Exception as jar_err:
                                print(colorize_log(f"[launcher] Debug: Could not read {filename}: {jar_err}"))

                        if tweak_class:
                            break

                    if not tweak_class and jars_checked:
                        print(colorize_log(f"[launcher] Debug: Checked {len(jars_checked)} JAR(s) but no Tweak-Class found"))
                    elif not jars_checked:
                        print(colorize_log(f"[launcher] Debug: No Forge core JAR files found in {forge_loader_path}"))

                    if not tweak_class:
                        metadata_tweak = _get_forge_tweak_class_from_metadata(version_dir, actual_loader_version)
                        if metadata_tweak:
                            tweak_class = metadata_tweak
                            print(colorize_log(f"[launcher] Using Forge tweak class from metadata: {tweak_class}"))

                    if not tweak_class:
                        tweak_class = "cpw.mods.fml.common.launcher.FMLTweaker"
                        print(colorize_log(f"[launcher] Falling back to default Forge tweak class: {tweak_class}"))

            except Exception as e:
                print(colorize_log(f"[launcher] Warning: Could not extract tweak class: {e}"))

        if tweak_class:
            cmd.extend(["--tweakClass", tweak_class])
            print(colorize_log(f"[launcher] Added Forge tweaker: {tweak_class}"))
        elif not is_pre_16_forge:
            print(colorize_log(f"[launcher] Warning: Could not determine Forge tweak class (mods may not load)"))
    
    if loader and loader.lower() == "forge" and not main_class:
        print(colorize_log(f"[launcher] ERROR: Could not determine Forge main class!"))
        print(colorize_log(f"[launcher] This Forge version may not be properly supported yet."))
        print(colorize_log(f"[launcher] Attempting to use vanilla launcher as fallback..."))
        main_class = "net.minecraft.client.Minecraft"
        cmd[-1] = main_class
    
    username, auth_uuid_raw = _get_username_and_uuid()
    auth_uuid = (
        f"{auth_uuid_raw[0:8]}-{auth_uuid_raw[8:12]}-{auth_uuid_raw[12:16]}-"
        f"{auth_uuid_raw[16:20]}-{auth_uuid_raw[20:]}"
    )

    expanded_game_args = []
    extra = meta.get("extra_jvm_args")
    if extra:
        expanded = _expand_placeholders(
            extra,
            version_identifier,
            game_dir,
            version_dir,
            global_settings,
            meta,
            assets_root_override=assets_root_override,
        )
        expanded_game_args = expanded.split()
        cmd.extend(expanded_game_args)
    else:
        cmd.append(username)

    # Only force --gameDir for flag-style argument sets. Very old versions use positional args.
    has_flag_style_game_args = any(arg.startswith("--") for arg in expanded_game_args)
    if game_dir is not None and has_flag_style_game_args:
        _set_or_append_cli_arg(cmd, "--gameDir", game_dir)

    if loader and loader.lower() == "forge" and main_class == "cpw.mods.modlauncher.Launcher":
        mc_ver = _normalize_forge_mc_version(forge_fml_metadata.get("mc_version", "")) or _extract_mc_version_string(version_identifier)
        forge_ver = (forge_fml_metadata.get("forge_version") or "").strip()
        if mc_ver and forge_ver:
            forge_profile_version = f"{mc_ver}-forge-{forge_ver}"
            _set_or_append_cli_arg(cmd, "--version", forge_profile_version)
            print(colorize_log(f"[launcher] Set Forge profile --version argument: {forge_profile_version}"))
    
    if loader and loader.lower() == "forge":
        print("[launcher] Validating Forge configuration...")
        actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
        if actual_loader_version:
            forge_loader_dir = os.path.join(version_dir, "loaders", "forge", actual_loader_version)
            
            if not os.path.isdir(forge_loader_dir):
                print(colorize_log(f"[launcher] ERROR: Forge loader directory not found: {forge_loader_dir}"))
                return False
            
            jar_files = [f for f in os.listdir(forge_loader_dir) if f.endswith(".jar")]
            if not jar_files:
                print(colorize_log(f"[launcher] ERROR: No JAR files found in Forge directory"))
                return False

            if _legacy_forge_requires_modloader(version_dir, actual_loader_version) and not _has_modloader_runtime(version_dir):
                print(colorize_log(
                    "[launcher] ERROR: This pre-FML Forge build requires ModLoader, but no ModLoader runtime was found."
                ))
                print(colorize_log(
                    "[launcher] Forge 1.1-era builds are ModLoader addons and cannot function as standalone Forge installs."
                ))
                print(colorize_log(
                    "[launcher] Add a matching ModLoader jar (containing BaseMod.class and ModLoader.class) "
                    "to the version root, e.g. clients/<category>/<version>/modloader-<version>.jar, then relaunch Forge."
                ))
                return False
            
            print(colorize_log(f"[launcher] [OK] Forge loader directory valid ({len(jar_files)} JARs)"))
            
            if main_class and main_class == "cpw.mods.modlauncher.Launcher":
                print(colorize_log(f"[launcher] Setting up ModLauncher forge JAR paths..."))
                try:
                    universal_jar = None
                    for jar_file in jar_files:
                        if jar_file.startswith("forge-") and jar_file.endswith("-universal.jar"):
                            universal_jar = jar_file
                            break
                    
                    if universal_jar:
                        jar_base = universal_jar.replace("forge-", "").replace("-universal.jar", "")
                        parts = jar_base.rsplit("-", 1)
                        if len(parts) == 2:
                            mc_ver, forge_ver = parts
                            maven_path = os.path.join(forge_loader_dir, "libraries", "net", "minecraftforge", "forge", f"{mc_ver}-{forge_ver}")
                            
                            print(colorize_log(f"[launcher] Forge JAR: {universal_jar} -> MC:{mc_ver} Forge:{forge_ver}"))
                            
                            os.makedirs(maven_path, exist_ok=True)
                            
                            src_jar = os.path.join(forge_loader_dir, universal_jar)
                            dst_jar = os.path.join(maven_path, universal_jar)
                            
                            try:
                                if os.path.exists(dst_jar):
                                    print(colorize_log(f"[launcher] Maven universal JAR already exists"))
                                else:
                                    try:
                                        os.link(src_jar, dst_jar)
                                        print(colorize_log(f"[launcher] Linked universal JAR to Maven path"))
                                    except (OSError, NotImplementedError):
                                        shutil.copy2(src_jar, dst_jar)
                                        print(colorize_log(f"[launcher] Copied universal JAR to Maven path"))
                            except Exception as link_err:
                                print(colorize_log(f"[launcher] Warning: Could not link/copy universal JAR: {link_err}"))
                            
                            client_jar_name = f"forge-{mc_ver}-{forge_ver}.jar"
                            client_jar_path = os.path.join(forge_loader_dir, client_jar_name)
                            
                            if os.path.exists(client_jar_path):
                                dst_client_jar = os.path.join(maven_path, f"forge-{mc_ver}-{forge_ver}-client.jar")
                                try:
                                    if not os.path.exists(dst_client_jar):
                                        try:
                                            os.link(client_jar_path, dst_client_jar)
                                            print(colorize_log(f"[launcher] Linked client JAR to Maven path"))
                                        except (OSError, NotImplementedError):
                                            shutil.copy2(client_jar_path, dst_client_jar)
                                            print(colorize_log(f"[launcher] Copied client JAR to Maven path"))
                                except Exception as e:
                                    print(colorize_log(f"[launcher] Warning: Could not link/copy client JAR: {e}"))

                            # Self-heal missing MCP-scoped client resources required by
                            # ModLauncher-era Forge (some restricted-network installs miss these).
                            try:
                                raw_mcp = _normalize_forge_mcp_version(
                                    forge_fml_metadata.get("mcp_version", ""),
                                    mc_ver,
                                )
                                if raw_mcp:
                                    token = f"{mc_ver}-{raw_mcp}"
                                    client_mcp_dir = os.path.join(
                                        forge_loader_dir,
                                        "libraries",
                                        "net",
                                        "minecraft",
                                        "client",
                                        token,
                                    )
                                    os.makedirs(client_mcp_dir, exist_ok=True)

                                    plain_extra = os.path.join(
                                        forge_loader_dir,
                                        "libraries",
                                        "net",
                                        "minecraft",
                                        "client",
                                        mc_ver,
                                        f"client-{mc_ver}-extra.jar",
                                    )
                                    base_client_jar = os.path.join(version_dir, "client.jar")
                                    source_client = plain_extra if os.path.exists(plain_extra) else base_client_jar

                                    for suffix in ("extra", "srg"):
                                        target_jar = os.path.join(client_mcp_dir, f"client-{token}-{suffix}.jar")
                                        if os.path.exists(target_jar):
                                            continue
                                        if not os.path.exists(source_client):
                                            continue
                                        try:
                                            os.link(source_client, target_jar)
                                        except (OSError, NotImplementedError):
                                            shutil.copy2(source_client, target_jar)
                                        print(colorize_log(
                                            f"[launcher] Staged missing ModLauncher MCP client resource: "
                                            f"libraries/net/minecraft/client/{token}/client-{token}-{suffix}.jar"
                                        ))
                            except Exception as e:
                                print(colorize_log(f"[launcher] Warning: Could not stage MCP client resources: {e}"))
                        else:
                            print(colorize_log(f"[launcher] Warning: Could not parse forge JAR version from {universal_jar}"))
                except Exception as maven_err:
                    print(colorize_log(f"[launcher] Warning: Could not set up Maven path: {maven_err}"))

            has_log4j = any(f in os.listdir(forge_loader_dir) for f in ["log4j2.xml", "log4j.properties", "log4j.xml"])
            if has_log4j:
                print(colorize_log(f"[launcher] [OK] Log4j configuration found"))
            else:
                print(colorize_log(f"[launcher] [WARN] No log4j configuration found (may cause startup warnings)"))
        else:
            print(colorize_log(f"[launcher] ERROR: Could not determine Forge version"))
            return False
    
    if loader and loader.lower() == "fabric":
        classpath_file = os.path.join(version_dir, ".fabric_remap_classpath.txt")
        if not os.path.exists(classpath_file):
            print(colorize_log(f"[launcher] ERROR: Fabric remapping classpath file missing"))
            print(colorize_log(f"[launcher] Expected: {classpath_file}"))
            return False
        
        with open(classpath_file, 'r') as f:
            classpath_lines = [line.strip() for line in f if line.strip()]
        
        if not classpath_lines:
            print(colorize_log(f"[launcher] ERROR: Fabric remapping classpath file is empty"))
            return False
        
        relative_entries = []
        for path in classpath_lines:
            if not os.path.isabs(path):
                relative_entries.append(path)
        
        if relative_entries:
            print(colorize_log(f"[launcher] ERROR: Relative paths in classpath file (must be absolute):"))
            for path in relative_entries[:3]:
                print(f"    {path}")
            return False
        
        print(colorize_log(f"[launcher] [OK] Fabric configuration validated ({len(classpath_lines)} JARs"))
    
    skins_cache_dir = os.path.join(base_dir, "assets", "skins")
    if os.path.isdir(skins_cache_dir):
        try:
            shutil.rmtree(skins_cache_dir)
            print(colorize_log("[launcher] Cleared skin texture cache"))
        except Exception as e:
            print(colorize_log(f"[launcher] Warning: could not clear skin cache: {e}"))

    # Copy mods for the appropriate loader before launch
    copied_mods = []
    if loader and game_dir:
        copied_mods = _copy_mods_for_launch(game_dir, loader)

    print("Launching version:", version_identifier)
    print("Version dir:", version_dir)
    if loader:
        print(f"Mod loader: {loader}")
    launch_cwd = game_dir if (game_dir and os.path.isdir(game_dir)) else version_dir
    print("Working dir:", launch_cwd)
    print("Command:", " ".join(cmd))
    try:
        log_file_path, log_file = _create_client_log_file(version_identifier)
        
        if log_file:
            process = subprocess.Popen(
                cmd,
                cwd=launch_cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1
            )
        else:
            process = subprocess.Popen(cmd, cwd=launch_cwd)
        
        version_name = version_identifier.split("/", 1)[1] if "/" in version_identifier else version_identifier
        
        if log_file and process.stdout:
            reader_thread = threading.Thread(
                target=_output_reader_thread,
                args=(process, log_file, version_name),
                daemon=True
            )
            reader_thread.start()
            print(colorize_log(f"[launcher] Output reader thread started"))
        
        process_id = hashlib.sha1(
            f"{time.time()}{process.pid}".encode()
        ).hexdigest()[:16]
        
        _register_process(process_id, process, version_identifier, log_file_path, copied_mods)
        
        print(colorize_log(f"[launcher] Process launched with ID: {process_id}"))
        return process_id
    except Exception as e:
        print("ERROR launching:", e)
        return None
