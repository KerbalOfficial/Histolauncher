from __future__ import annotations

import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from core.logger import colorize_log
from core.settings import (
    _apply_url_proxy,
    clear_account_token,
    get_base_dir,
    load_global_settings,
    save_global_settings,
)

from server.api._constants import HISTOLAUNCHER_WEB_ORIGINS


__all__ = [
    "_verify_and_store_session_token",
    "api_account_login",
    "api_account_verify_session",
    "api_account_current",
    "api_account_refresh_assets",
    "api_account_settings_iframe",
    "api_account_launcher_message",
    "api_account_status",
    "api_account_disconnect",
]


def _verify_and_store_session_token(session_token: str):
    from core.settings import save_account_token
    from server.auth import get_user_info

    session_value = str(session_token or "").strip()
    if not session_value:
        return {"ok": False, "error": "missing sessionToken"}

    success, user_data, error = get_user_info(session_value)
    if not success:
        return {"ok": False, "error": error or "Failed to verify session"}

    save_account_token(session_value)

    try:
        s = load_global_settings() or {}
        s["account_type"] = "Histolauncher"
        s.pop("uuid", None)
        s.pop("username", None)
        save_global_settings(s)
    except Exception as e:
        return {"ok": False, "error": f"Failed to save settings: {str(e)}"}

    username = user_data.get("username", "")
    account_uuid = user_data.get("uuid", "")
    print(colorize_log(
        f"[api_account_verify_session] Account verified: "
        f"username={username}, uuid={account_uuid}"
    ))

    return {
        "ok": True,
        "message": "Session verified and stored",
        "username": username,
        "uuid": account_uuid,
    }


