from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import tkinter
from tkinter import ttk

from core.subprocess_utils import no_window_kwargs
from core.logger import colorize_log
from launcher._constants import (
    BUTTON_STYLE_MAP,
    FOCUS_COLOR,
    ICO_PATH,
    PANEL_BG_COLOR,
    PANEL_BORDER_COLOR,
    TEXT_PRIMARY_COLOR,
    TEXT_SECONDARY_COLOR,
    TOPBAR_ACTIVE_COLOR,
    TOPBAR_BG_COLOR,
)
from launcher.dialogs import center_dialog_window, resolve_dialog_owner
from launcher.dispatcher import create_tk_ui_dispatcher
from launcher.fonts import get_native_ui_font_family
from launcher.i18n import t, tk_direction_options


__all__ = ["install"]


_PIP_PHASES = {
    "collecting": 0.1,
    "downloading": 0.4,
    "using cached": 0.6,
    "installing collected packages": 0.9,
    "successfully installed": 1.0,
}


def install(package, *, display_name: str | None = None):
    if isinstance(package, str):
        packages = package.split()
    else:
        packages = list(package)

    if not packages:
        return True

    package_label = display_name or (
        packages[0] if len(packages) == 1 else t("native.install.requiredComponents")
    )

    result = {"success": False}

    total_packages = 0
    completed_packages = 0

    collapsed_size = (600, 220)
    expanded_size = (600, 410)

    def detect_phase_fraction(line):
        l = line.lower()
        for key, frac in _PIP_PHASES.items():
            if key in l:
                return frac
        return None

    owner, owns_owner = resolve_dialog_owner()
    root = tkinter.Toplevel(owner)
    queue_ui, start_ui_dispatcher, stop_ui_dispatcher = create_tk_ui_dispatcher(root)
    title_text = t("native.install.title", {"target": package_label})
    ui_font = get_native_ui_font_family(root)
    direction = tk_direction_options()
    drag_state = {"x": 0, "y": 0}

    def ui_log(line):
        output_box.configure(state="normal")
        output_box.insert("end", line)
        output_box.see("end")
        output_box.configure(state="disabled")

    def ui_set_status(text):
        progress_label.config(text=text)

    def ui_set_progress(value):
        progress.config(mode="determinate", maximum=100)
        progress.stop()
        progress["value"] = max(0, min(100, value))

    def ui_finish(success):
        ui_set_status(
            t("native.install.statusFinished")
            if success
            else t("native.install.statusFailed")
        )
        if success:
            ui_set_progress(100)
        else:
            progress.stop()

    def close_dialog():
        stop_ui_dispatcher()
        try:
            root.grab_release()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

    def _same_path(first: str, second: str) -> bool:
        try:
            return os.path.normcase(os.path.realpath(first)) == os.path.normcase(
                os.path.realpath(second)
            )
        except Exception:
            return first == second

    def _installed_python_candidates(exclude_python: str) -> list[str]:
        candidates: list[str] = []

        def add(candidate: str | None) -> None:
            if not candidate or _same_path(candidate, exclude_python):
                return
            if any(_same_path(candidate, existing) for existing in candidates):
                return
            candidates.append(candidate)

        add(sys.executable)
        add(shutil.which("python"))
        add(shutil.which("python3"))
        return candidates

    def _run_pip(extra_args: list, python_exe: str | None = None) -> tuple[int, str]:
        nonlocal total_packages, completed_packages
        py = python_exe or sys.executable
        cmd = [py, "-m", "pip", "install", *extra_args] + packages
        print(colorize_log(
            f"[installation] Installing {package_label} with {py}..."
        ))
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                **no_window_kwargs(),
            )
        except OSError as e:
            msg = f"[installation] pip launch failed with {py}: {e}\n"
            print(colorize_log(msg.rstrip()))
            queue_ui(lambda m=msg: ui_log(m))
            return 127, msg
        collected: list[str] = []
        stream = process.stdout if process.stdout is not None else []
        for line in stream:
            collected.append(line)
            print(colorize_log(f"[pip] {line.rstrip()}"))
            queue_ui(lambda line=line: ui_log(line))
            if line.lower().startswith("collecting "):
                total_packages += 1
                queue_ui(lambda: ui_set_status(t("native.install.statusCollecting")))
            phase_frac = detect_phase_fraction(line)
            if phase_frac is not None and total_packages > 0:
                if "successfully installed" in line.lower():
                    completed_packages += 1
                    queue_ui(lambda: ui_set_status(t("native.install.statusPackages")))
                overall = (
                    (completed_packages + phase_frac) / total_packages
                ) * 100
                queue_ui(lambda overall=overall: ui_set_progress(overall))
        process.wait()
        print(colorize_log(
            f"[installation] pip exited with code {process.returncode}"
        ))
        return process.returncode, "".join(collected)

    def _try_venv_install() -> int:
        from launcher.venv_manager import (
            activate_venv_site_packages,
            ensure_venv,
            get_venv_dir,
            get_venv_python,
            get_venv_site_packages,
        )

        def venv_log(msg: str) -> None:
            print(colorize_log(msg))
            queue_ui(lambda m=msg: ui_log(m + "\n"))

        def target_site_packages() -> str:
            existing = get_venv_site_packages()
            if existing:
                return existing

            venv_dir = get_venv_dir()
            if sys.platform.startswith("win"):
                return os.path.join(venv_dir, "Lib", "site-packages")
            version_dir = f"python{sys.version_info.major}.{sys.version_info.minor}"
            return os.path.join(venv_dir, "lib", version_dir, "site-packages")

        def try_installed_python_target_install(venv_py: str) -> int:
            site_packages = target_site_packages()
            try:
                os.makedirs(site_packages, exist_ok=True)
            except Exception as e:
                venv_log(
                    f"[installer] Could not prepare launcher site-packages "
                    f"at {site_packages}: {e}"
                )
                return 1

            candidates = _installed_python_candidates(venv_py)
            if not candidates:
                venv_log(
                    "[installer] No installed Python executable was found for "
                    "the fallback install."
                )
                return 1

            venv_log(
                "[installer] Retrying install with the installed Python and "
                f"targeting launcher site-packages at {site_packages}."
            )
            target_args = [
                "--upgrade",
                "--ignore-installed",
                "--target",
                site_packages,
                "--no-warn-script-location",
            ]
            last_rc = 1
            for candidate in candidates:
                venv_log(f"[installer] Trying installed Python: {candidate}")
                last_rc, _ = _run_pip(target_args, python_exe=candidate)
                if last_rc == 0:
                    activate_venv_site_packages()
                    return 0
            return last_rc

        queue_ui(lambda: ui_log(
            "\n[installer] Installing into launcher venv at "
            "~/.histolauncher/venv ...\n\n"
        ))
        venv_py = get_venv_python()
        if not ensure_venv(log=venv_log):
            queue_ui(lambda: ui_log(
                "\n[installer] Could not create a complete launcher venv.\n"
            ))
            return try_installed_python_target_install(venv_py)

        if sys.platform.startswith("win"):
            venv_log(
                "[installer] Windows launcher venv is created without pip to "
                "avoid a transient console during bootstrap. Installing "
                "packages directly into launcher site-packages."
            )
            rc = try_installed_python_target_install(venv_py)
            if rc == 0:
                activate_venv_site_packages()
            return rc

        rc, _ = _run_pip([], python_exe=venv_py)
        if rc == 0:
            activate_venv_site_packages()
            return rc

        rc = try_installed_python_target_install(venv_py)
        if rc == 0:
            activate_venv_site_packages()
        return rc

    def _venv_available() -> bool:
        try:
            import venv  # noqa: F401
            return True
        except Exception:
            return False

    def _bootstrap_pip() -> bool:
        import os

        cmd = [sys.executable, "-m", "ensurepip", "--upgrade", "--user"]

        attempts = [None]
        if not sys.platform.startswith("win"):
            override_env = dict(os.environ)
            override_env["PIP_BREAK_SYSTEM_PACKAGES"] = "1"
            attempts.append(override_env)

        queue_ui(lambda: ui_log(
            "\n[installer] pip is missing. Attempting to bootstrap with "
            "ensurepip...\n"
        ))

        last_output = ""
        for env in attempts:
            label = " (with PIP_BREAK_SYSTEM_PACKAGES=1)" if env else ""
            print(colorize_log(
                f"[installation] Bootstrapping pip: {' '.join(cmd)}{label}"
            ))
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env=env,
                    **no_window_kwargs(),
                )
            except Exception as e:
                print(colorize_log(f"[installation] ensurepip failed to launch: {e}"))
                continue
            output_lines = (proc.stdout or "").splitlines() + (proc.stderr or "").splitlines()
            for line in output_lines:
                print(colorize_log(f"[ensurepip] {line}"))
                queue_ui(lambda line=line: ui_log(line + "\n"))
            print(colorize_log(
                f"[installation] ensurepip exited with code {proc.returncode}"
            ))
            last_output = (proc.stdout or "") + (proc.stderr or "")
            if proc.returncode == 0:
                return True
            if "externally-managed" not in last_output.lower():
                break
        return False

    def _linux_distro_pip_hint() -> str:
        info: dict[str, str] = {}
        try:
            with open("/etc/os-release", encoding="utf-8") as fp:
                for raw in fp:
                    if "=" in raw:
                        k, v = raw.rstrip().split("=", 1)
                        info[k] = v.strip().strip('"')
        except Exception:
            pass
        ids = (info.get("ID", "") + " " + info.get("ID_LIKE", "")).lower()
        if "arch" in ids or "cachyos" in ids or "manjaro" in ids:
            return "  sudo pacman -S python python-pip tk"
        if "debian" in ids or "ubuntu" in ids or "pop" in ids or "mint" in ids:
            return "  sudo apt install python3-venv python3-pip python3-tk"
        if "fedora" in ids or "rhel" in ids or "centos" in ids:
            return "  sudo dnf install python3-pip python3-tkinter"
        if "opensuse" in ids or "suse" in ids:
            return "  sudo zypper install python3-pip python3-tk"
        return "  Install the 'python3-pip' (or equivalent) package for your distro."

    def run_install():
        try:
            returncode = _try_venv_install()

            if returncode != 0 and not _venv_available():
                queue_ui(lambda: ui_log(
                    "\n[installer] venv unavailable; falling back to system pip...\n\n"
                ))
                returncode, output = _run_pip([])

                if returncode != 0 and "no module named pip" in output.lower():
                    if _bootstrap_pip():
                        queue_ui(lambda: ui_log(
                            "\n[installer] pip bootstrapped. Retrying install...\n\n"
                        ))
                        returncode, output = _run_pip([])
                    else:
                        hint = _linux_distro_pip_hint() if sys.platform.startswith("linux") else ""
                        msg = (
                            "\n[installer] pip is not installed and could not be "
                            "bootstrapped automatically.\n"
                        )
                        if hint:
                            msg += f"Install pip manually with:\n{hint}\n"
                        msg += "Then restart Histolauncher and try again.\n"
                        print(colorize_log(msg.rstrip()))
                        queue_ui(lambda m=msg: ui_log(m))

                if (
                    returncode != 0
                    and "externally-managed" in output.lower()
                    and not sys.platform.startswith("win")
                ):
                    queue_ui(lambda: ui_log(
                        "\n[installer] Externally-managed Python environment detected.\n"
                        "Retrying with --break-system-packages...\n\n"
                    ))
                    returncode, output = _run_pip(["--break-system-packages"])

            result["success"] = returncode == 0
            queue_ui(lambda success=result["success"]: ui_finish(success))
        except Exception as e:
            result["success"] = False
            queue_ui(
                lambda err=e: ui_log(
                    "\n" + t("native.install.errorPrefix", {"error": err}) + "\n"
                )
            )
            queue_ui(lambda: ui_set_status(t("native.install.statusFailed")))
        finally:
            queue_ui(lambda: root.after(300, close_dialog))

    try:
        root.iconbitmap(ICO_PATH)
    except Exception:
        pass
    root.withdraw()
    root.title(title_text)
    root.geometry(f"{collapsed_size[0]}x{collapsed_size[1]}")
    root.resizable(False, False)
    root.configure(bg="#000000")
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    root.overrideredirect(True)
    try:
        root.wm_attributes("-toolwindow", True)
    except Exception:
        pass
    try:
        root.transient(owner)
    except Exception:
        pass
    root.protocol("WM_DELETE_WINDOW", lambda: None)
    root.bind("<Escape>", lambda _event: "break")

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    progress_style_name = "HistolauncherInstall.Horizontal.TProgressbar"
    style.configure(
        progress_style_name,
        troughcolor=TOPBAR_BG_COLOR,
        background=BUTTON_STYLE_MAP["primary"]["bg"],
        darkcolor=BUTTON_STYLE_MAP["primary"]["bg"],
        lightcolor=BUTTON_STYLE_MAP["primary"]["active_bg"],
        bordercolor=PANEL_BORDER_COLOR,
        thickness=12,
    )

    outer = tkinter.Frame(root, bg=PANEL_BORDER_COLOR, padx=4, pady=4)
    outer.pack(fill="both", expand=True)

    card = tkinter.Frame(outer, bg=PANEL_BG_COLOR)
    card.pack(fill="both", expand=True)

    topbar = tkinter.Frame(card, bg=TOPBAR_BG_COLOR, height=34)
    topbar.pack(fill="x")
    topbar.pack_propagate(False)

    topbar_title = tkinter.Label(
        topbar,
        text=title_text,
        bg=TOPBAR_BG_COLOR,
        fg=TEXT_PRIMARY_COLOR,
        font=(ui_font, 10, "bold"),
        anchor=direction["anchor"],
        justify=direction["justify"],
        padx=12,
    )
    topbar_title.pack(side=direction["start_side"], fill="both", expand=True)

    topbar_status = tkinter.Label(
        topbar,
        text=t("native.install.statusInstalling"),
        bg=TOPBAR_BG_COLOR,
        fg=TEXT_SECONDARY_COLOR,
        font=(ui_font, 9),
        anchor="w" if direction["start_side"] == "right" else "e",
        padx=12,
    )
    topbar_status.pack(side=direction["end_side"], fill="y")

    def start_drag(event):
        drag_state["x"] = event.x_root - root.winfo_x()
        drag_state["y"] = event.y_root - root.winfo_y()

    def do_drag(event):
        new_x = event.x_root - drag_state["x"]
        new_y = event.y_root - drag_state["y"]
        root.geometry(f"+{max(0, new_x)}+{max(0, new_y)}")

    for draggable in (topbar, topbar_title, topbar_status):
        draggable.bind("<ButtonPress-1>", start_drag)
        draggable.bind("<B1-Motion>", do_drag)

    content = tkinter.Frame(card, bg=PANEL_BG_COLOR, padx=18, pady=18)
    content.pack(fill="both", expand=True)

    label = tkinter.Label(
        content,
        text=t("native.install.label", {"target": package_label}),
        font=(ui_font, 12, "bold"),
        bg=PANEL_BG_COLOR,
        fg=TEXT_PRIMARY_COLOR,
        anchor=direction["anchor"],
        justify=direction["justify"],
    )
    label.pack(anchor=direction["anchor"])

    progress_label = tkinter.Label(
        content,
        text=t("native.install.statusStarting"),
        font=(ui_font, 10),
        bg=PANEL_BG_COLOR,
        fg=TEXT_SECONDARY_COLOR,
        anchor=direction["anchor"],
        justify=direction["justify"],
    )
    progress_label.pack(anchor=direction["anchor"], pady=(8, 10))

    progress = ttk.Progressbar(
        content,
        mode="indeterminate",
        length=360,
        style=progress_style_name,
    )
    progress.pack(fill="x")
    progress.start(10)

    controls_row = tkinter.Frame(content, bg=PANEL_BG_COLOR)
    controls_row.pack(fill="x", pady=(14, 0))

    button_style = BUTTON_STYLE_MAP["default"]
    details_visible = False

    details_button = tkinter.Button(
        controls_row,
        text=t("native.install.showConsole"),
        command=lambda: toggle_details(),
        bg=button_style["bg"],
        fg=button_style["fg"],
        activebackground=button_style["active_bg"],
        activeforeground=button_style["fg"],
        highlightthickness=3,
        highlightbackground=button_style["border"],
        highlightcolor=FOCUS_COLOR,
        bd=0,
        relief="flat",
        padx=12,
        pady=6,
        cursor="hand2",
        takefocus=True,
        font=(ui_font, 10),
    )
    details_button.pack(anchor="center")
    details_button.bind(
        "<Return>", lambda _event: (details_button.invoke(), "break")[1]
    )
    details_button.bind(
        "<KP_Enter>", lambda _event: (details_button.invoke(), "break")[1]
    )
    details_button.bind(
        "<space>", lambda _event: (details_button.invoke(), "break")[1]
    )

    details_frame = tkinter.Frame(content, bg=PANEL_BG_COLOR)

    console_border = tkinter.Frame(
        details_frame, bg=PANEL_BORDER_COLOR, padx=1, pady=1
    )
    console_border.pack(fill="both", expand=True, pady=(12, 0))

    console_panel = tkinter.Frame(console_border, bg=TOPBAR_BG_COLOR)
    console_panel.pack(fill="both", expand=True)

    output_box = tkinter.Text(
        console_panel,
        height=10,
        width=60,
        font=("Consolas", 8),
        bg="#0b0b0b",
        fg=TEXT_PRIMARY_COLOR,
        insertbackground=TEXT_PRIMARY_COLOR,
        relief="flat",
        bd=0,
        highlightthickness=0,
        padx=10,
        pady=10,
        wrap="char",
        state="disabled",
    )
    output_box.pack(side="left", fill="both", expand=True)

    scrollbar = tkinter.Scrollbar(
        console_panel,
        command=output_box.yview,
        bg=TOPBAR_BG_COLOR,
        activebackground=TOPBAR_ACTIVE_COLOR,
        troughcolor=PANEL_BG_COLOR,
        highlightthickness=0,
        bd=0,
        relief="flat",
        width=12,
    )
    scrollbar.pack(side="right", fill="y")
    output_box.config(yscrollcommand=scrollbar.set)

    def toggle_details():
        nonlocal details_visible
        details_visible = not details_visible

        if details_visible:
            details_button.config(text=t("native.install.hideConsole"))
            details_frame.pack(fill="both", expand=True)
            root.geometry(f"{expanded_size[0]}x{expanded_size[1]}")
        else:
            details_button.config(text=t("native.install.showConsole"))
            details_frame.pack_forget()
            root.geometry(f"{collapsed_size[0]}x{collapsed_size[1]}")

    start_ui_dispatcher()
    threading.Thread(target=run_install, daemon=True).start()

    root.update_idletasks()
    center_dialog_window(root, owner if not owns_owner else None)
    root.deiconify()
    root.lift()
    try:
        root.wait_visibility()
    except Exception:
        pass
    try:
        root.grab_set()
    except Exception:
        pass
    try:
        root.focus_force()
        details_button.focus_force()
    except Exception:
        pass

    root.wait_window()
    if owns_owner:
        try:
            owner.destroy()
        except Exception:
            pass
    return result["success"]
