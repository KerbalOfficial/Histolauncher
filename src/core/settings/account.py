from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from core.settings.profiles import (
    get_account_cache_path,
    get_active_profile_id,
    get_token_path,
    list_profiles,
    safe_profile_id,
)
from core.settings.store import load_global_settings, save_global_settings

logger = logging.getLogger(__name__)

__all__ = [
    "clear_account_token",
    "clear_cached_account_identity",
    "get_account_type",
    "load_account_token",
    "load_cached_account_identity",
    "migrate_all_tokens_to_keyring",
    "save_account_token",
    "save_cached_account_identity",
    "set_account_type",
]


_TOKEN_HEADER = (
    b"# WARNING: DO NOT SHARE THIS TOKEN!\n"
    b"# ANYONE THAT HAS HOLD OF IT CAN ACCESS YOUR LAUNCHER ACCOUNT SESSION!\n\n"
    b"# Keep this file secure and never share it with anyone!!!\n"
)

# ---------------------------------------------------------------------------
# keyring integration
# ---------------------------------------------------------------------------

_KEYRING_SERVICE = "histolauncher"
_KEYRING_CHUNK_BYTES = 1200
_KEYRING_SPLIT_PREFIX = "__split__:"
_KEYRING_CHUNK_SUFFIX = "|chunk:"
_KEYRING_IMPORT_ERROR: Exception | None = None

try:
    import keyring as _keyring  # type: ignore[import-untyped]
    import keyring.errors as _keyring_errors  # type: ignore[import-untyped]
    _KEYRING_IMPORT_ERROR = None
except Exception as _kr_import_exc:
    _keyring = None  # type: ignore[assignment]
    _keyring_errors = None  # type: ignore[assignment]
    _KEYRING_IMPORT_ERROR = _kr_import_exc


def _keyring_available() -> bool:
    if _KEYRING_IMPORT_ERROR is not None or _keyring is None:
        return False
    try:
        backend = _keyring.get_keyring()
        mod = type(backend).__module__ or ""
        return "fail" not in mod
    except Exception:
        return False