def api_account_login(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid request"}

        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "").strip()
        if not username or not password:
            return {"ok": False, "error": "missing username or password"}

        from server.auth import login_with_session

        success, session_token, error = login_with_session(username, password)
        if not success or not session_token:
            return {"ok": False, "error": error or "Invalid credentials"}

        return _verify_and_store_session_token(session_token)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_account_verify_session(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid request"}
        return _verify_and_store_session_token(data.get("sessionToken", ""))
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


def api_account_current():
    try:
        settings = load_global_settings() or {}
        if str(settings.get("account_type") or "Local").strip().lower() != "histolauncher":
            return {
                "ok": False,
                "error": "Histolauncher account not enabled",
                "authenticated": False,
                "unauthorized": False,
                "local_account": True,
            }

        from server.auth import get_verified_account

        success, user_data, error = get_verified_account()
        if not success:
            err_msg = (error or "").lower()
            unauthorized = False
            if "not logged in" in err_msg or "session expired" in err_msg:
                unauthorized = True
            return {
                "ok": False,
                "error": error or "Not authenticated",
                "authenticated": False,
                "unauthorized": unauthorized,
            }

        return {
            "ok": True,
            "authenticated": True,
            "uuid": user_data.get("uuid", ""),
            "username": user_data.get("username", ""),
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "authenticated": False,
            "network_error": True,
        }


def api_account_refresh_assets(data=None):
    try:
        settings = load_global_settings() or {}
        if str(settings.get("account_type") or "Local").strip().lower() != "histolauncher":
            return {
                "ok": False,
                "error": "Histolauncher account not enabled",
                "authenticated": False,
                "unauthorized": False,
            }

        from core.settings import load_account_token
        from server import yggdrasil
        from server.auth import get_user_info

        session_token = load_account_token()
        if not session_token:
            return {
                "ok": False,
                "error": "Not authenticated",
                "authenticated": False,
                "unauthorized": True,
            }

        success, user_data, error = get_user_info(session_token)
        if not success:
            err_msg = (error or "").lower()
            unauthorized = (
                "session expired" in err_msg
                or "not logged in" in err_msg
                or "unauthorized" in err_msg
            )
            return {
                "ok": False,
                "error": error or "Failed to verify session",
                "authenticated": False,
                "unauthorized": unauthorized,
            }

        refresh_result = yggdrasil.refresh_textures(
            user_data.get("uuid", ""),
            user_data.get("username", ""),
            timeout_seconds=5.0,
        )
        return {
            "ok": True,
            "authenticated": True,
            "uuid": user_data.get("uuid", ""),
            "username": user_data.get("username", ""),
            "texture_revision": int(
                (refresh_result or {}).get("texture_revision") or time.time() * 1000
            ),
            "refresh_result": refresh_result or {},
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "authenticated": False,
            "network_error": True,
        }


def _get_histolauncher_settings_proxy_config_script() -> str:
    return """<script>
const IS_DEV = false;
const LOCAL_PROXY_ORIGIN = window.location.origin;
const ACCOUNTS_BASE = `${LOCAL_PROXY_ORIGIN}/histolauncher-proxy/accounts`;
const TEXTURE_BASE = `${LOCAL_PROXY_ORIGIN}/histolauncher-proxy/textures`;

const CONFIG = {
  API: {
    BASE: `${ACCOUNTS_BASE}/api`,
    LOGIN: `${ACCOUNTS_BASE}/api/login`,
    SIGNUP: `${ACCOUNTS_BASE}/api/signup`,
    ADMIN_ME: `${ACCOUNTS_BASE}/api/admin/me`,
    ADMIN_PANEL_CONTENT: `${ACCOUNTS_BASE}/api/admin/panel-content`,
    ADMIN_PANEL_SCRIPT: `${ACCOUNTS_BASE}/api/admin/panel-script`,
    ADMIN_GLOBAL_MESSAGE: `${ACCOUNTS_BASE}/api/admin/global-message`,
    GLOBAL_MESSAGE: `${ACCOUNTS_BASE}/api/global-message`,
    UPLOAD_SKIN: `${ACCOUNTS_BASE}/api/settings/uploadSkin`,
    CAPE_OPTIONS: `${ACCOUNTS_BASE}/api/settings/capes`,
    TEXTURES_BASE: `${TEXTURE_BASE}`
  },
  GITHUB: {
    OWNER: 'KerbalOfficial',
    REPO: 'Histolauncher'
  },
  STORAGE_KEYS: {
    UUID: 'uuid',
    USERNAME: 'username'
  }
};

function getGitHubReleasesUrl(owner = CONFIG.GITHUB.OWNER, repo = CONFIG.GITHUB.REPO) {
  return `https://api.github.com/repos/${owner}/${repo}/releases`;
}
</script>"""


def _get_histolauncher_settings_cache_path() -> str:
    cache_dir = os.path.join(get_base_dir(), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "account_settings_iframe.html")


def _load_cached_histolauncher_settings_html() -> str | None:
    cache_path = _get_histolauncher_settings_cache_path()
    if not os.path.isfile(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _store_cached_histolauncher_settings_html(html: str) -> None:
    cache_path = _get_histolauncher_settings_cache_path()
    tmp_path = cache_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(str(html or ""))
        os.replace(tmp_path, cache_path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _get_histolauncher_iframe_navigation_guard_script() -> str:
    return """<script>
(function () {
  const logBlocked = (reason, target) => {
    try {
      console.warn('[Histolauncher iframe] Blocked navigation:', reason, target || '');
    } catch (_) {}
  };

  try {
    window.open = function (targetUrl) {
      logBlocked('window.open', targetUrl);
      return null;
    };
  } catch (_) {}

  try {
    if (window.history) {
      window.history.pushState = function () {
        logBlocked('history.pushState', '');
      };
      window.history.replaceState = function () {
        logBlocked('history.replaceState', '');
      };
    }
  } catch (_) {}

  document.addEventListener('click', function (event) {
    const link = event.target && event.target.closest ? event.target.closest('a[href]') : null;
    if (!link) return;

    const href = link.getAttribute('href') || '';
    if (!href || href.startsWith('#')) return;

    event.preventDefault();
    event.stopPropagation();
    logBlocked('link-click', href);
  }, true);

  document.addEventListener('submit', function (event) {
    event.preventDefault();
    event.stopPropagation();
    const action = event.target && event.target.getAttribute ? (event.target.getAttribute('action') || '') : '';
    logBlocked('form-submit', action);
  }, true);
})();
</script>"""


def _fetch_histolauncher_text(
    url: str,
    *,
    include_auth_cookie: bool = False,
    timeout_seconds: float = 15.0,
) -> str:
    from server.auth import load_histolauncher_cookie_header

    candidate_urls = []
    proxied = _apply_url_proxy(url)
    if proxied:
        candidate_urls.append(proxied)
    if url not in candidate_urls:
        candidate_urls.append(url)

    last_error = "Failed to load remote resource"
    for candidate in candidate_urls:
        try:
            headers = {"User-Agent": "Histolauncher/1.0"}
            if include_auth_cookie:
                cookie_header = load_histolauncher_cookie_header()
                if cookie_header:
                    headers["Cookie"] = cookie_header

            req = urllib.request.Request(candidate, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", errors="replace").strip()
            except Exception:
                detail = ""
            last_error = detail or f"Remote request failed ({e.code})"
        except Exception as e:
            last_error = str(e)

    raise RuntimeError(last_error)


def _extract_histolauncher_loader_scripts(html: str) -> list[tuple[str, str]]:
    loader_scripts: list[tuple[str, str]] = []
    seen_paths = set()

    for match in re.finditer(
        r"<script[^>]+src=[\"']([^\"']+)[\"'][^>]*></script>",
        str(html or ""),
        flags=re.IGNORECASE,
    ):
        script_src = str(match.group(1) or "").strip()
        if not script_src:
            continue

        parsed = urllib.parse.urlparse(script_src)
        script_path = parsed.path or ""
        if not script_path.lower().startswith("/loaders/") or not script_path.lower().endswith(".js"):
            continue
        if script_path.lower().endswith("/config.js"):
            continue
        if script_path in seen_paths:
            continue

        seen_paths.add(script_path)
        loader_scripts.append((script_src, script_path))

    return loader_scripts


def _patch_histolauncher_loader_script(script_path: str, script_body: str) -> str:
    patched = str(script_body or "")

    if script_path.endswith("/loaders/topbar.js"):
        patched = re.sub(
            r"const topbarDisabled = .*?;",
            "const topbarDisabled = true;",
            patched,
            count=1,
        )
        patched = re.sub(
            r"const globalMessageDisabled = .*?;",
            "const globalMessageDisabled = true;",
            patched,
            count=1,
        )

    if script_path.endswith("/loaders/router.js") and "iframeSettingsRoute" not in patched:
        router_alias_injection = (
            "  const iframeSettingsRoute = ROUTES.find(function (route) {\n"
            "    return route.key === 'settings';\n"
            "  });\n"
            "  if (iframeSettingsRoute) {\n"
            "    for (const alias of ['/account-settings-frame', '/account-settings-frame/']) {\n"
            "      routeLookup.set(normalizePathname(alias), iframeSettingsRoute);\n"
            "    }\n"
            "  }\n"
            "\n"
        )
        patched = re.sub(
            r"(^\s*function emitRouterEvent\(name, detail\) \{\r?\n)",
            router_alias_injection + r"\1",
            patched,
            count=1,
            flags=re.MULTILINE,
        )

    patched = re.sub(
        r"(?:window\.)?location\.href\s*=\s*(['\"]).*?\1\s*;",
        "console.warn('[Histolauncher iframe] Blocked redirect via location.href');",
        patched,
        flags=re.IGNORECASE,
    )
    patched = re.sub(
        r"(?:window\.)?location\.(?:assign|replace)\s*\([^)]*\)\s*;",
        "console.warn('[Histolauncher iframe] Blocked redirect via location method');",
        patched,
        flags=re.IGNORECASE,
    )

    if script_path.endswith("/loaders/settings.js"):
        patched = patched.replace(
            'document.body.innerHTML = "<main><p>Please <a href=\'/login\'>log in</a> first</p></main>";',
            'document.body.innerHTML = "<main><p>Please log in first.</p></main>";',
        )

    return patched.replace("</script>", "<\\/script>")


def _inline_histolauncher_loader_script(html: str, script_src: str, script_body: str) -> str:
    inline_script = f"<script>\n{script_body}\n</script>"
    pattern = rf"<script[^>]+src=[\"']{re.escape(script_src)}[\"'][^>]*></script>"
    return re.sub(pattern, lambda _: inline_script, html, count=1, flags=re.IGNORECASE)


def _transform_histolauncher_settings_html(raw_html: str, source_origin: str = "") -> str:
    html = str(raw_html or "")
    base_origin = str(source_origin or HISTOLAUNCHER_WEB_ORIGINS[0]).rstrip("/")
    config_script = _get_histolauncher_settings_proxy_config_script()
    navigation_guard_script = _get_histolauncher_iframe_navigation_guard_script()

    html = re.sub(
        r"https://(?:histolauncher\.org|histolauncher\.pages\.dev)/",
        f"{base_origin}/",
        html,
        flags=re.IGNORECASE,
    )

    config_pattern = r"<script[^>]+src=[\"']/loaders/config\.js(?:\?[^\"']*)?[\"'][^>]*>\s*</script>"
    html = re.sub(config_pattern, "", html, flags=re.IGNORECASE)
    html = html.replace("</head>", f"{config_script}\n</head>", 1)

    if "Blocked navigation" not in html:
        html = html.replace("</head>", f"{navigation_guard_script}\n</head>", 1)

    if "<base " not in html.lower():
        html = re.sub(
            r"<head([^>]*)>",
            f'<head\\1>\n<base href="{base_origin}/">',
            html,
            count=1,
            flags=re.IGNORECASE,
        )

    html = re.sub(
        r"<script[^>]*>[^<]*__CF\\$cv\\$params.*?</script>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html = re.sub(
        r"<script[^>]+src=[\"'][^\"']*cdn-cgi/challenge-platform[^\"']*[\"'][^>]*></script>",
        "",
        html,
        flags=re.IGNORECASE,
    )
    html = re.sub(
        r"<script[^>]+src=[\"'][^\"']*static\\.cloudflareinsights\\.com[^\"']*[\"'][^>]*></script>",
        "",
        html,
        flags=re.IGNORECASE,
    )

    for script_src, script_path in _extract_histolauncher_loader_scripts(html):
        remote_script = None
        last_error = None
        candidate_origins = [base_origin] + [
            origin for origin in HISTOLAUNCHER_WEB_ORIGINS
            if origin.rstrip("/") != base_origin
        ]
        for origin in candidate_origins:
            try:
                remote_script = _fetch_histolauncher_text(
                    f"{origin.rstrip('/')}{script_path}",
                    include_auth_cookie=False,
                    timeout_seconds=15.0,
                )
                break
            except Exception as e:
                last_error = e
        if remote_script is None:
            raise RuntimeError(
                f"Failed to load account settings script {script_path}: {last_error}"
            )
        html = _inline_histolauncher_loader_script(
            html,
            script_src,
            _patch_histolauncher_loader_script(script_path, remote_script),
        )

    return html


def api_account_settings_iframe():
    from server.auth import load_histolauncher_cookie_header

    cookie_header = load_histolauncher_cookie_header()
    if not cookie_header:
        return {"ok": False, "error": "Not authenticated"}

    last_error = "Failed to load account settings"
    for origin in HISTOLAUNCHER_WEB_ORIGINS:
        base_url = f"{origin.rstrip('/')}/settings?disable-topbar=1&disable-global-message=1"
        try:
            payload = _fetch_histolauncher_text(
                base_url,
                include_auth_cookie=True,
                timeout_seconds=15.0,
            )
            transformed_html = _transform_histolauncher_settings_html(
                payload, source_origin=origin
            )
            _store_cached_histolauncher_settings_html(transformed_html)
            return {"ok": True, "html": transformed_html}
        except Exception as e:
            last_error = str(e)

    cached_html = _load_cached_histolauncher_settings_html()
    if cached_html:
        return {"ok": True, "html": cached_html, "cached": True}

    return {"ok": False, "error": last_error}


def api_account_launcher_message():
    try:
        from server.auth import get_launcher_message

        success, payload, error = get_launcher_message()
        if not success:
            return {
                "ok": False,
                "active": False,
                "error": error or "Failed to load launcher message",
            }

        if not isinstance(payload, dict):
            return {"ok": False, "active": False, "error": "Invalid launcher message response"}

        active = bool(payload.get("active"))
        message = str(payload.get("message") or "")
        msg_type = str(payload.get("type") or "message").strip().lower()
        if msg_type not in {"message", "warning", "important"}:
            msg_type = "message"

        return {
            "ok": True,
            "active": active,
            "message": message,
            "type": msg_type,
            "updatedAt": payload.get("updatedAt"),
            "updatedBy": payload.get("updatedBy"),
        }
    except Exception as e:
        return {"ok": False, "active": False, "error": str(e)}


def api_account_status():
    try:
        s = load_global_settings() or {}
        account_type = s.get("account_type", "Local")
        return {"ok": True, "connected": account_type == "Histolauncher"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_account_disconnect():
    try:
        s = load_global_settings() or {}
        s["account_type"] = "Local"
        save_global_settings(s)
        clear_account_token()
        return {"ok": True, "message": "Account disconnected."}
    except Exception as e:
        return {"ok": False, "error": str(e)}
