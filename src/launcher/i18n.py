from __future__ import annotations

import configparser
import json
import locale
import os
import re
from functools import lru_cache
from typing import Any

from launcher._constants import PROJECT_ROOT


DEFAULT_LANGUAGE = "en"
LANGUAGE_CODE_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")

_BASE_DIR = os.path.join(os.path.expanduser("~"), ".histolauncher")
_UI_I18N_DIR = os.path.join(PROJECT_ROOT, "ui", "i18n")
RTL_LANGUAGE_BASES = {"ar", "fa", "he", "ur"}
_TRADITIONAL_CHINESE_PARTS = {"hant", "tw", "hk", "mo"}
_SIMPLIFIED_CHINESE_PARTS = {"hans", "cn", "sg"}
_TEMPORARY_LANGUAGE_CODE: str | None = None


def _normalize_language_code(value: Any) -> str:
    code = str(value or DEFAULT_LANGUAGE).strip().lower().replace("_", "-")
    code = code.split(".", 1)[0]
    if code == "system":
        return code
    return code if LANGUAGE_CODE_RE.fullmatch(code) else DEFAULT_LANGUAGE


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


@lru_cache(maxsize=1)
def _language_manifest() -> dict[str, Any]:
    return _read_json(os.path.join(_UI_I18N_DIR, "languages.json"), {"languages": []})


def _language_entries() -> list[dict[str, Any]]:
    entries = _language_manifest().get("languages")
    if not isinstance(entries, list):
        return []
    valid_entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        code = _normalize_language_code(entry.get("code"))
        if LANGUAGE_CODE_RE.fullmatch(code):
            valid_entries.append({**entry, "code": code})
    return valid_entries


def _available_language_codes() -> list[str]:
    return [entry["code"] for entry in _language_entries()]


def _language_entry_for(code: str) -> dict[str, Any] | None:
    normalized = _normalize_language_code(code)
    for entry in _language_entries():
        if entry.get("code") == normalized:
            return entry
    return None


def _language_file_for(code: str) -> str:
    normalized = _normalize_language_code(code)
    entry = _language_entry_for(normalized)
    if entry is not None:
        file_name = str(entry.get("file") or "").strip()
        if re.fullmatch(r"[a-z0-9._-]+\.json", file_name, flags=re.IGNORECASE):
            return file_name
    return f"{normalized}.json"


@lru_cache(maxsize=64)
def _ui_dictionary(code: str) -> dict[str, Any]:
    normalized = _normalize_language_code(code)
    data = _read_json(os.path.join(_UI_I18N_DIR, _language_file_for(normalized)), {})
    return data if isinstance(data, dict) else {}


def _nested_value(source: dict[str, Any], key: str) -> Any:
    value: Any = source
    for part in str(key or "").split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _interpolate(value: Any, replacements: dict[str, Any] | None) -> str:
    text = str(value)
    if not replacements:
        return text

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return str(replacements[name]) if name in replacements else match.group(0)

    return re.sub(r"\{([a-zA-Z0-9_]+)\}", replace, text)


def _safe_profile_id(value: Any) -> str:
    raw = str(value or "default").strip().lower().replace(" ", "-")
    raw = re.sub(r"[^a-z0-9_-]+", "", raw).strip("-_")
    return (raw or "default")[:48]


def _read_active_profile_id() -> str:
    meta_path = os.path.join(_BASE_DIR, "profiles", "settings", "profiles.json")
    data = _read_json(meta_path, {})
    if isinstance(data, dict):
        return _safe_profile_id(data.get("active") or "default")
    return "default"