def _keyring_save_credential(username: str, token_str: str) -> None:
    _keyring_delete_credential(username)

    encoded = token_str.encode("utf-8")
    if len(encoded) <= _KEYRING_CHUNK_BYTES:
        _keyring.set_password(_KEYRING_SERVICE, username, token_str)
        return

    chunks: list[str] = []
    pos = 0
    while pos < len(encoded):
        end = min(pos + _KEYRING_CHUNK_BYTES, len(encoded))
        while end > pos and end < len(encoded) and (encoded[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(encoded[pos:end].decode("utf-8"))
        pos = end

    try:
        _keyring.set_password(
            _KEYRING_SERVICE,
            username,
            f"{_KEYRING_SPLIT_PREFIX}{len(chunks)}",
        )
        for i, chunk in enumerate(chunks):
            _keyring.set_password(
                _KEYRING_SERVICE,
                f"{username}{_KEYRING_CHUNK_SUFFIX}{i}",
                chunk,
            )
    except Exception:
        _keyring_delete_credential(username)
        raise


def _keyring_load_credential(username: str) -> str | None:
    value = _keyring.get_password(_KEYRING_SERVICE, username)
    if value is None:
        return None
    if not value.startswith(_KEYRING_SPLIT_PREFIX):
        return value

    try:
        count = int(value[len(_KEYRING_SPLIT_PREFIX):])
    except (ValueError, IndexError):
        logger.warning(f"Keyring entry {username!r} has malformed split header; ignoring")
        return None

    parts: list[str] = []
    for i in range(count):
        chunk = _keyring.get_password(_KEYRING_SERVICE, f"{username}{_KEYRING_CHUNK_SUFFIX}{i}")
        if chunk is None:
            logger.warning(
                f"Keyring credential {username!r} is incomplete (missing chunk {i}); "
                "falling back to file"
            )
            return None
        parts.append(chunk)
    return "".join(parts)


def _keyring_delete_credential(username: str) -> None:
    try:
        existing = _keyring.get_password(_KEYRING_SERVICE, username)
    except Exception:
        existing = None

    if existing and existing.startswith(_KEYRING_SPLIT_PREFIX):
        try:
            count = int(existing[len(_KEYRING_SPLIT_PREFIX):])
        except (ValueError, IndexError):
            count = 0
        for i in range(count):
            try:
                _keyring.delete_password(_KEYRING_SERVICE, f"{username}{_KEYRING_CHUNK_SUFFIX}{i}")
            except Exception:
                pass

    try:
        _keyring.delete_password(_KEYRING_SERVICE, username)
    except Exception:
        pass


def _keyring_username(profile_id: str | None) -> str:
    pid = safe_profile_id(profile_id or get_active_profile_id())
    return f"token:{pid}"


def _delete_token_file_if_exists(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def save_account_token(token: Any, profile_id: str | None = None) -> None:
    token_str: str = token if isinstance(token, str) else (
        token.decode("utf-8") if isinstance(token, (bytes, bytearray)) else str(token)
    )
    if _keyring_available():
        try:
            _keyring_save_credential(_keyring_username(profile_id), token_str)
            _delete_token_file_if_exists(get_token_path(profile_id))
            logger.debug("Account token saved to keyring")
            return
        except Exception as kr_exc:
            logger.debug(f"Keyring save failed, falling back to file: {kr_exc}")
    _save_token_file(token_str, profile_id)


def _save_token_file(token_str: str, profile_id: str | None = None) -> None:
    try:
        path = get_token_path(profile_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"

        token_bytes = token_str.encode("utf-8")


        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(tmp, flags, 0o600)
        except OSError:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(_TOKEN_HEADER)
                f.write(token_bytes)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

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

        if os.name == "nt":
            try:
                _restrict_windows_token_acl(path)
            except Exception as acl_exc:
                logger.debug(
                    f"Could not tighten Windows ACL on token file {path}: {acl_exc}"
                )
    except OSError as e:
        logger.error(f"Failed to save account token: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error saving account token: {e}")
        raise


def _restrict_windows_token_acl(path: str) -> None:
    if os.name != "nt":
        return
    import subprocess

    from core.subprocess_utils import no_window_kwargs

    user = os.environ.get("USERNAME") or ""
    if not user:
        return

    try:
        subprocess.run(
            [
                "icacls",
                path,
                "/inheritance:r",
                "/grant:r",
                f"{user}:F",
            ],
            check=False,
            capture_output=True,
            timeout=5,
            **no_window_kwargs(),
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return


def load_account_token(profile_id: str | None = None) -> str | None:
    if _keyring_available():
        try:
            token = _keyring_load_credential(_keyring_username(profile_id))
            if token is not None:
                _delete_token_file_if_exists(get_token_path(profile_id))
                return token
        except Exception as kr_exc:
            logger.debug(f"Keyring load failed, falling back to file: {kr_exc}")

    token = _load_token_file(profile_id)
    if token is not None and _keyring_available():
        try:
            _keyring_save_credential(_keyring_username(profile_id), token)
            _delete_token_file_if_exists(get_token_path(profile_id))
            logger.info(f"Account token migrated to keyring for profile {profile_id!r}")
        except Exception as kr_exc:
            logger.debug(f"Keyring migration failed, keeping file: {kr_exc}")
    return token


def _load_token_file(profile_id: str | None = None) -> str | None:
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
    if _keyring_available():
        try:
            _keyring_delete_credential(_keyring_username(profile_id))
            logger.debug("Account token cleared from keyring")
        except Exception:
            pass
    path = get_token_path(profile_id)
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.debug(f"Account token file cleared: {path}")
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


def migrate_all_tokens_to_keyring() -> None:
    if not _keyring_available():
        return
    try:
        profiles = list_profiles()
    except Exception as exc:
        logger.debug(f"migrate_all_tokens_to_keyring: could not list profiles: {exc}")
        return
    for profile in profiles:
        pid = profile.get("id")
        if not pid:
            continue
        try:
            if os.path.exists(get_token_path(pid)):
                load_account_token(pid)
        except Exception as exc:
            logger.debug(f"migrate_all_tokens_to_keyring: skipped profile {pid!r}: {exc}")
