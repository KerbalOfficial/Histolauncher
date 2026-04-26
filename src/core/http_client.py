from __future__ import annotations

import json
import os
import ssl
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from core.constants import (
    DOWNLOAD_CHUNK_BYTES,
    HTTP_DEFAULT_TIMEOUT_S,
    HTTP_DOWNLOAD_TIMEOUT_S,
    HTTP_RETRY_ATTEMPTS,
    HTTP_RETRY_BACKOFF_S,
    HTTP_USER_AGENT,
)

__all__ = ["HttpClient", "HttpClientError"]


ProgressCallback = Callable[[int, int], None]


class HttpClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        url: str,
        attempts: int,
        status: int | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.attempts = attempts
        self.status = status
        self.__cause__ = cause


def _apply_proxy(url: str) -> str:
    try:
        from core.settings import _apply_url_proxy  # noqa: PLC0415

        return _apply_url_proxy(url)
    except Exception:
        return url


def _build_unverified_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


class HttpClient:
    def __init__(
        self,
        *,
        user_agent: str = HTTP_USER_AGENT,
        timeout: float = HTTP_DEFAULT_TIMEOUT_S,
        retry_attempts: int = HTTP_RETRY_ATTEMPTS,
        retry_backoff_s: float = HTTP_RETRY_BACKOFF_S,
        allow_insecure_fallback: bool = False,
    ) -> None:
        self._user_agent = user_agent
        self._timeout = timeout
        self._retry_attempts = max(1, int(retry_attempts))
        self._retry_backoff_s = max(0.0, float(retry_backoff_s))
        self._allow_insecure_fallback = bool(allow_insecure_fallback)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_bytes(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> bytes:
        return self._request(url, headers=headers, timeout=timeout)

    def get_text(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        encoding: str = "utf-8",
    ) -> str:
        body = self._request(url, headers=headers, timeout=timeout)
        return body.decode(encoding, errors="replace")

    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Any:
        body = self._request(url, headers=headers, timeout=timeout)
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HttpClientError(
                f"failed to parse JSON from {url}: {exc}",
                url=url,
                attempts=self._retry_attempts,
                cause=exc,
            ) from exc

    def stream_to(
        self,
        url: str,
        dest_path: str | Path,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        chunk_size: int = DOWNLOAD_CHUNK_BYTES,
        on_progress: ProgressCallback | None = None,
    ) -> int:
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        effective_timeout = HTTP_DOWNLOAD_TIMEOUT_S if timeout is None else timeout

        last_error: BaseException | None = None
        last_status: int | None = None
        attempts = 0

        for candidate, attempt in self._iter_attempts(url):
            attempts += 1
            tmp_path: Path | None = None
            try:
                req = self._build_request(candidate, headers)
                with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
                    last_status = getattr(resp, "status", None)
                    total = int(resp.headers.get("Content-Length") or -1)
                    written = 0
                    with tempfile.NamedTemporaryFile(
                        "wb",
                        dir=str(dest.parent),
                        prefix=f".{dest.name}.",
                        suffix=".part",
                        delete=False,
                    ) as out:
                        tmp_path = Path(out.name)
                        while True:
                            chunk = resp.read(chunk_size)
                            if not chunk:
                                break
                            out.write(chunk)
                            written += len(chunk)
                            if on_progress is not None:
                                on_progress(written, total)
                    os.replace(tmp_path, dest)
                    return written
            except Exception as exc:  # noqa: BLE001
                if tmp_path is not None:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                last_error = exc
                last_status = self._extract_status(exc, last_status)
                self._sleep_for_attempt(attempt)

        raise HttpClientError(
            f"all {attempts} attempts to download {url} failed: {last_error!r}",
            url=url,
            attempts=attempts,
            status=last_status,
            cause=last_error,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _request(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None,
        timeout: float | None,
    ) -> bytes:
        effective_timeout = self._timeout if timeout is None else timeout
        last_error: BaseException | None = None
        last_status: int | None = None
        attempts = 0
        used_insecure = False

        for candidate, attempt in self._iter_attempts(url):
            attempts += 1
            context: ssl.SSLContext | None = None
            if used_insecure and candidate.lower().startswith("https://"):
                context = _build_unverified_context()

            try:
                req = self._build_request(candidate, headers)
                with urllib.request.urlopen(req, timeout=effective_timeout, context=context) as resp:
                    last_status = getattr(resp, "status", None)
                    return resp.read()
            except ssl.SSLError as exc:
                last_error = exc
                if self._allow_insecure_fallback and not used_insecure:
                    used_insecure = True
                    continue
                self._sleep_for_attempt(attempt)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                last_status = self._extract_status(exc, last_status)
                self._sleep_for_attempt(attempt)

        raise HttpClientError(
            f"all {attempts} attempts to fetch {url} failed: {last_error!r}",
            url=url,
            attempts=attempts,
            status=last_status,
            cause=last_error,
        )

    def _build_request(
        self,
        url: str,
        headers: Mapping[str, str] | None,
    ) -> urllib.request.Request:
        merged: dict[str, str] = {"User-Agent": self._user_agent}
        if headers:
            merged.update({str(k): str(v) for k, v in headers.items()})
        return urllib.request.Request(url, headers=merged)

    def _iter_attempts(self, url: str):
        candidates: list[str] = []
        proxied = _apply_proxy(url)
        if proxied:
            candidates.append(proxied)
        if url not in candidates:
            candidates.append(url)

        for candidate in candidates:
            for attempt in range(self._retry_attempts):
                yield candidate, attempt

    def _sleep_for_attempt(self, attempt: int) -> None:
        if self._retry_backoff_s <= 0:
            return
        time.sleep(self._retry_backoff_s * (attempt + 1))

    @staticmethod
    def _extract_status(exc: BaseException, fallback: int | None) -> int | None:
        if isinstance(exc, urllib.error.HTTPError):
            return int(exc.code)
        return fallback
