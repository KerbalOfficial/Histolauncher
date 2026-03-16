# core/downloader.py

import hashlib
import json
import os
import shutil
import ssl
import threading
import time
import urllib.parse
import urllib.request
import zipfile
import tempfile
import traceback
import subprocess

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.settings import _apply_url_proxy, get_base_dir, load_global_settings
from core import manifest as core_manifest
from core.libraries.plyer import notification
from core.logger import colorize_log

BASE_DIR = get_base_dir()

DOWNLOAD_DIR = os.path.join(BASE_DIR, "clients")
PROGRESS_DIR = os.path.join(BASE_DIR, "cache", "progress")
CACHE_LIBRARIES_DIR = os.path.join(BASE_DIR, "cache", "libraries")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
ASSETS_INDEXES_DIR = os.path.join(ASSETS_DIR, "indexes")
ASSETS_OBJECTS_DIR = os.path.join(ASSETS_DIR, "objects")

# Download tuning
DOWNLOAD_CHUNK_SIZE = 64 * 1024  # 64 KB chunks
ASSET_THREADS_HIGH = 16
ASSET_THREADS_MED = 8
ASSET_THREADS_LOW = 4

_workers: Dict[str, threading.Thread] = {}
_cancel_flags: Dict[str, bool] = {}
_pause_flags: Dict[str, bool] = {}
_file_locks: Dict[str, threading.Lock] = {}
_file_locks_lock = threading.Lock()

class ThreadSafeProgress:
    def __init__(self):
        self._lock = threading.Lock()
        self.bytes_done = 0
        self.bytes_total = 0
    
    def add_done(self, delta: int) -> None:
        with self._lock:
            self.bytes_done += delta
    
    def add_total(self, delta: int) -> None:
        with self._lock:
            self.bytes_total += delta
    
    def set_totals(self, done: int, total: int) -> None:
        with self._lock:
            self.bytes_done = done
            self.bytes_total = total
    
    def get_totals(self) -> Tuple[int, int]:
        with self._lock:
            return (self.bytes_done, self.bytes_total)
    
    def reset(self) -> None:
        with self._lock:
            self.bytes_done = 0
            self.bytes_total = 0


