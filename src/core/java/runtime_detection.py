from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import threading
import time
from typing import Final, TypedDict

from core.constants import JAVA_DETECT_CACHE_TTL_S
from core.subprocess_utils import no_window_kwargs

__all__ = [
    "JAVA_RUNTIME_MODE_AUTO",
    "JAVA_RUNTIME_MODE_PATH",
    "JavaRuntime",
    "detect_java_runtimes",
    "get_path_java_executable",
    "get_path_java_runtime",
    "probe_java_runtime",
]


JAVA_RUNTIME_MODE_AUTO: Final[str] = "auto"
JAVA_RUNTIME_MODE_PATH: Final[str] = "__java_path_default__"

_JAVA_VERSION_RE: Final[re.Pattern[str]] = re.compile(r'version\s+"([^"]+)"')

_WIN_VENDOR_DIRS: Final[tuple[str, ...]] = (
    "Java",
    "Eclipse Adoptium",
    "AdoptOpenJDK",
    "BellSoft",
    "Temurin",
    "OpenJDK",
    "Zulu",
    "Microsoft",
    "Amazon Corretto",
    "Semeru",
)

_WIN_JAVA_DIR_HINTS: Final[tuple[str, ...]] = (
    "java",
    "jdk",
    "jre",
    "adoptium",
    "temurin",
    "openjdk",
    "zulu",
    "corretto",
    "bellsoft",
    "liberica",
    "microsoft",
    "semeru",
)


class JavaRuntime(TypedDict):
    path: str
    label: str
    version: str
    major: int


_cache_lock = threading.Lock()
_cache_at: float = 0.0
_cache_runtimes: list[JavaRuntime] = []


def _is_windows() -> bool:
    return platform.system().lower().startswith("win")


def _java_executable_name() -> str:
    return "java.exe" if _is_windows() else "java"


def _parse_java_version(text: str) -> tuple[str, int]:
    raw = ""
    match = _JAVA_VERSION_RE.search(text)
    if match:
        raw = match.group(1)
    else:
        first_line = (text or "").splitlines()[0] if text else ""
        raw = first_line.strip()

    if not raw:
        return "unknown", 0

    main = raw.split("_", 1)[0]
    parts = main.split(".")
    try:
        if len(parts) >= 2 and parts[0] == "1":
            major = int(parts[1])
        else:
            major = int(parts[0])
    except ValueError:
        major = 0

    return raw, major


def _probe(java_path: str) -> JavaRuntime | None:
    try:
        proc = subprocess.run(
            [java_path, "-version"],
            capture_output=True,
            text=True,
            timeout=4,
            **no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return None

    output = "\n".join(
        part
        for part in (proc.stdout, proc.stderr)
        if isinstance(part, str) and part.strip()
    ).strip()
    if not output:
        return None

    version, major = _parse_java_version(output)
    label = f"Java {major}" if major > 0 else "Java"
    return JavaRuntime(path=java_path, label=label, version=version, major=major)


def probe_java_runtime(java_path: str) -> JavaRuntime | None:
    return _probe(java_path)


def get_path_java_executable() -> str:
    path_java = shutil.which("java")
    if path_java and os.path.isfile(path_java):
        return path_java
    return "java"


def get_path_java_runtime() -> JavaRuntime | None:
    return _probe(get_path_java_executable())


def _iter_windows_common_java_paths() -> list[str]:
    exe_name = _java_executable_name()
    out: list[str] = []

    roots = []
    for env_name in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        env_value = os.environ.get(env_name)
        if env_value and os.path.isdir(env_value):
            roots.append(env_value)

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        local_programs = os.path.join(local_app_data, "Programs")
        if os.path.isdir(local_programs):
            roots.append(local_programs)

    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        user_jdks = os.path.join(user_profile, ".jdks")
        if os.path.isdir(user_jdks):
            roots.append(user_jdks)

    def add_home(home_path: str):
        candidate = os.path.join(home_path, "bin", exe_name)
        if os.path.isfile(candidate):
            out.append(candidate)

    def name_looks_like_java_dir(name: str) -> bool:
        lower = str(name or "").lower()
        return any(hint in lower for hint in _WIN_JAVA_DIR_HINTS)

    for root in roots:
        add_home(root)

        for vendor in _WIN_VENDOR_DIRS:
            vendor_path = os.path.join(root, vendor)
            if not os.path.isdir(vendor_path):
                continue
            add_home(vendor_path)
            try:
                children = os.listdir(vendor_path)
            except OSError:
                continue
            for child in children:
                add_home(os.path.join(vendor_path, child))

        try:
            children = os.listdir(root)
        except OSError:
            continue
        for child in children:
            if not name_looks_like_java_dir(child):
                continue
            child_path = os.path.join(root, child)
            if not os.path.isdir(child_path):
                continue
            add_home(child_path)

    return out


def _iter_windows_registry_java_paths() -> list[str]:
    if not _is_windows():
        return []

    try:
        import winreg
    except Exception:
        return []

    exe_name = _java_executable_name()
    out: list[str] = []
    roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\JavaSoft"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Eclipse Adoptium"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\JavaSoft"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Eclipse Adoptium"),
    )
    access_masks = [winreg.KEY_READ]
    for attr in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
        mask = getattr(winreg, attr, 0)
        if mask:
            access_masks.append(winreg.KEY_READ | mask)

    def add_home(raw_home: object):
        home = str(raw_home or "").strip()
        if not home:
            return
        candidate = os.path.join(home, "bin", exe_name)
        if os.path.isfile(candidate):
            out.append(candidate)

    def walk_key(root_key, sub_key: str, access: int):
        try:
            with winreg.OpenKey(root_key, sub_key, 0, access) as key:
                try:
                    value, _value_type = winreg.QueryValueEx(key, "JavaHome")
                    add_home(value)
                except OSError:
                    pass

                index = 0
                while True:
                    try:
                        child = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    walk_key(root_key, sub_key + "\\" + child, access)
        except OSError:
            return

    for root_key, sub_key in roots:
        for access in access_masks:
            walk_key(root_key, sub_key, access)

    return out


