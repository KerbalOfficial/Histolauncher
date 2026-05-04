from __future__ import annotations

import hashlib
import uuid
from typing import Tuple

from core.logger import colorize_log
from core.settings import load_global_settings


__all__ = [
    "_active_account_scope",
    "_histolauncher_account_enabled",
    "_ensure_uuid",
    "_get_username_and_uuid",
    "_normalize_uuid_hex",
    "_uuid_hex_to_dashed",
]


def _active_account_scope() -> str:
    try:
        settings = load_global_settings() or {}
        account_type = str(settings.get("account_type") or "Local").strip().lower()
    except Exception:
        account_type = "local"
    if account_type in {"microsoft", "histolauncher"}:
        return account_type
    return "local"


def _histolauncher_account_enabled() -> bool:
    try:
        settings = load_global_settings() or {}
        return str(settings.get("account_type") or "Local").strip().lower() == "histolauncher"
    except Exception:
        return False


def _ensure_uuid(username: str) -> str:
    digest = hashlib.md5(("OfflinePlayer:" + (username or "")).encode("utf-8")).digest()
    as_list = bytearray(digest)
    as_list[6] = (as_list[6] & 0x0F) | 0x30
    as_list[8] = (as_list[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(as_list)))


def _get_username_and_uuid() -> Tuple[str, str]:
    settings = load_global_settings()
    account_type = str(settings.get("account_type", "Local") or "Local").strip()
    account_type_norm = account_type.lower()

    if account_type_norm == "microsoft":
        try:
            from server.auth.microsoft import get_verified_microsoft_account

            success, account_data, _error = get_verified_microsoft_account()
            if success and account_data:
                username = account_data.get("username", "Player")
                u = str(account_data.get("uuid", "")).replace("-", "")
                if u:
                    try:
                        uuid.UUID(u)
                        return username, u
                    except Exception:
                        pass
        except Exception as e:
            print(colorize_log(f"[yggdrasil] Failed to verify Microsoft session: {e}"))

    if account_type_norm == "histolauncher":
        try:
            from server.auth import get_verified_account

            success, account_data, _error = get_verified_account()
            if success and account_data:
                username = account_data.get("username", "Player")
                u = account_data.get("uuid", "").replace("-", "")
                if u:
                    try:
                        uuid.UUID(account_data.get("uuid", ""))
                        return username, u
                    except Exception:
                        pass
        except Exception as e:
            print(colorize_log(f"[yggdrasil] Failed to verify Histolauncher session: {e}"))

    username = (settings.get("username") or "Player").strip() or "Player"
    u = _ensure_uuid(username)
    return username, u.replace("-", "")


def _normalize_uuid_hex(value: str | None) -> str:
    raw = str(value or "").strip().replace("-", "")
    if len(raw) != 32:
        return ""
    try:
        uuid.UUID(raw)
    except Exception:
        return ""
    return raw.lower()


def _uuid_hex_to_dashed(u_hex: str) -> str:
    return (
        f"{u_hex[0:8]}-{u_hex[8:12]}-{u_hex[12:16]}-"
        f"{u_hex[16:20]}-{u_hex[20:]}"
    )
