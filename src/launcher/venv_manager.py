from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Optional


__all__ = [
    "get_venv_dir",
    "get_venv_python",
    "get_venv_site_packages",
    "venv_exists",
    "venv_uses_system_site_packages",
    "ensure_venv",
    "activate_venv_site_packages",
]


def _base_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".histolauncher")


def get_venv_dir() -> str:
    return os.path.join(_base_dir(), "venv")


def get_venv_python() -> str:
    venv = get_venv_dir()
    if sys.platform.startswith("win"):
        return os.path.join(venv, "Scripts", "python.exe")
    return os.path.join(venv, "bin", "python")


def _pyvenv_cfg_path() -> str:
    return os.path.join(get_venv_dir(), "pyvenv.cfg")


def get_venv_site_packages() -> Optional[str]:
    venv = get_venv_dir()
    if not os.path.isdir(venv):
        return None

    if sys.platform.startswith("win"):
        candidate = os.path.join(venv, "Lib", "site-packages")
        return candidate if os.path.isdir(candidate) else None

    lib_dir = os.path.join(venv, "lib")
    if not os.path.isdir(lib_dir):
        return None
    preferred = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = sorted(os.listdir(lib_dir))
    if preferred in candidates:
        candidates = [preferred] + [c for c in candidates if c != preferred]
    for name in candidates:
        if not name.startswith("python"):
            continue
        sp = os.path.join(lib_dir, name, "site-packages")
        if os.path.isdir(sp):
            return sp
    return None


def venv_exists() -> bool:
    return os.path.isfile(get_venv_python())


def venv_uses_system_site_packages() -> bool:
    cfg_path = _pyvenv_cfg_path()
    if not os.path.isfile(cfg_path):
        return False

    try:
        with open(cfg_path, encoding="utf-8") as handle:
            for raw in handle:
                if raw.lower().startswith("include-system-site-packages"):
                    _, value = raw.split("=", 1)
                    return value.strip().lower() == "true"
    except Exception:
        return False

    return False


def _linux_distro_ids() -> set[str]:
    ids: set[str] = set()
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            for raw in handle:
                if "=" not in raw:
                    continue
                key, value = raw.rstrip().split("=", 1)
                if key not in {"ID", "ID_LIKE"}:
                    continue
                ids.update(part.lower() for part in value.strip().strip('"').split() if part)
    except Exception:
        pass
    return ids


def _linux_venv_install_commands() -> tuple[str, list[list[str]]]:
    ids = _linux_distro_ids()
    if ids & {"arch", "cachyos", "manjaro", "artix"}:
        return "Arch/CachyOS", [["pacman", "-S", "--needed", "--noconfirm", "python", "python-pip"]]
    if ids & {"debian", "ubuntu", "pop", "linuxmint"}:
        return "Debian/Ubuntu/Pop!_OS", [
            ["apt-get", "update"],
            ["apt-get", "install", "-y", "python3-venv", "python3-pip"],
        ]
    if ids & {"fedora", "rhel", "centos"}:
        return "Fedora/RHEL", [["dnf", "install", "-y", "python3-pip"]]
    if ids & {"opensuse", "suse", "sles"}:
        return "openSUSE", [["zypper", "--non-interactive", "install", "python3-pip"]]
    return "Linux", []


def _try_install_linux_venv_support(log=print) -> bool:
    if not sys.platform.startswith("linux"):
        return False

    pkexec = shutil.which("pkexec")
    if not pkexec:
        log("[venv] pkexec not found; install Python venv/pip support manually.")
        return False

    distro_label, commands = _linux_venv_install_commands()
    if not commands:
        log("[venv] Could not detect a supported Linux package manager for venv recovery.")
        return False

    log(f"[venv] Attempting to install Python venv/pip support ({distro_label})...")
    for command in commands:
        proc = subprocess.run(
            [pkexec, *command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if proc.returncode != 0:
            log(f"[venv] Package install command failed: {' '.join(command)}")
            return False
    return True


def ensure_venv(log=print) -> bool:
    venv_dir = get_venv_dir()
    if venv_exists():
        if not venv_uses_system_site_packages():
            return True

        log(
            "[venv] Rebuilding legacy launcher venv without "
            "system-site-packages to avoid mixed Qt imports."
        )
        try:
            shutil.rmtree(venv_dir)
        except Exception as e:
            log(f"[venv] Failed to remove legacy venv at {venv_dir}: {e}")
            return False

    os.makedirs(os.path.dirname(venv_dir), exist_ok=True)

    cmd = [
        sys.executable, "-m", "venv",
        venv_dir,
    ]
    log(f"[venv] Creating launcher venv: {' '.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except Exception as e:
        log(f"[venv] Failed to launch venv creation: {e}")
        return False

    for line in (proc.stdout or "").splitlines() + (proc.stderr or "").splitlines():
        log(f"[venv] {line}")

    if proc.returncode != 0:
        log(f"[venv] venv creation exited with code {proc.returncode}")

        missing_venv = (
            "without pip" in (proc.stderr or "").lower() or
            "ensurepip is not available" in (proc.stderr or "").lower() or
            "No module named venv" in (proc.stderr or "") or
            "python3-venv" in (proc.stderr or "") or proc.returncode == 1
        )
        if sys.platform.startswith("linux") and missing_venv:
            try:
                if _try_install_linux_venv_support(log=log):
                    proc_retry = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                    if proc_retry.returncode == 0:
                        log("[venv] venv creation succeeded after installing venv support")
                        return venv_exists()
            except Exception as ex:
                log(f"[venv] Auto-install failed: {ex}")

        return False

    if not venv_exists():
        log(f"[venv] venv created but {get_venv_python()} is missing")
        return False

    log(f"[venv] Created venv at {venv_dir}")
    return True


def activate_venv_site_packages() -> bool:
    sp = get_venv_site_packages()
    if not sp:
        return False

    try:
        sys.path.remove(sp)
    except ValueError:
        pass

    insert_at = 1 if sys.path else 0
    sys.path.insert(insert_at, sp)

    try:
        import site

        site.addsitedir(sp)
    except Exception:
        pass

    try:
        sys.path.remove(sp)
    except ValueError:
        pass
    sys.path.insert(insert_at, sp)

    return True
