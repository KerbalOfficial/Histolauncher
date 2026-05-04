from __future__ import annotations

from server.auth.cookies import (
    build_histolauncher_cookie_header,
    load_histolauncher_cookie_header,
)
from server.auth.http import ACCOUNT_API_URL, TIMEOUT, _make_request
from server.auth.session import (
    get_user_info,
    login,
    login_with_session,
    logout,
    signup,
)
from server.auth.microsoft import (
    get_microsoft_launch_account,
    get_verified_microsoft_account,
    microsoft_account_enabled,
    poll_device_code,
    refresh_microsoft_account,
    resolve_microsoft_texture_url,
    start_device_code,
)
from server.auth.verification import (
    _histolauncher_account_enabled,
    get_launcher_message,
    get_verified_account,
)


__all__ = [
    "ACCOUNT_API_URL",
    "TIMEOUT",
    "_make_request",
    "_histolauncher_account_enabled",
    "build_histolauncher_cookie_header",
    "load_histolauncher_cookie_header",
    "get_user_info",
    "get_microsoft_launch_account",
    "get_verified_microsoft_account",
    "login",
    "login_with_session",
    "logout",
    "microsoft_account_enabled",
    "poll_device_code",
    "refresh_microsoft_account",
    "resolve_microsoft_texture_url",
    "start_device_code",
    "signup",
    "get_launcher_message",
    "get_verified_account",
]
