from __future__ import annotations

from typing import Any

from core.settings import load_global_settings


__all__ = [
    "get_launch_auth_info",
    "is_microsoft_account_active",
]


def _uuid_hex_to_dashed(uuid_hex: str) -> str:
    raw = str(uuid_hex or "").strip().replace("-", "")
    if len(raw) != 32:
        return raw
    return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


def is_microsoft_account_active(settings: dict[str, Any] | None = None) -> bool:
    try:
        cfg = settings if isinstance(settings, dict) else load_global_settings()
        return str((cfg or {}).get("account_type") or "Local").strip().lower() == "microsoft"
    except Exception:
        return False


def get_launch_auth_info(*, require_valid: bool = False) -> dict[str, str]:
    if is_microsoft_account_active():
        try:
            from server.auth.microsoft import get_microsoft_launch_account

            success, account, error = get_microsoft_launch_account()
            if success and account:
                real_access_token = str(account.get("access_token") or "").strip()
                if not real_access_token:
                    raise RuntimeError("Microsoft account launch token is missing.")
                uuid_hex = str(account.get("uuid") or "").strip().replace("-", "")
                username = str(account.get("username") or "Player").strip() or "Player"
                return {
                    "username": username,
                    "uuid_hex": uuid_hex,
                    "uuid": _uuid_hex_to_dashed(uuid_hex),
                    "access_token": real_access_token,
                    "user_type": "msa",
                    "user_properties": "{}",
                    "xuid": str(account.get("xuid") or ""),
                    "client_id": str(account.get("client_id") or ""),
                }
            if require_valid:
                raise RuntimeError(error or "Microsoft account is not authenticated.")
        except Exception as e:
            if require_valid:
                raise RuntimeError(str(e)) from e

    from server.yggdrasil import _get_username_and_uuid

    username, auth_uuid_raw = _get_username_and_uuid()
    uuid_hex = str(auth_uuid_raw or "").replace("-", "")
    return {
        "username": str(username or "Player"),
        "uuid_hex": uuid_hex,
        "uuid": _uuid_hex_to_dashed(uuid_hex),
        "access_token": "0",
        "user_type": "legacy",
        "user_properties": "{}",
        "xuid": "",
        "client_id": "",
    }