def _read_language_from_ini(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error:
        try:
            with open(path, encoding="utf-8") as handle:
                for raw in handle:
                    if "=" not in raw:
                        continue
                    key, value = raw.split("=", 1)
                    if key.strip() == "launcher_language":
                        return _normalize_language_code(value)
        except OSError:
            return None
        return None
    except OSError:
        return None

    for section in ("appearance", "launcher", "DEFAULT"):
        if parser.has_option(section, "launcher_language"):
            return _normalize_language_code(parser.get(section, "launcher_language"))
    return None


def _configured_language_code() -> str:
    if not os.path.isdir(_BASE_DIR):
        return DEFAULT_LANGUAGE

    active_profile = _read_active_profile_id()
    candidates = [
        os.path.join(_BASE_DIR, "profiles", "settings", f"{active_profile}.ini"),
        os.path.join(_BASE_DIR, "profiles", "settings", "default.ini"),
        os.path.join(_BASE_DIR, "settings.ini"),
    ]
    for path in candidates:
        language = _read_language_from_ini(path)
        if language:
            return language
    return DEFAULT_LANGUAGE


def _system_language_code() -> str:
    candidates = []
    try:
        language, _encoding = locale.getlocale()
        if language:
            candidates.append(language)
    except Exception:
        pass
    candidates.extend(os.environ.get(name) for name in ("LC_ALL", "LC_MESSAGES", "LANG"))

    available = _available_language_codes()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = _normalize_language_code(candidate)
        if normalized == DEFAULT_LANGUAGE and not str(candidate).strip().lower().startswith("en"):
            continue
        if normalized in available:
            return normalized

        parts = normalized.split("-")
        base = parts[0]
        if base == "zh":
            if any(part in _TRADITIONAL_CHINESE_PARTS for part in parts) and "zh-tw" in available:
                return "zh-tw"
            if any(part in _SIMPLIFIED_CHINESE_PARTS for part in parts) and "zh-cn" in available:
                return "zh-cn"
        for code in available:
            if code == base or code.split("-", 1)[0] == base:
                return code
    return DEFAULT_LANGUAGE


def available_languages() -> list[dict[str, str]]:
    languages = []
    for entry in _language_entries():
        code = entry["code"]
        name = str(entry.get("name") or code).strip() or code
        native_name = str(entry.get("nativeName") or name).strip() or name
        direction = str(entry.get("dir") or "").strip().lower()
        if direction not in {"rtl", "ltr"}:
            direction = "rtl" if code.split("-", 1)[0] in RTL_LANGUAGE_BASES else "ltr"
        languages.append({
            "code": code,
            "name": name,
            "nativeName": native_name,
            "dir": direction,
        })
    return languages


def suggested_language_code() -> str:
    available = _available_language_codes()
    configured = _configured_language_code()
    if configured == "system":
        return _system_language_code()
    if os.path.isdir(_BASE_DIR) and configured in available:
        return configured
    system_language = _system_language_code()
    return system_language if system_language in available else DEFAULT_LANGUAGE


def set_temporary_language(code: str | None) -> str:
    global _TEMPORARY_LANGUAGE_CODE

    normalized = _normalize_language_code(code)
    if normalized == "system":
        normalized = _system_language_code()
    if normalized not in _available_language_codes():
        normalized = DEFAULT_LANGUAGE
    _TEMPORARY_LANGUAGE_CODE = normalized
    return normalized


def clear_temporary_language() -> None:
    global _TEMPORARY_LANGUAGE_CODE

    _TEMPORARY_LANGUAGE_CODE = None


def current_language_code() -> str:
    if _TEMPORARY_LANGUAGE_CODE in _available_language_codes():
        return str(_TEMPORARY_LANGUAGE_CODE)

    configured = _configured_language_code()
    if configured == "system":
        return _system_language_code()
    if configured in _available_language_codes():
        return configured
    return DEFAULT_LANGUAGE


def language_direction(code: str | None = None) -> str:
    language = current_language_code() if code is None else _normalize_language_code(code)
    if language == "system":
        language = _system_language_code()

    entry = _language_entry_for(language)
    manifest_direction = str((entry or {}).get("dir") or "").strip().lower()
    if manifest_direction in {"rtl", "ltr"}:
        return manifest_direction

    base = language.split("-", 1)[0]
    return "rtl" if base in RTL_LANGUAGE_BASES else "ltr"


def is_rtl_language(code: str | None = None) -> bool:
    return language_direction(code) == "rtl"


def tk_direction_options(code: str | None = None) -> dict[str, str]:
    if is_rtl_language(code):
        return {
            "anchor": "e",
            "justify": "right",
            "start_side": "right",
            "end_side": "left",
        }
    return {
        "anchor": "w",
        "justify": "left",
        "start_side": "left",
        "end_side": "right",
    }


def t(key: str, replacements: dict[str, Any] | None = None, default: str | None = None) -> str:
    language = current_language_code()

    for source in (
        _ui_dictionary(language),
        _ui_dictionary(DEFAULT_LANGUAGE),
    ):
        value = _nested_value(source, key)
        if value is not None:
            return _interpolate(value, replacements)

    return _interpolate(default if default is not None else key, replacements)
