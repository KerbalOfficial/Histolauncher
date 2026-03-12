# core/java_runtime.py

import os
import platform
import re
import shutil
import subprocess
import threading
import time

from typing import Dict, List, Optional

_CACHE_LOCK = threading.Lock()
_CACHE_AT = 0.0
_CACHE_RUNTIMES: List[Dict[str, object]] = []
_CACHE_TTL_SECONDS = 30.0


def _java_executable_name() -> str:
    return "java.exe" if platform.system().lower().startswith("win") else "java"


def _parse_java_version(text: str) -> Dict[str, object]:
    raw = ""
    major = 0

    m = re.search(r'version\s+"([^"]+)"', text)
    if m:
        raw = m.group(1)
    else:
        # Fallback for uncommon formats.
        first_line = (text or "").splitlines()[0] if text else ""
        raw = first_line.strip()

    if raw:
        main = raw.split("_", 1)[0]
        parts = main.split(".")
        try:
            if len(parts) >= 2 and parts[0] == "1":
                major = int(parts[1])
            else:
                major = int(parts[0])
        except Exception:
            major = 0

    return {"version": raw or "unknown", "major": major}


def _probe_java_runtime(java_path: str) -> Optional[Dict[str, object]]:
    try:
        proc = subprocess.run(
            [java_path, "-version"],
            capture_output=True,
            text=True,
            timeout=4,
        )
    except Exception:
        return None

    output = "\n".join(
        part for part in [proc.stdout, proc.stderr] if isinstance(part, str) and part.strip()
    ).strip()
    if not output:
        return None

    parsed = _parse_java_version(output)
    major = int(parsed.get("major") or 0)
    version = str(parsed.get("version") or "unknown")

    label = f"Java {major}" if major > 0 else "Java"
    return {
        "path": java_path,
        "label": label,
        "version": version,
        "major": major,
    }


def _iter_windows_common_java_paths() -> List[str]:
    roots = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        env_value = os.environ.get(env_name)
        if env_value and os.path.isdir(env_value):
            roots.append(env_value)

    vendor_dirs = [
        "Java",
        "Eclipse Adoptium",
        "AdoptOpenJDK",
        "BellSoft",
        "Zulu",
        "Microsoft",
        "Amazon Corretto",
        "Semeru",
    ]

    exe_name = _java_executable_name()
    out: List[str] = []

    for root in roots:
        for vendor in vendor_dirs:
            vendor_path = os.path.join(root, vendor)
            if not os.path.isdir(vendor_path):
                continue
            try:
                for child in os.listdir(vendor_path):
                    candidate = os.path.join(vendor_path, child, "bin", exe_name)
                    if os.path.isfile(candidate):
                        out.append(candidate)
            except Exception:
                continue

    return out


def _collect_candidate_java_paths() -> List[str]:
    exe_name = _java_executable_name()
    candidates = []

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        home_candidate = os.path.join(java_home, "bin", exe_name)
        if os.path.isfile(home_candidate):
            candidates.append(home_candidate)

    path_java = shutil.which("java")
    if path_java and os.path.isfile(path_java):
        candidates.append(path_java)

    if platform.system().lower().startswith("win"):
        try:
            where_out = subprocess.run(
                ["where", "java"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            for line in (where_out.stdout or "").splitlines():
                candidate = line.strip()
                if candidate and os.path.isfile(candidate):
                    candidates.append(candidate)
        except Exception:
            pass
        candidates.extend(_iter_windows_common_java_paths())
    elif platform.system().lower() == "darwin":
        mac_root = "/Library/Java/JavaVirtualMachines"
        if os.path.isdir(mac_root):
            try:
                for child in os.listdir(mac_root):
                    candidate = os.path.join(mac_root, child, "Contents", "Home", "bin", "java")
                    if os.path.isfile(candidate):
                        candidates.append(candidate)
            except Exception:
                pass
    else:
        jvm_root = "/usr/lib/jvm"
        if os.path.isdir(jvm_root):
            try:
                for child in os.listdir(jvm_root):
                    candidate = os.path.join(jvm_root, child, "bin", "java")
                    if os.path.isfile(candidate):
                        candidates.append(candidate)
            except Exception:
                pass

    # Deduplicate while preserving order.
    seen = set()
    unique = []
    for p in candidates:
        norm = os.path.normcase(os.path.normpath(p))
        if norm in seen:
            continue
        seen.add(norm)
        unique.append(p)
    return unique


def detect_java_runtimes(force_refresh: bool = False) -> List[Dict[str, object]]:
    global _CACHE_AT, _CACHE_RUNTIMES

    with _CACHE_LOCK:
        now = time.time()
        if (not force_refresh) and _CACHE_RUNTIMES and (now - _CACHE_AT) < _CACHE_TTL_SECONDS:
            return list(_CACHE_RUNTIMES)

    detected: List[Dict[str, object]] = []
    for java_path in _collect_candidate_java_paths():
        runtime = _probe_java_runtime(java_path)
        if not runtime:
            continue
        detected.append(runtime)

    detected.sort(key=lambda r: (int(r.get("major") or 0), str(r.get("path") or "")), reverse=True)

    with _CACHE_LOCK:
        _CACHE_RUNTIMES = detected
        _CACHE_AT = time.time()

    return list(detected)
