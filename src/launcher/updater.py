from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import tkinter
import urllib.request
import zipfile
from itertools import zip_longest
from tkinter import ttk

from core.logger import colorize_log
from core.settings import _apply_url_proxy
from core.zip_utils import safe_extract_zip

from launcher._constants import ICO_PATH, PROJECT_ROOT, REMOTE_TIMEOUT
from launcher.dispatcher import create_tk_ui_dispatcher
from launcher.theme import themed_colors


__all__ = [
    "parse_version",
    "get_github_releases_url",
    "fetch_github_releases",
    "separate_releases",
    "is_beta_version",
    "select_latest_release_for_local",
    "perform_self_update",
    "should_prompt_update",
    "should_prompt_beta_warning",
]


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


def _iter_request_urls(url):
    try:
        proxied = _apply_url_proxy(url)
    except Exception:
        proxied = url

    out = []
    if proxied:
        out.append(proxied)
    if url not in out:
        out.append(url)

    return out


def fetch_github_releases(
    owner="KerbalOfficial", repo="Histolauncher", timeout=REMOTE_TIMEOUT
):
    try:
        url = get_github_releases_url(owner, repo)
        for candidate_url in _iter_request_urls(url):
            try:
                req = urllib.request.Request(
                    candidate_url,
                    headers={
                        "User-Agent": "Histolauncher/1.0",
                        "Accept": "application/vnd.github+json",
                    },
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = resp.read().decode("utf-8")
                data = json.loads(payload)
                if isinstance(data, list):
                    return data
            except Exception:
                continue
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
        return {"name": f"{tag}.zip", "url": zipball_url}

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


def _clear_project_root(project_root):
    root_real = os.path.realpath(project_root)
    for entry_name in os.listdir(project_root):
        entry_path = os.path.join(project_root, entry_name)
        entry_real = os.path.realpath(entry_path)
        if os.path.commonpath([root_real, entry_real]) != root_real:
            continue
        if os.path.isdir(entry_path) and not os.path.islink(entry_path):
            shutil.rmtree(entry_path)
        else:
            os.remove(entry_path)


def perform_self_update(release, current_version):
    result = {"success": False, "error": None}
    root = tkinter.Tk()
    queue_ui, start_ui_dispatcher, stop_ui_dispatcher = create_tk_ui_dispatcher(root)

    def ui_log(line):
        output_box.insert("end", line + "\n")
        output_box.see("end")

    def ui_progress(percent, label_text):
        progress_label.config(text=label_text)
        progress.config(mode="determinate", maximum=100)
        progress["value"] = max(0, min(100, percent))

    def close_window():
        stop_ui_dispatcher()
        try:
            root.destroy()
        except Exception:
            pass

    def worker():
        try:
            release_tag = (
                release.get("tag_name") or release.get("name") or "latest"
            )
            asset = _pick_release_zip_asset(release)
            if not asset:
                raise RuntimeError(
                    "No ZIP asset or zipball URL found for selected release."
                )

            current_ver_name = _sanitize_version_for_filename(current_version)
            backup_name = f"backup_histolauncher_{current_ver_name}.zip"
            backup_path = os.path.join(tempfile.gettempdir(), backup_name)
            download_name = (
                f"histolauncher_update_"
                f"{_sanitize_version_for_filename(release_tag)}.zip"
            )
            download_path = os.path.join(tempfile.gettempdir(), download_name)

            queue_ui(lambda: ui_log(f"Selected release: {release_tag}"))
            queue_ui(lambda: ui_progress(2, "Creating backup..."))

            project_files = []
            for base, _, files in os.walk(PROJECT_ROOT):
                for file_name in files:
                    abs_path = os.path.join(base, file_name)
                    rel_path = os.path.relpath(abs_path, PROJECT_ROOT)
                    project_files.append((abs_path, rel_path))

            total_files = max(1, len(project_files))
            with zipfile.ZipFile(
                backup_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as backup_zip:
                for idx, (abs_path, rel_path) in enumerate(project_files, start=1):
                    backup_zip.write(abs_path, rel_path)
                    pct = 2 + int((idx / total_files) * 23)
                    queue_ui(
                        lambda p=pct: ui_progress(
                            p, f"Creating backup... {p}%"
                        )
                    )

            queue_ui(lambda: ui_log(f"Backup saved: {backup_path}"))
            queue_ui(lambda: ui_progress(26, "Downloading update package..."))

            last_download_error = None
            for candidate_url in _iter_request_urls(asset["url"]):
                try:
                    req = urllib.request.Request(
                        candidate_url,
                        headers={
                            "User-Agent": "Histolauncher/1.0",
                            "Accept": "application/octet-stream",
                        },
                    )
                    with urllib.request.urlopen(
                        req, timeout=60
                    ) as resp, open(download_path, "wb") as out_f:
                        total_bytes = resp.headers.get("Content-Length")
                        total_bytes = (
                            int(total_bytes)
                            if total_bytes and total_bytes.isdigit()
                            else None
                        )
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
                                queue_ui(
                                    lambda p=pct: ui_progress(
                                        p,
                                        f"Downloading update package... {p}%",
                                    )
                                )
                    last_download_error = None
                    break
                except Exception as e:
                    last_download_error = e
                    continue

            if last_download_error is not None:
                raise last_download_error

            queue_ui(lambda: ui_log(f"Update package downloaded: {download_path}"))
            queue_ui(lambda: ui_progress(56, "Clearing old launcher files..."))
            _clear_project_root(PROJECT_ROOT)
            queue_ui(lambda: ui_progress(60, "Applying update..."))

            with zipfile.ZipFile(download_path, "r") as update_zip:
                members = [i for i in update_zip.infolist() if not i.is_dir()]
                member_names = [m.filename for m in members]
                top_level = _strip_single_top_level_folder(member_names)

                def _name_transform(name, _info):
                    rel_name = name
                    if top_level and rel_name.startswith(top_level + "/"):
                        rel_name = rel_name[len(top_level) + 1:]
                    rel_name = rel_name.strip("/")
                    return rel_name or None

                def _progress_cb(done, total, _name, _info):
                    pct = 60 + int((done / max(1, total)) * 38)
                    queue_ui(
                        lambda p=pct: ui_progress(
                            p, f"Applying update... {p}%"
                        )
                    )

                safe_extract_zip(
                    update_zip,
                    PROJECT_ROOT,
                    name_transform=_name_transform,
                    progress_cb=_progress_cb,
                )

            queue_ui(lambda: ui_progress(100, "Update complete."))
            queue_ui(lambda: ui_log("Update completed successfully."))
            result["success"] = True
        except Exception as e:
            result["error"] = str(e)
            queue_ui(lambda err=e: ui_log(f"Update failed: {err}"))
            queue_ui(lambda: ui_log("Restoring from backup..."))
            try:
                current_ver_name = _sanitize_version_for_filename(current_version)
                backup_name = f"backup_histolauncher_{current_ver_name}.zip"
                backup_path = os.path.join(tempfile.gettempdir(), backup_name)
                if os.path.exists(backup_path):
                    try:
                        _clear_project_root(PROJECT_ROOT)
                    except Exception as clear_err:
                        queue_ui(lambda err=clear_err: ui_log(f"Could not clear partial update before restore: {err}"))
                    _restore_backup_zip(backup_path, PROJECT_ROOT)
                    queue_ui(lambda: ui_log("Backup restored successfully."))
                else:
                    queue_ui(lambda: ui_log("Backup file was not found in %temp%."))
            except Exception as restore_err:
                queue_ui(
                    lambda err=restore_err: ui_log(
                        f"Backup restore failed: {err}"
                    )
                )
        finally:
            queue_ui(lambda: root.after(900, close_window))

    try:
        root.iconbitmap(ICO_PATH)
    except Exception:
        pass
    root.title("Updating Histolauncher...")
    root.geometry("680x360")
    root.resizable(False, False)
    root.focus_set()
    colors = themed_colors(root)
    root.protocol("WM_DELETE_WINDOW", lambda: None)

    style = ttk.Style()
    try:
        style.theme_use("vista")
    except Exception:
        pass

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

    start_ui_dispatcher()
    threading.Thread(target=worker, daemon=True).start()

    root.update_idletasks()
    root.geometry(
        f"{root.winfo_width()}x{root.winfo_height()}+"
        f"{(root.winfo_screenwidth() - root.winfo_width()) // 2}+"
        f"{(root.winfo_screenheight() - root.winfo_height()) // 2}"
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

    if (
        l_letter is not None
        and r_letter is not None
        and l_letter != r_letter
    ):
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
