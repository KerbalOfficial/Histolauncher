from __future__ import annotations

import time
import urllib.error
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.downloader.errors import DownloadCancelled, DownloadFailed
from core.downloader.http import CLIENT
from core.mod_manager._constants import (
    CURSEFORGE_API_BASE,
    DIRECT_MODRINTH_API_BASE,
    IMPORT_RETRY_ATTEMPTS,
    IMPORT_RETRY_DELAY,
    MODRINTH_API_BASE,
    REQUEST_RETRY_ATTEMPTS,
    REQUEST_RETRY_DELAY,
    REQUEST_TIMEOUT,
    _MODRINTH_CACHE,
    logger,
)
from core.mod_manager._validation import _normalize_download_url


# ---------------------------------------------------------------------------
# Cache helpers (Modrinth)
# ---------------------------------------------------------------------------


def _modrinth_cache_get(key: str) -> Optional[Any]:
    entry = _MODRINTH_CACHE.get(key)
    if entry and time.monotonic() < entry["expires"]:
        return entry["data"]
    if entry:
        del _MODRINTH_CACHE[key]
    return None


def _modrinth_cache_set(key: str, data: Any, ttl: float) -> None:
    _MODRINTH_CACHE[key] = {"data": data, "expires": time.monotonic() + ttl}


# ---------------------------------------------------------------------------
# Cancellation helpers
# ---------------------------------------------------------------------------


def _raise_if_cancelled(cancel_check: Optional[Callable[[], None]] = None) -> None:
    if cancel_check:
        cancel_check()


def _sleep_with_cancel(
    delay_seconds: float,
    cancel_check: Optional[Callable[[], None]] = None,
) -> None:
    if delay_seconds <= 0:
        return
    deadline = time.monotonic() + delay_seconds
    while True:
        _raise_if_cancelled(cancel_check)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.1, remaining))


# ---------------------------------------------------------------------------
# Status / response helpers
# ---------------------------------------------------------------------------


def _is_retryable_http_status(status_code: int) -> bool:
    try:
        status = int(status_code)
    except Exception:
        return False
    return status == 429 or status >= 500


def _modrinth_response_looks_like_project(
    payload: Any, expected_project_type: str = "",
) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("error") and not payload.get("id"):
        return False
    project_type = str(payload.get("project_type") or "").strip().lower()
    expected = str(expected_project_type or "").strip().lower()
    if expected and project_type and project_type != expected:
        return False
    if not expected and project_type and project_type != "mod":
        return False
    return bool(
        str(payload.get("id") or "").strip()
        or str(payload.get("slug") or "").strip()
    )


# ---------------------------------------------------------------------------
# JSON API requests via shared HttpClient
# ---------------------------------------------------------------------------


def _http_status_from_exc(exc: BaseException) -> Optional[int]:
    cur: Optional[BaseException] = exc
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, urllib.error.HTTPError):
            return int(cur.code)
        cur = (
            getattr(cur, "cause", None)
            or getattr(cur, "__cause__", None)
            or getattr(cur, "__context__", None)
        )
    return None


def _curseforge_request(
    endpoint: str,
    params: Dict[str, Any] = None,
    api_key: str = None,
    max_attempts: int = REQUEST_RETRY_ATTEMPTS,
    retry_delay: float = REQUEST_RETRY_DELAY,
) -> Optional[Dict[str, Any]]:
    url = f"{CURSEFORGE_API_BASE}{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {"Accept": "application/json", "User-Agent": "Histolauncher/1.0"}
    if api_key:
        headers["x-api-key"] = str(api_key).strip()

    attempt_limit = max(1, int(max_attempts or 1))
    last_error: Optional[Dict[str, Any]] = None

    for attempt_index in range(attempt_limit):
        try:
            return CLIENT.fetch_json(
                url, headers=headers, timeout=REQUEST_TIMEOUT,
            )
        except DownloadCancelled:
            raise
        except DownloadFailed as exc:
            status = _http_status_from_exc(exc)
            if status is not None:
                logger.error(
                    f"CurseForge API HTTP error: {status} url={endpoint}"
                )
                last_error = {
                    "error": f"CurseForge HTTP {status}",
                    "requires_api_key": status in (401, 403),
                }
                if not _is_retryable_http_status(status):
                    return last_error
            else:
                logger.error(f"CurseForge API request failed: {exc}")
                last_error = {
                    "error": "CurseForge connection failed",
                    "requires_api_key": False,
                }
        except Exception as exc:  # noqa: BLE001
            logger.error(f"CurseForge API request failed: {exc}")
            last_error = {
                "error": "CurseForge request failed",
                "requires_api_key": False,
            }

        if attempt_index < attempt_limit - 1:
            time.sleep(retry_delay)

    return last_error or {
        "error": "CurseForge request failed",
        "requires_api_key": False,
    }


