# launcher.py
import os
import random
import urllib.request
import urllib.error
import webbrowser
import sys
import time
import threading

# existing server start import (keep as-is)
from server.http_server import start_server

# tkinter for update prompt
import tkinter as tk
from tkinter import messagebox

GITHUB_RAW_VERSION_URL = "https://raw.githubusercontent.com/KerbalOfficial/Histolauncher/main/version.dat"
GITHUB_RELEASES_URL = "https://github.com/KerbalOfficial/Histolauncher/releases"

REMOTE_TIMEOUT = 5.0

def read_local_version(base_dir=None):
    try:
        if base_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base_dir, "version.dat")
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None

def fetch_remote_version(timeout=REMOTE_TIMEOUT):
    try:
        req = urllib.request.Request(GITHUB_RAW_VERSION_URL, headers={"User-Agent": "Histolauncher-Updater/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8").strip()
            return data
    except Exception as e:
        print(e)
        return None

def parse_version(ver):
    if not ver or len(ver) < 2:
        return None, None
    letter = ver[0]
    num_part = ver[1:]
    try:
        num = int(num_part)
        return letter, num
    except ValueError:
        return None, None

def should_prompt_update(local_ver, remote_ver):
    if not local_ver or not remote_ver:
        return False, "missing", local_ver, remote_ver

    l_letter, l_num = parse_version(local_ver)
    r_letter, r_num = parse_version(remote_ver)

    if l_letter is None or r_letter is None:
        return False, "parse_error", local_ver, remote_ver
    if l_letter != r_letter:
        return False, "letter_mismatch", local_ver, remote_ver
    if r_num > l_num:
        return True, "newer_available", local_ver, remote_ver

    return False, "up_to_date", local_ver, remote_ver

def prompt_user_update(local, remote):
    try:
        root = tk.Tk()
        root.withdraw()
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

def check_and_prompt_update():
    project_root = os.path.dirname(os.path.abspath(__file__))
    local = read_local_version(base_dir=project_root)
    remote = fetch_remote_version(timeout=REMOTE_TIMEOUT)
    prompt, reason, l, r = should_prompt_update(local, remote)

    if prompt:
        open_update = prompt_user_update(l, r)
        if open_update:
            try:
                webbrowser.open(GITHUB_RELEASES_URL, new=2)
            except Exception:
                pass
            return False
        else:
            return True
    return True

def set_console_visible(visible: bool):
    try:
        if sys.platform.startswith("win"):
            import ctypes
            whnd = ctypes.windll.kernel32.GetConsoleWindow()
            if whnd:
                SW_HIDE = 0
                SW_SHOW = 5
                ctypes.windll.user32.ShowWindow(whnd, SW_SHOW if visible else SW_HIDE)
    except Exception as e:
        print("An error has been encountered when attempting to change visibility of the debug window:", e)
        pass

try:
    import webview
    _HAS_WEBVIEW = True
except Exception:
    webview = None
    _HAS_WEBVIEW = False
    print("pywebview not available; will open the launcher in the default browser instead.")

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
        print("Opened launcher in default browser:", url)
    except Exception as e:
        print("Failed to open default browser! You MUST manually go to your browser and go to", url)


def open_with_webview(port, title="Histolauncher", width=900, height=520):
    url = f"http://127.0.0.1:{port}/"
    try:
        window = webview.create_window(title, url, width=width, height=height)
        print("Opened launcher in pywebview window:", url)
        print("------------------------------------------------")
        webview.start()
        return True
    except Exception as e:
        print("pywebview failed to open window.")
        print("------------------------------------------------")
        return False

def main():
    project_root = os.path.dirname(os.path.abspath(__file__))
    debug_flag_path = os.path.join(project_root, "__debug__")
    console_should_be_visible = os.path.exists(debug_flag_path)

    set_console_visible(console_should_be_visible)

    print("------------------------------------------------")

    try:
        print("Checking if launcher is up-to-date...")
        proceed = check_and_prompt_update()
        if proceed:
            print("Launcher is up-to-date! Initializing launcher...")
    except Exception:
        print("Something went wrong while checking if launcher is up-to-date, continuing launcher initializing...")
        proceed = True

    if not proceed:
        print("Exiting launcher...")
        return

    print("------------------------------------------------")

    port = random.randint(3000, 9000)
    server_thread = threading.Thread(target=start_server, args=(port,), daemon=True)
    server_thread.start()
    url = f"http://127.0.0.1:{port}/"

    if not wait_for_server(url, timeout=5.0):
        print("Server did not respond within timeout; something has failed! Exiting launcher...")
        return

    print("------------------------------------------------")

    if not _HAS_WEBVIEW or not open_with_webview(port):
        set_console_visible(True)
        open_in_browser(port)
        try:
            print("------------------------------------------------")
            print("[!!!] Press Enter (or Ctrl+C) to exit the launcher.")
            print("------------------------------------------------")
            input()
        except KeyboardInterrupt:
            print("Exiting...")
            return

if __name__ == "__main__":
    main()
