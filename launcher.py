# launcher.py

import os
import random
import urllib.request
import webbrowser
import subprocess
import sys
import time
import threading
import tkinter as tk

from datetime import datetime
from tkinter import ttk, messagebox

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
            print(f"[launcher] Console visibility error: {e}")

debug_flag_path = os.path.join(PROJECT_ROOT, "__debug__")
console_should_be_visible = os.path.exists(debug_flag_path)

set_console_visible(console_should_be_visible)

if not DATA_FILE_EXISTS:
    try:
        root = tk.Tk()
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

from server.http_server import start_server
from server.api_handler import read_local_version, fetch_remote_version
from core.settings import save_global_settings
from core.discord_rpc import start_discord_rpc, set_launcher_presence, set_launcher_version, stop_discord_rpc
from core.logger import colorize_log, dim_line

GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/KerbalOfficial/Histolauncher/releases/latest"
GITHUB_RELEASES_URL = "https://github.com/KerbalOfficial/Histolauncher/releases"

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

    root = tk.Tk()
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

    label = tk.Label(
        root,
        text=f"Installing component: {package}",
        font=("Segoe UI", 11, "bold"),
        bg=colors["bg"],
        fg=colors["fg"]
    )
    label.pack(pady=10)

    progress_label = tk.Label(
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

    details_frame = tk.Frame(root)
    details_visible = False

    output_box = tk.Text(
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
        return None, None
    letter = ver[0]
    num = ver[1:]
    return letter, num

def should_prompt_update(local_ver, remote_ver):
    if local_ver is None or remote_ver is None:
        return False, "missing"

    l_letter, l_num = parse_version(local_ver)
    r_letter, r_num = parse_version(remote_ver)

    if l_letter is None or r_letter is None:
        return False, "parse_error"
    if l_letter != r_letter:
        return False, "letter_mismatch"
    if r_num > l_num:
        return True, "newer_available"

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
        root = tk.Tk()
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
        root = tk.Tk()
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
        root = tk.Tk()
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
        root = tk.Tk()
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
        root = tk.Tk()
        try: root.iconbitmap(ICO_PATH)
        except: pass
        root.attributes('-topmost', True)
        root.withdraw()
        root.lift()
        msg = (
            "Your launcher is out-dated! Please press \"OK\" to open up the GitHub link for the latest version "
            "or press \"Cancel\" to continue using this version of the launcher.\n\n"
            f"(your version: {local}, latest version: {remote})"
        )
        result = messagebox.askokcancel("Launcher update available", msg)
        root.destroy()
        return bool(result)
    except Exception:
        return False

def prompt_beta_warning(local):
    try:
        root = tk.Tk()
        try: root.iconbitmap(ICO_PATH)
        except: pass
        root.attributes('-topmost', True)
        root.withdraw()
        root.lift()
        msg = (
            "This is a beta version of Histolauncher, you may encounter many bugs during testing "
            "so please keep that in mind. If you did encounter any problems or bugs, please report "
            "it to us in the GitHub as soon as possible!\n\n"
            f"(beta version: {local})"
        )
        messagebox.showwarning("Beta version warning", msg)
        root.destroy()
        return True
    except Exception:
        return False

def check_and_prompt():
    local = read_local_version(base_dir=PROJECT_ROOT)
    remote = fetch_remote_version(timeout=REMOTE_TIMEOUT)

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
    if not promptb and promptu:
        print(colorize_log("[launcher] PROMPTING USER UPDATE..."))
        open_update = prompt_user_update(local, remote)
        print(colorize_log(f"[launcher] prompt_user_update[user_accepted]: {open_update}"))
        if open_update:
            try: webbrowser.open(GITHUB_RELEASES_URL, new=2)
            except Exception: pass
            return False
    
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
    root = tk.Tk()
    try: root.iconbitmap(ICO_PATH)
    except: pass
    root.title("Histolauncher")
    colors = themed_colors(root)

    style = ttk.Style()
    try: style.theme_use("vista")
    except Exception: pass

    root.geometry("520x240")
    root.resizable(False, False)

    title = tk.Label(
        root,
        text="Histolauncher - Control Panel for Browser-users",
        font=("Segoe UI", 12, "bold"),
        bg=colors["bg"],
        fg=colors["fg"]
    )
    title.pack(pady=20)

    desc = tk.Label(
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
    set_launcher_presence("Starting launcher", "Checking prerequisites")

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
        print(colorize_log(f"[launcher] pywebview failed to load: {e}"))
        _HAS_WEBVIEW = False
        if prompt_install_pywebview():
            print(colorize_log("[launcher] User agreed to install pywebview."))
            success = install("pywebview")
            if success:
                try:
                    print(colorize_log("[launcher] Refreshing python packages..."))
                    import site
                    site.main()
                    user_site = site.getusersitepackages()
                    if user_site not in sys.path: sys.path.append(user_site)
                    import webview as wv
                    _HAS_WEBVIEW = True
                    print(colorize_log("[launcher] pywebview installed and imported successfully."))
                except Exception as import_err:
                    print(colorize_log(f"[launcher] pywebview installed but failed to import: {import_err}"))
                    print(colorize_log("[launcher] Falling back to browser mode."))
            else: print(colorize_log("[launcher] pywebview installation failed. Falling back to browser mode."))
        else: print(colorize_log("[launcher] User declined pywebview installation. Falling back to browser mode."))

    try:
        import cryptography
    except Exception as e:
        print(colorize_log(f"[launcher] cryptography failed to load: {e}"))
        if prompt_install_cryptography():
            print(colorize_log("[launcher] User agreed to install cryptography."))
            success = install("cryptography")
            if success:
                try:
                    print(colorize_log("[launcher] Refreshing python packages..."))
                    import site
                    site.main()
                    user_site = site.getusersitepackages()
                    if user_site not in sys.path: sys.path.append(user_site)
                    import cryptography
                    print("cryptography installed and imported successfully.")
                except Exception as import_err:
                    print("cryptography installed but failed to import:", import_err)
                    print("Custom skins will NOT load in 1.20.2 and above.")
            else: print("cryptography installation failed. Custom skins will NOT load in 1.20.2 and above.")
        else: print("User declined cryptography installation. Custom skins will NOT load in 1.20.2 and above.")

    try:
        import pypresence
    except Exception as e:
        print(colorize_log(f"[launcher] pypresence failed to load: {e}"))
        if prompt_install_pypresence():
            print(colorize_log("[launcher] User agreed to install pypresence."))
            success = install("pypresence")
            if success:
                try:
                    print(colorize_log("[launcher] Refreshing python packages..."))
                    import site
                    site.main()
                    user_site = site.getusersitepackages()
                    if user_site not in sys.path: sys.path.append(user_site)
                    import pypresence
                    print(colorize_log("[launcher] pypresence installed and imported successfully."))
                except Exception as import_err:
                    print(colorize_log(f"[launcher] pypresence installed but failed to import: {import_err}"))
                    print(colorize_log("[launcher] Discord Rich Presence will be disabled."))
            else: print(colorize_log("[launcher] pypresence installation failed. Discord Rich Presence will be disabled."))
        else: print(colorize_log("[launcher] User declined pypresence installation. Discord Rich Presence will be disabled."))

    print(dim_line("------------------------------------------------"))

    try:
        print("Checking information and prompting...")
        proceed = check_and_prompt()
        if proceed:
            print("Finished prompting! Initializing launcher...")
    except Exception as e:
        print("Something went wrong while checking and prompting:",e)
        proceed = True

    if not proceed:
        print("Exiting launcher...")
        stop_discord_rpc()
        return

    print(dim_line("------------------------------------------------"))

    port = random.randint(10000, 20000)

    try:
        from server import yggdrasil
        yggdrasil.ensure_signature_keys_ready()
    except Exception as e:
        print(f"Warning: could not pre-generate signature keys: {e}")

    try: save_global_settings({"ygg_port": str(port)})
    except Exception: pass

    os.environ["HISTOLAUNCHER_PORT"] = str(port)
    server_thread = threading.Thread(target=start_server, args=(port,), daemon=True)
    server_thread.start()
    url = f"http://127.0.0.1:{port}/"

    if not wait_for_server(url, timeout=5.0):
        print("Server did not respond within timeout; something has failed! Exiting launcher...")
        stop_discord_rpc()
        return

    print(dim_line("------------------------------------------------"))
    set_launcher_presence("Browsing launcher", "Idle in Histolauncher")


    if not _HAS_WEBVIEW or not open_with_webview(wv, port):
        open_in_browser(port)
        control_panel_fallback_window(port)
        stop_discord_rpc()
        return

    stop_discord_rpc()

if __name__ == "__main__":
    main()
