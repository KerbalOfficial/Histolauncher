from __future__ import annotations

import base64
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from core.logger import safe_print
from core.notifications import send_desktop_notification
from core.settings import (
    _apply_url_proxy,
    clear_account_token,
    get_base_dir,
    load_global_settings,
    save_global_settings,
)

from server.api._constants import (
    HISTOLAUNCHER_ACCOUNTS_PROXY_PREFIX,
    HISTOLAUNCHER_TEXTURES_PROXY_PREFIX,
    HISTOLAUNCHER_WEB_ORIGINS,
    HISTOLAUNCHER_WEB_PROXY_PREFIX,
)


__all__ = [
    "_verify_and_store_session_token",
    "api_account_login",
    "api_account_microsoft_device_code",
    "api_account_microsoft_cape_disable",
    "api_account_microsoft_cape_select",
    "api_account_microsoft_poll",
    "api_account_microsoft_skin_delete",
    "api_account_microsoft_skin_favorite",
    "api_account_microsoft_skin_save",
    "api_account_microsoft_skin_select",
    "api_account_microsoft_skin_upload",
    "api_account_microsoft_textures",
    "api_account_verify_session",
    "api_account_current",
    "api_account_refresh_assets",
    "api_account_settings_iframe",
    "api_account_launcher_message",
    "api_account_status",
    "api_account_disconnect",
]


MAX_SKIN_UPLOAD_BASE64_LENGTH = 4 * 1024 * 1024


def _account_error_is_unauthorized(error: str | None) -> bool:
    err_msg = str(error or "").lower()
    return (
        "not logged in" in err_msg
        or "session expired" in err_msg
        or "sign in again" in err_msg
        or "unauthorized" in err_msg
        or "invalid_grant" in err_msg
    )


def _dashed_uuid(uuid_value: str) -> str:
    clean = re.sub(r"[^a-fA-F0-9]", "", str(uuid_value or ""))
    if len(clean) != 32:
        return str(uuid_value or "").strip()
    return f"{clean[0:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:32]}"