def _download_with_retry(url: str, dest_file: str, progress_hook: Optional[Callable] = None, max_retries: int = 3) -> None:
    url = _apply_url_proxy(url)
    
    last_error = None
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher"})
            with urllib.request.urlopen(req) as response:
                total_size = int(response.headers.get("Content-Length", 0)) or None
                
                if progress_hook:
                    block_size = 8192
                    downloaded = 0
                    with open(dest_file, "wb") as f:
                        while True:
                            block = response.read(block_size)
                            if not block:
                                break
                            f.write(block)
                            downloaded += len(block)
                            progress_hook(downloaded // block_size, block_size, total_size)
                else:
                    with open(dest_file, "wb") as f:
                        f.write(response.read())
            return
        except ssl.SSLError as e:
            last_error = e
            if attempt < max_retries - 1:
                print(colorize_log(f"[download] SSL error on attempt {attempt + 1}, retrying with unverified context..."))
                time.sleep(1)
                
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher"})
                    with urllib.request.urlopen(req, context=context) as response:
                        total_size = int(response.headers.get("Content-Length", 0)) or None
                        
                        if progress_hook:
                            block_size = 8192
                            downloaded = 0
                            with open(dest_file, "wb") as f:
                                while True:
                                    block = response.read(block_size)
                                    if not block:
                                        break
                                    f.write(block)
                                    downloaded += len(block)
                                    progress_hook(downloaded // block_size, block_size, total_size)
                        else:
                            with open(dest_file, "wb") as f:
                                f.write(response.read())
                    return
                except Exception as retry_error:
                    last_error = retry_error
                    if attempt < max_retries - 2:
                        time.sleep(1)
                        continue
                    else:
                        raise
            else:
                raise
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                print(colorize_log(f"[download] Download error on attempt {attempt + 1}: {e}"))
                time.sleep(1)
            else:
                raise
    
    if last_error:
        raise last_error


# ============ FAST DOWNLOAD (PARALLEL) SUPPORT ============


def _is_fast_download_enabled() -> bool:
    try:
        settings = load_global_settings()
        return settings.get("fast_download", "0").lower() in ("1", "true", "yes", "enabled")
    except Exception:
        return False


def _download_parallel(
    download_tasks: List[Tuple[str, str, Optional[str], Optional[Callable], Optional[str]]],
    max_workers: int = 15,
) -> None:
    if not download_tasks:
        return
    
    # If fast download is enabled, increase worker count
    if _is_fast_download_enabled():
        max_workers = min(30, max(max_workers, 20))  # Use at least 20, up to 30 workers
    
    print(colorize_log(f"[download] Starting parallel download of {len(download_tasks)} files with {max_workers} workers"))
    
    completed = 0
    failed = []
    
    def download_task(task):
        url, dest_path, expected_sha1, progress_cb, version_key = task
        try:
            download_file(url, dest_path, expected_sha1, progress_cb, version_key=version_key)
            return True, None
        except Exception as e:
            return False, str(e)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(download_task, task): task for task in download_tasks}
        
        for future in as_completed(futures):
            task = futures[future]
            url, dest_path = task[0], task[1]
            try:
                success, error = future.result()
                if success:
                    completed += 1
                    print(colorize_log(f"[download] Completed: {os.path.basename(dest_path)} ({completed}/{len(download_tasks)})"))
                else:
                    failed.append((url, error))
                    print(colorize_log(f"[download] Failed: {os.path.basename(dest_path)} - {error}"))
            except Exception as e:
                failed.append((url, str(e)))
                print(colorize_log(f"[download] Error for {os.path.basename(dest_path)}: {e}"))
    
    if failed:
        error_msg = f"Failed to download {len(failed)}/{len(download_tasks)} files"
        print(colorize_log(f"[download] {error_msg}"))
        raise RuntimeError(error_msg)
    else:
        print(colorize_log(f"[download] All {len(download_tasks)} files downloaded successfully"))


STAGE_WEIGHTS = {
    "version_json": 5,
    "client": 20,
    "libraries": 25,
    "natives": 15,
    "assets": 25,
    "finalize": 10,
    "download": 20,
    "extracting_loader": 30,
    "downloading_libs": 40,
    "error": 0,
}


# ---------------- Filesystem / progress helpers ----------------


def ensure_dirs() -> None:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    os.makedirs(CACHE_LIBRARIES_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(ASSETS_INDEXES_DIR, exist_ok=True)
    os.makedirs(ASSETS_OBJECTS_DIR, exist_ok=True)


def encode_key(key: str) -> str:
    return urllib.parse.quote(key, safe="")


def progress_path(version_key: str) -> str:
    ensure_dirs()
    safe = encode_key(version_key)
    return os.path.join(PROGRESS_DIR, f"{safe}.json")


def write_progress(version_key: str, data: Dict[str, Any]) -> None:
    path = progress_path(version_key)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        # Progress is best-effort; ignore failures
        pass


def read_progress(version_key: str) -> Optional[Dict[str, Any]]:
    path = progress_path(version_key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def delete_progress(version_key: str) -> None:
    try:
        path = progress_path(version_key)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def list_progress_files() -> List[Tuple[str, Dict[str, Any]]]:
    ensure_dirs()
    out: List[Tuple[str, Dict[str, Any]]] = []
    for name in os.listdir(PROGRESS_DIR):
        if not name.endswith(".json"):
            continue
        path = os.path.join(PROGRESS_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = urllib.parse.unquote(name[:-5])
            out.append((key, data))
        except Exception:
            continue
    return out


def cleanup_orphaned_progress_files(max_age_seconds: int = 3600) -> None:
    try:
        ensure_dirs()
        current_time = time.time()
        
        for name in os.listdir(PROGRESS_DIR):
            if not name.endswith(".json"):
                continue
            path = os.path.join(PROGRESS_DIR, name)
            try:
                # Check file modification time
                file_mtime = os.path.getmtime(path)
                age_seconds = current_time - file_mtime
                
                # If file is older than max_age_seconds, delete it
                if age_seconds > max_age_seconds:
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        status = data.get("status", "").lower()
                        if status in ("downloading", "starting", "paused", "error"):
                            os.remove(path)
                            key = urllib.parse.unquote(name[:-5])
                            print(colorize_log(f"[cleanup] Removed orphaned progress file for {key} (age: {age_seconds:.0f}s)"))
                    except Exception:
                        pass
            except Exception:
                continue
    except Exception as e:
        print(colorize_log(f"[cleanup] Error cleaning orphaned progress files: {e}"))


# ---------------- Settings / proxy ----------------


def _get_url_proxy_prefix() -> str:
    try:
        settings = load_global_settings() or {}
    except Exception:
        settings = {}
    prefix = (settings.get("url_proxy") or "").strip()
    return prefix


# ---------------- Cancellation / pause ----------------


def _check_pause(version_key: str) -> None:
    """Check if paused and block until resumed. Updates progress state while paused."""
    if not _pause_flags.get(version_key):
        return
    
    # Write paused status once
    prog = read_progress(version_key) or {}
    write_progress(
        version_key,
        {
            "status": "paused",
            "stage": prog.get("stage", "downloading"),
            "stage_percent": prog.get("stage_percent", 0),
            "overall_percent": prog.get("overall_percent", 0),
            "message": "Paused",
            "bytes_done": prog.get("bytes_done", 0),
            "bytes_total": prog.get("bytes_total", 0),
        },
    )
    
    while _pause_flags.get(version_key):
        time.sleep(0.1)


def _maybe_abort(version_key: Optional[str]) -> None:
    """Check for cancellation or pause. Non-blocking."""
    if version_key:
        if _cancel_flags.get(version_key):
            raise RuntimeError("Download cancelled by user")
        _check_pause(version_key)


# ---------------- Hashing / integrity ----------------


def _sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(DOWNLOAD_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------- Download core ----------------


def _safe_remove_file(file_path: str, max_retries: int = 5) -> bool:
    for attempt in range(max_retries):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            return True
        except (OSError, PermissionError) as e:
            if attempt < max_retries - 1:
                # Wait a bit and retry
                time.sleep(0.1 * (attempt + 1))  # Exponential backoff: 0.1s, 0.2s, etc.
            else:
                print(colorize_log(f"[download] Warning: Could not remove {file_path} after {max_retries} attempts: {e}"))
                return False
    return False


def _get_file_lock(file_path: str) -> threading.Lock:
    with _file_locks_lock:
        if file_path not in _file_locks:
            _file_locks[file_path] = threading.Lock()
        return _file_locks[file_path]


def _cleanup_file_locks(max_locks: int = 1000) -> None:
    """Clean up old file locks to prevent memory leak. Keeps only recent locks."""
    with _file_locks_lock:
        if len(_file_locks) > max_locks:
            # Keep only the most recent locks by removing oldest entries
            to_remove = list(_file_locks.keys())[:-max_locks]
            for key in to_remove:
                del _file_locks[key]
            print(colorize_log(f"[download] Cleaned up file locks (kept {max_locks})"))



def download_file(
    url: str,
    dest_path: str,
    expected_sha1: Optional[str] = None,
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
    retries: int = 3,
    version_key: Optional[str] = None,
) -> None:
    _maybe_abort(version_key)

    url = _apply_url_proxy(url)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    file_lock = _get_file_lock(dest_path)

    print(colorize_log(f"[download] Starting: {url} -> {dest_path}"))
    last_err: Optional[Exception] = None

    with file_lock:
        if os.path.exists(dest_path):
            print(colorize_log(f"[download] File already exists: {dest_path}"))
            return

        for attempt in range(1, retries + 1):
            tmp_path = dest_path + ".part"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher"})
                with urllib.request.urlopen(req) as resp:
                    total = getattr(resp, "length", None)
                    if total is None:
                        try:
                            total = int(resp.headers.get("Content-Length") or 0) or None
                        except Exception:
                            total = None

                    downloaded = 0

                    with open(tmp_path, "wb") as f:
                        while True:
                            _maybe_abort(version_key)
                            chunk = resp.read(DOWNLOAD_CHUNK_SIZE)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_cb:
                                progress_cb(downloaded, total)

                if expected_sha1:
                    actual = _sha1_file(tmp_path)
                    if actual.lower() != expected_sha1.lower():
                        _safe_remove_file(tmp_path)
                        raise ValueError(
                            f"SHA1 mismatch for {dest_path}: expected {expected_sha1}, got {actual}"
                        )

                if os.path.exists(dest_path):
                    _safe_remove_file(tmp_path)
                    print(colorize_log(f"[download] File was downloaded by another thread: {dest_path}"))
                    return

                if os.path.exists(dest_path):
                    _safe_remove_file(dest_path)
                os.rename(tmp_path, dest_path)
                print(colorize_log(f"[download] Completed: {dest_path}"))
                
                if __name__ != "__main__":
                    _cleanup_file_locks()
                
                return
            except Exception as e:
                last_err = e
                print(colorize_log(f"[download] Error on attempt {attempt}/{retries} for {url}: {e}"))
                _safe_remove_file(tmp_path)
                _maybe_abort(version_key)

    raise last_err or RuntimeError(f"Failed to download {url}")



# ---------------- Progress computation ----------------


def _compute_overall(stage: str, stage_percent: float, version_key: str | None = None) -> float:
    if version_key and "modloader-" in version_key:
        loader_seq = ["download", "downloading_libs", "extracting_loader", "finalize"]
        loader_weights = {k: STAGE_WEIGHTS[k] for k in loader_seq if k in STAGE_WEIGHTS}
        total = 0.0
        for key, weight in loader_weights.items():
            if key == stage:
                total += weight * (stage_percent / 100.0)
                break
            total += weight
        return min(100.0, max(0.0, total))

    total = 0.0
    for key, weight in STAGE_WEIGHTS.items():
        if key == stage:
            total += weight * (stage_percent / 100.0)
            break
        total += weight
    return min(100.0, max(0.0, total))


def _update_progress(
    version_key: str,
    stage: str,
    stage_percent: float,
    message: str,
    bytes_done: int = 0,
    bytes_total: int = 0,
) -> None:
    overall = _compute_overall(stage, stage_percent, version_key)
    write_progress(
        version_key,
        {
            "status": "downloading",
            "stage": stage,
            "stage_percent": int(stage_percent),
            "overall_percent": int(overall),
            "message": message,
            "bytes_done": int(bytes_done),
            "bytes_total": int(bytes_total),
        },
    )
    print(
        colorize_log(
            f"[progress] {version_key} | {stage} {stage_percent:.1f}% "
            f"(overall {overall:.1f}%) - {message}"
        )
    )


# ---------------- Version / argument helpers ----------------


def _flatten_arguments_list(arg_list: List[Any]) -> List[str]:
    result: List[str] = []
    for item in arg_list or []:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            val = item.get("value")
            if isinstance(val, str):
                result.append(val)
            elif isinstance(val, list):
                for v in val:
                    if isinstance(v, str):
                        result.append(v)
    return result


def _extract_extra_args(vjson: Dict[str, Any]) -> Optional[str]:
    args = vjson.get("arguments")
    if isinstance(args, dict):
        game_args = _flatten_arguments_list(args.get("game", []))
        if game_args:
            return " ".join(game_args)

    legacy = vjson.get("minecraftArguments")
    if isinstance(legacy, str) and legacy.strip():
        return legacy.strip()

    return None


def _choose_asset_threads() -> int:
    threads = os.cpu_count() or 1
    
    # If fast download is enabled, use maximum threads
    if _is_fast_download_enabled():
        return ASSET_THREADS_HIGH  # 16 threads
    
    # Otherwise, choose based on CPU count
    if threads >= 12:
        return ASSET_THREADS_HIGH
    if threads >= 6:
        return ASSET_THREADS_MED
    return ASSET_THREADS_LOW


def _is_modern_assets(version_id: str) -> bool:
    base = (version_id or "").split("-", 1)[0]
    parts = base.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        return True
    if major > 1:
        return True
    if major == 1 and minor >= 6:
        return True
    return False


def _extract_os_from_classifier_key(key: str) -> Optional[str]:
    k = key.lower()
    if "windows" in k or "win" in k:
        return "windows"
    if "linux" in k:
        return "linux"
    if "osx" in k or "mac" in k:
        return "mac"
    return None


def _parse_mc_version(version_id: str) -> Optional[Tuple[int, int]]:
    base = (version_id or "").split("-", 1)[0]
    parts = base.split(".")
    if not parts:
        return None
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return major, minor
    except Exception:
        return None


def _is_at_least(version_id: str, major_req: int, minor_req: int) -> bool:
    parsed = _parse_mc_version(version_id)
    if not parsed:
        return False
    major, minor = parsed
    if major > major_req:
        return True
    if major == major_req and minor >= minor_req:
        return True
    return False


def _parse_lwjgl_version(lib_basename: str) -> Optional[int]:
    name = lib_basename.lower()
    if not name.startswith("lwjgl"):
        return None

    parts = name.split("-")
    if len(parts) < 2:
        return None

    ver_part = parts[-1].replace(".jar", "")
    digits = ver_part.replace(".", "")
    return int(digits) if digits.isdigit() else None


def _should_skip_library_for_version(
    version_id: str, lib_basename: str, highest_versions: Dict[str, int]
) -> bool:
    ver = _parse_lwjgl_version(lib_basename)
    if ver is None:
        return False

    module = lib_basename.split("-")[0]
    highest = highest_versions.get(module)
    return highest is not None and ver < highest


def _compute_total_size(
    vjson: Dict[str, Any], version_id: str, full_assets: bool
) -> int:
    total = 0

    client_info = (vjson.get("downloads") or {}).get("client")
    if client_info:
        total += int(client_info.get("size") or 0)

    libs = vjson.get("libraries") or []
    for lib in libs:
        downloads = lib.get("downloads") or {}
        artifact = downloads.get("artifact")
        if artifact:
            total += int(artifact.get("size") or 0)
        classifiers = downloads.get("classifiers") or {}
        for nat in classifiers.values():
            total += int(nat.get("size") or 0)

    assets_info = vjson.get("assetIndex") or {}
    assets_url = assets_info.get("url")
    if assets_url and full_assets and _is_modern_assets(version_id):
        try:
            index_path = os.path.join(
                ASSETS_INDEXES_DIR, f"{assets_info.get('id', '')}.json"
            )
            if os.path.exists(index_path):
                with open(index_path, "r", encoding="utf-8") as f:
                    idx_json = json.load(f)
            else:
                idx_json = {}
        except Exception:
            idx_json = {}
        objects = idx_json.get("objects") or {}
        for obj in objects.values():
            total += int(obj.get("size") or 0)

    return total


def _normalize_storage_category(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return "Release"
    return n[0].upper() + n[1:].lower()


def _wiki_image_url(version_id: str, version_type: str) -> Optional[str]:
    settings = load_global_settings()
    low_data = settings.get("low_data_mode") == "1"
    pixel_res = round(260/(2 if low_data else 1))

    t = (version_type or "").lower()
    if t == "release" or t == "snapshot":
        prefix = "Java_Edition_"
        clean_id = version_id \
            .replace("-", "_") \
            .replace("pre", "Pre-Release_") \
            .replace("rc", "Release_Candidate_") \
            .replace("snapshot", "Snapshot")
    elif t == "old_beta":
        prefix = "Beta_"
        clean_id = (version_id[1:] if version_id.startswith("b") else version_id) + "_menu"
    elif t == "old_alpha":
        if version_id.startswith("i"):
            prefix = "Infdev_"
            clean_id = version_id[4:] + "_menu"
        else:
            prefix = "Alpha_v"
            clean_id = (version_id[1:] if version_id.startswith("a") else version_id) + "_menu"
    else: return None

    return f"https://minecraft.wiki/images/thumb/{prefix}{clean_id}.png/{pixel_res}px-.png"


# ---------------- Core install pipeline ----------------


def _install_version(version_id: str, storage_category: str, full_assets: bool) -> None:
    ensure_dirs()

    version_key = f"{storage_category}/{version_id}"
    _cancel_flags.pop(version_key, None)
    _pause_flags.pop(version_key, None)

    print(colorize_log(f"[install] Starting install for {version_key} (full_assets={full_assets})"))
    _update_progress(version_key, "version_json", 0, "Fetching version metadata...")

    try:
        entry = core_manifest.get_version_entry(version_id)
    except Exception as e:
        raise RuntimeError(f"failed to find version in manifest: {e}")

    version_url = entry.get("url")
    if not version_url:
        raise RuntimeError("manifest entry missing version URL")

    try:
        vjson = core_manifest.fetch_version_json(version_url)
    except Exception as e:
        raise RuntimeError(f"failed to fetch version json: {e}")

    if not isinstance(vjson, dict):
        raise RuntimeError("version json is not an object")

    total_size = _compute_total_size(vjson, version_id, full_assets)
    bytes_done = 0

    _update_progress(
        version_key,
        "version_json",
        100,
        "Version metadata loaded",
        bytes_done=bytes_done,
        bytes_total=total_size,
    )

    storage_fs = _normalize_storage_category(storage_category)
    version_dir = os.path.join(DOWNLOAD_DIR, storage_fs, version_id)
    os.makedirs(version_dir, exist_ok=True)

    _maybe_abort(version_key)

    # ---- Client JAR ----
    client_info = (vjson.get("downloads") or {}).get("client")
    if not client_info:
        raise RuntimeError("version json missing client download info")

    client_url = client_info.get("url")
    client_sha1 = client_info.get("sha1")
    client_size = int(client_info.get("size") or 0)
    if not client_url:
        raise RuntimeError("client download url missing")

    client_path = os.path.join(version_dir, "client.jar")
    _update_progress(
        version_key,
        "client",
        0,
        "Downloading client.jar...",
        bytes_done=bytes_done,
        bytes_total=total_size,
    )
    print(colorize_log(f"[install] Downloading client.jar for {version_key} ({client_size} bytes)"))

    def client_cb(done: int, total: Optional[int]) -> None:
        _maybe_abort(version_key)
        pct = 0.0
        if total and total > 0:
            pct = done * 100.0 / total
        _update_progress(
            version_key,
            "client",
            pct,
            "Downloading client.jar...",
            bytes_done=bytes_done + min(done, client_size),
            bytes_total=total_size,
        )

    download_file(
        client_url,
        client_path,
        expected_sha1=client_sha1,
        progress_cb=client_cb,
        version_key=version_key,
    )
    bytes_done += client_size
    _update_progress(
        version_key,
        "client",
        100,
        "client.jar downloaded",
        bytes_done=bytes_done,
        bytes_total=total_size,
    )

    _maybe_abort(version_key)

    # ---- Libraries ----
    libs = vjson.get("libraries") or []
    total_libs = len(libs)
    done_libs = 0
    copied_lib_basenames: List[str] = []

    highest_versions: Dict[str, int] = {}
    for lib in libs:
        downloads = lib.get("downloads") or {}
        artifact = downloads.get("artifact")
        if not artifact:
            continue
        base_name = os.path.basename(artifact.get("path") or "")
        ver = _parse_lwjgl_version(base_name)
        if ver is None:
            continue
        module = base_name.split("-")[0]
        if module not in highest_versions or ver > highest_versions[module]:
            highest_versions[module] = ver

    if total_libs == 0:
        _update_progress(
            version_key,
            "libraries",
            100,
            "No libraries to download",
            bytes_done=bytes_done,
            bytes_total=total_size,
        )
    else:
        print(colorize_log(f"[install] Downloading {total_libs} libraries for {version_key}"))
        for lib in libs:
            _maybe_abort(version_key)

            downloads = lib.get("downloads") or {}
            artifact = downloads.get("artifact")
            if artifact:
                a_url = artifact.get("url")
                a_sha1 = artifact.get("sha1")
                a_path = artifact.get("path") or ""
                a_size = int(artifact.get("size") or 0)
                cache_path = os.path.join(CACHE_LIBRARIES_DIR, a_path)
                msg = f"Downloading library {done_libs + 1}/{total_libs}"

                base_name = os.path.basename(a_path) if a_path else ""

                if _should_skip_library_for_version(
                    version_id, base_name, highest_versions
                ):
                    done_libs += 1
                    pct = (done_libs * 100.0) / max(1, total_libs)
                    _update_progress(
                        version_key,
                        "libraries",
                        pct,
                        f"Libraries {done_libs}/{total_libs}",
                        bytes_done=bytes_done,
                        bytes_total=total_size,
                    )
                    continue

                def lib_cb(done_bytes: int, total_bytes: Optional[int]) -> None:
                    _maybe_abort(version_key)
                    pct = (done_libs * 100.0) / max(1, total_libs)
                    _update_progress(
                        version_key,
                        "libraries",
                        pct,
                        msg,
                        bytes_done=bytes_done + min(done_bytes, a_size),
                        bytes_total=total_size,
                    )

                if a_url and a_path:
                    # Reuse cached library if SHA1 matches
                    if (
                        os.path.exists(cache_path)
                        and a_sha1
                        and _sha1_file(cache_path).lower() == a_sha1.lower()
                    ):
                        print(
                            f"[install] Using cached library {done_libs + 1}/{total_libs}: {a_path}"
                        )
                    else:
                        print(
                            f"[install] Library {done_libs + 1}/{total_libs}: {a_path} ({a_size} bytes)"
                        )
                        download_file(
                            a_url,
                            cache_path,
                            expected_sha1=a_sha1,
                            progress_cb=lib_cb,
                            version_key=version_key,
                        )

                    bytes_done += a_size
                    dest_lib = os.path.join(version_dir, base_name)
                    os.makedirs(os.path.dirname(dest_lib), exist_ok=True)
                    if os.path.abspath(cache_path) != os.path.abspath(dest_lib):
                        with open(cache_path, "rb") as src, open(
                            dest_lib, "wb"
                        ) as dst:
                            while True:
                                _maybe_abort(version_key)
                                chunk = src.read(DOWNLOAD_CHUNK_SIZE)
                                if not chunk:
                                    break
                                dst.write(chunk)
                    copied_lib_basenames.append(base_name)

            done_libs += 1
            pct = (done_libs * 100.0) / max(1, total_libs)
            _update_progress(
                version_key,
                "libraries",
                pct,
                f"Libraries {done_libs}/{total_libs}",
                bytes_done=bytes_done,
                bytes_total=total_size,
            )

        _update_progress(
            version_key,
            "libraries",
            100,
            "Libraries downloaded",
            bytes_done=bytes_done,
            bytes_total=total_size,
        )

    _maybe_abort(version_key)

    # ---- Natives ----
    total_native_entries = 0
    for lib in libs:
        downloads = lib.get("downloads") or {}
        classifiers = downloads.get("classifiers") or {}
        total_native_entries += len(classifiers)

    done_native_entries = 0

    if total_native_entries == 0:
        _update_progress(
            version_key,
            "natives",
            100,
            "No natives to download",
            bytes_done=bytes_done,
            bytes_total=total_size,
        )
    else:
        print(
            f"[install] Downloading {total_native_entries} native entries for {version_key}"
        )
        for lib in libs:
            downloads = lib.get("downloads") or {}
            classifiers = downloads.get("classifiers") or {}
            for key, nat in classifiers.items():
                _maybe_abort(version_key)

                n_url = nat.get("url")
                n_sha1 = nat.get("sha1")
                n_path = nat.get("path") or ""
                n_size = int(nat.get("size") or 0)
                cache_path = os.path.join(CACHE_LIBRARIES_DIR, n_path)
                msg = (
                    f"Downloading natives {done_native_entries + 1}/{total_native_entries}"
                )

                def nat_cb(done_bytes: int, total_bytes: Optional[int]) -> None:
                    _maybe_abort(version_key)
                    pct = (done_native_entries * 100.0) / max(
                        1, total_native_entries
                    )
                    _update_progress(
                        version_key,
                        "natives",
                        pct,
                        msg,
                        bytes_done=bytes_done + min(done_bytes, n_size),
                        bytes_total=total_size,
                    )

                if n_url and n_path:
                    # Reuse cached native if SHA1 matches
                    if (
                        os.path.exists(cache_path)
                        and n_sha1
                        and _sha1_file(cache_path).lower() == n_sha1.lower()
                    ):
                        print(
                            f"[install] Using cached native {done_native_entries + 1}/{total_native_entries}: {n_path}"
                        )
                    else:
                        print(
                            f"[install] Native {done_native_entries + 1}/{total_native_entries}: {n_path} ({n_size} bytes)"
                        )
                        download_file(
                            n_url,
                            cache_path,
                            expected_sha1=n_sha1,
                            progress_cb=nat_cb,
                            version_key=version_key,
                        )

                    bytes_done += n_size
                    os_name = _extract_os_from_classifier_key(key) or "unknown"
                    target_dir = os.path.join(version_dir, "native", os_name)
                    os.makedirs(target_dir, exist_ok=True)
                    try:
                        with zipfile.ZipFile(cache_path, "r") as zf:
                            for member in zf.infolist():
                                _maybe_abort(version_key)
                                zf.extract(member, target_dir)
                    except Exception as e:
                        raise RuntimeError(
                            f"failed to extract natives from {n_path}: {e}"
                        )

                done_native_entries += 1
                pct = (done_native_entries * 100.0) / max(1, total_native_entries)
                _update_progress(
                    version_key,
                    "natives",
                    pct,
                    f"Natives {done_native_entries}/{total_native_entries}",
                    bytes_done=bytes_done,
                    bytes_total=total_size,
                )

        _update_progress(
            version_key,
            "natives",
            100,
            "Natives downloaded",
            bytes_done=bytes_done,
            bytes_total=total_size,
        )

    _maybe_abort(version_key)

    # ---- Assets ----
    assets_info = vjson.get("assetIndex") or {}
    assets_url = assets_info.get("url")
    asset_index_name = assets_info.get("id") or None
    assets_sha1 = assets_info.get("sha1")

    modern = _is_modern_assets(version_id)

    if assets_url and asset_index_name:
        _update_progress(
            version_key,
            "assets",
            0,
            "Downloading asset index...",
            bytes_done=bytes_done,
            bytes_total=total_size,
        )
        index_path = os.path.join(ASSETS_INDEXES_DIR, f"{asset_index_name}.json")
        os.makedirs(os.path.dirname(index_path), exist_ok=True)

        def idx_cb(done: int, total: Optional[int]) -> None:
            _maybe_abort(version_key)
            _update_progress(
                version_key,
                "assets",
                0,
                "Downloading asset index...",
                bytes_done=bytes_done,
                bytes_total=total_size,
            )

        print(colorize_log(f"[install] Downloading asset index for {version_key}: {asset_index_name}"))
        download_file(
            assets_url,
            index_path,
            expected_sha1=assets_sha1,
            progress_cb=idx_cb,
            version_key=version_key,
        )

        try:
            with open(index_path, "r", encoding="utf-8") as f:
                idx_json = json.load(f)
        except Exception as e:
            raise RuntimeError(f"failed to read asset index: {e}")

        objects = idx_json.get("objects") or {}
        keys = list(objects.keys())

        if full_assets and modern:
            asset_total = sum(int(obj.get("size") or 0) for obj in objects.values())
            total_size = bytes_done + asset_total

        if modern and not full_assets:
            _update_progress(
                version_key,
                "assets",
                100,
                "Assets will be downloaded by the game at runtime",
                bytes_done=bytes_done,
                bytes_total=total_size,
            )
        else:
            total_assets = len(keys)
            done_assets = 0

            if total_assets == 0:
                _update_progress(
                    version_key,
                    "assets",
                    100,
                    "No assets to download",
                    bytes_done=bytes_done,
                    bytes_total=total_size,
                )
            else:
                print(
                    f"[install] Downloading {total_assets} assets for {version_key}"
                )
                asset_threads = _choose_asset_threads()
                progress_lock = threading.Lock()
                
                # Track asset count and bytes separately
                asset_count_done = 0
                asset_bytes_done = 0

                def worker(asset_keys: List[str]) -> None:
                    nonlocal asset_count_done, asset_bytes_done
                    for k in asset_keys:
                        if _cancel_flags.get(version_key):
                            return
                        _check_pause(version_key)

                        obj = objects[k]
                        h = obj.get("hash")
                        size = int(obj.get("size") or 0)
                        if not h:
                            continue

                        subdir = os.path.join(h[0:2])
                        obj_path = os.path.join(ASSETS_OBJECTS_DIR, subdir, h)
                        if os.path.exists(obj_path):
                            # File already exists, just account for it
                            with progress_lock:
                                asset_count_done += 1
                                asset_bytes_done += size
                                pct = (asset_count_done * 100.0) / max(1, total_assets)
                                _update_progress(
                                    version_key,
                                    "assets",
                                    pct,
                                    f"Assets {asset_count_done}/{total_assets}",
                                    bytes_done=bytes_done + asset_bytes_done,
                                    bytes_total=total_size,
                                )
                            continue

                        obj_url = (
                            f"https://resources.download.minecraft.net/{h[0:2]}/{h}"
                        )

                        def asset_cb(done_bytes: int, total_bytes: Optional[int]) -> None:
                            _maybe_abort(version_key)
                            # Per-asset progress is noisy; we only update on completion below.

                        print(
                            f"[install] Asset {asset_count_done + 1}/{total_assets}: {h} ({size} bytes)"
                        )
                        try:
                            download_file(
                                obj_url,
                                obj_path,
                                expected_sha1=h,
                                progress_cb=asset_cb,
                                version_key=version_key,
                            )
                        except Exception as e:
                            print(colorize_log(f"[install] Failed to download asset {h}: {e}"))
                            # Don't fail entire installation for one asset
                            continue
                        
                        if _cancel_flags.get(version_key):
                            return
                        
                        # Update progress safely
                        with progress_lock:
                            asset_count_done += 1
                            asset_bytes_done += size
                            pct = (asset_count_done * 100.0) / max(1, total_assets)
                            _update_progress(
                                version_key,
                                "assets",
                                pct,
                                f"Assets {asset_count_done}/{total_assets}",
                                bytes_done=bytes_done + asset_bytes_done,
                                bytes_total=total_size,
                            )

                if keys:
                    chunks: List[List[str]] = [[] for _ in range(asset_threads)]
                    for i, k in enumerate(keys):
                        chunks[i % asset_threads].append(k)

                    threads: List[threading.Thread] = []
                    for chunk in chunks:
                        if not chunk:
                            continue
                        t = threading.Thread(
                            target=worker, args=(chunk,), daemon=True
                        )
                        threads.append(t)
                        t.start()
                    for t in threads:
                        t.join()

                _update_progress(
                    version_key,
                    "assets",
                    100,
                    "Assets downloaded",
                    bytes_done=bytes_done,
                    bytes_total=total_size,
                )
    else:
        _update_progress(
            version_key,
            "assets",
            100,
            "No assets required",
            bytes_done=bytes_done,
            bytes_total=total_size,
        )

    _maybe_abort(version_key)

    # ---- Finalize / metadata ----
    vtype = entry.get("type", "")
    img_url = _wiki_image_url(version_id, vtype)
    if img_url:
        try:
            _update_progress(
                version_key,
                "finalize",
                0,
                "Downloading display image...",
                bytes_done=bytes_done,
                bytes_total=total_size,
            )
            display_path = os.path.join(version_dir, "display.png")

            def img_cb(done_bytes: int, total_bytes: Optional[int]) -> None:
                _maybe_abort(version_key)

            print(colorize_log(f"[install] Downloading display image for {version_key}"))
            download_file(
                img_url,
                display_path,
                expected_sha1=None,
                progress_cb=img_cb,
                version_key=version_key,
            )
        except Exception: pass

    _update_progress(
        version_key,
        "finalize",
        50,
        "Writing metadata...",
        bytes_done=bytes_done,
        bytes_total=total_size,
    )

    main_class = vjson.get("mainClass") or "net.minecraft.client.Minecraft"
    extra_args = _extract_extra_args(vjson)
    version_type = entry.get("type", "") or vjson.get("type", "")

    seen_libs = set()
    unique_libs: List[str] = []
    for name in copied_lib_basenames:
        if name not in seen_libs:
            seen_libs.add(name)
            unique_libs.append(name)

    cp_entries = ["client.jar"] + unique_libs
    classpath_str = ",".join(cp_entries)

    data_ini_path = os.path.join(version_dir, "data.ini")
    lines = [
        f"main_class={main_class}",
        f"classpath={classpath_str}",
        f"asset_index={asset_index_name or ''}",
        f"version_type={version_type}",
        f"full_assets={'true' if full_assets else 'false'}",
        f"total_size_bytes={total_size}",
    ]
    if extra_args:
        lines.append(f"extra_jvm_args={extra_args}")
    lines.append("launch_disabled=false")

    with open(data_ini_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    _update_progress(
        version_key,
        "finalize",
        100,
        "Installation complete",
        bytes_done=bytes_done,
        bytes_total=total_size,
    )

    try:
        write_progress(
            version_key,
            {
                "status": "installed",
                "stage": "finalize",
                "stage_percent": 100,
                "overall_percent": 100,
                "message": "Installation complete",
                "bytes_done": int(bytes_done),
                "bytes_total": int(total_size),
            },
        )
        def delayed_cleanup():
            time.sleep(0.5)
            delete_progress(version_key)
        
        cleanup_thread = threading.Thread(target=delayed_cleanup, daemon=True)
        cleanup_thread.start()
    except Exception:
        pass

    try:
        notification.notify(
            title=f"[{version_id}] Installation complete!",
            message=f"Minecraft {version_id} has installed successfully!",
            app_icon=os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "ui",
                "assets",
                "images",
                "histolauncher_256x256.ico",
            ),
        )
    except Exception:
        pass

    print(colorize_log(f"[install] Installation complete for {version_key}"))


# ---------------- Public API ----------------


def _version_key(version_id: str, storage_category: str) -> str:
    return f"{storage_category}/{version_id}"


def install_version(
    version_id: str,
    storage_category: str = "Release",
    full_assets: bool = True,
    background: bool = True,
) -> None:
    version_key = _version_key(version_id, storage_category)

    if background:
        t = _workers.get(version_key)
        if t and t.is_alive():
            print(colorize_log(f"[install] Worker already running for {version_key}"))
            return

        def runner() -> None:
            vk = _version_key(version_id, storage_category)
            storage_fs = _normalize_storage_category(storage_category)
            version_dir = os.path.join(DOWNLOAD_DIR, storage_fs, version_id)

            cancelled = False
            failed = False
            error_message = ""

            try:
                _install_version(version_id, storage_category, full_assets)
            except RuntimeError as e:
                if str(e) == "cancelled":
                    cancelled = True
                    print(colorize_log(f"[install] Installation cancelled for {vk}"))
                    write_progress(
                        vk,
                        {
                            "status": "cancelled",
                            "stage": "finalize",
                            "stage_percent": 0,
                            "overall_percent": 0,
                            "message": "Installation cancelled",
                            "bytes_done": 0,
                            "bytes_total": 0,
                        },
                    )

                    time.sleep(0.5)
                    delete_progress(vk)
                else:
                    failed = True
                    error_message = str(e)
                    print(colorize_log(f"[install] Error during install for {vk}: {e}"))
                    write_progress(
                        vk,
                        {
                            "status": "error",
                            "stage": "finalize",
                            "stage_percent": 0,
                            "overall_percent": 0,
                            "message": error_message,
                            "bytes_done": 0,
                            "bytes_total": 0,
                        },
                    )

                    time.sleep(2.0)
                    delete_progress(vk)
                    
                    # Send error notification to user
                    try:
                        notification.notify(
                            title=f"[{version_id}] Download failed.",
                            message=f"Failed to install {version_id}: {error_message}",
                            app_icon=os.path.join(
                                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "ui",
                                "assets",
                                "images",
                                "histolauncher_256x256.ico",
                            ),
                        )
                    except Exception as notif_err:
                        print(colorize_log(f"[install] Failed to send notification: {notif_err}"))
            finally:
                if cancelled or failed:
                    try:
                        if os.path.isdir(version_dir):
                            print(
                                f"[install] Removing incomplete folder: {version_dir}"
                            )
                            shutil.rmtree(version_dir)
                    except Exception as cleanup_err:
                        print(colorize_log(f"[install] Cleanup failed: {cleanup_err}"))

                _workers.pop(vk, None)
                _cancel_flags.pop(vk, None)
                _pause_flags.pop(vk, None)

        worker = threading.Thread(target=runner, daemon=True)
        _workers[version_key] = worker
        worker.start()
    else:
        _install_version(version_id, storage_category, full_assets)


def cancel_install(version_id: str, storage_category: str = "Release") -> None:
    version_key = _version_key(version_id, storage_category)
    print(colorize_log(f"[install] Cancel requested for {version_key}"))
    _cancel_flags[version_key] = True
    _pause_flags.pop(version_key, None)


def pause_install(version_id: str, storage_category: str = "Release") -> None:
    version_key = _version_key(version_id, storage_category)
    print(colorize_log(f"[install] Pause requested for {version_key}"))
    _pause_flags[version_key] = True


def resume_install(version_id: str, storage_category: str = "Release") -> None:
    version_key = _version_key(version_id, storage_category)
    print(colorize_log(f"[install] Resume requested for {version_key}"))
    _pause_flags[version_key] = False


def is_installing(version_id: str, storage_category: str = "Release") -> bool:
    version_key = _version_key(version_id, storage_category)
    t = _workers.get(version_key)
    return bool(t and t.is_alive())


def get_install_status(
    version_id: str, storage_category: str = "Release"
) -> Optional[Dict[str, Any]]:
    version_key = _version_key(version_id, storage_category)
    prog = read_progress(version_key)
    if not prog:
        # Progress file doesn't exist - check if version is actually installed
        try:
            base_dir = get_base_dir()
            clients_dir = os.path.join(base_dir, "clients")
            version_dir = os.path.join(clients_dir, storage_category.lower(), version_id.lower())
            
            # If the version directory exists and has a data.ini file, it's installed
            if os.path.isdir(version_dir):
                data_ini = os.path.join(version_dir, "data.ini")
                if os.path.isfile(data_ini):
                    return {
                        "status": "installed",
                        "stage": "finalize",
                        "stage_percent": 100,
                        "overall_percent": 100,
                        "message": "Installation complete",
                    }
        except Exception:
            pass
        
        return None
    if _pause_flags.get(version_key):
        prog["status"] = "paused"
    return prog


# =============== MOD LOADER INSTALLATION ===============


def download_loader(
    loader_type: str,
    mc_version: str,
    loader_version: str,
    category: str,
    folder: str,
) -> Dict[str, Any]:
    if loader_type.lower() not in ["fabric", "forge"]:
        return {"ok": False, "error": "Invalid loader type"}
    
    loader_type = loader_type.lower()
    blocked_forge_versions = {"1.2.4", "1.2.3", "1.1"}
    if loader_type == "forge" and mc_version in blocked_forge_versions:
        return {
            "ok": False,
            "error": (
                f"Forge installation is disabled for Minecraft {mc_version}. "
                "These legacy Forge builds are ModLoader addons and are not supported by automatic Forge installation."
            ),
        }

    # Use special version key format for modloaders: {category}/{folder}/modloader-{type}-{version}
    version_key = f"{category.lower()}/{folder}/modloader-{loader_type}-{loader_version}"
    
    try:
        # Import here to avoid circular deps
        from core.modloaders import (
            get_fabric_installer_url,
            get_forge_installer_url,
        )
        from core.version_manager import ensure_loaders_dir
        
        loader_name = "Fabric" if loader_type == "fabric" else "Forge"
        
        # Initialize progress tracking
        _update_progress(
            version_key,
            "download",
            0,
            f"Starting {loader_name} installation..."
        )
        
        loaders_dir = ensure_loaders_dir(category, folder)
        
        _update_progress(
            version_key,
            "download",
            10,
            f"Preparing {loader_name} installer..."
        )
        
        if loader_type == "fabric":
            result = _install_fabric_loader(
                mc_version, loader_version, loaders_dir, version_key
            )
        else:  # forge
            result = _install_forge_loader(
                mc_version, loader_version, loaders_dir, version_key
            )
        
        # Update final progress state
        if result.get("ok"):
            _update_progress(
                version_key,
                "finalize",
                100,
                f"{loader_name} installation complete"
            )
            
            time.sleep(0.2)
            delete_progress(version_key)
        else:
            error_msg = result.get("error", "Unknown error")
            _update_progress(
                version_key,
                "error",
                0,
                f"{loader_name} installation failed: {error_msg}"
            )
            
            write_progress(
                version_key,
                {
                    "status": "failed",
                    "stage": "error",
                    "stage_percent": 0,
                    "overall_percent": 0,
                    "message": error_msg,
                    "bytes_done": 0,
                    "bytes_total": 0,
                },
            )

            time.sleep(2.0)
            delete_progress(version_key)
        
        return result
    
    except RuntimeError as e:
        if "cancel" in str(e).lower():
            error_msg = "Loader installation cancelled by user"
            print(colorize_log(f"[downloader] {loader_type.capitalize()} loader installation cancelled"))
            # Clean up the partial loader directory
            try:
                loader_dir = os.path.join(os.path.dirname(loaders_dir), f"{loader_type}")
                if os.path.exists(loader_dir):
                    # Only clean up version subdirs that are incomplete
                    version_dir = os.path.join(loader_dir, loader_version)
                    if os.path.exists(version_dir):
                        shutil.rmtree(version_dir, ignore_errors=True)
            except Exception as cleanup_err:
                print(colorize_log(f"[downloader] Warning: Could not clean up partial loader: {cleanup_err}"))
            
            write_progress(
                version_key,
                {
                    "status": "cancelled",
                    "stage": "error",
                    "stage_percent": 0,
                    "overall_percent": 0,
                    "message": error_msg,
                    "bytes_done": 0,
                    "bytes_total": 0,
                },
            )
            time.sleep(0.5)
            delete_progress(version_key)
            return {"ok": False, "error": error_msg}
        else:
            # Other runtime errors
            error_msg = f"Failed to install loader: {str(e)}"
            print(colorize_log(f"[downloader] Error installing {loader_type} loader: {e}"))
            write_progress(
                version_key,
                {
                    "status": "failed",
                    "stage": "error",
                    "stage_percent": 0,
                    "overall_percent": 0,
                    "message": error_msg,
                    "bytes_done": 0,
                    "bytes_total": 0,
                },
            )
            time.sleep(2.0)
            delete_progress(version_key)
            return {"ok": False, "error": error_msg}
    
    except Exception as e:
        error_msg = f"Failed to install loader: {str(e)}"
        print(colorize_log(f"[downloader] Error installing {loader_type} loader: {e}"))
        
        # Log error to progress tracking
        write_progress(
            version_key,
            {
                "status": "failed",
                "stage": "error",
                "stage_percent": 0,
                "overall_percent": 0,
                "message": error_msg,
                "bytes_done": 0,
                "bytes_total": 0,
            },
        )

        time.sleep(2.0)
        delete_progress(version_key)
        
        return {"ok": False, "error": error_msg}


def _get_failed_yarn_builds(version_dir: str) -> set:
    failed_file = os.path.join(version_dir, ".failed_yarn_builds.txt")
    if not os.path.exists(failed_file):
        return set()
    try:
        with open(failed_file, "r") as f:
            return set(line.strip() for line in f if line.strip())
    except Exception:
        return set()


def _record_failed_yarn_build(version_dir: str, build_id: str) -> None:
    failed_file = os.path.join(version_dir, ".failed_yarn_builds.txt")
    try:
        failed_builds = _get_failed_yarn_builds(version_dir)
        if build_id not in failed_builds:
            with open(failed_file, "a") as f:
                f.write(f"{build_id}\n")
    except Exception:
        pass


def _download_yarn_mappings(version_dir: str, mc_version: str, version_key: str) -> Optional[str]:
    try:
        # Check for existing Yarn mappings (reuse if found)
        try:
            for filename in os.listdir(version_dir):
                if filename.startswith(f"yarn-{mc_version}-build.") and filename.endswith(".jar"):
                    yarn_path = os.path.join(version_dir, filename)
                    print(colorize_log(f"[fabric] Using existing Yarn mappings: {filename}"))
                    return yarn_path
        except Exception:
            pass
        
        # Load previously failed builds to skip them
        failed_builds = _get_failed_yarn_builds(version_dir)
        
        # Try builds in descending order (8, 7, 6, ..., 1)
        # This is generic - try up to 20 builds to cover most versions
        max_build_attempts = 20
        attempted_builds = []
        
        for build_num in range(max_build_attempts, 0, -1):
            build_id = f"build.{build_num}"
            
            # Skip if this build is known to have failed
            if build_id in failed_builds:
                continue
            
            # URL-encode the version string (+ becomes %2B)
            version_code = f"{mc_version}%2Bbuild.{build_num}"
            safe_filename = f"yarn-{mc_version}-build.{build_num}.jar"
            yarn_path = os.path.join(version_dir, safe_filename)
            
            attempted_builds.append(build_id)
            
            base_url = f"https://maven.fabricmc.net/net/fabricmc/yarn/{version_code}/yarn-{version_code}.jar"
            
            # Try download with proxy first
            try:
                proxied_url = _apply_url_proxy(base_url)
                req = urllib.request.Request(proxied_url, headers={"User-Agent": "Histolauncher"})
                with urllib.request.urlopen(req, timeout=30) as response:
                    with open(yarn_path, "wb") as f:
                        f.write(response.read())
                if os.path.exists(yarn_path):
                    print(colorize_log(f"[fabric] Downloaded Yarn {build_id} ({os.path.getsize(yarn_path) / (1024*1024):.1f}MB)"))
                    return yarn_path
            except Exception:
                pass
            
            # Try direct download as fallback
            try:
                req = urllib.request.Request(base_url, headers={"User-Agent": "Histolauncher"})
                with urllib.request.urlopen(req, timeout=30) as response:
                    with open(yarn_path, "wb") as f:
                        f.write(response.read())
                if os.path.exists(yarn_path):
                    print(colorize_log(f"[fabric] Downloaded Yarn {build_id} ({os.path.getsize(yarn_path) / (1024*1024):.1f}MB)"))
                    return yarn_path
            except Exception:
                pass
            
            # Try with unverified SSL as fallback
            try:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(base_url, headers={"User-Agent": "Histolauncher"})
                with urllib.request.urlopen(req, context=context, timeout=30) as response:
                    with open(yarn_path, "wb") as f:
                        f.write(response.read())
                if os.path.exists(yarn_path):
                    print(colorize_log(f"[fabric] Downloaded Yarn {build_id} (unverified SSL)"))
                    return yarn_path
            except Exception:
                pass
            
            # Clean up failed download
            if os.path.exists(yarn_path):
                try:
                    os.remove(yarn_path)
                except Exception:
                    pass
        
        # All builds failed
        print(colorize_log(f"[fabric] Could not download any Yarn mappings for {mc_version}"))
        if failed_builds:
            print(colorize_log(f"[fabric] (Skipped known failures: {', '.join(sorted(failed_builds))})"))
        return None
        
    except Exception as e:
        print(colorize_log(f"[fabric] ERROR downloading Yarn: {e}"))
        return None


def _install_fabric_loader(
    mc_version: str, loader_version: str, loaders_dir: str, version_key: str
) -> Dict[str, Any]:
    _cancel_flags.pop(version_key, None)
    
    try:
        from core.modloaders import _http_get_json
        
        print(colorize_log(f"[fabric] Installing Fabric loader version {loader_version}"))
        
        loader_dest_dir = os.path.join(loaders_dir, "fabric", loader_version)
        os.makedirs(loader_dest_dir, exist_ok=True)
        
        print(colorize_log(f"[fabric] Cleaning up old library versions..."))
        try:
            for filename in os.listdir(loader_dest_dir):
                if filename.startswith("asm-") and filename.endswith(".jar"):
                    if "9.9" not in filename and "9.7" not in filename:
                        old_jar = os.path.join(loader_dest_dir, filename)
                        try:
                            os.remove(old_jar)
                            print(colorize_log(f"[fabric] Removed old ASM: {filename}"))
                        except Exception as e:
                            print(colorize_log(f"[fabric] Could not remove {filename}: {e}"))
                # Remove old Mixin versions (Fabric uses sponge-mixin now)
                elif filename.startswith("mixin-") and filename.endswith(".jar"):
                    old_jar = os.path.join(loader_dest_dir, filename)
                    try:
                        os.remove(old_jar)
                        print(colorize_log(f"[fabric] Removed old standalone Mixin: {filename}"))
                    except Exception as e:
                        print(colorize_log(f"[fabric] Could not remove {filename}: {e}"))
        except Exception as e:
            print(colorize_log(f"[fabric] Error during cleanup: {e}"))
        
        from core.modloaders import get_fabric_loader_libraries
        libraries = get_fabric_loader_libraries(loader_version, mc_version)
        
        if not libraries:
            print(colorize_log(f"[fabric] ERROR: Failed to get any libraries for Fabric {loader_version}"))
            return {"ok": False, "error": "No libraries to download"}
        
        print(f"[fabric] Will download {len(libraries)} libraries")
        for lib_name, maven_base in libraries:
            print(f"[fabric]   - {lib_name} from {maven_base}")
        
        jars_downloaded = 0
        total_libs = len(libraries)
        
        bytes_done = 0

        for idx, (lib_name, maven_base) in enumerate(libraries):
            parts = lib_name.split(":", 2)
            if len(parts) < 3:
                print(colorize_log(f"[fabric] Invalid library: {lib_name}"))
                continue

            group = parts[0].replace(".", "/")
            artifact = parts[1]
            version_str = parts[2]
            # URL-encode the version string to handle special characters like '+' -> '%2B'
            version_encoded = urllib.parse.quote(version_str, safe='')

            lib_url = f"{maven_base}/{group}/{artifact}/{version_encoded}/{artifact}-{version_encoded}.jar"
            lib_dest_path = os.path.join(loader_dest_dir, f"{artifact}-{version_str}.jar")

            if artifact == "yarn":
                print(colorize_log(f"[fabric] Attempting to download Yarn mappings from: {lib_url}"))

            if os.path.exists(lib_dest_path):
                jars_downloaded += 1
                pct = (jars_downloaded * 100.0) / max(1, total_libs)
                try:
                    file_size = os.path.getsize(lib_dest_path)
                    bytes_done += file_size
                except Exception:
                    pass
                _update_progress(version_key, "downloading_libs", pct,
                                 f"Libraries {jars_downloaded}/{total_libs}",
                                 bytes_done, 0)
                continue

            pct = (jars_downloaded * 100.0) / max(1, total_libs)
            _update_progress(version_key, "downloading_libs", pct,
                             f"Downloading {artifact} ({jars_downloaded + 1}/{total_libs})...",
                             bytes_done, 0)

            try:
                print(colorize_log(f"[fabric] Downloading {artifact}-{version_str}.jar..."))

                download_file(lib_url, lib_dest_path, version_key=version_key, progress_cb=None)

                if os.path.exists(lib_dest_path):
                    jars_downloaded += 1
                    pct = (jars_downloaded * 100.0) / max(1, total_libs)
                    try:
                        file_size = os.path.getsize(lib_dest_path)
                        bytes_done += file_size
                    except Exception:
                        file_size = 0
                    print(colorize_log(f"[fabric] Downloaded {artifact}-{version_str}.jar ({file_size} bytes)"))
                    _update_progress(version_key, "downloading_libs", pct,
                                     f"Libraries {jars_downloaded}/{total_libs}",
                                     bytes_done, 0)
                else:
                    print(colorize_log(f"[fabric] Failed to verify {artifact}-{version_str}.jar download"))

            except RuntimeError as e:
                # Cancellation
                if "cancel" in str(e).lower():
                    print(colorize_log(f"[fabric] Download cancelled - cleaning up"))
                    _safe_remove_file(lib_dest_path)
                    raise
                # Other runtime errors
                print(colorize_log(f"[fabric] Error downloading {artifact}-{version_str}.jar: {e}"))
                # If it's fabric-loader (critical), return error
                if artifact == "fabric-loader":
                    return {"ok": False, "error": f"Failed to download {artifact}: {str(e)}"}
                # For yarn mappings, log the error but continue (it's optional for now)
                if artifact == "yarn":
                    print(colorize_log(f"[fabric] WARNING: Yarn mappings could not be downloaded, some mods may not work"))
                # Continue with non-critical libraries
                continue
            except Exception as e:
                print(colorize_log(f"[fabric] Error downloading {artifact}-{version_str}.jar: {e}"))
                # If it's fabric-loader (critical), return error
                if artifact == "fabric-loader":
                    return {"ok": False, "error": f"Failed to download {artifact}: {str(e)}"}
                # For yarn mappings, log the error but continue (it's optional for now)
                if artifact == "yarn":
                    print(colorize_log(f"[fabric] WARNING: Yarn mappings could not be downloaded, some mods may not work"))
                # Continue with non-critical libraries
                continue
        
        if jars_downloaded == 0:
            return {"ok": False, "error": "Could not download any Fabric libraries"}
        
        _update_progress(version_key, "extracting_loader", 100, f"Fabric loader installed ({jars_downloaded} JARs)")
        print(colorize_log(f"[fabric] Successfully downloaded {jars_downloaded} libraries"))
        
        # Try to download Yarn mappings for better mod compatibility
        # This is optional - Fabric will work without them but some mods may have issues
        version_dir = os.path.dirname(loaders_dir)
        yarn_jar = _download_yarn_mappings(version_dir, mc_version, version_key)
        if yarn_jar:
            print(colorize_log(f"[fabric] Yarn mappings available for enhanced mod compatibility"))
        else:
            print(colorize_log(f"[fabric] Yarn mappings not available (optional), Fabric will still work with basic mods"))
        
        result = {"ok": True, "loader_version": loader_version}
        
        # Note: Do NOT delete progress file here - let download_loader() handle cleanup
        # This keeps the progress file available for frontend polling
        
        return result
    
    except Exception as e:
        print(colorize_log(f"[fabric] Error: {e}"))
        traceback.print_exc()
        _update_progress(version_key, "failed", 0, "Failed to install loader")
        return {"ok": False, "error": str(e)}


def _install_forge_loader(
    mc_version: str, loader_version: str, loaders_dir: str, version_key: str
) -> Dict[str, Any]:
    _cancel_flags.pop(version_key, None)
    
    version_dir = os.path.dirname(loaders_dir)

    def _is_modlauncher_era(mc_ver: str) -> bool:
        try:
            parts = (mc_ver or "").split(".")
            major = int(parts[0]) if len(parts) > 0 else 0
            minor = int(parts[1]) if len(parts) > 1 else 0
            return major > 1 or (major == 1 and minor >= 13)
        except Exception:
            return False

    modlauncher_era = _is_modlauncher_era(mc_version)
    
    try:
        from core.modloaders import get_forge_artifact_urls

        artifact_urls = get_forge_artifact_urls(mc_version, loader_version)
        if not artifact_urls:
            return {"ok": False, "error": "Could not resolve Forge artifact URLs"}
        
        with tempfile.TemporaryDirectory() as temp_dir:
            downloaded_artifact_path = ""
            downloaded_artifact_name = ""
            is_installer_archive = False

            _update_progress(version_key, "download", 0, "Downloading Forge package...")
            
            # Download with progress hook
            def progress_hook(downloaded, total):
                if _cancel_flags.get(version_key):
                    raise RuntimeError("Download cancelled by user")
                percent = int(100 * downloaded / total) if total > 0 else 0
                _update_progress(version_key, "download", percent, f"Downloading installer {percent}%...", downloaded, 0)
            
            last_download_error = None
            for artifact_url in artifact_urls:
                artifact_name = os.path.basename(urllib.parse.urlparse(artifact_url).path) or "forge-artifact.jar"
                artifact_path = os.path.join(temp_dir, artifact_name)
                print(f"[forge] Downloading Forge artifact from {artifact_url}")
                try:
                    download_file(artifact_url, artifact_path, version_key=version_key, progress_cb=progress_hook)
                    if os.path.exists(artifact_path) and os.path.getsize(artifact_path) > 0:
                        downloaded_artifact_path = artifact_path
                        downloaded_artifact_name = artifact_name
                        is_installer_archive = artifact_name.lower().endswith("-installer.jar")
                        print(colorize_log(f"[forge] Using Forge artifact: {artifact_name}"))
                        break
                except RuntimeError as e:
                    if "cancel" in str(e).lower():
                        print(colorize_log(f"[forge] Download cancelled"))
                        _safe_remove_file(artifact_path)
                        raise
                    last_download_error = str(e)
                    _safe_remove_file(artifact_path)
                    print(colorize_log(f"[forge] Download failed for {artifact_name}: {e}"))
                except Exception as e:
                    last_download_error = str(e)
                    _safe_remove_file(artifact_path)
                    print(colorize_log(f"[forge] Download failed for {artifact_name}: {e}"))

            if not downloaded_artifact_path:
                return {"ok": False, "error": f"Failed to download Forge artifact: {last_download_error or 'all URLs failed'}"}

            # Prepare extraction staging area.
            _update_progress(version_key, "extracting_loader", 25, "Preparing Forge package...")
            extraction_dir = os.path.join(temp_dir, "forge_extracted")
            os.makedirs(extraction_dir, exist_ok=True)

            lower_name = downloaded_artifact_name.lower()
            is_legacy_universal_archive = (
                lower_name.endswith(".zip")
                and (not is_installer_archive)
                and (not modlauncher_era)
            )
            if lower_name.endswith(".zip"):
                try:
                    with zipfile.ZipFile(downloaded_artifact_path, 'r') as zip_ref:
                        zip_ref.extractall(extraction_dir)
                except Exception as e:
                    print(f"[forge] ZIP extraction error: {e}")
                    return {"ok": False, "error": f"Failed to extract Forge archive: {str(e)}"}
            elif is_installer_archive:
                try:
                    with zipfile.ZipFile(downloaded_artifact_path, 'r') as zip_ref:
                        zip_ref.extractall(extraction_dir)
                except Exception as e:
                    print(f"[forge] Installer extraction error: {e}")
                    return {"ok": False, "error": f"Failed to extract Forge installer: {str(e)}"}
            else:
                # Legacy universal JARs are runtime artifacts; keep JAR intact for classpath use.
                try:
                    shutil.copy2(downloaded_artifact_path, os.path.join(extraction_dir, downloaded_artifact_name))
                except Exception as e:
                    return {"ok": False, "error": f"Failed to stage Forge artifact: {str(e)}"}
            
            # Create loader destination directory
            loader_dest_dir = os.path.join(loaders_dir, "forge", loader_version)
            os.makedirs(loader_dest_dir, exist_ok=True)
            
            jars_copied = 0
            files_copied = 0
            
            # Parse install_profile.json for metadata
            profile_data = None
            profile_path = os.path.join(extraction_dir, "install_profile.json")
            metadata_dir = os.path.join(loader_dest_dir, ".metadata")
            os.makedirs(metadata_dir, exist_ok=True)
            
            if os.path.exists(profile_path):
                try:
                    with open(profile_path, 'r') as f:
                        profile_data = json.load(f)
                    print(f"[forge] Parsed install_profile.json")
                    # Save install_profile.json to a metadata subdirectory (NOT in classpath root)
                    dst_profile = os.path.join(metadata_dir, "install_profile.json")
                    shutil.copy2(profile_path, dst_profile)
                    print(f"[forge] Saved install_profile.json to metadata")
                except Exception as e:
                    print(f"[forge] WARNING: Could not parse install_profile.json: {e}")
            
            # Also save version.json to metadata for reference
            version_json_src = os.path.join(extraction_dir, "version.json")
            if os.path.exists(version_json_src):
                try:
                    dst_version = os.path.join(metadata_dir, "version.json")
                    shutil.copy2(version_json_src, dst_version)
                    print(f"[forge] Saved version.json to metadata")
                except Exception as e:
                    print(f"[forge] WARNING: Could not save version.json: {e}")
            
            # Extract log4j configuration files (critical for 1.16.5+)
            print(f"[forge] Extracting configuration files...")
            for root, dirs, files in os.walk(extraction_dir):
                for filename in files:
                    # Extract configuration files - DO NOT extract version.json or install_profile.json to classpath
                    if filename in ["log4j2.xml", "log4j.properties", "log4j.xml"] or filename.endswith(".properties"):
                        src_file = os.path.join(root, filename)
                        dst_file = os.path.join(loader_dest_dir, filename)
                        try:
                            shutil.copy2(src_file, dst_file)
                            files_copied += 1
                            print(f"[forge] Extracted config: {filename}")
                        except Exception as e:
                            print(f"[forge] Warning: Could not copy {filename}: {e}")
            
            # Extract all JARs - try both maven/ (1.17+) and libraries/ (1.12.2) directories
            libraries_extracted = 0
            
            # Try maven directory first (Forge 1.13+)
            maven_dir = os.path.join(extraction_dir, "maven")
            if os.path.isdir(maven_dir):
                print(f"[forge] Extracting from maven directory (Forge 1.13+)...")
                for root, dirs, files in os.walk(maven_dir):
                    for filename in files:
                        if filename.endswith(".jar"):
                            src_jar = os.path.join(root, filename)
                            # Preserve Maven directory structure in libraries/ subdir.
                            # ModLauncher (1.13+) resolves artifacts by Maven path, so the
                            # structure net/minecraftforge/forge/{ver}/forge-{ver}.jar must be intact.
                            rel_path = os.path.relpath(src_jar, maven_dir)
                            dst_jar_structured = os.path.join(loader_dest_dir, "libraries", rel_path)
                            os.makedirs(os.path.dirname(dst_jar_structured), exist_ok=True)
                            if not os.path.exists(dst_jar_structured):
                                try:
                                    shutil.copy2(src_jar, dst_jar_structured)
                                    jars_copied += 1
                                    libraries_extracted += 1
                                    if libraries_extracted <= 20:  # Log first 20 for debugging
                                        print(f"[forge] Copied (structured): {rel_path}")
                                except Exception as e:
                                    print(f"[forge] Failed to copy {filename}: {e}")
                            # Also keep a flat copy at the loader root for backward-compat
                            # classpath scanning that looks for JARs by filename only.
                            dst_jar_flat = os.path.join(loader_dest_dir, filename)
                            if not os.path.exists(dst_jar_flat):
                                try:
                                    shutil.copy2(src_jar, dst_jar_flat)
                                except Exception:
                                    pass
                print(f"[forge] Extracted {jars_copied} JARs from maven")
            
            # Try libraries directory (Forge 1.12.2 and older)
            libraries_dir = os.path.join(extraction_dir, "libraries")
            if os.path.isdir(libraries_dir):
                print(f"[forge] Extracting from libraries directory (Forge < 1.13)...")
                # Create libraries structure in loader directory to match Forge manifest paths
                dst_libraries_dir = os.path.join(loader_dest_dir, "libraries")
                os.makedirs(dst_libraries_dir, exist_ok=True)
                
                for root, dirs, files in os.walk(libraries_dir):
                    for filename in files:
                        if filename.endswith(".jar"):
                            src_jar = os.path.join(root, filename)
                            # Preserve directory structure: libraries/org/... -> loader/libraries/org/...
                            rel_path = os.path.relpath(src_jar, libraries_dir)
                            dst_jar = os.path.join(dst_libraries_dir, rel_path)
                            os.makedirs(os.path.dirname(dst_jar), exist_ok=True)
                            try:
                                shutil.copy2(src_jar, dst_jar)
                                jars_copied += 1
                                libraries_extracted += 1
                                if libraries_extracted <= 20:  # Log first 20 for debugging
                                    print(f"[forge] Copied: {rel_path}")
                            except Exception as e:
                                print(f"[forge] Failed to copy {filename}: {e}")
                print(f"[forge] Extracted {libraries_extracted} libraries from libraries/")
                
                # The libraries/ directory must be in the classpath for manifest Class-Path to work
                # This allows launchwrapper and other dependencies to be found
            
            if libraries_extracted == 0:
                print(f"[forge] WARNING: No pre-extracted libraries found!")
                print(f"[forge] Will download all libraries from version.json metadata...")
            
            # Parse version.json or install_profile.json for library information
            # Two formats exist:
            # 1. New format (Forge 1.12.2+): version.json with complete artifact info
            # 2. Old format (Forge 1.12.1 and earlier): install_profile.json.versionInfo.libraries
            version_json_path = os.path.join(extraction_dir, "version.json")
            install_profile_path = os.path.join(extraction_dir, "install_profile.json")
            loader_libraries_dir = os.path.join(loader_dest_dir, "libraries")
            os.makedirs(loader_libraries_dir, exist_ok=True)
            
            libraries = []
            
            # Try new format first (Forge 1.12.2+)
            if os.path.exists(version_json_path):
                try:
                    with open(version_json_path, 'r') as f:
                        version_data = json.load(f)
                    libraries = version_data.get("libraries", [])
                    print(f"[forge] Found {len(libraries)} libraries in version.json (new format)")
                except Exception as e:
                    print(f"[forge] WARNING: Could not parse version.json: {e}")
            
            # Try old format if no libraries found (Forge 1.12.1 and earlier)
            if not libraries and os.path.exists(install_profile_path):
                try:
                    with open(install_profile_path, 'r') as f:
                        install_data = json.load(f)
                    version_info = install_data.get("versionInfo", {})
                    libraries = version_info.get("libraries", [])
                    if libraries:
                        print(f"[forge] Found {len(libraries)} libraries in install_profile.json versionInfo (old format)")
                except Exception as e:
                    print(f"[forge] WARNING: Could not parse install_profile.json: {e}")
            
            if libraries:
                try:
                    print(f"[forge] Processing {len(libraries)} libraries from Forge metadata")
                    
                    downloaded_libs = set()
                    libs_count = 0
                    
                    bytes_done = 0
                    bytes_total = 0
                    for lib in libraries:
                        try:
                            if isinstance(lib, dict):
                                artifact_info = (lib.get("downloads") or {}).get("artifact") or {}
                                size_hint = artifact_info.get("size")
                                if size_hint is not None:
                                    bytes_total += int(size_hint)
                        except Exception:
                            continue

                    for lib in libraries:
                        lib_name = lib.get("name", "") if isinstance(lib, dict) else lib
                        if not lib_name or ("net.minecraftforge:forge:" in lib_name and ":client" in lib_name):
                            continue
                        
                        if lib_name in downloaded_libs:
                            continue
                        
                        download_url = None
                        expected_sha1 = None
                        jar_path = None
                        
                        if isinstance(lib, dict) and lib.get("downloads"):
                            # New format: version.json with artifact info
                            artifact_info = lib.get("downloads", {}).get("artifact")
                            if artifact_info:
                                download_url = artifact_info.get("url", "")
                                expected_sha1 = artifact_info.get("sha1", "")
                                artifact_path = artifact_info.get("path", "")
                                if artifact_path:
                                    jar_path = os.path.join(loader_libraries_dir, artifact_path)
                        else:
                            # Old format: just Maven library name
                            # net.minecraft:launchwrapper:1.12 -> net/minecraft/launchwrapper/1.12/launchwrapper-1.12.jar
                            parts = lib_name.split(':')
                            if len(parts) >= 3:
                                group = parts[0].replace(".", "/")
                                artifact = parts[1]
                                version = parts[2]
                                jar_name = f"{artifact}-{version}.jar"
                                jar_path = os.path.join(loader_libraries_dir, group, artifact, version, jar_name)
                                
                                # Try multiple Maven repositories for old Forge libraries
                                maven_path = f"{group}/{artifact}/{version}/{jar_name}"
                                maven_repos = [
                                    "https://maven.minecraftforge.net/",  # Primary: most Forge libs here
                                    "https://libraries.minecraft.net/",
                                    "https://repo1.maven.org/maven2/",
                                ]
                                # Set first repo as default, will try others as fallback
                                download_url = maven_repos[0] + maven_path
                        
                        if not jar_path:
                            # Fallback: construct path from lib_name
                            parts = lib_name.split(':')
                            if len(parts) < 3:
                                print(f"[forge] WARNING: Invalid library name: {lib_name}")
                                continue
                            group = parts[0].replace(".", "/")
                            artifact = parts[1]
                            version = parts[2]
                            jar_name = f"{artifact}-{version}.jar"
                            jar_path = os.path.join(loader_libraries_dir, group, artifact, version, jar_name)
                        
                        if not download_url:
                            print(f"[forge] WARNING: No download URL for {lib_name}")
                            continue
                        
                        os.makedirs(os.path.dirname(jar_path), exist_ok=True)
                        
                        # Check if file already exists
                        if os.path.exists(jar_path):
                            if expected_sha1:
                                try:
                                    sha1_hash = hashlib.sha1()
                                    with open(jar_path, 'rb') as f:
                                        sha1_hash.update(f.read())
                                    if sha1_hash.hexdigest() == expected_sha1:
                                        # File is already correct; count it as done
                                        libs_count += 1
                                        pct = (libs_count * 100.0) / max(1, len(libraries))
                                        try:
                                            file_size = os.path.getsize(jar_path)
                                            bytes_done += file_size
                                            # bytes_total is fixed for this install
                                        except Exception:
                                            pass
                                        _update_progress(version_key, "downloading_libs", pct,
                                                        f"Libraries {libs_count}/{len(libraries)}",
                                                        bytes_done, bytes_total)
                                        downloaded_libs.add(lib_name)
                                        if libs_count <= 15:
                                            print(f"[forge] Already cached: {lib_name}")
                                        continue
                                except Exception as e:
                                    print(f"[forge] WARNING: Could not verify {lib_name}: {e}")
                            else:
                                # No SHA1 to verify, assume it's correct
                                libs_count += 1
                                pct = (libs_count * 100.0) / max(1, len(libraries))
                                try:
                                    file_size = os.path.getsize(jar_path)
                                    bytes_done += file_size
                                    # bytes_total is fixed for this install
                                except Exception:
                                    pass
                                _update_progress(version_key, "downloading_libs", pct,
                                                f"Libraries {libs_count}/{len(libraries)}",
                                                bytes_done, bytes_total)
                                downloaded_libs.add(lib_name)
                                if libs_count <= 15:
                                    print(f"[forge] Already cached: {lib_name}")
                                continue
                        
                        # Download the library - try multiple repos if needed
                        urls_to_try = []
                        
                        # Start with initial download_url
                        if download_url:
                            urls_to_try.append(download_url)
                        
                        # Add fallback repos if this is old format with known retries
                        if 'maven_repos' in locals() and 'maven_path' in locals() and len(urls_to_try) > 0:
                            # Add remaining repos we haven't tried yet
                            for repo in maven_repos[1:]:  # Skip first since it's already in urls_to_try
                                urls_to_try.append(repo + maven_path)
                        
                        # Try all URLs
                        for try_idx, try_url in enumerate(urls_to_try):
                            try:
                                _maybe_abort(version_key)  # Check cancellation
                                
                                # Update progress before starting download
                                pct = (libs_count * 100.0) / max(1, len(libraries))
                                _update_progress(version_key, "downloading_libs", pct,
                                                 f"Downloading {lib_name} ({libs_count + 1}/{len(libraries)})...",
                                                 bytes_done, bytes_total)

                                if try_idx == 0:
                                    print(colorize_log(f"[forge] Downloading: {lib_name}"))
                                else:
                                    print(colorize_log(f"[forge] Retrying {lib_name} from different repo..."))
                                
                                # Use file-count based progress, not byte-based
                                download_file(try_url, jar_path, version_key=version_key, progress_cb=None)
                                
                                # Verify SHA1 if provided
                                if expected_sha1:
                                    sha1_hash = hashlib.sha1()
                                    with open(jar_path, 'rb') as f:
                                        sha1_hash.update(f.read())
                                    actual_sha1 = sha1_hash.hexdigest()
                                    
                                    if actual_sha1 != expected_sha1:
                                        print(colorize_log(f"[forge] ERROR: SHA1 mismatch for {lib_name}"))
                                        print(colorize_log(f"[forge] Expected: {expected_sha1}"))
                                        print(colorize_log(f"[forge] Got: {actual_sha1}"))
                                        os.remove(jar_path)
                                        continue
                                
                                jars_copied += 1
                                downloaded_libs.add(lib_name)
                                libs_count += 1
                                pct = (libs_count * 100.0) / max(1, len(libraries))
                                try:
                                    file_size = os.path.getsize(jar_path)
                                    bytes_done += file_size
                                    # bytes_total is fixed for this install
                                except Exception:
                                    file_size = 0
                                _update_progress(version_key, "downloading_libs", pct,
                                                 f"Libraries {libs_count}/{len(libraries)}",
                                                 bytes_done, bytes_total)
                                if libs_count <= 15:
                                    print(colorize_log(f"[forge] Downloaded to: {os.path.relpath(jar_path, loader_dest_dir)}"))
                                break  # Success
                            
                            except RuntimeError as e:
                                if "cancel" in str(e).lower():
                                    print(colorize_log(f"[forge] Download cancelled - cleaning up"))
                                    _safe_remove_file(jar_path)
                                    raise
                                if try_url == urls_to_try[-1]:
                                    # Last attempt failed
                                    print(colorize_log(f"[forge] ERROR: Failed to download {lib_name} from any repo: {e}"))
                            except Exception as e:
                                if try_url == urls_to_try[-1]:
                                    # Last attempt failed
                                    print(colorize_log(f"[forge] ERROR: Failed to download {lib_name} from any repo: {e}"))
                    
                    print(colorize_log(f"[forge] Successfully downloaded {jars_copied} libraries from Forge metadata"))
                
                except RuntimeError as e:
                    if "cancel" in str(e).lower():
                        print(colorize_log(f"[forge] Library download cancelled"))
                        raise
                    print(colorize_log(f"[forge] ERROR: Could not process Forge metadata: {e}"))
                    traceback.print_exc()
                    return {"ok": False, "error": f"Failed to download Forge libraries: {e}"}
                except Exception as e:
                    print(colorize_log(f"[forge] ERROR: Could not process Forge metadata: {e}"))
                    traceback.print_exc()
            else:
                print(f"[forge] WARNING: No library metadata found (version.json or install_profile.json)!")

            # ---------------------------------------------------------------
            # Determine installer format: new (1.13+) vs old (â‰¤1.12.2)
            #
            # New-format installers (Forge 1.13+) contain a "processors" list
            # in install_profile.json.  These processors must be executed to:
            #   1. Download Minecraft client mappings from Mojang.
            #   2. Binary-patch the vanilla client JAR with Forge changes.
            #   3. Produce forge-{mc}-{forge}-client.jar (required by ModLauncher).
            #
            # Without running the processors the patched client JAR never
            # exists and ModLauncher fails at startup â€” this was the root cause
            # of all Forge 1.13+ launches silently failing.
            # ---------------------------------------------------------------

            def _jar_has_class(jar_path: str, class_path: str) -> bool:
                try:
                    with zipfile.ZipFile(jar_path, 'r') as z:
                        return class_path in z.namelist()
                except Exception:
                    return False

            def _find_runtime_jars(search_roots):
                found = []
                for root in search_roots:
                    if not root or not os.path.isdir(root):
                        continue
                    for dirpath, _, files in os.walk(root):
                        for f in files:
                            if not f.endswith('.jar'):
                                continue
                            p = os.path.join(dirpath, f)
                            try:
                                if _jar_has_class(p, 'cpw/mods/modlauncher/Launcher.class') or \
                                   _jar_has_class(p, 'net/minecraft/launchwrapper/Launch.class'):
                                    found.append(p)
                            except Exception:
                                continue
                return found

            is_new_forge_installer = bool(profile_data and profile_data.get("processors"))

            if is_new_forge_installer:
                # ---- Forge 1.13+ â€” run the official installer ----
                # The installer contains binary patches (LZMA) and a chain of
                # processor JARs.  We must invoke it with --installClient so
                # it applies those patches and deposits all runtime libraries
                # into a .minecraft-style directory that we can then harvest.
                print(f"[forge] Detected new-format installer (1.13+) â€” running installer to apply binary patches...")
                _update_progress(version_key, "extracting_loader", 40, "Running Forge installer (applying patches)...")

                # Build a minimal fake .minecraft directory the installer can use
                fake_mc_dir = os.path.join(temp_dir, "fake_mc")
                os.makedirs(fake_mc_dir, exist_ok=True)

                mc_ver_dir = os.path.join(fake_mc_dir, "versions", mc_version)
                os.makedirs(mc_ver_dir, exist_ok=True)

                # Place our already-downloaded client.jar where the installer expects it.
                # The installer checks for versions/{mc}/{mc}.jar and skips the Mojang
                # download when it's already present â€” saves bandwidth and works offline.
                client_jar_src = os.path.join(version_dir, "client.jar")
                client_jar_dst = os.path.join(mc_ver_dir, f"{mc_version}.jar")
                if os.path.exists(client_jar_src):
                    try:
                        shutil.copy2(client_jar_src, client_jar_dst)
                        print(f"[forge] Placed client.jar ({os.path.getsize(client_jar_dst) // 1024} KB) for installer")
                    except Exception as e:
                        print(f"[forge] WARNING: Could not place client.jar: {e}")
                else:
                    print(f"[forge] WARNING: client.jar not found at {client_jar_src} â€” installer will try to download it")

                # Fetch and place the Mojang version JSON.
                # The installer reads it to locate client mappings (client.txt) used by
                # the binary patcher, and to verify library checksums.
                version_json_dst = os.path.join(mc_ver_dir, f"{mc_version}.json")
                try:
                    from core import manifest as mc_manifest
                    mc_version_entry = mc_manifest.get_version_entry(mc_version)
                    mc_version_url = mc_version_entry.get("url")
                    if mc_version_url:
                        mc_version_data = mc_manifest.fetch_version_json(mc_version_url)
                        with open(version_json_dst, 'w') as vf:
                            json.dump(mc_version_data, vf)
                        print(f"[forge] Placed MC {mc_version} version JSON for installer")
                except Exception as e:
                    print(f"[forge] WARNING: Could not fetch Mojang version JSON ({e}) â€” installer will try to download it")

                # Pre-populate fake_mc/libraries/ from the installer's embedded maven/ directory.
                # This prevents the installer from re-downloading JARs we already have,
                # making the install faster and more reliable on slow connections.

                # CRITICAL: The Forge installer checks for launcher_profiles.json before
                # doing anything else and hard-aborts if it's missing.  Create a minimal
                # stub so the installer proceeds past that check.
                launcher_profiles_path = os.path.join(fake_mc_dir, "launcher_profiles.json")
                try:
                    with open(launcher_profiles_path, 'w') as lpf:
                        json.dump({
                            "profiles": {
                                "(Default)": {
                                    "name": "(Default)",
                                    "type": "latest-release"
                                }
                            },
                            "selectedProfile": "(Default)",
                            "authenticationDatabase": {},
                            "clientToken": "histolauncher-fake-token",
                            "launcherVersion": {
                                "format": 21,
                                "name": "2.2.1234",
                                "profilesFormat": 2
                            }
                        }, lpf, indent=2)
                    print(f"[forge] Created launcher_profiles.json stub for installer")
                except Exception as e:
                    print(f"[forge] WARNING: Could not create launcher_profiles.json: {e}")

                installer_maven = os.path.join(extraction_dir, "maven")
                fake_libs_dir = os.path.join(fake_mc_dir, "libraries")
                if os.path.isdir(installer_maven):
                    try:
                        shutil.copytree(installer_maven, fake_libs_dir, dirs_exist_ok=True)
                        print(f"[forge] Pre-populated installer libraries from embedded maven/ directory")
                    except Exception as e:
                        print(f"[forge] Warning: Could not pre-populate libraries: {e}")

                # Run the Forge installer
                java_exe = _get_java_executable() or "java"
                installer_success = False
                expected_patched_client = os.path.join(
                    fake_libs_dir,
                    "net", "minecraftforge", "forge", f"{mc_version}-{loader_version}",
                    f"forge-{mc_version}-{loader_version}-client.jar"
                )

                installer_candidates = [
                    [java_exe, "-jar", downloaded_artifact_path, "--installClient", fake_mc_dir],
                    [java_exe, "-jar", downloaded_artifact_path, "--installClient", "--installDir", fake_mc_dir],
                    [java_exe, "-jar", downloaded_artifact_path, "--installClient"],
                ]

                network_failure_markers = [
                    "failed to validate certificates",
                    "unsupported or unrecognized ssl message",
                    "error checking https://",
                    "sslhandshakeexception",
                    "unable to tunnel through proxy",
                ]
                network_failure_detected = False

                for attempt, installer_cmd in enumerate(installer_candidates, start=1):
                    print(f"[forge] Running installer attempt {attempt}/{len(installer_candidates)}: {' '.join(installer_cmd)}")
                    try:
                        proc = subprocess.run(
                            installer_cmd,
                            cwd=fake_mc_dir,
                            capture_output=True,
                            text=True,
                            timeout=600,  # 10 minutes - binary patching can take a while
                        )
                        # Log a reasonable slice of installer output for diagnostics
                        for line in proc.stdout.splitlines()[:50]:
                            print(f"[forge-installer] {line}")
                        if proc.returncode != 0 and proc.stderr:
                            for line in proc.stderr.splitlines()[:20]:
                                print(f"[forge-installer-err] {line}")
                        print(f"[forge] Installer exit code: {proc.returncode}")

                        combined_output = f"{proc.stdout}\n{proc.stderr}".lower()
                        if any(marker in combined_output for marker in network_failure_markers):
                            network_failure_detected = True
                            print("[forge] Detected installer network/certificate issue; will retry with --offline mode")
                    except subprocess.TimeoutExpired:
                        print(f"[forge] Installer timed out after 10 minutes")
                        continue
                    except Exception as e:
                        print(f"[forge] Installer run error: {e}")
                        continue

                    if proc.returncode != 0:
                        continue

                    installer_success = True

                    if os.path.exists(expected_patched_client):
                        print(f"[forge] Found patched Forge client JAR from installer")
                        break

                    # Some installer variants do not create the exact expected
                    # client JAR name but still populate runtime libraries.
                    has_any_library_jar = False
                    if os.path.isdir(fake_libs_dir):
                        for _, _, files in os.walk(fake_libs_dir):
                            if any(name.endswith(".jar") for name in files):
                                has_any_library_jar = True
                                break

                    if has_any_library_jar:
                        print(f"[forge] Installer produced runtime libraries")
                        break

                    installer_success = False
                    print(f"[forge] Installer exited successfully but produced no usable artifacts; trying next command form")

                if network_failure_detected and not os.path.exists(expected_patched_client):
                    _update_progress(version_key, "extracting_loader", 55, "Re-running Forge installer in offline mode...")

                    for attempt, base_cmd in enumerate(installer_candidates, start=1):
                        offline_cmd = base_cmd[:3] + ["--offline"] + base_cmd[3:]
                        print(
                            f"[forge] Running offline installer attempt {attempt}/{len(installer_candidates)}: "
                            f"{' '.join(offline_cmd)}"
                        )
                        try:
                            proc = subprocess.run(
                                offline_cmd,
                                cwd=fake_mc_dir,
                                capture_output=True,
                                text=True,
                                timeout=600,
                            )
                            for line in proc.stdout.splitlines()[:50]:
                                print(f"[forge-installer-offline] {line}")
                            if proc.returncode != 0 and proc.stderr:
                                for line in proc.stderr.splitlines()[:20]:
                                    print(f"[forge-installer-offline-err] {line}")
                            print(f"[forge] Offline installer exit code: {proc.returncode}")
                        except subprocess.TimeoutExpired:
                            print("[forge] Offline installer timed out after 10 minutes")
                            continue
                        except Exception as e:
                            print(f"[forge] Offline installer run error: {e}")
                            continue

                        if proc.returncode != 0:
                            continue

                        installer_success = True

                        if os.path.exists(expected_patched_client):
                            print("[forge] Offline installer produced patched Forge client JAR")
                            break

                        has_any_library_jar = False
                        if os.path.isdir(fake_libs_dir):
                            for _, _, files in os.walk(fake_libs_dir):
                                if any(name.endswith(".jar") for name in files):
                                    has_any_library_jar = True
                                    break

                        if has_any_library_jar:
                            print("[forge] Offline installer produced runtime libraries")
                            break

                        installer_success = False
                        print("[forge] Offline installer exited successfully but still produced no usable artifacts")

                # Harvest all JARs the installer placed into fake_mc/libraries/.
                # This includes the binary-patched forge-*-client.jar that ModLauncher
                # needs, plus any Minecraft/Forge runtime libraries downloaded by the
                # installer's own dependency resolver.
                if os.path.isdir(fake_libs_dir):
                    new_jars = 0
                    replaced_jars = 0

                    def _should_overwrite_from_installer(rel_path: str) -> bool:
                        rel_norm = rel_path.replace("\\", "/").lower()
                        # New-format Forge installers generate patched client jars that
                        # must replace any earlier placeholder copy from embedded maven/.
                        if "net/minecraftforge/forge/" in rel_norm and rel_norm.endswith("-client.jar"):
                            return True
                        # These Minecraft client artifacts are also produced/updated by
                        # installer processors and should not remain stale.
                        if rel_norm.startswith("net/minecraft/client/"):
                            if rel_norm.endswith("-srg.jar") or rel_norm.endswith("-slim.jar") or rel_norm.endswith("-extra.jar"):
                                return True
                        return False

                    for root, dirs, files in os.walk(fake_libs_dir):
                        for filename in files:
                            if filename.endswith(".jar"):
                                src_jar = os.path.join(root, filename)
                                rel_path = os.path.relpath(src_jar, fake_libs_dir)
                                dst_jar = os.path.join(loader_dest_dir, "libraries", rel_path)
                                os.makedirs(os.path.dirname(dst_jar), exist_ok=True)
                                dst_exists = os.path.exists(dst_jar)
                                should_overwrite = dst_exists and _should_overwrite_from_installer(rel_path)

                                if (not dst_exists) or should_overwrite:
                                    try:
                                        shutil.copy2(src_jar, dst_jar)
                                        if dst_exists:
                                            replaced_jars += 1
                                        else:
                                            jars_copied += 1
                                            new_jars += 1
                                    except Exception as e:
                                        print(f"[forge] Warning: Could not copy {filename}: {e}")
                    print(f"[forge] Collected {new_jars} new and {replaced_jars} replaced JAR(s) from installer output into loader/libraries/")

                if installer_success:
                    # Prefer installer-generated profile JSON so launcher metadata
                    # matches the exact classpath/arguments produced by Forge.
                    try:
                        versions_root = os.path.join(fake_mc_dir, "versions")
                        generated_profile_json = None
                        preferred_profile_id = f"{mc_version}-forge-{loader_version}".lower()

                        if os.path.isdir(versions_root):
                            for entry in os.listdir(versions_root):
                                entry_dir = os.path.join(versions_root, entry)
                                if not os.path.isdir(entry_dir):
                                    continue
                                if entry.lower() != preferred_profile_id:
                                    continue
                                candidate = os.path.join(entry_dir, f"{entry}.json")
                                if os.path.isfile(candidate):
                                    generated_profile_json = candidate
                                    break

                        if not generated_profile_json and os.path.isdir(versions_root):
                            forge_candidates = []
                            for entry in os.listdir(versions_root):
                                entry_dir = os.path.join(versions_root, entry)
                                if not os.path.isdir(entry_dir):
                                    continue
                                if "forge" not in entry.lower():
                                    continue
                                candidate = os.path.join(entry_dir, f"{entry}.json")
                                if os.path.isfile(candidate):
                                    try:
                                        mtime = os.path.getmtime(candidate)
                                    except Exception:
                                        mtime = 0
                                    forge_candidates.append((mtime, candidate))
                            if forge_candidates:
                                forge_candidates.sort(key=lambda t: t[0], reverse=True)
                                generated_profile_json = forge_candidates[0][1]

                        if generated_profile_json:
                            metadata_version_json = os.path.join(loader_dest_dir, ".metadata", "version.json")
                            os.makedirs(os.path.dirname(metadata_version_json), exist_ok=True)
                            shutil.copy2(generated_profile_json, metadata_version_json)
                            print(
                                f"[forge] Updated metadata version.json from installer output: "
                                f"{os.path.basename(generated_profile_json)}"
                            )
                    except Exception as e:
                        print(f"[forge] Warning: Could not refresh metadata version.json from installer output: {e}")

                    _update_progress(version_key, "extracting_loader", 80, f"Forge patches applied ({jars_copied} libraries)")
                else:
                    print(f"[forge] Installer did not exit cleanly â€” some Forge features may not work correctly")
                    _update_progress(version_key, "extracting_loader", 70, "Installer finished (check logs if launch fails)")

            else:
                # ---- Forge â‰¤1.12.2 â€” run installer only if LaunchWrapper is missing ----
                existing = _find_runtime_jars([loader_dest_dir])
                if not existing and is_installer_archive:
                    print(f"[forge] LaunchWrapper not found â€” attempting to run installer to finish installation")
                    try:
                        candidate_cmds = [
                            ["java", "-jar", downloaded_artifact_path, "--installClient"],
                            ["java", "-jar", downloaded_artifact_path, "--installClient", version_dir],
                            ["java", "-jar", downloaded_artifact_path, "--installClient", "--installDir", version_dir],
                        ]
                        for cmd in candidate_cmds:
                            try:
                                print(f"[forge] Running installer: {' '.join(cmd)} (cwd={version_dir})")
                                proc = subprocess.run(cmd, cwd=version_dir, capture_output=True, text=True, timeout=180)
                                print(f"[forge] Installer exit {proc.returncode}; stdout[:1024]: {proc.stdout[:1024]!r}")
                                if proc.stderr:
                                    print(f"[forge] Installer stderr[:1024]: {proc.stderr[:1024]!r}")
                                if proc.returncode == 0:
                                    break
                            except Exception as e:
                                print(f"[forge] Installer invocation failed: {e}")
                    except Exception as e:
                        print(f"[forge] Error attempting to run installer: {e}")

                    search_paths = [loader_dest_dir, version_dir]
                    try:
                        appdata = os.environ.get('APPDATA')
                        if appdata:
                            search_paths.append(os.path.join(appdata, '.minecraft', 'libraries'))
                    except Exception:
                        pass

                    found_runtimes = _find_runtime_jars(search_paths)
                    for src in found_runtimes:
                        try:
                            dst = os.path.join(loader_dest_dir, os.path.basename(src))
                            if not os.path.exists(dst):
                                shutil.copy2(src, dst)
                                jars_copied += 1
                                print(f"[forge] Copied runtime jar from installer output: {os.path.basename(src)}")
                        except Exception as e:
                            print(f"[forge] Warning: could not copy runtime jar {src}: {e}")

                    if not found_runtimes:
                        print(f"[forge] Installer did not produce LaunchWrapper jars in known locations")
            
            # Extract root-level JARs if any (forge-X.X.X-universal.jar, etc.)
            # Skip forge-installer.jar - it's only for extraction, not game launch
            print(f"[forge] Checking for root-level JARs...")
            for filename in os.listdir(extraction_dir):
                if filename.endswith(".jar"):
                    # Skip the installer JAR - it has Main-Class: SimpleInstaller
                    # which will execute instead of the game launcher
                    if filename.lower() == "forge-installer.jar":
                        print(f"[forge] Skipping forge-installer.jar (not needed for game launch)")
                        continue
                    
                    src_jar = os.path.join(extraction_dir, filename)
                    dst_jar = os.path.join(loader_dest_dir, filename)
                    if not os.path.exists(dst_jar):
                        try:
                            shutil.copy2(src_jar, dst_jar)
                            jars_copied += 1
                            print(f"[forge] Copied root JAR: {filename}")
                        except Exception as e:
                            print(f"[forge] Failed to copy {filename}: {e}")

            # Some legacy Forge archives place universal/client jars in subfolders.
            # Recover those jars into loader root so LaunchWrapper can bootstrap.
            has_forge_core_jar = any(
                n.endswith(".jar") and (n.startswith("forge-") or n.startswith("minecraftforge-"))
                for n in os.listdir(loader_dest_dir)
            )
            if not has_forge_core_jar:
                recovered = 0
                for root, _, files in os.walk(extraction_dir):
                    for filename in files:
                        if not filename.endswith(".jar"):
                            continue
                        lower_name = filename.lower()
                        if lower_name == "forge-installer.jar":
                            continue
                        is_legacy_core = (
                            lower_name.startswith("forge-")
                            or lower_name.startswith("minecraftforge-")
                            or "universal" in lower_name
                        )
                        if not is_legacy_core:
                            continue

                        src_jar = os.path.join(root, filename)
                        dst_jar = os.path.join(loader_dest_dir, filename)
                        if os.path.exists(dst_jar):
                            continue
                        try:
                            shutil.copy2(src_jar, dst_jar)
                            jars_copied += 1
                            recovered += 1
                            print(f"[forge] Recovered legacy core JAR from nested path: {filename}")
                        except Exception as e:
                            print(f"[forge] Failed recovering nested JAR {filename}: {e}")

                if recovered > 0:
                    print(f"[forge] Recovered {recovered} nested legacy Forge core JAR(s)")

            has_forge_core_jar = any(
                n.endswith(".jar") and (n.startswith("forge-") or n.startswith("minecraftforge-"))
                for n in os.listdir(loader_dest_dir)
            )
            if (not has_forge_core_jar) and is_legacy_universal_archive:
                staged_name = downloaded_artifact_name
                if staged_name.lower().endswith(".zip"):
                    staged_name = staged_name[:-4] + ".jar"
                staged_path = os.path.join(loader_dest_dir, staged_name)
                try:
                    shutil.copy2(downloaded_artifact_path, staged_path)
                    jars_copied += 1
                    print(f"[forge] Staged legacy universal archive as runtime JAR: {staged_name}")
                except Exception as e:
                    print(f"[forge] Failed to stage legacy universal archive as JAR: {e}")

            def _jar_contains_class(jar_path: str, class_path: str) -> bool:
                try:
                    with zipfile.ZipFile(jar_path, 'r') as z:
                        return class_path in z.namelist()
                except Exception:
                    return False

            def _loader_has_class(class_path: str) -> bool:
                try:
                    for name in os.listdir(loader_dest_dir):
                        if not name.endswith('.jar'):
                            continue
                        if _jar_contains_class(os.path.join(loader_dest_dir, name), class_path):
                            return True
                except Exception:
                    pass
                return False

            if (not modlauncher_era) and (not _loader_has_class('cpw/mods/fml/common/launcher/FMLTweaker.class')):
                props_path = os.path.join(loader_dest_dir, 'fmlversion.properties')
                if not os.path.exists(props_path):
                    props_path = os.path.join(extraction_dir, 'fmlversion.properties')

                props = {}
                if os.path.exists(props_path):
                    try:
                        with open(props_path, 'r', encoding='utf-8', errors='replace') as pf:
                            for line in pf:
                                line = line.strip()
                                if not line or line.startswith('#') or '=' not in line:
                                    continue
                                k, v = line.split('=', 1)
                                props[k.strip()] = v.strip()
                    except Exception as e:
                        print(f"[forge] Warning: Could not parse fmlversion.properties: {e}")

                fml_mc = props.get('fmlbuild.mcversion', mc_version).strip()
                fml_major = props.get('fmlbuild.major.number', '').strip()
                fml_minor = props.get('fmlbuild.minor.number', '').strip()
                fml_revision = props.get('fmlbuild.revision.number', '').strip()
                fml_build = props.get('fmlbuild.build.number', '').strip()

                if all([fml_mc, fml_major, fml_minor, fml_revision, fml_build]):
                    fml_numeric = f"{fml_major}.{fml_minor}.{fml_revision}.{fml_build}"
                    fml_coord = f"{fml_mc}-{fml_numeric}"
                    fml_zip_url = (
                        f"https://maven.minecraftforge.net/net/minecraftforge/fml/{fml_coord}/"
                        f"fml-{fml_coord}-universal.zip"
                    )
                    fml_dest_name = f"fml-{fml_coord}-universal.jar"
                    fml_dest_path = os.path.join(loader_dest_dir, fml_dest_name)

                    if not os.path.exists(fml_dest_path):
                        fml_tmp_path = os.path.join(temp_dir, f"fml-{fml_coord}-universal.zip")
                        try:
                            print(f"[forge] Downloading legacy FML artifact: {fml_zip_url}")
                            _download_with_retry(fml_zip_url, fml_tmp_path)
                            shutil.copy2(fml_tmp_path, fml_dest_path)
                            jars_copied += 1
                            print(f"[forge] Staged legacy FML artifact as JAR: {fml_dest_name}")
                        except Exception as e:
                            print(f"[forge] Warning: Could not download legacy FML artifact: {e}")

                if _loader_has_class('cpw/mods/fml/common/launcher/FMLTweaker.class'):
                    print("[forge] Legacy FMLTweaker class is available")
                else:
                    print("[forge] Warning: FMLTweaker class still missing after legacy FML recovery")
            
            # If we still have no runtime jars, attempt ModLauncher fallback only for
            # modern MC lines. Legacy Forge must stay LaunchWrapper-based.
            existing_runtime_jars = _find_runtime_jars([loader_dest_dir])
            if not existing_runtime_jars and modlauncher_era:
                print(f"[forge] No JARs found from installer extraction; attempting modlauncher download...")
                
                # Try to download modlauncher directly
                modlauncher_versions = ["9.1.3", "9.1.2", "9.1.1", "9.1.0", "9.0.17", "9.0.16", "8.1.26"]
                
                for ml_version in modlauncher_versions:
                    ml_jar_name = f"modlauncher-{ml_version}.jar"
                    ml_jar_path = os.path.join(loader_dest_dir, ml_jar_name)
                    
                    ml_urls = [
                        f"https://maven.minecraftforge.net/cpw/mods/modlauncher/{ml_version}/{ml_jar_name}",
                        f"https://repo1.maven.org/maven2/cpw/mods/modlauncher/{ml_version}/{ml_jar_name}",
                    ]
                    
                    for ml_url in ml_urls:
                        try:
                            print(f"[forge] Trying modlauncher {ml_version}...")
                            _download_with_retry(ml_url, ml_jar_path)
                            if os.path.exists(ml_jar_path):
                                # Verify it has the Launcher class
                                def _jar_has_class(jar_path: str, class_path: str) -> bool:
                                    try:
                                        with zipfile.ZipFile(jar_path, 'r') as z:
                                            return class_path in z.namelist()
                                    except Exception:
                                        return False
                                
                                if _jar_has_class(ml_jar_path, 'cpw/mods/modlauncher/Launcher.class'):
                                    jars_copied += 1
                                    print(f"[forge] Successfully downloaded modlauncher {ml_version}")
                                    break
                                else:
                                    os.remove(ml_jar_path)
                        except Exception as e:
                            continue
                    else:
                        continue
                    break
            
            # Before we give up, inspect any Forge JARs we copied for additional
            # libraries listed in their manifests.  This catches runtime deps such as
            # ModLauncher which the installer sometimes downloads separately.
            def _gather_manifest_libraries(jar_path: str) -> List[str]:
                libs: List[str] = []
                try:
                    with zipfile.ZipFile(jar_path, 'r') as jf:
                        mf = jf.read('META-INF/MANIFEST.MF').decode('utf-8', errors='ignore')
                    for line in mf.splitlines():
                        if line.startswith('libraries/'):
                            # manifest paths are relative to the Maven repo root
                            libs.append(line.strip())
                except Exception:
                    pass
                return libs

            # scan all jars we already copied for manifest entries
            manifest_libs: List[str] = []
            for jarfile in os.listdir(loader_dest_dir):
                if jarfile.endswith('.jar'):
                    manifest_libs.extend(_gather_manifest_libraries(os.path.join(loader_dest_dir, jarfile)))

            if manifest_libs:
                print(f"[forge] Found {len(manifest_libs)} libraries in JAR manifests")
                for rel in manifest_libs:
                    dest_name = os.path.basename(rel)
                    dest_path = os.path.join(loader_dest_dir, dest_name)
                    if os.path.exists(dest_path):
                        continue
                    url = _apply_url_proxy(f"https://maven.minecraftforge.net/{rel}")
                    try:
                        print(f"[forge] Downloading manifest library: {rel}")
                        _download_with_retry(url, dest_path)
                        jars_copied += 1
                        if jars_copied <= 20:
                            print(f"[forge] Downloaded: {dest_name}")
                    except Exception as e:
                        print(f"[forge] Failed to download manifest library {rel}: {e}")

            existing_runtime_jars = _find_runtime_jars([loader_dest_dir])
            if not existing_runtime_jars:
                if modlauncher_era:
                    return {"ok": False, "error": "Could not find any Forge runtime JARs"}

                has_legacy_core_jar = any(
                    name.endswith(".jar") and (
                        name.lower().startswith("forge-")
                        or name.lower().startswith("minecraftforge-")
                        or "universal" in name.lower()
                    )
                    for name in os.listdir(loader_dest_dir)
                )
                if has_legacy_core_jar:
                    print("[forge] Legacy Forge core JAR detected without embedded LaunchWrapper; continuing (vanilla classpath provides LaunchWrapper)")
                else:
                    return {"ok": False, "error": "Could not find LaunchWrapper runtime JARs for legacy Forge"}
            
            print(f"[forge] Extracting service providers from Forge JARs...")
            services_dest = os.path.join(loader_dest_dir, "META-INF", "services")
            os.makedirs(services_dest, exist_ok=True)
            
            services_copied = 0
            try:
                jar_files = [f for f in os.listdir(loader_dest_dir) if f.endswith(".jar")]
                print(f"[forge] Found {len(jar_files)} JARs to scan for service providers")
                
                for jar_filename in sorted(jar_files):
                    jar_path = os.path.join(loader_dest_dir, jar_filename)
                    try:
                        with zipfile.ZipFile(jar_path, 'r') as jar:
                            for name in jar.namelist():
                                if name.startswith("META-INF/services/"):
                                    service_name = os.path.basename(name)
                                    if service_name:  # Ensure it's not just a directory
                                        # Don't overwrite if already extracted
                                        service_file = os.path.join(services_dest, service_name)
                                        if not os.path.exists(service_file):
                                            content = jar.read(name)
                                            with open(service_file, 'wb') as f:
                                                f.write(content)
                                            services_copied += 1
                                            print(f"[forge] Extracted service from {jar_filename}: {service_name}")
                    except Exception as e:
                        # Skip non-JAR files or corrupt JARs
                        pass
                
                if services_copied > 0:
                    print(f"[forge] Total: {services_copied} service provider files extracted")
                else:
                    print(f"[forge] Note: No service providers found in JARs (they may still be discoverable)")
                    
            except Exception as e:
                print(f"[forge] Warning: Error extracting service providers: {e}")
            
            # Extract bootstrap-related files - CRITICAL for FML initialization
            # These include bootstrap-shim.list(if present) and other config files
            print(f"[forge] Extracting bootstrap configuration files...")
            bootstrap_extracted = False
            try:
                if not is_installer_archive:
                    raise RuntimeError("bootstrap extraction skipped for non-installer Forge artifact")

                with zipfile.ZipFile(downloaded_artifact_path, 'r') as jar:
                    all_entries = jar.namelist()
                    
                    # Look for bootstrap files in root and META-INF
                    for entry in all_entries:
                        # Bootstrap list files
                        if entry.lower().endswith('bootstrap-shim.list') or \
                           entry.lower().endswith('.shim') or \
                           (entry.lower().startswith('bootstrap') and entry.lower().endswith('.list')):
                            try:
                                content = jar.read(entry)
                                # Extract to root of loader directory
                                basename = os.path.basename(entry)
                                dst_path = os.path.join(loader_dest_dir, basename)
                                with open(dst_path, 'wb') as f:
                                    f.write(content)
                                print(f"[forge] Extracted critical bootstrap file: {basename}")
                                bootstrap_extracted = True
                            except Exception as e:
                                print(f"[forge] Warning: Could not extract {entry}: {e}")
                        
                        # Also extract any files from META-INF that might be bootstrap/launcher related
                        elif entry.startswith('META-INF/') and \
                             ('launcher' in entry.lower() or 'modlauncher' in entry.lower() or \
                              'bootstrap' in entry.lower() or 'fml' in entry.lower()):
                            # Only extract non-directory entries
                            if not entry.endswith('/'):
                                try:
                                    content = jar.read(entry)
                                    # Preserve directory structure
                                    sub_path = os.path.join(loader_dest_dir, entry.replace('/', os.sep))
                                    os.makedirs(os.path.dirname(sub_path), exist_ok=True)
                                    with open(sub_path, 'wb') as f:
                                        f.write(content)
                                    print(f"[forge] Extracted bootstrap config: {os.path.basename(entry)}")
                                except Exception as e:
                                    pass
                
                if bootstrap_extracted:
                    print(f"[forge] Bootstrap files extracted successfully")
                else:
                    print(f"[forge] Note: No explicit bootstrap-shim.list found")
                    print(f"[forge] This is normal for Forge 36.x - using extracted JARs for bootstrap")
            
            except Exception as e:
                print(f"[forge] Warning: Could not extract bootstrap files: {e}")
            
            # If log4j2.xml wasn't found in the installer, try extracting it from the Forge JARs
            # Some Forge versions embed the config inside JAR files
            log4j_config_path = os.path.join(loader_dest_dir, "log4j2.xml")
            if not os.path.exists(log4j_config_path):
                print(f"[forge] log4j2.xml not found at top level, searching Forge JARs...")
                
                # Look for universal and main Forge JARs
                forge_jars = [f for f in os.listdir(loader_dest_dir) if f.endswith(".jar")]
                for jar_file in sorted(forge_jars):
                    jar_path = os.path.join(loader_dest_dir, jar_file)
                    try:
                        with zipfile.ZipFile(jar_path, 'r') as jar:
                            # Try different locations where log4j config might be
                            for config_name in ["log4j2.xml", "log4j.properties", "log4j.xml"]:
                                # Check root and common locations
                                for potential_path in [
                                    config_name,
                                    f"assets/{config_name}",
                                    f"META-INF/{config_name}",
                                    f"com/mojang/launcher/{config_name}",
                                ]:
                                    try:
                                        content = jar.read(potential_path)
                                        # Extract it to loader directory
                                        dst_path = os.path.join(loader_dest_dir, config_name)
                                        with open(dst_path, 'wb') as f:
                                            f.write(content)
                                        print(f"[forge] Extracted {config_name} from {jar_file}")
                                        if os.path.exists(log4j_config_path):
                                            break
                                    except KeyError:
                                        # File not in this location, try next
                                        continue
                                
                                if os.path.exists(log4j_config_path):
                                    break
                    except Exception as e:
                        # Not a valid JAR or couldn't read it
                        continue
                    
                    if os.path.exists(log4j_config_path):
                        break
            
            # Check if extracted log4j2.xml has incompatible components
            # If it does, replace it with a compatible version
            if os.path.exists(log4j_config_path):
                try:
                    with open(log4j_config_path, 'r') as f:
                        log4j_content = f.read()
                    
                    # Check for components that require missing libraries
                    incompatible_markers = [
                        "TerminalConsole",  # Requires net.minecrell:terminalconsole
                        "LoggerNamePatternSelector",  # Requires special handling
                        "%highlightForge",  # Custom Forge formatter
                        "%minecraftFormatting",  # Custom Forge formatter
                        "net.minecrell.terminalconsole",  # Missing package
                    ]
                    
                    has_incompatible = any(marker in log4j_content for marker in incompatible_markers)
                    
                    if has_incompatible:
                        print(f"[forge] Detected incompatible log4j2.xml components")
                        print(f"[forge] Replacing with compatible fallback...")
                        
                        # Replace with compatible version
                        fallback_log4j = """<?xml version="1.0" encoding="UTF-8"?>
<Configuration status="warn" packages="net.minecraftforge.fml.loading.moddiscovery" shutdownHook="disable">
    <Appenders>
        <Console name="Console" target="SYSTEM_OUT" follow="true">
            <PatternLayout pattern="[%d{HH:mm:ss}] [%t/%level] [%c{1.}]: %msg%n" />
        </Console>
        <RollingRandomAccessFile name="File" fileName="logs/latest.log" filePattern="logs/%d{yyyy-MM-dd}-%i.log.gz">
            <PatternLayout pattern="[%d{ddMMMyyyy HH:mm:ss.SSS}] [%t/%level] [%c{2.}]: %msg%n" />
            <Policies>
                <TimeBasedTriggeringPolicy />
                <OnStartupTriggeringPolicy />
            </Policies>
            <DefaultRolloverStrategy max="99" fileIndex="min" />
        </RollingRandomAccessFile>
    </Appenders>
    <Loggers>
        <Root level="info">
            <AppenderRef ref="Console" />
            <AppenderRef ref="File" />
        </Root>
    </Loggers>
</Configuration>"""
                        with open(log4j_config_path, 'w') as f:
                            f.write(fallback_log4j)
                        print(f"[forge] Replaced with compatible log4j2.xml")
                except Exception as e:
                    print(f"[forge] Could not check log4j2.xml: {e}")
                
                if not os.path.exists(log4j_config_path):
                    print(f"[forge] WARNING: log4j2.xml not found in any Forge JAR")
                    print(f"[forge] Creating compatible log4j2.xml configuration...")
                    
                    # Create a compatible log4j2.xml that works with standard log4j2
                    # Uses only standard appenders/components to avoid missing library errors
                    fallback_log4j = """<?xml version="1.0" encoding="UTF-8"?>
<Configuration status="warn" packages="net.minecraftforge.fml.loading.moddiscovery" shutdownHook="disable">
    <Appenders>
        <Console name="Console" target="SYSTEM_OUT" follow="true">
            <PatternLayout pattern="[%d{HH:mm:ss}] [%t/%level] [%c{1.}]: %msg%n" />
        </Console>
        <RollingRandomAccessFile name="File" fileName="logs/latest.log" filePattern="logs/%d{yyyy-MM-dd}-%i.log.gz">
            <PatternLayout pattern="[%d{ddMMMyyyy HH:mm:ss.SSS}] [%t/%level] [%c{2.}]: %msg%n" />
            <Policies>
                <TimeBasedTriggeringPolicy />
                <OnStartupTriggeringPolicy />
            </Policies>
            <DefaultRolloverStrategy max="99" fileIndex="min" />
        </RollingRandomAccessFile>
    </Appenders>
    <Loggers>
        <Root level="info">
            <AppenderRef ref="Console" />
            <AppenderRef ref="File" />
        </Root>
    </Loggers>
</Configuration>"""
                    try:
                        with open(log4j_config_path, 'w') as f:
                            f.write(fallback_log4j)
                        print(f"[forge] Created compatible log4j2.xml (using standard appenders)")
                        files_copied += 1
                    except Exception as e:
                        print(f"[forge] Failed to create log4j2.xml: {e}")
            
            # Create a Forge metadata file for the launcher
            metadata_file = os.path.join(loader_dest_dir, "forge_metadata.json")
            metadata = {
                "forge_version": loader_version,
                "mc_version": mc_version,
                "installed_jars": jars_copied,
                "installed_configs": files_copied,
            }
            try:
                if profile_data:
                    metadata["profile_spec"] = profile_data.get("spec", 0)
                    # In new-format installers (1.13+), "version" is a plain string like
                    # "1.13.2-forge-25.0.223".  In very old installers it could be a dict.
                    raw_version = profile_data.get("version", "")
                    if isinstance(raw_version, dict):
                        metadata["profile_version"] = raw_version.get("id", "unknown")
                    else:
                        metadata["profile_version"] = raw_version or "unknown"
                    # Forge 1.13+ install_profile.json carries the MCP Config version in
                    # data.MCP_VERSION.  FML uses this to locate client-{mc}-{mcp}-srg.jar,
                    # so it MUST be stored and passed as --fml.mcpVersion at launch time.
                    # Values use Forge's literal-string syntax: "'20190213.203750'" (single quotes).
                    profile_data_section = profile_data.get("data", {})
                    mcp_ver = ""

                    # Primary: data.MCP_VERSION.client
                    raw_mcp = (profile_data_section.get("MCP_VERSION") or {}).get("client", "")
                    if raw_mcp:
                        mcp_ver = raw_mcp.strip("'")

                    # Fallback: parse from data.MC_SRG.client â€” e.g.
                    # "[net.minecraft:client:1.13.2-20190213.203750:srg]"
                    if not mcp_ver:
                        raw_srg = (profile_data_section.get("MC_SRG") or {}).get("client", "")
                        if raw_srg:
                            # Strip [] and split by : to get the version field
                            inner = raw_srg.strip("[]")
                            srg_parts = inner.split(":")
                            if len(srg_parts) >= 3:
                                mcp_ver = srg_parts[2]  # e.g. "1.13.2-20190213.203750"

                    # Fallback: parse from data.MAPPINGS.client â€” e.g.
                    # "[de.oceanlabs.mcp:mcp_config:1.13.2-20190213.203750@zip]"
                    if not mcp_ver:
                        raw_mappings = (profile_data_section.get("MAPPINGS") or {}).get("client", "")
                        if raw_mappings:
                            inner = raw_mappings.strip("[]").split("@")[0]
                            map_parts = inner.split(":")
                            if len(map_parts) >= 3:
                                mcp_ver = map_parts[2]  # e.g. "1.13.2-20190213.203750"

                    if mcp_ver:
                        metadata["mcp_version"] = mcp_ver
                        print(f"[forge] Stored MCP Config version: {mcp_ver}")
                    else:
                        print(f"[forge] Warning: MCP_VERSION not found in install_profile.json data section")

                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f, indent=2)
                print(f"[forge] Created metadata file")
            except Exception as e:
                print(f"[forge] Warning: Could not create metadata file: {e}")
            
            # Workaround for ModLauncher (Forge 1.13+): Ensure Minecraft client resources are available
            # ModLauncher may look for client-X.Y.Z-extra.jar in the loader's libraries directory
            # If using ModLauncher and the Minecraft client jar exists, create the expected library structure
            is_modlauncher = False
            if loader_version:
                # Check for modlauncher JAR in root loader dir or any libraries subdirectory
                for root, dirs, files in os.walk(loader_dest_dir):
                    for f in files:
                        if f.endswith('.jar') and 'modlauncher' in f.lower():
                            is_modlauncher = True
                            break
                    if is_modlauncher:
                        break
            
            if is_modlauncher and modlauncher_era:
                # This is ModLauncher-based Forge (1.13+)
                print(f"[forge] Detected ModLauncher-based Forge, preparing client resources...")
                # Check if main version has client.jar
                main_client_jar = os.path.join(version_dir, 'client.jar')
                if os.path.exists(main_client_jar):
                    # Extract Minecraft version from version directory name (last component of path)
                    mc_version_folder = os.path.basename(version_dir.rstrip(os.sep))
                    # e.g., "1.13.2" from "C:\.../1.13.2"
                    
                    # Create the expected Maven structure: libraries/net/minecraft/client/VERSION/client-VERSION-extra.jar
                    minecraft_client_dir = os.path.join(loader_dest_dir, 'libraries', 'net', 'minecraft', 'client', mc_version_folder)
                    os.makedirs(minecraft_client_dir, exist_ok=True)
                    
                    # Create or link the client extra JAR
                    # Use the version folder name for the version string
                    expected_jar = os.path.join(minecraft_client_dir, f'client-{mc_version_folder}-extra.jar')
                    
                    if not os.path.exists(expected_jar):
                        try:
                            # Copy the client.jar as the client-extra.jar
                            # This is a workaround - the real jar may be different, but ModLauncher may just need the file to exist
                            shutil.copy2(main_client_jar, expected_jar)
                            print(f"[forge] Created minecraft client resource for ModLauncher: {os.path.relpath(expected_jar, loader_dest_dir)}")
                            files_copied += 1
                        except Exception as e:
                            print(f"[forge] Note: Could not create client resource structure: {e}")
                            print(f"[forge] (This may be needed for ModLauncher - will attempt at runtime if needed)")

                    # Forge processors may expect MCP-scoped client resources under
                    # libraries/net/minecraft/client/<mc-mcp>/ with either an
                    # "-extra.jar" or "-srg.jar" suffix depending on Forge generation.
                    # On restricted networks these can be missing even when installer
                    # exits successfully, so stage local fallbacks for both names.
                    try:
                        raw_mcp = str(metadata.get("mcp_version") or "").strip()
                        if raw_mcp:
                            mcp_only = raw_mcp
                            prefix = f"{mc_version_folder}-"
                            if mcp_only.startswith(prefix):
                                mcp_only = mcp_only[len(prefix):]

                            if mcp_only:
                                version_token = f"{mc_version_folder}-{mcp_only}"
                                srg_dir = os.path.join(
                                    loader_dest_dir,
                                    'libraries',
                                    'net',
                                    'minecraft',
                                    'client',
                                    version_token,
                                )
                                os.makedirs(srg_dir, exist_ok=True)
                                source_jar = expected_jar if os.path.exists(expected_jar) else main_client_jar

                                mcp_extra_jar = os.path.join(srg_dir, f'client-{version_token}-extra.jar')
                                if not os.path.exists(mcp_extra_jar):
                                    shutil.copy2(source_jar, mcp_extra_jar)
                                    print(
                                        f"[forge] Staged missing ModLauncher MCP client resource: "
                                        f"{os.path.relpath(mcp_extra_jar, loader_dest_dir)}"
                                    )

                                srg_jar = os.path.join(srg_dir, f'client-{version_token}-srg.jar')
                                if not os.path.exists(srg_jar):
                                    shutil.copy2(source_jar, srg_jar)
                                    print(
                                        f"[forge] Staged missing ModLauncher SRG client resource: "
                                        f"{os.path.relpath(srg_jar, loader_dest_dir)}"
                                    )
                    except Exception as e:
                        print(f"[forge] Warning: Could not stage ModLauncher MCP resources: {e}")
            
            print(f"[forge] Forge {loader_version} installed successfully")
            print(f"[forge]   - {jars_copied} JARs")
            print(f"[forge]   - {files_copied} configuration/service files")
            print(f"[forge]   - Location: {loader_dest_dir}")
            
            _update_progress(version_key, "extracting_loader", 100, f"Forge installed ({jars_copied} JARs + configs)")
            
            result = {"ok": True, "loader_version": loader_version}
            
            # Note: Do NOT delete progress file here - let download_loader() handle cleanup
            # This keeps the progress file available for frontend polling
            
            return result
    
    except Exception as e:
        print(f"[forge] Error: {e}")
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


def _get_java_executable() -> Optional[str]:
    settings = load_global_settings()
    java_path = settings.get("java_path")
    
    if java_path and os.path.exists(java_path):
        return java_path
    
    # Try to find java in PATH
    try:
        result = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return "java"
    except:
        pass
    
    return None