def _modrinth_request(
    endpoint: str,
    params: Dict[str, Any] = None,
    max_attempts: int = REQUEST_RETRY_ATTEMPTS,
    retry_delay: float = REQUEST_RETRY_DELAY,
) -> Optional[Any]:
    headers = {"Accept": "application/json", "User-Agent": "Histolauncher/1.0"}
    attempt_limit = max(1, int(max_attempts or 1))
    bases = [("Histolauncher discovery", MODRINTH_API_BASE)]
    if DIRECT_MODRINTH_API_BASE.rstrip("/") != MODRINTH_API_BASE.rstrip("/"):
        bases.append(("Modrinth direct", DIRECT_MODRINTH_API_BASE))

    for base_index, (base_label, base_url) in enumerate(bases):
        url = f"{base_url.rstrip('/')}{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        for attempt_index in range(attempt_limit):
            try:
                payload = CLIENT.fetch_json(
                    url, headers=headers, timeout=REQUEST_TIMEOUT,
                )
                if (
                    base_index < len(bases) - 1
                    and isinstance(payload, dict)
                    and (
                        payload.get("error")
                        or payload.get("errors")
                        or (payload.get("ok") is False and payload.get("message"))
                    )
                ):
                    logger.error(
                        f"Modrinth API error payload via {base_label}: url={endpoint}"
                    )
                    break
                return payload
            except DownloadCancelled:
                raise
            except DownloadFailed as exc:
                status = _http_status_from_exc(exc)
                if status is not None:
                    logger.error(
                        f"Modrinth API HTTP error via {base_label}: {status} url={endpoint}"
                    )
                    if base_index < len(bases) - 1:
                        break
                    if base_index == len(bases) - 1 and not _is_retryable_http_status(status):
                        return None
                else:
                    logger.error(f"Modrinth API request failed via {base_label}: {exc}")
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Modrinth API request failed via {base_label}: {exc}")

            if attempt_index < attempt_limit - 1:
                time.sleep(retry_delay)

        if base_index < len(bases) - 1:
            logger.info(
                f"Falling back from {base_label} to {bases[base_index + 1][0]} for Modrinth {endpoint}"
            )

    return None


# ---------------------------------------------------------------------------
# Binary file fetch (modpack imports)
# ---------------------------------------------------------------------------


def _download_external_mod_file(
    urls: List[str],
    *,
    max_attempts: int = IMPORT_RETRY_ATTEMPTS,
    retry_delay: float = IMPORT_RETRY_DELAY,
    cancel_check: Optional[Callable[[], None]] = None,
) -> Tuple[Optional[bytes], str]:
    normalized: List[str] = []
    for raw in urls:
        norm = _normalize_download_url(raw)
        if norm and norm not in normalized:
            normalized.append(norm)

    if not normalized:
        return None, "No valid download URL"

    last_error = ""
    attempt_limit = max(1, int(max_attempts or 1))

    for attempt_index in range(attempt_limit):
        _raise_if_cancelled(cancel_check)
        retryable = False
        for request_url in normalized:
            _raise_if_cancelled(cancel_check)
            try:
                payload = CLIENT.fetch_bytes(
                    request_url,
                    headers={"Accept": "application/octet-stream, */*"},
                    timeout=REQUEST_TIMEOUT,
                    cancel_check=cancel_check,
                )
                return payload, ""
            except DownloadCancelled:
                raise
            except DownloadFailed as exc:
                status = _http_status_from_exc(exc)
                if status is not None:
                    last_error = f"{request_url}: HTTP {status}"
                    retryable = retryable or _is_retryable_http_status(status)
                else:
                    last_error = f"{request_url}: {exc}"
                    retryable = True
            except Exception as exc:  # noqa: BLE001
                last_error = f"{request_url}: {exc}"
                retryable = True

        if attempt_index >= attempt_limit - 1 or not retryable:
            break
        _sleep_with_cancel(retry_delay, cancel_check=cancel_check)

    return None, (last_error or "No valid download URL")