def _safe_texture_cache_identifier(value: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 160:
        return ""
    if not re.match(r"^[A-Za-z0-9_. -]+$", text):
        return ""
    return text


def _invalidate_account_texture_cache(uuid_value: str = "", username: str = "") -> None:
    uuid_raw = str(uuid_value or "").strip()
    username_raw = str(username or "").strip()
    identifiers: list[str] = []

    for value in (uuid_raw, _dashed_uuid(uuid_raw), uuid_raw.replace("-", ""), username_raw):
        clean = _safe_texture_cache_identifier(value)
        if clean and clean not in identifiers:
            identifiers.append(clean)

    try:
        from server import yggdrasil

        yggdrasil.invalidate_texture_cache(uuid_raw, username_raw)
    except Exception:
        pass

    if identifiers:
        try:
            from server.auth.microsoft import remove_microsoft_texture_cache

            for identifier in identifiers:
                for suffix in ("skin", "cape"):
                    remove_microsoft_texture_cache(identifier, suffix)
        except Exception:
            pass

    try:
        from server import yggdrasil

        yggdrasil.prewarm_authlib_texture_properties(
            target_uuid_hex=uuid_raw,
            target_username=username_raw,
            wait_seconds=0.0,
        )
    except Exception:
        pass


def _rebuild_active_authlib_texture_cache(
    previous_uuid: str = "",
    previous_username: str = "",
    *,
    target_uuid: str = "",
    target_username: str = "",
) -> None:
    try:
        from server import yggdrasil

        if previous_uuid or previous_username:
            yggdrasil.invalidate_texture_cache(previous_uuid, previous_username)
        yggdrasil.prewarm_authlib_texture_properties(
            target_uuid_hex=target_uuid,
            target_username=target_username,
            wait_seconds=0.0,
        )
    except Exception:
        pass


def _send_microsoft_login_notification(
    *,
    username: str = "",
    error: str | None = None,
) -> None:
    try:
        if error:
            detail = str(error).strip() or "Microsoft login failed."
            send_desktop_notification(
                title="Microsoft Login Failed",
                message=detail,
                icon_kind="failed",
            )
            return

        display_name = str(username or "Microsoft account").strip() or "Microsoft account"
        send_desktop_notification(
            title="Microsoft Login Successful",
            message=f"Signed in to Microsoft account as {display_name}.",
            icon_kind="success",
        )
    except Exception as exc:
        safe_print(f"[api] Could not send Microsoft login notification: {exc}")


def _microsoft_texture_response(texture_profile: dict, *, refresh_result: dict | None = None):
    uuid_value = str(texture_profile.get("uuid") or "")
    username = str(texture_profile.get("username") or "")
    texture_revision = int(time.time() * 1000)
    return {
        "ok": True,
        "authenticated": True,
        "account_type": "Microsoft",
        "uuid": uuid_value,
        "username": username,
        "texture_revision": texture_revision,
        "textures": texture_profile,
        "skins": texture_profile.get("skins") if isinstance(texture_profile.get("skins"), list) else [],
        "capes": texture_profile.get("capes") if isinstance(texture_profile.get("capes"), list) else [],
        "active_skin": texture_profile.get("active_skin"),
        "active_cape": texture_profile.get("active_cape"),
        "refresh_result": refresh_result or {"provider": "Microsoft"},
    }


def _decode_skin_upload(data: dict) -> bytes:
    raw = str(data.get("file_base64") or data.get("skin_base64") or "").strip()
    if not raw:
        raise ValueError("Choose a skin PNG before saving.")
    if "," in raw and raw.lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    if len(raw) > MAX_SKIN_UPLOAD_BASE64_LENGTH:
        raise ValueError("Skin file is too large. Choose a PNG under 2 MB.")
    try:
        return base64.b64decode(raw, validate=True)
    except Exception as e:
        raise ValueError("Could not read the uploaded skin PNG.") from e


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

    username = user_data.get("username", "")
    account_uuid = user_data.get("uuid", "")

    try:
        s = load_global_settings() or {}
        previous_username = str(s.get("username") or "").strip()
        previous_uuid = str(s.get("uuid") or "").strip()
        s["account_type"] = "Histolauncher"
        s["username"] = username
        s["uuid"] = account_uuid
        save_global_settings(s)
    except Exception as e:
        return {"ok": False, "error": f"Failed to save settings: {str(e)}"}

    _rebuild_active_authlib_texture_cache(
        previous_uuid,
        previous_username,
        target_uuid=account_uuid,
        target_username=username,
    )

    safe_print(
        f"[api_account_verify_session] Account verified: "
        f"username={username}, uuid={account_uuid}"
    )

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


def api_account_microsoft_device_code(data=None):
    try:
        from server.auth.microsoft import start_device_code

        result = start_device_code()
        if not result.get("ok"):
            _send_microsoft_login_notification(error=result.get("error"))
        return result
    except Exception as e:
        _send_microsoft_login_notification(error=str(e))
        return {"ok": False, "error": str(e)}


def api_account_microsoft_poll(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid request"}

        from server.auth.microsoft import poll_device_code

        interval = data.get("interval")
        try:
            interval_int = int(interval) if interval is not None else None
        except Exception:
            interval_int = None
        result = poll_device_code(data.get("device_code", ""), interval=interval_int)
        if result.get("ok") and result.get("authenticated"):
            _rebuild_active_authlib_texture_cache(
                target_uuid=str(result.get("uuid") or ""),
                target_username=str(result.get("username") or ""),
            )
            _send_microsoft_login_notification(username=result.get("username"))
        elif not result.get("pending"):
            _send_microsoft_login_notification(error=result.get("error"))
        return result
    except Exception as e:
        _send_microsoft_login_notification(error=str(e))
        return {"ok": False, "error": str(e)}


def api_account_microsoft_textures(data=None):
    try:
        from server.auth.microsoft import get_microsoft_texture_profile

        texture_profile, used_cached_profile = get_microsoft_texture_profile(
            force_profile=True,
            return_cache_state=True,
        )
        if not used_cached_profile:
            _invalidate_account_texture_cache(
                texture_profile.get("uuid", ""),
                texture_profile.get("username", ""),
            )
        return _microsoft_texture_response(texture_profile)
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "authenticated": False,
            "unauthorized": _account_error_is_unauthorized(str(e)),
        }


def api_account_microsoft_skin_upload(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid request"}

        from server.auth.microsoft import upload_microsoft_skin

        skin_bytes = _decode_skin_upload(data)
        texture_profile = upload_microsoft_skin(
            skin_bytes,
            variant=str(data.get("variant") or data.get("model") or "classic"),
            file_name=str(data.get("file_name") or "skin.png"),
            display_name=str(data.get("name") or ""),
            library_id=str(data.get("skin_id") or data.get("library_id") or ""),
            cape_id=data.get("cape_id") if "cape_id" in data else data.get("capeId") if "capeId" in data else None,
            texture_type=data.get("texture_type"),
            legacy_overlay_parts=data.get("legacy_overlay_parts"),
            legacy_arm_mirror=data.get("legacy_arm_mirror"),
            legacy_leg_mirror=data.get("legacy_leg_mirror"),
        )
        _invalidate_account_texture_cache(
            texture_profile.get("uuid", ""),
            texture_profile.get("username", ""),
        )
        return _microsoft_texture_response(texture_profile, refresh_result={"provider": "Microsoft", "action": "skin_upload"})
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "authenticated": False,
            "unauthorized": _account_error_is_unauthorized(str(e)),
        }


def api_account_microsoft_skin_save(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid request"}

        from server.auth.microsoft import save_microsoft_local_skin

        has_skin_data = bool(str(data.get("file_base64") or data.get("skin_base64") or "").strip())
        skin_bytes = _decode_skin_upload(data) if has_skin_data else None
        texture_profile = save_microsoft_local_skin(
            skin_bytes,
            variant=str(data.get("variant") or data.get("model") or "classic"),
            file_name=str(data.get("file_name") or "skin.png"),
            display_name=str(data.get("name") or ""),
            library_id=str(data.get("skin_id") or data.get("library_id") or ""),
            cape_id=data.get("cape_id") if "cape_id" in data else data.get("capeId") if "capeId" in data else None,
            texture_type=data.get("texture_type"),
            legacy_overlay_parts=data.get("legacy_overlay_parts"),
            legacy_arm_mirror=data.get("legacy_arm_mirror"),
            legacy_leg_mirror=data.get("legacy_leg_mirror"),
        )
        _invalidate_account_texture_cache(
            texture_profile.get("uuid", ""),
            texture_profile.get("username", ""),
        )
        return _microsoft_texture_response(texture_profile, refresh_result={"provider": "Microsoft", "action": "skin_save"})
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "authenticated": False,
            "unauthorized": _account_error_is_unauthorized(str(e)),
        }


def api_account_microsoft_skin_delete(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid request"}

        from server.auth.microsoft import delete_microsoft_local_skin

        texture_profile = delete_microsoft_local_skin(data.get("skin_id") or data.get("id") or "")
        _invalidate_account_texture_cache(
            texture_profile.get("uuid", ""),
            texture_profile.get("username", ""),
        )
        return _microsoft_texture_response(texture_profile, refresh_result={"provider": "Microsoft", "action": "skin_delete"})
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "authenticated": False,
            "unauthorized": _account_error_is_unauthorized(str(e)),
        }


def api_account_microsoft_skin_favorite(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid request"}

        from server.auth.microsoft import set_microsoft_skin_favorite

        texture_profile = set_microsoft_skin_favorite(
            data.get("skin_id") or data.get("id") or "",
            data.get("favorite"),
        )
        return _microsoft_texture_response(texture_profile, refresh_result={"provider": "Microsoft", "action": "skin_favorite"})
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "authenticated": False,
            "unauthorized": _account_error_is_unauthorized(str(e)),
        }


def api_account_microsoft_skin_select(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid request"}

        from server.auth.microsoft import activate_microsoft_skin

        texture_profile = activate_microsoft_skin(
            data.get("skin_id") or data.get("id") or "",
            display_name=str(data.get("name") or ""),
            variant=str(data.get("variant") or data.get("model") or ""),
            cape_id=data.get("cape_id") if "cape_id" in data else data.get("capeId") if "capeId" in data else None,
        )
        _invalidate_account_texture_cache(
            texture_profile.get("uuid", ""),
            texture_profile.get("username", ""),
        )
        return _microsoft_texture_response(texture_profile, refresh_result={"provider": "Microsoft", "action": "skin_select"})
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "authenticated": False,
            "unauthorized": _account_error_is_unauthorized(str(e)),
        }


def api_account_microsoft_cape_select(data):
    try:
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid request"}

        cape_id = str(data.get("cape_id") or data.get("id") or "").strip()
        if cape_id.lower() in {"", "none", "null"}:
            return api_account_microsoft_cape_disable(data)

        from server.auth.microsoft import activate_microsoft_cape

        texture_profile = activate_microsoft_cape(cape_id)
        _invalidate_account_texture_cache(
            texture_profile.get("uuid", ""),
            texture_profile.get("username", ""),
        )
        return _microsoft_texture_response(texture_profile, refresh_result={"provider": "Microsoft", "action": "cape_select"})
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "authenticated": False,
            "unauthorized": _account_error_is_unauthorized(str(e)),
        }


