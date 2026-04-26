from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from typing import Dict, Optional, Tuple

from core.logger import colorize_log
from core.settings import _apply_url_proxy, load_global_settings

from server.auth.http import ACCOUNT_API_URL, TIMEOUT, _make_request


__all__ = [
    "login",
    "login_with_session",
    "signup",
    "logout",
    "get_user_info",
]


def login_with_session(
    username: str, password: str
) -> Tuple[bool, Optional[str], Optional[str]]:
    body = json.dumps({"username": username, "password": password})
    endpoint = "/api/login"

    def _attempt(use_proxy: bool) -> Tuple[bool, Optional[str], Optional[str], int]:
        status, data, resp_headers = _make_request("POST", endpoint, body, use_proxy=use_proxy)
        if status == 200 and data and data.get("success"):
            session_token = ""
            if isinstance(data, dict):
                session_token = str(data.get("sessionToken") or "").strip()

            if not session_token:
                set_cookie = None
                if isinstance(resp_headers, dict):
                    for k, v in resp_headers.items():
                        if k.lower() == "set-cookie":
                            set_cookie = v
                            break
                if set_cookie:
                    m = re.search(r"sessionToken=([^;,\s]+)", set_cookie)
                    if m:
                        session_token = m.group(1)

            if session_token:
                return True, session_token, None, status

            print(colorize_log(
                f"[auth] Warning: No session token returned for user '{username}'! "
                f"Response data: {data} Headers: {resp_headers}"
            ))
            return False, None, "No session token returned", status

        error = "Invalid credentials"
        if data and data.get("error"):
            error = str(data["error"])
        elif status >= 500:
            print(colorize_log(
                f"[auth] Server error for user '{username}'. Status: {status}. Response data: {data}"
            ))
            error = "Server error"
        elif status == 429:
            print(colorize_log(
                f"[auth] Too many login attempts for user '{username}'. Response data: {data}"
            ))
            error = "Too many login attempts"

        return False, None, error, status

    ok, session_token, error, status = _attempt(use_proxy=True)
    if ok:
        return True, session_token, None

    proxied_url = _apply_url_proxy(ACCOUNT_API_URL + endpoint)
    if proxied_url != ACCOUNT_API_URL + endpoint and status not in (401, 403):
        ok2, session_token2, error2, _ = _attempt(use_proxy=False)
        if ok2:
            return True, session_token2, None
        return False, None, error2

    return False, None, error


def login(username: str, password: str) -> Tuple[bool, Optional[str], Optional[str]]:
    body = json.dumps({"username": username, "password": password})
    status, data, _ = _make_request("POST", "/api/login", body)

    if status == 200 and data and data.get("success"):
        uuid = data.get("uuid")
        return True, uuid, None

    error = "Invalid credentials"
    if data and data.get("error"):
        error = data["error"]
    elif status >= 500:
        print(colorize_log(
            f"[auth] Server error for user '{username}'. Status: {status}. Response data: {data}"
        ))
        error = "Server error"
    elif status == 429:
        print(colorize_log(
            f"[auth] Too many login attempts for user '{username}'. Response data: {data}"
        ))
        error = "Too many login attempts"

    return False, None, error


def signup(username: str, password: str) -> Tuple[bool, Optional[str], Optional[str]]:
    body = json.dumps({"username": username, "password": password})
    status, data, _ = _make_request("POST", "/api/signup", body)

    if status == 200 and data and data.get("success"):
        uuid = data.get("uuid")
        return True, uuid, None

    error = "Failed to create account"
    if data and data.get("error"):
        error = data["error"]
    elif status == 409:
        error = "Username already taken"
    elif status >= 500:
        print(colorize_log(
            f"[auth] Server error for user '{username}'. Status: {status}. Response data: {data}"
        ))
        error = "Server error"
    elif status == 429:
        print(colorize_log(
            f"[auth] Too many signup attempts for user '{username}'. Response data: {data}"
        ))
        error = "Too many signup attempts"

    return False, None, error


def get_user_info(
    session_token: str,
) -> Tuple[bool, Optional[Dict], Optional[str]]:
    headers = {
        "Cookie": f"sessionToken={session_token}",
        "User-Agent": "Histolauncher/1.0",
    }

    def _attempt(
        use_proxy: bool,
    ) -> Tuple[bool, Optional[Dict], Optional[str], Optional[int]]:
        url = ACCOUNT_API_URL + "/api/me"
        if use_proxy:
            url = _apply_url_proxy(url)

        req = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                status = response.status
                resp_body = response.read().decode("utf-8")
                data = json.loads(resp_body)

                if status == 200 and data and data.get("success"):
                    user_data = {
                        "uuid": data.get("uuid"),
                        "username": data.get("username"),
                    }
                    try:
                        from core.settings import save_cached_account_identity

                        save_cached_account_identity(user_data)
                    except Exception:
                        pass
                    return True, user_data, None, status
                return False, None, data.get("error", "Failed to get user info"), status
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return False, None, "Session expired", e.code
            try:
                data = json.loads(e.read().decode("utf-8"))
                error = data.get("error", "Failed to get user info")
            except Exception:
                error = "Failed to get user info"
            return False, None, error, e.code
        except Exception as e:
            return False, None, str(e), None

    ok, user_data, error, status = _attempt(use_proxy=True)
    if ok:
        try:
            settings = load_global_settings() or {}
            prefetch = (
                str(settings.get("prefetch_textures") or "").strip().lower()
                in {"1", "true", "yes"}
            )
            if prefetch:
                import threading

                try:
                    import server.yggdrasil as _ygg

                    threading.Thread(
                        target=_ygg.cache_textures,
                        args=(user_data.get("uuid", ""), user_data.get("username", "")),
                        kwargs={"probe_remote": True},
                        daemon=True,
                    ).start()
                except Exception:
                    pass
        except Exception:
            pass
        return True, user_data, None

    proxied_url = _apply_url_proxy(ACCOUNT_API_URL + "/api/me")
    if proxied_url != ACCOUNT_API_URL + "/api/me" and status != 401:
        ok2, user_data2, error2, _ = _attempt(use_proxy=False)
        if ok2:
            return True, user_data2, None
        return False, None, error2

    return False, None, error


def logout(session_token: str) -> bool:
    headers = {
        "Cookie": f"sessionToken={session_token}",
        "User-Agent": "Histolauncher/1.0",
    }

    url = _apply_url_proxy(ACCOUNT_API_URL + "/api/logout")
    req = urllib.request.Request(url, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            return response.status == 200
    except Exception:
        return True
