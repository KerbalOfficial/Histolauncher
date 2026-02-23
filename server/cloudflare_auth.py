# server/cloudflare_auth.py

import json
import urllib.request
import urllib.error
from typing import Dict, Tuple, Optional

ACCOUNT_API_URL = "https://accounts.histolauncher.workers.dev"

TIMEOUT = 10.0


def _make_request(method: str, endpoint: str, body: Optional[str] = None) -> Tuple[int, Optional[Dict]]:
    url = ACCOUNT_API_URL + endpoint
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Histolauncher/1.0"
    }
    
    req_body = body.encode("utf-8") if body else None
    req = urllib.request.Request(url, data=req_body, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            status = response.status
            resp_body = response.read().decode("utf-8")
            try:
                data = json.loads(resp_body)
            except json.JSONDecodeError:
                data = {"raw": resp_body}
            return status, data
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            resp_body = e.read().decode("utf-8")
            data = json.loads(resp_body)
        except (json.JSONDecodeError, AttributeError):
            data = {"error": str(e)}
        return status, data
    except Exception as e:
        return 500, {"error": str(e)}


def login(username: str, password: str) -> Tuple[bool, Optional[str], Optional[str]]:
    body = json.dumps({"username": username, "password": password})
    status, data = _make_request("POST", "/api/login", body)
    
    if status == 200 and data and data.get("success"):
        uuid = data.get("uuid")
        return True, uuid, None
    
    error = "Invalid credentials"
    if data and data.get("error"):
        error = data["error"]
    elif status >= 500:
        error = "Server error"
    elif status == 429:
        error = "Too many login attempts"
    
    return False, None, error


def signup(username: str, password: str) -> Tuple[bool, Optional[str], Optional[str]]:
    body = json.dumps({"username": username, "password": password})
    status, data = _make_request("POST", "/api/signup", body)
    
    if status == 200 and data and data.get("success"):
        uuid = data.get("uuid")
        return True, uuid, None
    
    error = "Failed to create account"
    if data and data.get("error"):
        error = data["error"]
    elif status == 409:
        error = "Username already taken"
    elif status >= 500:
        error = "Server error"
    elif status == 429:
        error = "Too many signup attempts"
    
    return False, None, error


def get_user_info(session_token: str) -> Tuple[bool, Optional[Dict], Optional[str]]:
    headers = {
        "Cookie": f"sessionToken={session_token}",
        "User-Agent": "Histolauncher/1.0"
    }
    
    url = ACCOUNT_API_URL + "/api/me"
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
                return True, user_data, None
            else:
                return False, None, data.get("error", "Failed to get user info")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, None, "Session expired"
        try:
            data = json.loads(e.read().decode("utf-8"))
            error = data.get("error", "Failed to get user info")
        except:
            error = "Failed to get user info"
        return False, None, error
    except Exception as e:
        return False, None, str(e)


def logout(session_token: str) -> bool:
    headers = {
        "Cookie": f"sessionToken={session_token}",
        "User-Agent": "Histolauncher/1.0"
    }
    
    url = ACCOUNT_API_URL + "/api/logout"
    req = urllib.request.Request(url, headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            return response.status == 200
    except Exception:
        return True


def get_verified_account() -> Tuple[bool, Optional[Dict], Optional[str]]:
    """
    Get the currently authenticated account by verifying session token.
    
    This is MORE SECURE than trusting settings.ini because it:
    - Validates the session server-side at Cloudflare
    - Gets the REAL account info from Cloudflare, not local config
    - Prevents someone from editing settings.ini to impersonate another user
    
    Returns:
        Tuple of (success, account_data, error_message)
        account_data = {"uuid": "...", "username": "..."}
    """
    from core.settings import load_session_token
    
    session_token = load_session_token()
    if not session_token:
        return False, None, "Not logged in"
    
    return get_user_info(session_token)
