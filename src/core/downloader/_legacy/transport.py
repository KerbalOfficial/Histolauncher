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
from core.logger import safe_print
from core.settings import _apply_url_proxy, load_global_settings


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
# hashing / file utilities
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
                safe_print(
                    f"[download] Warning: Could not remove {file_path} "
                    f"after {max_retries} attempts: {e}"
                )
                return False
    return False


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

    def _cancel_check() -> None:
        _maybe_abort(version_key)

    _cancel_check()

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
        raise RuntimeError("Download cancelled by user")
    except DownloadFailed as exc:
        raise RuntimeError(str(exc)) from exc
    except Exception:  # noqa: BLE001
        raise


# ---------------------------------------------------------------------------
# legacy: _download_with_retry (used by yarn / Forge fallbacks)
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
            safe_print(f"[download] Falling back to alternate URL: {candidate_url}")

        for attempt in range(max_retries):
            try:
                _stream_to_file(candidate_url, dest_file, progress_hook, context=None)
                return
            except ssl.SSLError as e:
                last_error = e
                if not insecure_fallback_allowed:
                    if attempt < max_retries - 1:
                        safe_print(
                            f"[download] SSL error on attempt {attempt + 1}: {e}"
                        )
                        time.sleep(1)
                        continue
                    raise
                safe_print(
                    "[download] !! INSECURE: retrying with TLS verification disabled "
                    f"(allow_insecure_fallback=1) for {candidate_url}"
                )
                time.sleep(1)
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                try:
                    _stream_to_file(candidate_url, dest_file, progress_hook, context=context)
                    return
                except Exception as retry_error:
                    last_error = retry_error
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    raise
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    safe_print(
                        f"[download] Download error on attempt {attempt + 1}: {e}"
                    )
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
    tmp_file = dest_file + ".part"
    try:
        with urllib.request.urlopen(req, **open_kwargs) as response:
            total_size = int(response.headers.get("Content-Length", 0)) or None
            if progress_hook:
                block_size = 8192
                downloaded = 0
                with open(tmp_file, "wb") as f:
                    while True:
                        block = response.read(block_size)
                        if not block:
                            break
                        f.write(block)
                        downloaded += len(block)
                        progress_hook(downloaded // block_size, block_size, total_size)
            else:
                with open(tmp_file, "wb") as f:
                    f.write(response.read())
        os.replace(tmp_file, dest_file)
    except BaseException:
        _safe_remove_file(tmp_file)
        raise


# ---------------------------------------------------------------------------
# parallel downloader (used by asset workers)
# ---------------------------------------------------------------------------


DownloadTask = Tuple[str, str, Optional[str], Optional[Callable[[int, Optional[int]], None]], Optional[str]]


def _download_parallel(
    download_tasks: List[DownloadTask],
    max_workers: int = 15,
) -> None:
    if not download_tasks:
        return

    safe_print(
        f"[download] Starting parallel download of {len(download_tasks)} "
        f"files with {max_workers} workers"
    )

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
                    safe_print(
                        f"[download] Completed: {os.path.basename(dest_path)} "
                        f"({completed}/{len(download_tasks)})"
                    )
                else:
                    failed.append((url, error or "unknown error"))
                    safe_print(
                        f"[download] Failed: {os.path.basename(dest_path)} - {error}"
                    )
            except Exception as e:
                failed.append((url, str(e)))
                safe_print(
                    f"[download] Error for {os.path.basename(dest_path)}: {e}"
                )

    if failed:
        error_msg = f"Failed to download {len(failed)}/{len(download_tasks)} files"
        safe_print(f"[download] {error_msg}")
        raise RuntimeError(error_msg)
    safe_print(f"[download] All {len(download_tasks)} files downloaded successfully")


__all__ = [
    "_download_parallel",
    "_download_with_retry",
    "_is_insecure_fallback_allowed",
    "_iter_url_candidates",
    "_safe_remove_file",
    "_sha1_file",
    "_sha256_file",
    "download_file",
]