def _iter_macos_java_paths() -> list[str]:
    mac_root = "/Library/Java/JavaVirtualMachines"
    if not os.path.isdir(mac_root):
        return []
    try:
        children = os.listdir(mac_root)
    except OSError:
        return []
    return [
        candidate
        for child in children
        if os.path.isfile(
            candidate := os.path.join(mac_root, child, "Contents", "Home", "bin", "java")
        )
    ]


def _iter_linux_java_paths() -> list[str]:
    jvm_root = "/usr/lib/jvm"
    if not os.path.isdir(jvm_root):
        return []
    try:
        children = os.listdir(jvm_root)
    except OSError:
        return []
    return [
        candidate
        for child in children
        if os.path.isfile(candidate := os.path.join(jvm_root, child, "bin", "java"))
    ]


def _iter_managed_java_paths() -> list[str]:
    try:
        from core.settings import get_base_dir

        java_root = os.path.join(get_base_dir(), "java")
    except Exception:
        return []
    if not os.path.isdir(java_root):
        return []

    exe_name = _java_executable_name()
    out: list[str] = []
    try:
        children = os.listdir(java_root)
    except OSError:
        return []
    for child in children:
        child_path = os.path.join(java_root, child)
        if not os.path.isdir(child_path):
            continue
        direct = os.path.join(child_path, "bin", exe_name)
        if os.path.isfile(direct):
            out.append(direct)
            continue
        for dirpath, dirnames, filenames in os.walk(child_path):
            depth = os.path.relpath(dirpath, child_path).count(os.sep)
            if depth > 3:
                dirnames[:] = []
                continue
            if os.path.basename(dirpath) == "bin" and exe_name in filenames:
                out.append(os.path.join(dirpath, exe_name))
                break
    return out


def _iter_windows_where_results() -> list[str]:
    try:
        proc = subprocess.run(
            ["where", "java"],
            capture_output=True,
            text=True,
            timeout=3,
            **no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [
        candidate
        for line in (proc.stdout or "").splitlines()
        if (candidate := line.strip()) and os.path.isfile(candidate)
    ]


def _collect_candidate_java_paths() -> list[str]:
    exe_name = _java_executable_name()
    candidates: list[str] = []

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        home_candidate = os.path.join(java_home, "bin", exe_name)
        if os.path.isfile(home_candidate):
            candidates.append(home_candidate)

    candidates.extend(_iter_managed_java_paths())

    path_java = shutil.which("java")
    if path_java and os.path.isfile(path_java):
        candidates.append(path_java)

    if _is_windows():
        candidates.extend(_iter_windows_where_results())
        candidates.extend(_iter_windows_registry_java_paths())
        candidates.extend(_iter_windows_common_java_paths())
    elif platform.system().lower() == "darwin":
        candidates.extend(_iter_macos_java_paths())
    else:
        candidates.extend(_iter_linux_java_paths())

    seen: set[str] = set()
    unique: list[str] = []
    for p in candidates:
        norm = os.path.normcase(os.path.normpath(p))
        if norm in seen:
            continue
        seen.add(norm)
        unique.append(p)
    return unique


def detect_java_runtimes(force_refresh: bool = False) -> list[JavaRuntime]:
    global _cache_at, _cache_runtimes

    with _cache_lock:
        now = time.time()
        if (
            not force_refresh
            and _cache_runtimes
            and (now - _cache_at) < JAVA_DETECT_CACHE_TTL_S
        ):
            return list(_cache_runtimes)

    detected: list[JavaRuntime] = []
    for java_path in _collect_candidate_java_paths():
        runtime = _probe(java_path)
        if runtime is not None:
            detected.append(runtime)

    detected.sort(key=lambda r: (r["major"], r["path"]), reverse=True)

    with _cache_lock:
        _cache_runtimes = detected
        _cache_at = time.time()

    return list(detected)
