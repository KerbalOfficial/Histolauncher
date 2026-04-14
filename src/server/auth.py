# server/auth.py

import json
import urllib.request
import urllib.error
import re

from typing         import Dict, Tuple, Optional

from core.settings  import _apply_url_proxy, load_global_settings
from core.logger    import colorize_log


ACCOUNT_API_URL = "https://accounts.histolauncher.org"

TIMEOUT = 10.0


def _histolauncher_account_enabled() -> bool:
    try:
        settings = load_global_settings() or {}
        return str(settings.get("account_type") or "Local").strip().lower() == "histolauncher"
    except Exception:
        return False


def _make_request(method: str, endpoint: str, body: Optional[str] = None, use_proxy: bool = True) -> Tuple[int, Optional[Dict], Dict]:
    url = ACCOUNT_API_URL + endpoint
    if use_proxy:
        url = _apply_url_proxy(url)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Histolauncher/1.0"
    }

    req_body = body.encode("utf-8") if body else None
    req = urllib.request.Request(url, data=req_body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            status = getattr(response, 'status', None) or response.getcode()
            resp_body = response.read().decode("utf-8")
            try:
                data = json.loads(resp_body)
            except json.JSONDecodeError:
                data = {"raw": resp_body}

            try:
                response_headers = dict(response.getheaders())
            except Exception:
                try:
                    response_headers = dict(response.headers.items()) if hasattr(response, 'headers') else {}
                except Exception:
                    response_headers = {}

            return status, data, response_headers
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            resp_body = e.read().decode("utf-8")
            data = json.loads(resp_body)
        except (json.JSONDecodeError, AttributeError):
            data = {"error": str(e)}

        try:
            response_headers = dict(e.headers.items()) if hasattr(e, 'headers') else {}
        except Exception:
            response_headers = {}

        return status, data, response_headers
    except Exception as e:
        return 500, {"error": str(e)}, {}


def login_with_session(username: str, password: str) -> Tuple[bool, Optional[str], Optional[str]]:
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
                        if k.lower() == 'set-cookie':
                            set_cookie = v
                            break
                if set_cookie:
                    m = re.search(r"sessionToken=([^;,\s]+)", set_cookie)
                    if m:
                        session_token = m.group(1)

            if session_token:
                return True, session_token, None, status

            print(colorize_log(f"[auth] Warning: No session token returned for user '{username}'! Response data: {data} Headers: {resp_headers}"))
            return False, None, "No session token returned", status

        error = "Invalid credentials"
        if data and data.get("error"):
            error = str(data["error"])
        elif status >= 500:
            print(colorize_log(f"[auth] Server error for user '{username}'. Status: {status}. Response data: {data}"))
            error = "Server error"
        elif status == 429:
            print(colorize_log(f"[auth] Too many login attempts for user '{username}'. Response data: {data}"))
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
        print(colorize_log(f"[auth] Server error for user '{username}'. Status: {status}. Response data: {data}"))
        error = "Server error"
    elif status == 429:
        print(colorize_log(f"[auth] Too many login attempts for user '{username}'. Response data: {data}"))
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
        print(colorize_log(f"[auth] Server error for user '{username}'. Status: {status}. Response data: {data}"))
        error = "Server error"
    elif status == 429:
        print(colorize_log(f"[auth] Too many signup attempts for user '{username}'. Response data: {data}"))
        error = "Too many signup attempts"
    
    return False, None, error


def get_user_info(session_token: str) -> Tuple[bool, Optional[Dict], Optional[str]]:
    headers = {
        "Cookie": f"sessionToken={session_token}",
        "User-Agent": "Histolauncher/1.0"
    }

    def _attempt(use_proxy: bool) -> Tuple[bool, Optional[Dict], Optional[str], Optional[int]]:
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
                        "username": data.get("username")
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
            prefetch = str(settings.get("prefetch_textures") or "").strip().lower() in {"1", "true", "yes"}
            if prefetch:
                import threading
                try:
                    import server.yggdrasil as _ygg
                    threading.Thread(target=_ygg.cache_textures, args=(user_data.get("uuid", ""), user_data.get("username", "")), kwargs={"probe_remote": True}, daemon=True).start()
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
        "User-Agent": "Histolauncher/1.0"
    }
    
    url = _apply_url_proxy(ACCOUNT_API_URL + "/api/logout")
    req = urllib.request.Request(url, headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            return response.status == 200
    except Exception:
        return True


def build_histolauncher_cookie_header(session_token: str) -> str:
    token = str(session_token or "").strip()
    if not token:
        return ""

    # The account APIs use sessionToken while the website expects authtoken.
    # Sending both keeps the embedded settings bridge compatible with either.
    return f"authtoken={token}; sessionToken={token}"


def load_histolauncher_cookie_header() -> str:
    from core.settings import load_account_token

    try:
        return build_histolauncher_cookie_header(load_account_token() or "")
    except Exception:
        return ""


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