def api_account_microsoft_cape_disable(data=None):
    try:
        from server.auth.microsoft import disable_microsoft_cape

        texture_profile = disable_microsoft_cape()
        _invalidate_account_texture_cache(
            texture_profile.get("uuid", ""),
            texture_profile.get("username", ""),
        )
        return _microsoft_texture_response(texture_profile, refresh_result={"provider": "Microsoft", "action": "cape_disable"})
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "authenticated": False,
            "unauthorized": _account_error_is_unauthorized(str(e)),
        }


def api_account_current():
    try:
        settings = load_global_settings() or {}
        account_type = str(settings.get("account_type") or "Local").strip()
        account_type_norm = account_type.lower()
        if account_type_norm not in {"histolauncher", "microsoft"}:
            return {
                "ok": False,
                "error": "Online account not enabled",
                "authenticated": False,
                "unauthorized": False,
                "local_account": True,
            }

        if account_type_norm == "microsoft":
            from server.auth.microsoft import (
                get_microsoft_texture_profile,
                get_verified_microsoft_account,
                refresh_microsoft_account,
            )

            texture_revision = 0
            texture_profile = None
            try:
                user_data = refresh_microsoft_account(force_profile=True)
                success = True
                error = None
                try:
                    texture_profile = get_microsoft_texture_profile(force_profile=False)
                except Exception:
                    texture_profile = None
                texture_revision = int(time.time() * 1000)
                _invalidate_account_texture_cache(
                    user_data.get("uuid", ""),
                    user_data.get("username", ""),
                )
            except Exception as refresh_error:
                success, user_data, error = get_verified_microsoft_account()
                if not error:
                    error = str(refresh_error)
                if success:
                    try:
                        texture_profile = get_microsoft_texture_profile(force_profile=False)
                    except Exception:
                        texture_profile = None
        else:
            from server.auth import get_verified_account

            success, user_data, error = get_verified_account()
            texture_revision = 0

        if not success:
            unauthorized = _account_error_is_unauthorized(error)
            return {
                "ok": False,
                "error": error or "Not authenticated",
                "authenticated": False,
                "unauthorized": unauthorized,
            }

        response = {
            "ok": True,
            "authenticated": True,
            "account_type": "Microsoft" if account_type_norm == "microsoft" else "Histolauncher",
            "uuid": user_data.get("uuid", ""),
            "username": user_data.get("username", ""),
        }
        if texture_revision:
            response["texture_revision"] = texture_revision
        if account_type_norm == "microsoft" and isinstance(texture_profile, dict):
            response["active_skin"] = texture_profile.get("active_skin")
            response["active_cape"] = texture_profile.get("active_cape")
        elif account_type_norm == "histolauncher":
            try:
                from server.yggdrasil.identity import _normalize_uuid_hex
                from server.yggdrasil.textures.resolver import _resolve_cached_skin_model

                hl_uuid = _normalize_uuid_hex(user_data.get("uuid") or "") or ""
                hl_username = str(user_data.get("username") or "").strip()
                if hl_uuid:
                    skin_model = (
                        _resolve_cached_skin_model(hl_uuid, hl_username, allow_stale=True)
                        or "classic"
                    )
                    response["active_skin"] = {"variant": skin_model}
            except Exception:
                pass
        return response
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
        account_type = str(settings.get("account_type") or "Local").strip().lower()
        if account_type not in {"histolauncher", "microsoft"}:
            return {
                "ok": False,
                "error": "Online account not enabled",
                "authenticated": False,
                "unauthorized": False,
            }

        if account_type == "microsoft":
            from server.auth.microsoft import refresh_microsoft_account

            try:
                user_data = refresh_microsoft_account(force_profile=True)
                _invalidate_account_texture_cache(
                    user_data.get("uuid", ""),
                    user_data.get("username", ""),
                )
                return {
                    "ok": True,
                    "authenticated": True,
                    "account_type": "Microsoft",
                    "uuid": user_data.get("uuid", ""),
                    "username": user_data.get("username", ""),
                    "texture_revision": int(time.time() * 1000),
                    "refresh_result": {"provider": "Microsoft"},
                }
            except Exception as e:
                return {
                    "ok": False,
                    "error": str(e),
                    "authenticated": False,
                    "unauthorized": _account_error_is_unauthorized(str(e)),
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


def _build_histolauncher_proxy_config_script(config_js: str) -> str:
    patched = str(config_js or "")
    patched = re.sub(
        r"const IS_DEV\s*=[\s\S]*?;\s*\n\s*const ACCOUNTS_BASE\s*=[\s\S]*?;\s*\n\s*const TEXTURE_BASE\s*=[\s\S]*?;",
        (
            "const IS_DEV = false;\n"
            "const LOCAL_PROXY_ORIGIN = window.location.origin;\n"
            f"const ACCOUNTS_BASE = `${{LOCAL_PROXY_ORIGIN}}{HISTOLAUNCHER_ACCOUNTS_PROXY_PREFIX}`;\n"
            f"const TEXTURE_BASE = `${{LOCAL_PROXY_ORIGIN}}{HISTOLAUNCHER_TEXTURES_PROXY_PREFIX}`;"
        ),
        patched,
        count=1,
    )
    return patched.replace("</script>", "<\\/script>")


ACCOUNT_SETTINGS_IFRAME_CACHE_NAME = "account_settings_iframe_v2.html"


def _get_histolauncher_settings_cache_path() -> str:
    cache_dir = os.path.join(get_base_dir(), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, ACCOUNT_SETTINGS_IFRAME_CACHE_NAME)


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

    if script_path.endswith("/loaders/router.js"):
        if "iframeSettingsRoute" not in patched:
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

        if "resolveWebAssetUrl" not in patched:
            web_asset_helper = (
                f"  const WEB_PROXY_BASE = '{HISTOLAUNCHER_WEB_PROXY_PREFIX}';\n"
                "  function resolveWebAssetUrl(path) {\n"
                "    const raw = String(path || '').trim();\n"
                "    if (!raw || /^[a-z][a-z0-9+.-]*:/i.test(raw)) return raw;\n"
                "    if (raw.startsWith(WEB_PROXY_BASE)) return raw;\n"
                "    if (raw.startsWith('/')) return WEB_PROXY_BASE + raw;\n"
                "    return WEB_PROXY_BASE + '/' + raw;\n"
                "  }\n"
                "\n"
            )
            patched = re.sub(
                r"(^\s*async function getComponentHtml\(componentPath\) \{\r?\n)",
                web_asset_helper + r"\1",
                patched,
                count=1,
                flags=re.MULTILINE,
            )
            patched = patched.replace(
                "fetch(componentPath, { cache: 'default' })",
                "fetch(resolveWebAssetUrl(componentPath), { cache: 'default' })",
            )
            patched = patched.replace(
                "script.src = loaderPath;",
                "script.src = resolveWebAssetUrl(loaderPath);",
            )

    if script_path.endswith("/loaders/auth.js"):
        patched = patched.replace(
            "navigateWithinSite('/login', { replaceState: true });",
            "console.warn('[Histolauncher iframe] Login required');",
        )
        patched = patched.replace(
            "navigateWithinSite('/login', { replaceState: true })",
            "console.warn('[Histolauncher iframe] Login required')",
        )
        patched = patched.replace(
            "navigateWithinSite('/', { replaceState: true });",
            "console.warn('[Histolauncher iframe] Admin access denied');",
        )

    if script_path.endswith("/loaders/settings.js"):
        patched = patched.replace(
            "navigateWithinSite('/login', { replaceState: true });",
            "console.warn('[Histolauncher iframe] Login required');",
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

    return patched.replace("</script>", "<\\/script>")


def _inline_histolauncher_loader_script(html: str, script_src: str, script_body: str) -> str:
    inline_script = f"<script>\n{script_body}\n</script>"
    pattern = rf"<script[^>]+src=[\"']{re.escape(script_src)}[\"'][^>]*></script>"
    return re.sub(pattern, lambda _: inline_script, html, count=1, flags=re.IGNORECASE)


def _rewrite_histolauncher_web_urls_to_proxy(text: str) -> str:
    rewritten = str(text or "")
    for origin in HISTOLAUNCHER_WEB_ORIGINS:
        rewritten = rewritten.replace(
            f"{origin.rstrip('/')}/",
            f"{HISTOLAUNCHER_WEB_PROXY_PREFIX}/",
        )
    return rewritten


def _rewrite_histolauncher_root_asset_urls_to_proxy(text: str) -> str:
    rewritten = str(text or "")
    for attribute in ("href", "src"):
        rewritten = re.sub(
            rf'({attribute}=["\'])/(?!{re.escape(HISTOLAUNCHER_WEB_PROXY_PREFIX.lstrip("/"))})',
            rf"\1{HISTOLAUNCHER_WEB_PROXY_PREFIX}/",
            rewritten,
            flags=re.IGNORECASE,
        )
    return rewritten


def patch_histolauncher_web_loader_script(script_path: str, script_body: str) -> str:
    return _patch_histolauncher_loader_script(script_path, script_body)


def _transform_histolauncher_settings_html(raw_html: str, source_origin: str = "") -> str:
    html = str(raw_html or "")
    base_origin = str(source_origin or HISTOLAUNCHER_WEB_ORIGINS[0]).rstrip("/")
    navigation_guard_script = _get_histolauncher_iframe_navigation_guard_script()

    remote_config_js = _fetch_histolauncher_text(
        f"{base_origin}/loaders/config.js",
        include_auth_cookie=False,
        timeout_seconds=15.0,
    )
    config_script = (
        f"<script>\n{_build_histolauncher_proxy_config_script(remote_config_js)}\n</script>"
    )

    html = _rewrite_histolauncher_web_urls_to_proxy(html)
    html = _rewrite_histolauncher_root_asset_urls_to_proxy(html)

    config_pattern = r"<script[^>]+src=[\"']/loaders/config\.js(?:\?[^\"']*)?[\"'][^>]*>\s*</script>"
    html = re.sub(config_pattern, "", html, flags=re.IGNORECASE)
    html = html.replace("</head>", f"{config_script}\n</head>", 1)

    if "Blocked navigation" not in html:
        html = html.replace("</head>", f"{navigation_guard_script}\n</head>", 1)

    html = re.sub(
        r"<base[^>]*>\s*",
        "",
        html,
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
        website_origin = HISTOLAUNCHER_WEB_ORIGINS[0].rstrip("/")
        return {
            "ok": True,
            "connected": str(account_type).strip().lower() in {"histolauncher", "microsoft"},
            "account_type": account_type,
            "website_origin": website_origin,
            "signup_url": f"{website_origin}/signup",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_account_disconnect():
    try:
        s = load_global_settings() or {}
        previous_username = str(s.get("username") or "").strip()
        previous_uuid = str(s.get("uuid") or "").strip()
        s["account_type"] = "Local"
        s["uuid"] = ""
        save_global_settings(s)
        clear_account_token()
        _rebuild_active_authlib_texture_cache(previous_uuid, previous_username)
        return {"ok": True, "message": "Account disconnected."}
    except Exception as e:
        return {"ok": False, "error": str(e)}
