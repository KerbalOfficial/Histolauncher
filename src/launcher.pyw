#!/usr/bin/env python3
# launcher.pyw

from __future__ import annotations

import os
import sys
import traceback


def _show_fatal(message: str) -> None:
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, "Histolauncher", 0x40010)
            return
        except Exception:
            pass
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("Histolauncher", message)
        root.destroy()
        return
    except Exception:
        pass
    try:
        sys.stderr.write(message + "\n")
    except Exception:
        pass


_TK_INSTALL_HINT = """\
Histolauncher requires Tk/Tkinter, which is not installed on your system.

Install it for your distribution and then run Histolauncher again:

    Arch / CachyOS:               sudo pacman -S python tk python-pip
    Debian / Ubuntu / Pop!_OS:    sudo apt install python3-tk python3-venv python3-pip
    Fedora / RHEL:                sudo dnf install python3-tkinter python3-pip
    openSUSE:                     sudo zypper install python3-tk python3-pip

    Windows:                      Re-run the Python installer and tick
                                  "tcl/tk and IDLE" under Optional Features.
"""


def _check_tkinter() -> bool:
    try:
        import tkinter  # noqa: F401

        return True
    except ImportError:
        return False


def _bootstrap() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)

    if sys.platform.startswith("linux"):
        os.environ["PYWEBVIEW_GUI"] = "qt"
        os.environ["QT_API"] = "pyqt6"

    if not _check_tkinter():
        try:
            import subprocess
            import shutil

            def attempt_linux_install():
                if not sys.platform.startswith("linux"):
                    return False

                distro = None
                if os.path.exists("/etc/os-release"):
                    with open("/etc/os-release") as f:
                        for line in f:
                            if line.startswith("ID="):
                                distro = line.strip().split("=")[1].strip('"')
                                break
                            elif line.startswith("ID_LIKE="):
                                if not distro:
                                    distro = line.strip().split("=")[1].strip('"').split()[0]

                pkexec = shutil.which("pkexec")
                if not pkexec:
                    return False

                cmds = []
                if distro in ("arch", "cachyos", "manjaro", "artix"):
                    cmds = [["pacman", "-S", "--needed", "--noconfirm", "python", "tk", "python-pip"]]
                elif distro in ("ubuntu", "debian", "pop", "linuxmint"):
                    cmds = [
                        ["apt-get", "update"],
                        ["apt-get", "install", "-y", "python3-tk", "python3-venv", "python3-pip"]
                    ]
                elif distro in ("fedora", "rhel"):
                    cmds = [["dnf", "install", "-y", "python3-tkinter", "python3-pip"]]
                elif distro in ("opensuse", "sles"):
                    cmds = [["zypper", "install", "-y", "python3-tk", "python3-pip"]]
                else:
                    return False

                zenity = shutil.which("zenity")
                kdialog = shutil.which("kdialog")

                msg = "Histolauncher needs to install packages (Tkinter) to run on Linux. Do you want to proceed and allow pkexec?"
                proceed = False

                if zenity:
                    ret = subprocess.run([zenity, "--question", "--text", msg])
                    proceed = (ret.returncode == 0)
                elif kdialog:
                    ret = subprocess.run([kdialog, "--yesno", msg])
                    proceed = (ret.returncode == 0)
                else:
                    return False

                if not proceed:
                    return False

                for cmd in cmds:
                    ret = subprocess.run([pkexec] + cmd)
                    if ret.returncode != 0:
                        return False
                return True

            if attempt_linux_install():
                if _check_tkinter():
                    pass # Successfully installed Tkinter
                else:
                    _show_fatal(_TK_INSTALL_HINT)
                    return 1
            else:
                _show_fatal(_TK_INSTALL_HINT)
                return 1
        except Exception:
            _show_fatal(_TK_INSTALL_HINT)
            return 1

    try:
        from launcher.venv_manager import (
            activate_venv_site_packages,
            ensure_venv,
            venv_exists,
            venv_uses_system_site_packages,
        )

        if (
            sys.platform.startswith("linux")
            and venv_exists()
            and venv_uses_system_site_packages()
        ):
            print(
                "[venv] Legacy launcher venv detected on Linux; rebuilding "
                "it before loading optional GUI packages."
            )
            if not ensure_venv(log=print):
                print("[venv] Warning: automatic venv rebuild failed.")
        activate_venv_site_packages()
    except Exception:
        pass

    try:
        from launcher import main
    except Exception:
        _show_fatal(
            "Histolauncher failed to start.\n\n" + traceback.format_exc()
        )
        return 1

    try:
        main()
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 0
    except Exception:
        _show_fatal(
            "Histolauncher crashed while starting.\n\n"
            + traceback.format_exc()
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_bootstrap())
