# launcher.py

import os
import random
import urllib.request
import webbrowser
import subprocess
import sys
import time
import threading
import tkinter
import json
import re
import shutil
import tempfile
import zipfile

from datetime       import datetime
from tkinter        import ttk, messagebox
from itertools      import zip_longest

from core.logger    import colorize_log, dim_line
from core.zip_utils import safe_extract_zip

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ICO_PATH = os.path.join(PROJECT_ROOT, "ui", "favicon.ico")

DATA_FILE_EXISTS = os.path.exists(os.path.join(os.path.expanduser("~"), ".histolauncher"))

def set_console_visible(visible: bool):
    try:
        if sys.platform.startswith("win"):
            import ctypes
            import uuid
            kernel32 = ctypes.windll.kernel32
            user32 = ctypes.windll.user32

            SW_SHOW = 5
            SW_HIDE = 0
            SW_RESTORE = 9
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080

            hwnd = 0
            original_title = ctypes.create_unicode_buffer(1024)
            kernel32.GetConsoleTitleW(original_title, 1024)

            temp_title = f"histolauncher-{uuid.uuid4()}"
            try:
                kernel32.SetConsoleTitleW(temp_title)
                time.sleep(0.05)
                hwnd = user32.FindWindowW("CASCADIA_HOSTING_WINDOW_CLASS", temp_title)
                if not hwnd:
                    hwnd = user32.FindWindowW(None, temp_title)
            finally:
                kernel32.SetConsoleTitleW(original_title.value)

            if not hwnd:
                hwnd = kernel32.GetConsoleWindow()

            if hwnd:
                if visible:
                    user32.ShowWindowAsync(hwnd, SW_RESTORE)
                    user32.ShowWindowAsync(hwnd, SW_SHOW)
                    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
                    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
                else:
                    user32.ShowWindowAsync(hwnd, SW_HIDE)
                    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    style = (style & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW
                    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    except Exception as e:
        try:
            print(colorize_log(f"[launcher] Console visibility error: {e}"))
        except Exception:
            print(colorize_log(f"[launcher] Console visibility error: {e}"))

debug_flag_path = os.path.join(PROJECT_ROOT, "__debug__")
console_should_be_visible = os.path.exists(debug_flag_path)

set_console_visible(console_should_be_visible)

if not DATA_FILE_EXISTS:
    try:
        root = tkinter.Tk()
        try: root.iconbitmap(ICO_PATH)
        except: pass
        root.attributes('-topmost', True)
        root.withdraw()
        root.lift()
        msg = (
            "DISCLAIMER: Histolauncher is a third-party Minecraft launcher and is not affiliated with, endorsed by, or associated with Mojang Studios or Microsoft.\n\n"
            "All Minecraft game files are downloaded directly from Mojang's official servers. Histolauncher does not host, modify, or redistribute any proprietary Minecraft files.\n\n"
            "By pressing OK, you acknowledge that you have read and agreed to the Minecraft EULA (https://www.minecraft.net/en-us/eula) and understood that Histolauncher is an independent project with no official connection to Mojang or Microsoft. If you do not agree, please press Cancel and do not use this launcher."
        )
        result = messagebox.askokcancel("Disclaimer", msg)
        root.destroy()
        if not result: sys.exit()
    except Exception: sys.exit()

from server.http_server     import start_server
from server.api_handler     import read_local_version
from core.settings          import save_global_settings
from core.discord_rpc       import start_discord_rpc, set_launcher_presence, set_launcher_version, stop_discord_rpc

GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/KerbalOfficial/Histolauncher/releases/latest"
GITHUB_RELEASES_URL = "https://github.com/KerbalOfficial/Histolauncher/releases"
GITHUB_API_RELEASES_URL = "https://api.github.com/repos/KerbalOfficial/Histolauncher/releases"

REMOTE_TIMEOUT = 5.0


class TeeOutput:
    def __init__(self, file_obj, original_stream):
        self.file_obj = file_obj
        self.original_stream = original_stream
    
    @staticmethod
    def _strip_ansi_codes(text):
        import re
        ansi_escape = re.compile(r'\033\[[0-9;]*m|\u001b\[[0-9;]*m')
        return ansi_escape.sub('', text)
    
    def write(self, message):
        clean_message = self._strip_ansi_codes(message)
        self.file_obj.write(clean_message)
        self.file_obj.flush()
        self.original_stream.write(message)
        self.original_stream.flush()
    
    def flush(self):
        self.file_obj.flush()
        self.original_stream.flush()
    
    def isatty(self):
        return self.original_stream.isatty()


def setup_launcher_logging():
    try:
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        
        base_dir = os.path.expanduser("~/.histolauncher")
        logs_dir = os.path.join(base_dir, "logs", "launcher")
        os.makedirs(logs_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_file = os.path.join(logs_dir, f"{timestamp}.log")
        
        log_handle = open(log_file, "w", buffering=1)
        
        timestamp_display = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_handle.write(f"{'='*60}\n")
        log_handle.write(f"Histolauncher started at {timestamp_display}\n")
        log_handle.write(f"{'='*60}\n\n")
        log_handle.flush()
        
        sys.stdout = TeeOutput(log_handle, original_stdout)
        sys.stderr = TeeOutput(log_handle, original_stderr)
        
        print(colorize_log(f"[launcher] Logging to: {log_file}"))
        return log_handle
    except Exception as e:
        print(colorize_log(f"[launcher] ERROR: Could not set up logging: {e}"))
        return None

def is_dark_mode():
    if sys.platform.startswith("win"):
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
        except Exception: return False
    return False

def themed_colors(root):
    if is_dark_mode():
        root.configure(bg="#111111")

        style = ttk.Style()
        style.theme_use("default")

        style.configure(".", background="#111111", foreground="white")
        style.configure("TLabel", background="#111111", foreground="white")
        style.configure("TButton", background="#2d2d2d", foreground="white")
        style.map("TButton", background=[("active", "#3a3a3a")])

        style.configure("TProgressbar", background="#0078d4", troughcolor="#2d2d2d")

        return {
            "bg": "#111111",
            "fg": "white",
        }
    else:
        return {
            "bg": None,
            "fg": None,
        }

def install(package):
    result = {"success": False}

    total_packages = 0
    completed_packages = 0

    PHASES = {
        "collecting": 0.1,
        "downloading": 0.4,
        "using cached": 0.6,
        "installing collected packages": 0.9,
        "successfully installed": 1.0
    }

    def detect_phase_fraction(line):
        l = line.lower()
        for key, frac in PHASES.items():
            if key in l: return frac
        return None

    def run_install():
        nonlocal total_packages, completed_packages
        try:
            process = subprocess.Popen(
                [sys.executable, "-m", "pip", "install", package],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            for line in process.stdout:
                output_box.insert("end", line)
                output_box.see("end")
                if line.lower().startswith("collecting "):
                    progress_label.config(text="Collecting packages..")
                    total_packages += 1
                phase_frac = detect_phase_fraction(line)
                if phase_frac is not None and total_packages > 0:
                    if "successfully installed" in line.lower():
                        progress_label.config(text="Installing packages...")
                        completed_packages += 1
                    progress.config(mode="determinate", maximum=100)
                    overall = ((completed_packages + phase_frac) / total_packages) * 100
                    progress.stop()
                    progress["value"] = overall
            process.wait()
            progress_label.config(text="Finished!")
            progress["value"] = 100
            result["success"] = (process.returncode == 0)
        except Exception as e:
            output_box.insert("end", f"\nError: {e}\n")
            result["success"] = False
        finally: root.after(300, root.destroy)

    root = tkinter.Tk()
    try: root.iconbitmap(ICO_PATH)
    except: pass
    root.title("Installing component...")
    root.geometry("600x180")
    root.resizable(False, False)
    root.focus_set()
    colors = themed_colors(root)

    root.protocol("WM_DELETE_WINDOW", lambda: None)

    style = ttk.Style()
    try: style.theme_use("vista")
    except Exception: pass

    label = tkinter.Label(
        root,
        text=f"Installing component: {package}",
        font=("Segoe UI", 11, "bold"),
        bg=colors["bg"],
        fg=colors["fg"]
    )
    label.pack(pady=10)

    progress_label = tkinter.Label(
        root,
        text="Starting...",
        font=("Segoe UI", 9),
        bg=colors["bg"],
        fg=colors["fg"]
    )
    progress_label.pack(pady=5)

    progress = ttk.Progressbar(root, mode="indeterminate", length=360)
    progress.pack(pady=5)
    progress.start(10)

    details_frame = tkinter.Frame(root)
    details_visible = False

    output_box = tkinter.Text(
        details_frame,
        height=10,
        width=60,
        font=("Consolas", 8),
        bg="black",
        fg="white",
        insertbackground="white"
    )
    output_box.pack(side="left", fill="both", expand=True)

    scrollbar = ttk.Scrollbar(details_frame, command=output_box.yview)
    scrollbar.pack(side="right", fill="y")
    output_box.config(yscrollcommand=scrollbar.set)

    def toggle_details():
        nonlocal details_visible
        details_visible = not details_visible

        if details_visible:
            details_button.config(text="Hide console ▲")
            root.geometry("600x370")
            details_frame.pack(fill="both", expand=True, pady=5)
        else:
            details_button.config(text="Show console ▼")
            details_frame.pack_forget()
            root.geometry("600x180")

    details_button = ttk.Button(root, text="Show console ▼", command=toggle_details)
    details_button.pack(pady=5)

    threading.Thread(target=run_install, daemon=True).start()

    root.update_idletasks()
    root.geometry(
        f"{root.winfo_width()}x{root.winfo_height()}+"
        f"{(root.winfo_screenwidth()-root.winfo_width())//2}+"
        f"{(root.winfo_screenheight()-root.winfo_height())//2}"
    )

    root.mainloop()
    return result["success"]

def parse_version(ver):
    if not ver:
        return None, tuple()

    s = str(ver).strip().lower()
    if s.startswith("v") and len(s) > 1:
        s = s[1:]

    letter = None
    if s and s[0].isalpha():
        letter = s[0]
        s = s[1:]

    nums = tuple(int(n) for n in re.findall(r"\d+", s))
    return letter, nums

def get_github_releases_url(owner="KerbalOfficial", repo="Histolauncher"):
    return f"https://api.github.com/repos/{owner}/{repo}/releases"

def fetch_github_releases(owner="KerbalOfficial", repo="Histolauncher", timeout=REMOTE_TIMEOUT):
    try:
        url = get_github_releases_url(owner, repo)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Histolauncher-Updater/1.0",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8")
        data = json.loads(payload)
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        print(colorize_log(f"[launcher] Error fetching GitHub releases: {e}"))
        return []

def separate_releases(releases):
    return {
        "stable": [r for r in releases if not r.get("prerelease")],
        "beta": [r for r in releases if r.get("prerelease")],
    }

def _compare_numeric_versions(local_nums, remote_nums):
    if not local_nums and not remote_nums:
        return 0
    for l_val, r_val in zip_longest(local_nums, remote_nums, fillvalue=0):
        if r_val > l_val:
            return 1
        if r_val < l_val:
            return -1
    return 0

def is_beta_version(ver):
    if not ver:
        return False
    letter, _ = parse_version(ver)
    if letter == "b":
        return True
    return "beta" in str(ver).lower()

def select_latest_release_for_local(local_ver, timeout=REMOTE_TIMEOUT):
    releases = fetch_github_releases(timeout=timeout)
    groups = separate_releases(releases)
    wants_beta = is_beta_version(local_ver)
    if wants_beta:
        if groups["beta"]:
            return groups["beta"][0], "beta"
        return None, "missing_beta_release"
    if groups["stable"]:
        return groups["stable"][0], "stable"
    return None, "missing_stable_release"

def _pick_release_zip_asset(release):
    for asset in release.get("assets", []):
        name = (asset.get("name") or "").lower()
        url = asset.get("browser_download_url")
        if name.endswith(".zip") and url:
            return {
                "name": asset.get("name") or "launcher_update.zip",
                "url": url,
            }

    zipball_url = release.get("zipball_url")
    if zipball_url:
        tag = release.get("tag_name") or "latest"
        return {
            "name": f"{tag}.zip",
            "url": zipball_url,
        }

    return None

def _sanitize_version_for_filename(ver):
    if not ver:
        return "unknown"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(ver))

def _strip_single_top_level_folder(path_names):
    roots = set()
    for name in path_names:
        normalized = name.replace("\\", "/").strip("/")
        if not normalized:
            continue
        parts = normalized.split("/")
        roots.add(parts[0])
    if len(roots) == 1:
        return next(iter(roots))
    return None

def _restore_backup_zip(backup_zip_path, project_root):
    with zipfile.ZipFile(backup_zip_path, "r") as zf:
        safe_extract_zip(zf, project_root)

def perform_self_update(release, current_version):
    result = {"success": False, "error": None}

    def ui_log(line):
        output_box.insert("end", line + "\n")
        output_box.see("end")

    def ui_progress(percent, label_text):
        progress_label.config(text=label_text)
        progress.config(mode="determinate", maximum=100)
        progress["value"] = max(0, min(100, percent))

    def worker():
        try:
            release_tag = release.get("tag_name") or release.get("name") or "latest"
            asset = _pick_release_zip_asset(release)
            if not asset:
                raise RuntimeError("No ZIP asset or zipball URL found for selected release.")

            current_ver_name = _sanitize_version_for_filename(current_version)
            backup_name = f"backup_histolauncher_{current_ver_name}.zip"
            backup_path = os.path.join(tempfile.gettempdir(), backup_name)
            download_name = f"histolauncher_update_{_sanitize_version_for_filename(release_tag)}.zip"
            download_path = os.path.join(tempfile.gettempdir(), download_name)

            root.after(0, lambda: ui_log(f"Selected release: {release_tag}"))
            root.after(0, lambda: ui_progress(2, "Creating backup..."))

            project_files = []
            for base, _, files in os.walk(PROJECT_ROOT):
                for file_name in files:
                    abs_path = os.path.join(base, file_name)
                    rel_path = os.path.relpath(abs_path, PROJECT_ROOT)
                    project_files.append((abs_path, rel_path))

            total_files = max(1, len(project_files))
            with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as backup_zip:
                for idx, (abs_path, rel_path) in enumerate(project_files, start=1):
                    backup_zip.write(abs_path, rel_path)
                    pct = 2 + int((idx / total_files) * 23)
                    root.after(0, lambda p=pct: ui_progress(p, f"Creating backup... {p}%"))

            root.after(0, lambda: ui_log(f"Backup saved: {backup_path}"))
            root.after(0, lambda: ui_progress(26, "Downloading update package..."))

            req = urllib.request.Request(
                asset["url"],
                headers={
                    "User-Agent": "Histolauncher-Updater/1.0",
                    "Accept": "application/octet-stream",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp, open(download_path, "wb") as out_f:
                total_bytes = resp.headers.get("Content-Length")
                total_bytes = int(total_bytes) if total_bytes and total_bytes.isdigit() else None
                downloaded = 0
                while True:
                    chunk = resp.read(1024 * 64)
                    if not chunk:
                        break
                    out_f.write(chunk)
                    downloaded += len(chunk)
                    if total_bytes and total_bytes > 0:
                        frac = min(1.0, downloaded / total_bytes)
                        pct = 26 + int(frac * 29)
                        root.after(0, lambda p=pct: ui_progress(p, f"Downloading update package... {p}%"))

            root.after(0, lambda: ui_log(f"Update package downloaded: {download_path}"))
            root.after(0, lambda: ui_progress(56, "Applying update..."))

            with zipfile.ZipFile(download_path, "r") as update_zip:
                members = [i for i in update_zip.infolist() if not i.is_dir()]
                member_names = [m.filename for m in members]
                top_level = _strip_single_top_level_folder(member_names)
                def _name_transform(name, _info):
                    rel_name = name
                    if top_level and rel_name.startswith(top_level + "/"):
                        rel_name = rel_name[len(top_level) + 1 :]
                    rel_name = rel_name.strip("/")
                    return rel_name or None

                def _progress_cb(done, total, _name, _info):
                    pct = 56 + int((done / max(1, total)) * 42)
                    root.after(0, lambda p=pct: ui_progress(p, f"Applying update... {p}%"))

                safe_extract_zip(
                    update_zip,
                    PROJECT_ROOT,
                    name_transform=_name_transform,
                    progress_cb=_progress_cb,
                )

            root.after(0, lambda: ui_progress(100, "Update complete."))
            root.after(0, lambda: ui_log("Update completed successfully."))
            result["success"] = True
        except Exception as e:
            result["error"] = str(e)
            root.after(0, lambda: ui_log(f"Update failed: {e}"))
            root.after(0, lambda: ui_log("Restoring from backup..."))
            try:
                current_ver_name = _sanitize_version_for_filename(current_version)
                backup_name = f"backup_histolauncher_{current_ver_name}.zip"
                backup_path = os.path.join(tempfile.gettempdir(), backup_name)
                if os.path.exists(backup_path):
                    _restore_backup_zip(backup_path, PROJECT_ROOT)
                    root.after(0, lambda: ui_log("Backup restored successfully."))
                else:
                    root.after(0, lambda: ui_log("Backup file was not found in %temp%."))
            except Exception as restore_err:
                root.after(0, lambda: ui_log(f"Backup restore failed: {restore_err}"))
        finally:
            root.after(900, root.destroy)

    root = tkinter.Tk()
    try: root.iconbitmap(ICO_PATH)
    except: pass
    root.title("Updating Histolauncher...")
    root.geometry("680x360")
    root.resizable(False, False)
    root.focus_set()
    colors = themed_colors(root)
    root.protocol("WM_DELETE_WINDOW", lambda: None)

    style = ttk.Style()
    try: style.theme_use("vista")
    except Exception: pass

    label = tkinter.Label(
        root,
        text="Updating Histolauncher",
        font=("Segoe UI", 11, "bold"),
        bg=colors["bg"],
        fg=colors["fg"],
    )
    label.pack(pady=10)

    progress_label = tkinter.Label(
        root,
        text="Starting updater...",
        font=("Segoe UI", 9),
        bg=colors["bg"],
        fg=colors["fg"],
    )
    progress_label.pack(pady=4)

    progress = ttk.Progressbar(root, mode="determinate", length=520, maximum=100)
    progress.pack(pady=5)
    progress["value"] = 0

    details_frame = tkinter.Frame(root)
    details_frame.pack(fill="both", expand=True, padx=10, pady=6)

    output_box = tkinter.Text(
        details_frame,
        height=12,
        width=90,
        font=("Consolas", 8),
        bg="black",
        fg="white",
        insertbackground="white",
    )
    output_box.pack(side="left", fill="both", expand=True)

    scrollbar = ttk.Scrollbar(details_frame, command=output_box.yview)
    scrollbar.pack(side="right", fill="y")
    output_box.config(yscrollcommand=scrollbar.set)

    threading.Thread(target=worker, daemon=True).start()

    root.update_idletasks()
    root.geometry(
        f"{root.winfo_width()}x{root.winfo_height()}+"
        f"{(root.winfo_screenwidth()-root.winfo_width())//2}+"
        f"{(root.winfo_screenheight()-root.winfo_height())//2}"
    )

    root.mainloop()
    return result

def should_prompt_update(local_ver, remote_ver):
    if local_ver is None or remote_ver is None:
        return False, "missing"

    l_letter, l_num = parse_version(local_ver)
    r_letter, r_num = parse_version(remote_ver)

    if not l_num or not r_num:
        return False, "parse_error"

    if l_letter is not None and r_letter is not None and l_letter != r_letter:
        return False, "letter_mismatch"

    cmp_result = _compare_numeric_versions(l_num, r_num)
    if cmp_result > 0:
        return True, "newer_available"
    if cmp_result == 0 and str(remote_ver).strip() > str(local_ver).strip():
        return True, "newer_available_lexical"

    return False, "up_to_date"

def should_prompt_beta_warning(local_ver):
    if local_ver is None:
        return False, "missing"

    l_letter, l_num = parse_version(local_ver)

    if l_letter is None:
        return False, "parse_error"
    if l_letter == "b":
        return True, "beta_version"

    return False, "other_version"

def prompt_install_pywebview():
    try:
        root = tkinter.Tk()
        try: root.iconbitmap(ICO_PATH)
        except: pass
        root.attributes('-topmost', True)
        root.withdraw()
        root.lift()
        msg = (
            "Histolauncher can display its interface inside a built-in window, "
            "but this feature requires an additional component that is not currently installed in your system.\n\n"
            "Would you like to install this component (pywebview) automatically?\n\n"
            "If you choose Cancel, the launcher will open in your default web browser instead."
        )
        result = messagebox.askokcancel("Install additional component? (pywebview)", msg)
        root.destroy()
        return bool(result)
    except Exception:
        return False
    
def prompt_install_cryptography():
    try:
        root = tkinter.Tk()
        try: root.iconbitmap(ICO_PATH)
        except: pass
        root.attributes('-topmost', True)
        root.withdraw()
        root.lift()
        msg = (
            "Histolauncher can load its custom Histolauncher skins for Minecraft 1.20.2 and above, "
            "but this feature requires an additional component that is not currently installed in your system.\n\n"
            "Would you like to install this component (cryptography) automatically?\n\n"
            "If you choose Cancel, then custom Histolauncher skins won't load for Minecraft 1.20.2 and above."
        )
        result = messagebox.askokcancel("Install additional component? (cryptography)", msg)
        root.destroy()
        return bool(result)
    except Exception:
        return False

def prompt_install_pypresence():
    try:
        root = tkinter.Tk()
        try: root.iconbitmap(ICO_PATH)
        except: pass
        root.attributes('-topmost', True)
        root.withdraw()
        root.lift()
        msg = (
            "Histolauncher can display your current activity on Discord via Rich Presence, "
            "but this feature requires an additional component that is not currently installed in your system.\n\n"
            "Would you like to install this component (pypresence) automatically?\n\n"
            "If you choose Cancel, Discord Rich Presence will be disabled."
        )
        result = messagebox.askokcancel("Install additional component? (pypresence)", msg)
        root.destroy()
        return bool(result)
    except Exception:
        return False

def prompt_new_user():
    try:
        root = tkinter.Tk()
        try: root.iconbitmap(ICO_PATH)
        except: pass
        root.attributes('-topmost', True)
        root.withdraw()
        root.lift()
        msg = (
            "Hi there, new user! Welcome to Histolauncher!\n\n"
            "Would you like to read INSTRUCTIONS.txt for more information about this launcher "
            "and how to enable special features (such as debug mode)?"
        )
        result = messagebox.askokcancel("Welcome!", msg)
        root.destroy()
        return bool(result)
    except Exception:
        return False

def prompt_user_update(local, remote):
    try:
        root = tkinter.Tk()
        try: root.iconbitmap(ICO_PATH)
        except: pass
        root.attributes('-topmost', True)
        root.withdraw()
        root.lift()
        msg = (
            "Histolauncher is out-dated!\n\n"
            "Would you like to automatically download the latest version now? "
            "Be aware that this will delete everything inside the launcher directory "
            "and will reinstall everything freshly from the Histolauncher GitHub repository.\n\n"
            f"(your version: {local}, latest version: {remote})"
        )
        result = messagebox.askyesno("Launcher update available", msg)
        root.destroy()
        return bool(result)
    except Exception:
        return False

def prompt_beta_warning(local):
    try:
        root = tkinter.Tk()
        try: root.iconbitmap(ICO_PATH)
        except: pass
        root.attributes('-topmost', True)
        root.withdraw()
        root.lift()
        msg = (
            "This is a beta version of Histolauncher, you may encounter many bugs during usage "
            "so please keep that in mind. If you did encounter any problems or bugs, please report "
            "it to us in the GitHub/Discord as soon as possible!\n\n"
            f"(beta version: {local})"
        )
        messagebox.showwarning("Beta version warning", msg)
        root.destroy()
        return True
    except Exception:
        return False

def check_and_prompt():
    local = read_local_version(base_dir=PROJECT_ROOT)
    release_info, release_reason = select_latest_release_for_local(local, timeout=REMOTE_TIMEOUT)
    remote = (release_info or {}).get("tag_name")

    print(colorize_log("[launcher] should_prompt_new_user[prompt]: " + str(not DATA_FILE_EXISTS)))
    if not DATA_FILE_EXISTS:
        print(colorize_log("[launcher] PROMPTING NEW USER..."))
        open_instructions = prompt_new_user()
        print(colorize_log(f"[launcher] prompt_user_update[user_accepted]: {open_instructions}"))
        if open_instructions:
            try: subprocess.Popen(["notepad", os.path.join(PROJECT_ROOT, "INSTRUCTIONS.txt")])
            except Exception: pass
    
    promptb, reasonb = should_prompt_beta_warning(local)
    print(colorize_log(f"[launcher] should_prompt_beta_warning[prompt]: {promptb}"))
    print(colorize_log(f"[launcher] should_prompt_beta_warning[reason]: {reasonb}"))
    if promptb:
        print(colorize_log("[launcher] PROMPTING BETA WARNING..."))
        prompt_beta_warning(local)

    promptu, reasonu = should_prompt_update(local, remote)
    print(colorize_log(f"[launcher] should_prompt_update[prompt]: {promptu}"))
    print(colorize_log(f"[launcher] should_prompt_update[reason]: {reasonu}"))
    if not release_info:
        print(colorize_log(f"[launcher] No release candidate found for updater: {release_reason}"))
    if promptu and release_info:
        print(colorize_log("[launcher] PROMPTING USER UPDATE..."))
        open_update = prompt_user_update(local, remote)
        print(colorize_log(f"[launcher] prompt_user_update[user_accepted]: {open_update}"))
        if open_update:
            update_result = perform_self_update(release_info, local)
            if update_result.get("success"):
                try:
                    root = tkinter.Tk()
                    try: root.iconbitmap(ICO_PATH)
                    except: pass
                    root.attributes('-topmost', True)
                    root.withdraw()
                    root.lift()
                    messagebox.showinfo(
                        "Update installed",
                        "Histolauncher has been updated and will now restart.",
                    )
                    root.destroy()
                except Exception:
                    pass
                
                try:
                    launcher_script = os.path.join(PROJECT_ROOT, "launcher.py")
                    subprocess.Popen([sys.executable, launcher_script])
                except Exception as e:
                    print(colorize_log(f"[launcher] Failed to relaunch launcher: {e}"))
                
                return False

            print(colorize_log(f"[launcher] Self-update failed: {update_result.get('error')}"))
            try:
                root = tkinter.Tk()
                try: root.iconbitmap(ICO_PATH)
                except: pass
                root.attributes('-topmost', True)
                root.withdraw()
                root.lift()
                messagebox.showerror(
                    "Update failed",
                    "The update failed and Histolauncher attempted to restore from backup. Check logs for details.",
                )
                root.destroy()
            except Exception:
                pass
    
    return True

def wait_for_server(url, timeout=5.0, poll_interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as resp:
                if resp.status in (200, 301, 302, 304):
                    return True
        except Exception:
            time.sleep(poll_interval)
    return False

def open_in_browser(port):
    url = f"http://127.0.0.1:{port}/"
    try:
        webbrowser.open_new_tab(url)
        print(colorize_log(f"[launcher] Opened launcher in default browser: {url}"))
    except Exception as e:
        print(colorize_log(f"[launcher] Failed to open default browser! ({e}) You MUST manually go to your browser and enter this link: {url}"))

def open_with_webview(webview, port, title="Histolauncher", width=900, height=520):
    url = f"http://127.0.0.1:{port}/"
    try:
        webview.create_window(title, url, width=width, height=height)
        print(colorize_log(f"[launcher] Opened launcher in pywebview window: {url}"))
        print(dim_line("------------------------------------------------"))
        webview.start()
        return True
    except Exception as e:
        print(colorize_log(f"[launcher] pywebview failed to open window: {e}"))
        print(dim_line("------------------------------------------------"))
        return False

def control_panel_fallback_window(port):
    root = tkinter.Tk()
    try: root.iconbitmap(ICO_PATH)
    except: pass
    root.title("Histolauncher")
    colors = themed_colors(root)

    style = ttk.Style()
    try: style.theme_use("vista")
    except Exception: pass

    root.geometry("520x240")
    root.resizable(False, False)

    title = tkinter.Label(
        root,
        text="Histolauncher - Control Panel for Browser-users",
        font=("Segoe UI", 12, "bold"),
        bg=colors["bg"],
        fg=colors["fg"]
    )
    title.pack(pady=20)

    desc = tkinter.Label(
        root,
        text="This is the control panel for browser-users.\n\nClick 'Open Launcher' to open the launcher's web link onto your default browser.\nClick 'Close Launcher' to close the web server and exit Histolauncher.",
        font=("Segoe UI", 9),
        bg=colors["bg"],
        fg=colors["fg"]
    )
    desc.pack(pady=10)

    open_btn = ttk.Button(root, text="Open Launcher", command=lambda: open_in_browser(port))
    open_btn.pack(pady=5)

    close_btn = ttk.Button(root, text="Close Launcher", command=root.destroy)
    close_btn.pack(pady=5)

    root.mainloop()

def main():
    setup_launcher_logging()

    set_launcher_version(read_local_version(base_dir=PROJECT_ROOT))
    start_discord_rpc()
    set_launcher_presence("Starting launcher")

    try:
        from core.settings import get_base_dir
        import shutil
        cache_dir = os.path.join(get_base_dir(), "cache")
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
            print(colorize_log(f"[startup] Cleared cache directory: {cache_dir}"))
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: could not clear cache directory: {e}"))

    try:
        from core.downloader import cleanup_orphaned_progress_files
        cleanup_orphaned_progress_files(max_age_seconds=3600)
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: could not cleanup orphaned progress files: {e}"))

    try:
        import webview as wv
        _HAS_WEBVIEW = True
    except Exception as e:
        print(colorize_log(f"[installation] pywebview failed to load: {e}"))
        _HAS_WEBVIEW = False
        if prompt_install_pywebview():
            print(colorize_log("[installation] User agreed to install pywebview."))
            success = install("pywebview")
            if success:
                try:
                    print(colorize_log("[installation] Refreshing python packages..."))
                    import site
                    site.main()
                    user_site = site.getusersitepackages()
                    if user_site not in sys.path: sys.path.append(user_site)
                    import webview as wv
                    _HAS_WEBVIEW = True
                    print(colorize_log("[installation] pywebview installed and imported successfully."))
                except Exception as import_err:
                    print(colorize_log(f"[installation] pywebview installed but failed to import: {import_err}"))
                    print(colorize_log("[installation] Falling back to browser mode."))
            else: print(colorize_log("[installation] pywebview installation failed. Falling back to browser mode."))
        else: print(colorize_log("[installation] User declined pywebview installation. Falling back to browser mode."))

    try:
        import cryptography
    except Exception as e:
        print(colorize_log(f"[installation] cryptography failed to load: {e}"))
        if prompt_install_cryptography():
            print(colorize_log("[installation] User agreed to install cryptography."))
            success = install("cryptography")
            if success:
                try:
                    print(colorize_log("[installation] Refreshing python packages..."))
                    import site
                    site.main()
                    user_site = site.getusersitepackages()
                    if user_site not in sys.path: sys.path.append(user_site)
                    import cryptography
                    print(colorize_log("[installation] cryptography installed and imported successfully."))
                except Exception as import_err:
                    print(colorize_log(f"[installation] cryptography installed but failed to import: {import_err}"))
                    print(colorize_log("[installation] Custom skins will NOT load in 1.20.2 and above."))
            else: print(colorize_log("[installation] cryptography installation failed. Custom skins will NOT load in 1.20.2 and above."))
        else: print(colorize_log("[installation] User declined cryptography installation. Custom skins will NOT load in 1.20.2 and above."))

    try:
        import pypresence
    except Exception as e:
        print(colorize_log(f"[installation] pypresence failed to load: {e}"))
        if prompt_install_pypresence():
            print(colorize_log("[installation] User agreed to install pypresence."))
            success = install("pypresence")
            if success:
                try:
                    print(colorize_log("[installation] Refreshing python packages..."))
                    import site
                    site.main()
                    user_site = site.getusersitepackages()
                    if user_site not in sys.path: sys.path.append(user_site)
                    import pypresence
                    print(colorize_log("[installation] pypresence installed and imported successfully."))
                except Exception as import_err:
                    print(colorize_log(f"[installation] pypresence installed but failed to import: {import_err}"))
                    print(colorize_log("[installation] Discord Rich Presence will be disabled."))
            else: print(colorize_log("[installation] pypresence installation failed. Discord Rich Presence will be disabled."))
        else: print(colorize_log("[installation] User declined pypresence installation. Discord Rich Presence will be disabled."))

    print(dim_line("------------------------------------------------"))

    try:
        print(colorize_log("Checking information and prompting..."))
        proceed = check_and_prompt()
        if proceed:
            print(colorize_log("Finished prompting! Initializing launcher..."))
    except Exception as e:
        print(colorize_log(f"Something went wrong while checking and prompting: {e}"))
        proceed = True

    if not proceed:
        print(colorize_log("[launcher] Exiting launcher..."))
        stop_discord_rpc()
        return

    print(dim_line("------------------------------------------------"))

    port = random.randint(10000, 20000)



    try: save_global_settings({"ygg_port": str(port)})
    except Exception: pass

    os.environ["HISTOLAUNCHER_PORT"] = str(port)
    server_thread = threading.Thread(target=start_server, args=(port,), daemon=True)
    server_thread.start()
    url = f"http://127.0.0.1:{port}/"

    if not wait_for_server(url, timeout=5.0):
        print(colorize_log("[launcher] Server did not respond within timeout; something has failed! Exiting launcher..."))
        stop_discord_rpc()
        return

    print(dim_line("------------------------------------------------"))
    set_launcher_presence("Browsing launcher")


    if not _HAS_WEBVIEW or not open_with_webview(wv, port):
        open_in_browser(port)
        control_panel_fallback_window(port)
        stop_discord_rpc()
        return

    stop_discord_rpc()

if __name__ == "__main__":
    main()
