from __future__ import annotations

import hashlib
import os
import ssl
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, List, Optional, Tuple

from core.downloader._legacy._constants import DOWNLOAD_CHUNK_SIZE
from core.downloader._legacy._state import STATE
from core.downloader._legacy.progress import _maybe_abort
from core.logger import colorize_log
from core.settings import _apply_url_proxy, load_global_settings


# ---------------------------------------------------------------------------
# Settings flags
# ---------------------------------------------------------------------------


def _is_fast_download_enabled() -> bool:
    try:
        settings = load_global_settings()
        return str(settings.get("fast_download", "0")).lower() in ("1", "true", "yes", "enabled")
    except Exception:
        return False


def _is_insecure_fallback_allowed() -> bool:
    try:
        settings = load_global_settings()
        return str(settings.get("allow_insecure_fallback", "0")).lower() in (
            "1", "true", "yes", "enabled",
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# URL candidate iteration
# ---------------------------------------------------------------------------


def _iter_url_candidates(url: str) -> List[str]:
    raw_url = str(url or "").strip()
    if not raw_url:
        return []

    proxied_url = _apply_url_proxy(raw_url)
    candidates: List[str] = []
    if proxied_url:
        candidates.append(proxied_url)
    if raw_url not in candidates:
        candidates.append(raw_url)
    return candidates


# ---------------------------------------------------------------------------
# Hashing / file utilities
# ---------------------------------------------------------------------------


def _sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(DOWNLOAD_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _safe_remove_file(file_path: str, max_retries: int = 5) -> bool:
    for attempt in range(max_retries):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            return True
        except (OSError, PermissionError) as e:
            if attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
            else:
                print(colorize_log(
                    f"[download] Warning: Could not remove {file_path} "
                    f"after {max_retries} attempts: {e}"
                ))
                return False
    return False


def _get_file_lock(file_path: str) -> threading.Lock:
    with STATE.file_locks_lock:
        lock = STATE.file_locks.get(file_path)
        if lock is None:
            lock = threading.Lock()
            STATE.file_locks[file_path] = lock
        return lock


def _cleanup_file_locks(max_locks: int = 1000) -> None:
    with STATE.file_locks_lock:
        if len(STATE.file_locks) > max_locks:
            to_remove = list(STATE.file_locks.keys())[:-max_locks]
            for key in to_remove:
                del STATE.file_locks[key]
            print(colorize_log(f"[download] Cleaned up file locks (kept {max_locks})"))


# ---------------------------------------------------------------------------
# download_file
# ---------------------------------------------------------------------------


def download_file(
    url: str,
    dest_path: str,
    expected_sha1: Optional[str] = None,
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
    retries: int = 3,
    version_key: Optional[str] = None,
) -> None:
    from core.downloader.errors import DownloadCancelled, DownloadFailed
    from core.downloader.http import HttpClient

    # Legacy cancel/pause is observed through module state; bridge it.
    def _cancel_check() -> None:
        _maybe_abort(version_key)

    _cancel_check()

    # Honour the per-call retry override by constructing a one-off client.
    client = HttpClient(retries=max(1, int(retries)))

    try:
        client.download(
            url,
            dest_path,
            expected_sha1=expected_sha1,
            progress_cb=progress_cb,
            cancel_check=_cancel_check,
        )
        return
    except DownloadCancelled:
        # Legacy callers expect RuntimeError on cancellation. Translate.
        raise RuntimeError("Download cancelled by user")
    except DownloadFailed as exc:
        # Legacy code re-raises a generic Exception; preserve message.
        raise RuntimeError(str(exc)) from exc
    except Exception:  # noqa: BLE001 — rebind into legacy retry/except landing pads
        raise


# Old in-function fallback path kept below as dead code in case future hot-fixes
# need to swap implementations quickly. Removed in cleanup phase.
def _legacy_download_file_unused(
    url: str,
    dest_path: str,
    expected_sha1: Optional[str] = None,
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
    retries: int = 3,
    version_key: Optional[str] = None,
) -> None:  # pragma: no cover - retained for archaeological reference only
    _maybe_abort(version_key)

    url_candidates = _iter_url_candidates(url)
    if not url_candidates:
        raise RuntimeError("download url is empty")

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    file_lock = _get_file_lock(dest_path)
    print(colorize_log(f"[download] Starting: {url_candidates[0]} -> {dest_path}"))
    last_err: Optional[BaseException] = None

    with file_lock:
        if os.path.exists(dest_path):
            print(colorize_log(f"[download] File already exists: {dest_path}"))
            return

        for candidate_idx, candidate_url in enumerate(url_candidates, start=1):
            if candidate_idx > 1:
                print(colorize_log(f"[download] Falling back to alternate URL: {candidate_url}"))

            for attempt in range(1, retries + 1):
                tmp_path = dest_path + ".part"
                try:
                    req = urllib.request.Request(
                        candidate_url, headers={"User-Agent": "Histolauncher/1.0"}
                    )
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
                                f"SHA1 mismatch for {dest_path}: "
                                f"expected {expected_sha1}, got {actual}"
                            )

                    if os.path.exists(dest_path):
                        _safe_remove_file(tmp_path)
                        print(colorize_log(
                            f"[download] File was downloaded by another thread: {dest_path}"
                        ))
                        return

                    os.rename(tmp_path, dest_path)
                    print(colorize_log(f"[download] Completed: {dest_path}"))
                    _cleanup_file_locks()
                    return
                except Exception as e:
                    last_err = e
                    print(colorize_log(
                        f"[download] Error on attempt {attempt}/{retries} "
                        f"for {candidate_url}: {e}"
                    ))
                    _safe_remove_file(tmp_path)
                    _maybe_abort(version_key)

    raise last_err or RuntimeError(f"Failed to download {url}")


# ---------------------------------------------------------------------------
# Legacy: _download_with_retry (used by yarn / Forge fallbacks)
# ---------------------------------------------------------------------------


def _download_with_retry(
    url: str,
    dest_file: str,
    progress_hook: Optional[Callable[..., Any]] = None,
    max_retries: int = 3,
) -> None:
    url_candidates = _iter_url_candidates(url)
    if not url_candidates:
        raise RuntimeError("download url is empty")

    insecure_fallback_allowed = _is_insecure_fallback_allowed()
    last_error: Optional[BaseException] = None

    for candidate_idx, candidate_url in enumerate(url_candidates, start=1):
        if candidate_idx > 1:
            print(colorize_log(f"[download] Falling back to alternate URL: {candidate_url}"))

        for attempt in range(max_retries):
            try:
                _stream_to_file(candidate_url, dest_file, progress_hook, context=None)
                return
            except ssl.SSLError as e:
                last_error = e
                if not insecure_fallback_allowed:
                    if attempt < max_retries - 1:
                        print(colorize_log(
                            f"[download] SSL error on attempt {attempt + 1}: {e}"
                        ))
                        time.sleep(1)
                        continue
                    raise
                print(colorize_log(
                    "[download] !! INSECURE: retrying with TLS verification disabled "
                    f"(allow_insecure_fallback=1) for {candidate_url}"
                ))
                time.sleep(1)
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                try:
                    _stream_to_file(candidate_url, dest_file, progress_hook, context=context)
                    return
                except Exception as retry_error:
                    last_error = retry_error
                    if attempt < max_retries - 2:
                        time.sleep(1)
                        continue
                    raise
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    print(colorize_log(
                        f"[download] Download error on attempt {attempt + 1}: {e}"
                    ))
                    time.sleep(1)
                else:
                    break

    if last_error:
        raise last_error


def _stream_to_file(
    url: str,
    dest_file: str,
    progress_hook: Optional[Callable[..., Any]],
    *,
    context: Optional[ssl.SSLContext],
) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher/1.0"})
    open_kwargs: dict[str, Any] = {}
    if context is not None:
        open_kwargs["context"] = context
    with urllib.request.urlopen(req, **open_kwargs) as response:
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


# ---------------------------------------------------------------------------
# Parallel downloader (used by asset workers)
# ---------------------------------------------------------------------------


DownloadTask = Tuple[str, str, Optional[str], Optional[Callable[[int, Optional[int]], None]], Optional[str]]


def _download_parallel(
    download_tasks: List[DownloadTask],
    max_workers: int = 15,
) -> None:
    if not download_tasks:
        return

    if _is_fast_download_enabled():
        max_workers = min(30, max(max_workers, 20))

    print(colorize_log(
        f"[download] Starting parallel download of {len(download_tasks)} "
        f"files with {max_workers} workers"
    ))

    completed = 0
    failed: List[Tuple[str, str]] = []

    def task_runner(task: DownloadTask) -> Tuple[bool, Optional[str]]:
        url, dest_path, expected_sha1, progress_cb, version_key = task
        try:
            download_file(url, dest_path, expected_sha1, progress_cb, version_key=version_key)
            return True, None
        except Exception as e:
            return False, str(e)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(task_runner, task): task for task in download_tasks}
        for future in as_completed(futures):
            task = futures[future]
            url, dest_path = task[0], task[1]
            try:
                success, error = future.result()
                if success:
                    completed += 1
                    print(colorize_log(
                        f"[download] Completed: {os.path.basename(dest_path)} "
                        f"({completed}/{len(download_tasks)})"
                    ))
                else:
                    failed.append((url, error or "unknown error"))
                    print(colorize_log(
                        f"[download] Failed: {os.path.basename(dest_path)} - {error}"
                    ))
            except Exception as e:
                failed.append((url, str(e)))
                print(colorize_log(
                    f"[download] Error for {os.path.basename(dest_path)}: {e}"
                ))

    if failed:
        error_msg = f"Failed to download {len(failed)}/{len(download_tasks)} files"
        print(colorize_log(f"[download] {error_msg}"))
        raise RuntimeError(error_msg)
    print(colorize_log(f"[download] All {len(download_tasks)} files downloaded successfully"))


__all__ = [
    "_cleanup_file_locks",
    "_download_parallel",
    "_download_with_retry",
    "_get_file_lock",
    "_is_fast_download_enabled",
    "_is_insecure_fallback_allowed",
    "_iter_url_candidates",
    "_safe_remove_file",
    "_sha1_file",
    "_sha256_file",
    "download_file",
]
