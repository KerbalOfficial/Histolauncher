from __future__ import annotations


__all__ = ["build_histolauncher_cookie_header", "load_histolauncher_cookie_header"]


def build_histolauncher_cookie_header(session_token: str) -> str:
    token = str(session_token or "").strip()
    if not token:
        return ""

    return f"authtoken={token}; sessionToken={token}"


def load_histolauncher_cookie_header() -> str:
    from core.settings import load_account_token

    try:
        return build_histolauncher_cookie_header(load_account_token() or "")
    except Exception:
        return ""
