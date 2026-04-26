from __future__ import annotations

from typing import Dict, Optional, Tuple

from core.settings import _apply_url_proxy, load_global_settings

from server.auth.http import ACCOUNT_API_URL, _make_request
from server.auth.session import get_user_info


__all__ = [
    "_histolauncher_account_enabled",
    "get_verified_account",
    "get_launcher_message",
]


def _histolauncher_account_enabled() -> bool:
    try:
        settings = load_global_settings() or {}
        return str(settings.get("account_type") or "Local").strip().lower() == "histolauncher"
    except Exception:
        return False


def get_verified_account() -> Tuple[bool, Optional[Dict], Optional[str]]:
    from core.settings import load_account_token, load_cached_account_identity

    if not _histolauncher_account_enabled():
        return False, None, "Histolauncher account not enabled"

    session_token = load_account_token()
    if not session_token:
        return False, None, "Not logged in"

    success, user_data, error = get_user_info(session_token)
    if success:
        return True, user_data, None

    err = str(error or "").lower()
    if "session expired" in err or "not logged in" in err or "unauthorized" in err:
        return False, None, error

    cached = load_cached_account_identity()
    if cached:
        return True, cached, None

    return False, None, error


def get_launcher_message() -> Tuple[bool, Optional[Dict], Optional[str]]:
    endpoint = "/api/launcher-message"

    def _attempt(use_proxy: bool) -> Tuple[bool, Optional[Dict], Optional[str], int]:
        status, data, _ = _make_request("GET", endpoint, use_proxy=use_proxy)
        if status == 200 and isinstance(data, dict):
            return True, data, None, status

        error = "Failed to load launcher message"
        if isinstance(data, dict) and data.get("error"):
            error = str(data.get("error"))
        return False, None, error, status

    ok, payload, error, _ = _attempt(use_proxy=True)
    if ok:
        return True, payload, None

    proxied_url = _apply_url_proxy(ACCOUNT_API_URL + endpoint)
    if proxied_url != ACCOUNT_API_URL + endpoint:
        ok2, payload2, error2, _ = _attempt(use_proxy=False)
        if ok2:
            return True, payload2, None
        return False, None, error2

    return False, None, error
