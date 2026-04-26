from __future__ import annotations

import hashlib
import os
import shutil
import ssl
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, List, Optional, Tuple

from core.downloader.errors import DownloadFailed, HashMismatch
from core.logger import colorize_log

#: Streaming read size. Tuned for asset-heavy installs (~64 KiB == one OS page batch).
DEFAULT_CHUNK_SIZE: int = 64 * 1024

#: Default user agent. Mirrors legacy "Histolauncher/1.0" so downstream metrics
#: don't change.
DEFAULT_USER_AGENT: str = "Histolauncher/1.0"

#: Progress callback shape: ``(bytes_done, bytes_total_or_None)``.
ProgressCallback = Callable[[int, Optional[int]], None]

#: Cancel-check callable. Called between chunks; should raise to abort.
CancelCheck = Callable[[], None]


# ---------------------------------------------------------------------------
# URL candidate iteration (proxy fallback)
# ---------------------------------------------------------------------------


def iter_url_candidates(url: str) -> List[str]:
    raw = (url or "").strip()
    if not raw:
        return []

    try:
        from core.settings import _apply_url_proxy
    except Exception:
        _apply_url_proxy = lambda u: u  # noqa: E731

    candidates: List[str] = []
    proxied = _apply_url_proxy(raw)
    if proxied:
        candidates.append(proxied)
    if raw not in candidates:
        candidates.append(raw)
    return candidates


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def hash_file(path: str, algo: str = "sha1", chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_existing(
    path: str,
    *,
    expected_sha1: Optional[str] = None,
    expected_sha256: Optional[str] = None,
    expected_size: Optional[int] = None,
) -> bool:
    if not os.path.exists(path):
        return False
    if expected_size is not None:
        try:
            if os.path.getsize(path) != int(expected_size):
                return False
        except OSError:
            return False
    if expected_sha1:
        if hash_file(path, "sha1").lower() != expected_sha1.lower():
            return False
    if expected_sha256:
        if hash_file(path, "sha256").lower() != expected_sha256.lower():
            return False
    return True


# ---------------------------------------------------------------------------
# File locking helpers (per-destination, bounded LRU eviction)
# ---------------------------------------------------------------------------


class _FileLockTable:
    def __init__(self, max_locks: int = 1024) -> None:
        self._lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._touched: dict[str, float] = {}
        self._max = max_locks

    def get(self, path: str) -> threading.Lock:
        with self._lock:
            lock = self._locks.get(path)
            if lock is None:
                lock = threading.Lock()
                self._locks[path] = lock
            self._touched[path] = time.time()
            self._evict_locked()
            return lock

    def _evict_locked(self) -> None:
        if len(self._locks) <= self._max:
            return
        # Drop oldest unheld locks until we're back at threshold.
        for path, _ in sorted(self._touched.items(), key=lambda kv: kv[1]):
            if len(self._locks) <= self._max:
                return
            lock = self._locks.get(path)
            if lock is None:
                continue
            if lock.acquire(blocking=False):
                try:
                    self._locks.pop(path, None)
                    self._touched.pop(path, None)
                finally:
                    lock.release()


_FILE_LOCKS = _FileLockTable()


def _safe_remove(path: str, max_attempts: int = 5) -> bool:
    for attempt in range(max_attempts):
        try:
            if os.path.exists(path):
                os.remove(path)
            return True
        except (OSError, PermissionError):
            if attempt == max_attempts - 1:
                return False
            time.sleep(0.1 * (attempt + 1))
    return False


def _settings_flag(name: str, default: str = "0") -> bool:
    try:
        from core.settings import load_global_settings
    except Exception:
        return False
    try:
        settings = load_global_settings() or {}
        value = str(settings.get(name, default)).lower()
        return value in ("1", "true", "yes", "enabled", "on")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# HttpClient
# ---------------------------------------------------------------------------


@dataclass
class _AttemptResult:
    ok: bool
    error: Optional[BaseException] = None


class HttpClient:
    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        retries: int = 3,
        backoff_base: float = 0.5,
        opener: Optional[urllib.request.OpenerDirector] = None,
    ) -> None:
        self.user_agent = user_agent
        self.chunk_size = chunk_size
        self.retries = max(1, int(retries))
        self.backoff_base = backoff_base
        self._opener = opener  # if None, use module-level urllib

    # ---- public API ---------------------------------------------------------

    def download(
        self,
        url: str,
        dest_path: str,
        *,
        expected_sha1: Optional[str] = None,
        expected_sha256: Optional[str] = None,
        expected_size: Optional[int] = None,
        progress_cb: Optional[ProgressCallback] = None,
        cancel_check: Optional[CancelCheck] = None,
        resume: bool = True,
        force: bool = False,
    ) -> None:
        if cancel_check:
            cancel_check()

        candidates = iter_url_candidates(url)
        if not candidates:
            raise DownloadFailed("download URL is empty", url=url)

        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)

        file_lock = _FILE_LOCKS.get(dest_path)
        with file_lock:
            # Fast path: destination already valid.
            if not force and verify_existing(
                dest_path,
                expected_sha1=expected_sha1,
                expected_sha256=expected_sha256,
                expected_size=expected_size,
            ):
                if progress_cb and expected_size:
                    progress_cb(int(expected_size), int(expected_size))
                return

            # If file exists but we have no way to verify it, preserve
            # legacy behaviour and assume valid (skip download). This avoids
            # re-fetching libraries cached without sha metadata.
            if (
                not force
                and
                os.path.exists(dest_path)
                and not expected_sha1
                and not expected_sha256
                and expected_size is None
            ):
                if progress_cb:
                    size = os.path.getsize(dest_path)
                    progress_cb(size, size)
                return

            tmp_path = dest_path + ".part"
            if force:
                _safe_remove(tmp_path)
            insecure_allowed = _settings_flag("allow_insecure_fallback")
            last_error: Optional[BaseException] = None

            for c_index, candidate in enumerate(candidates):
                if c_index > 0:
                    print(colorize_log(f"[http] Falling back to {candidate}"))
                for attempt in range(1, self.retries + 1):
                    if cancel_check:
                        cancel_check()
                    try:
                        self._stream_one(
                            candidate,
                            tmp_path,
                            progress_cb=progress_cb,
                            cancel_check=cancel_check,
                            resume=resume and not force,
                            ssl_context=None,
                        )
                        self._finalize(
                            tmp_path,
                            dest_path,
                            expected_sha1=expected_sha1,
                            expected_sha256=expected_sha256,
                            expected_size=expected_size,
                        )
                        return
                    except ssl.SSLError as exc:
                        last_error = exc
                        if insecure_allowed:
                            print(colorize_log(
                                "[http] !! INSECURE: retrying with TLS verification "
                                f"disabled for {candidate}"
                            ))
                            ctx = ssl.create_default_context()
                            ctx.check_hostname = False
                            ctx.verify_mode = ssl.CERT_NONE
                            try:
                                self._stream_one(
                                    candidate,
                                    tmp_path,
                                    progress_cb=progress_cb,
                                    cancel_check=cancel_check,
                                    resume=resume and not force,
                                    ssl_context=ctx,
                                )
                                self._finalize(
                                    tmp_path,
                                    dest_path,
                                    expected_sha1=expected_sha1,
                                    expected_sha256=expected_sha256,
                                    expected_size=expected_size,
                                )
                                return
                            except Exception as inner:  # noqa: BLE001
                                last_error = inner
                        self._backoff(attempt)
                    except HashMismatch:
                        # Hash mismatch is terminal for this URL; clean up.
                        _safe_remove(tmp_path)
                        raise
                    except Exception as exc:  # noqa: BLE001
                        last_error = exc
                        print(colorize_log(
                            f"[http] attempt {attempt}/{self.retries} failed for "
                            f"{candidate}: {exc}"
                        ))
                        _safe_remove(tmp_path)
                        if cancel_check:
                            cancel_check()
                        self._backoff(attempt)

            raise DownloadFailed(
                f"failed to download {url} after retries",
                url=url,
                cause=last_error,
            )

    def download_many(
        self,
        tasks: Iterable["DownloadTask"],
        *,
        max_workers: int = 8,
        cancel_check: Optional[CancelCheck] = None,
    ) -> None:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        tasks = list(tasks)
        if not tasks:
            return

        max_workers = max(1, min(max_workers, len(tasks)))
        errors: List[BaseException] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for task in tasks:
                if cancel_check:
                    try:
                        cancel_check()
                    except BaseException as exc:
                        # Cancel propagates immediately; outstanding tasks
                        # will check cancel themselves.
                        errors.append(exc)
                        break
                futures.append(executor.submit(
                    self.download,
                    task.url,
                    task.dest_path,
                    expected_sha1=task.expected_sha1,
                    expected_sha256=task.expected_sha256,
                    expected_size=task.expected_size,
                    progress_cb=task.progress_cb,
                    cancel_check=cancel_check,
                    resume=task.resume,
                    force=task.force,
                ))
            for future in as_completed(futures):
                try:
                    future.result()
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

        if errors:
            # Re-raise the first error; preserve cancellations preferentially.
            from core.downloader.errors import DownloadCancelled
            for err in errors:
                if isinstance(err, DownloadCancelled):
                    raise err
            raise errors[0]

    # ---- lightweight one-shot helpers for API requests ---------------------

    def fetch_bytes(
        self,
        url: str,
        *,
        headers: Optional[dict[str, str]] = None,
        timeout: float = 30.0,
        cancel_check: Optional[CancelCheck] = None,
    ) -> bytes:
        if cancel_check:
            cancel_check()

        candidates = iter_url_candidates(url)
        if not candidates:
            raise DownloadFailed("URL is empty", url=url)

        merged_headers = {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
        }
        if headers:
            merged_headers.update(headers)

        insecure_allowed = _settings_flag("allow_insecure_fallback")
        last_error: Optional[BaseException] = None
        last_status: Optional[int] = None

        for c_index, candidate in enumerate(candidates):
            if c_index > 0:
                print(colorize_log(f"[http] fetch_bytes falling back to {candidate}"))
            for attempt in range(1, self.retries + 1):
                if cancel_check:
                    cancel_check()
                ctx_options = [None]
                if insecure_allowed:
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    ctx_options.append(ctx)
                tried_insecure = False
                for ctx_opt in ctx_options:
                    try:
                        req = urllib.request.Request(candidate, headers=merged_headers)
                        kwargs: dict[str, Any] = {"timeout": timeout}
                        if ctx_opt is not None:
                            kwargs["context"] = ctx_opt
                            tried_insecure = True
                        if self._opener is not None:
                            with self._opener.open(req, **kwargs) as resp:
                                return resp.read()
                        with urllib.request.urlopen(req, **kwargs) as resp:
                            return resp.read()
                    except urllib.error.HTTPError as exc:
                        last_error = exc
                        last_status = exc.code
                        # Non-retryable client errors: stop attempting this URL.
                        if exc.code in (400, 401, 403, 404, 410):
                            break
                    except ssl.SSLError as exc:
                        last_error = exc
                        if not insecure_allowed or tried_insecure:
                            break
                        # Allow the insecure-context retry pass.
                        continue
                    except Exception as exc:  # noqa: BLE001
                        last_error = exc
                    break  # break ctx loop after first non-SSL exception
                else:
                    continue
                # Attempt failed; back off and retry.
                if attempt < self.retries:
                    self._backoff(attempt)

        raise DownloadFailed(
            f"failed to fetch {url} after retries (last status: {last_status})",
            url=url,
            cause=last_error,
        )

    def fetch_json(
        self,
        url: str,
        *,
        headers: Optional[dict[str, str]] = None,
        timeout: float = 30.0,
        cancel_check: Optional[CancelCheck] = None,
    ) -> Any:
        import json as _json
        merged = {"Accept": "application/json"}
        if headers:
            merged.update(headers)
        body = self.fetch_bytes(
            url, headers=merged, timeout=timeout, cancel_check=cancel_check,
        )
        return _json.loads(body.decode("utf-8"))

    # ---- internals ----------------------------------------------------------

    def _backoff(self, attempt: int) -> None:
        time.sleep(min(5.0, self.backoff_base * (2 ** (attempt - 1))))

    def _open(
        self, request: urllib.request.Request, *, ssl_context: Optional[ssl.SSLContext]
    ):
        kwargs: dict[str, Any] = {}
        if ssl_context is not None:
            kwargs["context"] = ssl_context
        if self._opener is not None:
            return self._opener.open(request, **kwargs)
        return urllib.request.urlopen(request, **kwargs)

    def _stream_one(
        self,
        url: str,
        tmp_path: str,
        *,
        progress_cb: Optional[ProgressCallback],
        cancel_check: Optional[CancelCheck],
        resume: bool,
        ssl_context: Optional[ssl.SSLContext],
    ) -> None:
        headers: dict[str, str] = {"User-Agent": self.user_agent}
        existing_bytes = 0
        if resume and os.path.exists(tmp_path):
            try:
                existing_bytes = os.path.getsize(tmp_path)
            except OSError:
                existing_bytes = 0
            if existing_bytes > 0:
                headers["Range"] = f"bytes={existing_bytes}-"

        request = urllib.request.Request(url, headers=headers)
        try:
            response = self._open(request, ssl_context=ssl_context)
        except urllib.error.HTTPError as exc:
            # Server doesn't support resume — start from scratch.
            if existing_bytes and exc.code in (416,):
                _safe_remove(tmp_path)
                existing_bytes = 0
                headers.pop("Range", None)
                request = urllib.request.Request(url, headers=headers)
                response = self._open(request, ssl_context=ssl_context)
            else:
                raise

        with response:
            # If we asked for a Range and the server returned 200, it doesn't
            # support resume — restart.
            status = getattr(response, "status", None) or response.getcode()
            mode = "ab" if (existing_bytes and status == 206) else "wb"
            if mode == "wb":
                existing_bytes = 0

            content_length = self._read_content_length(response)
            total: Optional[int]
            if content_length is None:
                total = None
            else:
                total = existing_bytes + content_length

            downloaded = existing_bytes
            with open(tmp_path, mode) as out:
                while True:
                    if cancel_check:
                        cancel_check()
                    chunk = response.read(self.chunk_size)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total)

    @staticmethod
    def _read_content_length(response: Any) -> Optional[int]:
        # Prefer Content-Length; falls back to ``response.length`` if present.
        length_header = response.headers.get("Content-Length")
        if length_header:
            try:
                return int(length_header)
            except (TypeError, ValueError):
                pass
        attr_length = getattr(response, "length", None)
        if isinstance(attr_length, int):
            return attr_length
        return None

    def _finalize(
        self,
        tmp_path: str,
        dest_path: str,
        *,
        expected_sha1: Optional[str],
        expected_sha256: Optional[str],
        expected_size: Optional[int],
    ) -> None:
        if expected_size is not None:
            try:
                actual = os.path.getsize(tmp_path)
            except OSError:
                actual = -1
            if actual != int(expected_size):
                _safe_remove(tmp_path)
                raise DownloadFailed(
                    f"size mismatch for {dest_path}: "
                    f"expected {expected_size}, got {actual}"
                )

        if expected_sha1:
            actual = hash_file(tmp_path, "sha1")
            if actual.lower() != expected_sha1.lower():
                raise HashMismatch(dest_path, expected_sha1, actual, "sha1")

        if expected_sha256:
            actual = hash_file(tmp_path, "sha256")
            if actual.lower() != expected_sha256.lower():
                raise HashMismatch(dest_path, expected_sha256, actual, "sha256")

        if os.path.exists(dest_path):
            # Another worker won the race; drop our copy.
            _safe_remove(tmp_path)
            return

        # os.replace is atomic on Windows and POSIX.
        try:
            os.replace(tmp_path, dest_path)
        except OSError:
            # Cross-device or other rename failure: fall back to copy.
            shutil.copyfile(tmp_path, dest_path)
            _safe_remove(tmp_path)


# ---------------------------------------------------------------------------
# Parallel-download task
# ---------------------------------------------------------------------------


@dataclass
class DownloadTask:
    url: str
    dest_path: str
    expected_sha1: Optional[str] = None
    expected_sha256: Optional[str] = None
    expected_size: Optional[int] = None
    progress_cb: Optional[ProgressCallback] = None
    resume: bool = True
    force: bool = False


#: Process-wide singleton client.
CLIENT = HttpClient()


__all__ = [
    "CLIENT",
    "CancelCheck",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_USER_AGENT",
    "DownloadTask",
    "HttpClient",
    "ProgressCallback",
    "hash_file",
    "iter_url_candidates",
    "verify_existing",
]
