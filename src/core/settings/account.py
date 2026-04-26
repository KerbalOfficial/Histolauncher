from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from core.settings.profiles import (
    get_account_cache_path,
    get_token_path,
)
from core.settings.store import load_global_settings, save_global_settings

logger = logging.getLogger(__name__)

__all__ = [
    "clear_account_token",
    "clear_cached_account_identity",
    "get_account_type",
    "load_account_token",
    "load_cached_account_identity",
    "save_account_token",
    "save_cached_account_identity",
    "set_account_type",
]


_TOKEN_HEADER = (
    b"# WARNING: DO NOT SHARE THIS TOKEN!\n"
    b"# ANYONE THAT HAS HOLD OF IT CAN TAKE YOUR HISTOLAUNCHER ACCOUNT!\n\n"
    b"# Keep this file secure and never share it with anyone!!!\n"
)


def save_account_token(token: Any, profile_id: str | None = None) -> None:
    try:
        path = get_token_path(profile_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"

        token_bytes = token.encode("utf-8") if isinstance(token, str) else bytes(token)

        with open(tmp, "wb") as f:
            f.write(_TOKEN_HEADER)
            f.write(token_bytes)

        try:
            os.replace(tmp, path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

        try:
            os.chmod(path, 0o600)
        except OSError:
            logger.debug(f"Could not set file permissions for token file: {path}")
    except OSError as e:
        logger.error(f"Failed to save account token: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error saving account token: {e}")
        raise


def load_account_token(profile_id: str | None = None) -> str | None:
    path = get_token_path(profile_id)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "rb") as f:
            data = f.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning("Account token file appears to be corrupted")
            return None

        for line in text.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped
        return None
    except OSError as e:
        logger.error(f"Failed to read account token: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error loading account token: {e}")
        return None


def save_cached_account_identity(
    account: dict[str, Any], profile_id: str | None = None
) -> None:
    if not isinstance(account, dict):
        return

    username = str(account.get("username") or "").strip()
    uuid_value = str(account.get("uuid") or "").strip()
    if not username or not uuid_value:
        return

    path = get_account_cache_path(profile_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    payload = {"username": username, "uuid": uuid_value, "updated_at": int(time.time())}
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def load_cached_account_identity(profile_id: str | None = None) -> dict[str, str] | None:
    path = get_account_cache_path(profile_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    username = str(payload.get("username") or "").strip()
    uuid_value = str(payload.get("uuid") or "").strip()
    if not username or not uuid_value:
        return None
    return {"username": username, "uuid": uuid_value}


def clear_cached_account_identity(profile_id: str | None = None) -> None:
    path = get_account_cache_path(profile_id)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def clear_account_token(profile_id: str | None = None) -> None:
    path = get_token_path(profile_id)
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.debug(f"Account token cleared: {path}")
        clear_cached_account_identity(profile_id)
    except OSError as e:
        logger.error(f"Failed to clear account token: {e}")
    except Exception as e:
        logger.error(f"Unexpected error clearing account token: {e}")


def get_account_type(profile_id: str | None = None) -> str:
    cfg = load_global_settings(profile_id) or {}
    return (str(cfg.get("account_type") or "Local")).strip()


def set_account_type(value: str, profile_id: str | None = None) -> None:
    if not isinstance(value, str):
        raise TypeError("account type must be a string")
    save_global_settings({"account_type": value.strip() or "Local"}, profile_id=profile_id)
