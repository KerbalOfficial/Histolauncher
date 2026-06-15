from __future__ import annotations

import os
import subprocess
import sys

from launcher.cli.commands import Command, register
from launcher.cli.dialogs import confirm
from launcher.cli.scopes import scope_override
from launcher.cli.state import CliState
from launcher.cli.terminal import (
    FG, c, print_error, print_hint, print_info, print_section, print_success,
    print_table, writeln,
)


def _fmt_epoch_ms(value) -> str:
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return "-"
    if ms <= 0:
        return "-"
    import datetime

    if ms > 1e12:
        ms /= 1000.0
    try:
        return datetime.datetime.fromtimestamp(ms).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return "-"


def _fmt_size(value) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "-"
    if size <= 0:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


def _open_path(path: str) -> bool:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform.startswith("darwin"):
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


def _cmd_open_data_folder(state: CliState, args: list[str]) -> None:
    try:
        from core.settings import get_base_dir

        path = get_base_dir()
    except Exception as exc:
        print_error(f"Could not resolve data folder: {exc}")
        return
    writeln("  " + c(path, FG["accent"]))
    if _open_path(path):
        print_success("Opened in your file manager.")
    else:
        print_info("(Couldn't auto-open; the path above is your data folder.)")


def _cmd_list_java(state: CliState, args: list[str]) -> None:
    from server.api.routes.java import api_java_runtimes

    result = api_java_runtimes() or {}
    runtimes = result.get("runtimes") or []
    if not runtimes:
        print_info("No Java runtimes detected. Use 'install-java' to download one.")
        return
    rows = []
    for r in runtimes:
        if not isinstance(r, dict):
            continue
        rows.append((
            str(r.get("version") or r.get("major") or "?"),
            str(r.get("vendor") or "")[:18],
            str(r.get("path") or "")[:60],
        ))
    print_section("Detected Java runtimes")
    print_table(("Version", "Vendor", "Path"), rows)


def _cmd_install_java(state: CliState, args: list[str]) -> None:
    from server.api.routes.java import api_java_download, api_java_install_options

    response = api_java_install_options() or {}
    options = response.get("options") or []
    if not options:
        print_error(response.get("error") or "No installable Java options reported by the backend.")
        return
    if not args:
        print_section("Installable Java options")
        rows = [
            (
                str(o.get("version") or ""),
                str(o.get("label") or "") + (" (recommended)" if o.get("recommended") else ""),
                str(o.get("description") or ""),
            )
            for o in options if isinstance(o, dict)
        ]
        print_table(("Version", "Name", "Notes"), rows)
        print_hint("Run 'install-java <version>' to install one.")
        return
    target = args[0].strip()
    known = {str(o.get("version")) for o in options if isinstance(o, dict)}
    if target not in known:
        print_error(f"Unknown Java version: {target}")
        print_hint("Run 'install-java' with no argument to list installable versions.")
        return
    print_info(f"Downloading Java {target}...")
    result = api_java_download({"version": target}) or {}
    if not result.get("ok"):
        print_error(result.get("error") or "Java install failed.")
        return
    if result.get("installed"):
        print_success(f"Java {target} installed to {result.get('install_dir') or result.get('runtime_path')}.")
    elif result.get("opened"):
        print_success(f"Java {target} installer downloaded and opened — follow its prompts to finish.")
    else:
        print_success(f"Java {target} installer downloaded to {result.get('path')}.")
        detail = str(result.get("open_error") or "").strip()
        if detail:
            print_hint(f"Could not open it automatically: {detail}")


def _cmd_list_worlds(state: CliState, args: list[str]) -> None:
    from server.api.routes.worlds import api_worlds_installed

    with scope_override(state, "versions"):
        result = api_worlds_installed() or {}
    worlds = result.get("worlds") or []
    if not worlds:
        print_info("No worlds found.")
        return
    rows = []
    for w in worlds[:50]:
        if not isinstance(w, dict):
            continue
        rows.append((
            str(w.get("title") or w.get("display_name") or w.get("world_id") or "")[:32],
            str(w.get("version_name") or w.get("minecraft_version") or "")[:18],
            str(w.get("game_mode") or "")[:10],
            _fmt_epoch_ms(w.get("last_played") or w.get("modified_at")),
        ))
    print_section(f"Worlds ({len(worlds)} total)")
    print_table(("Name", "Version", "Mode", "Last played"), rows)


def _cmd_list_screenshots(state: CliState, args: list[str]) -> None:
    from server.api.routes.screenshots import api_screenshots_installed

    with scope_override(state, "versions"):
        result = api_screenshots_installed() or {}
    shots = result.get("screenshots") or []
    if not shots:
        print_info("No screenshots found.")
        return
    rows = []
    for s in shots[:50]:
        if not isinstance(s, dict):
            continue
        rows.append((
            str(s.get("file_name") or s.get("title") or s.get("relative_path") or "")[:34],
            str(s.get("storage_label") or "")[:14],
            _fmt_size(s.get("size_bytes")),
            _fmt_epoch_ms(s.get("modified_at") or s.get("created_at")),
        ))
    print_section(f"Screenshots ({len(shots)} total)")
    print_table(("File", "Storage", "Size", "Modified"), rows)


def _resolve_world(state: CliState, ident: str):
    from server.api.routes.worlds import api_worlds_installed

    with scope_override(state, "versions"):
        result = api_worlds_installed() or {}
    ident_l = ident.strip().lower()
    for w in result.get("worlds") or []:
        if not isinstance(w, dict):
            continue
        wid = str(w.get("world_id") or "")
        name = str(w.get("title") or w.get("name") or w.get("folder") or "")
        if ident_l in (wid.lower(), name.lower()):
            return w
    return None


def _world_storage(world: dict) -> str:
    return str(world.get("storage_target") or "default")


def _cmd_delete_world(state: CliState, args: list[str]) -> None:
    if not args:
        print_error("Usage: delete-world <world name or id>")
        return
    ident = " ".join(args).strip()
    world = _resolve_world(state, ident)
    if not world:
        print_error(f"World '{ident}' not found. Run 'list-worlds' to see worlds.")
        return
    wid = str(world.get("world_id") or "")
    name = str(world.get("title") or world.get("name") or wid)
    if not confirm("Delete world",
                   f"Permanently delete world '{name}'?\nThis cannot be undone.",
                   yes_label="Delete", no_label="Keep", default_yes=False, kind="warn"):
        print_info("Cancelled.")
        return
    from server.api.routes.worlds import api_worlds_delete

    with scope_override(state, "versions"):
        result = api_worlds_delete({"world_id": wid, "storage_target": _world_storage(world)}) or {}
    if not result.get("ok"):
        print_error(result.get("error") or "Delete failed.")
        return
    print_success(f"Deleted world '{name}'.")


def _cmd_open_world(state: CliState, args: list[str]) -> None:
    if not args:
        print_error("Usage: open-world <world name or id>")
        return
    ident = " ".join(args).strip()
    world = _resolve_world(state, ident)
    if not world:
        print_error(f"World '{ident}' not found. Run 'list-worlds' to see worlds.")
        return
    wid = str(world.get("world_id") or "")
    name = str(world.get("title") or world.get("name") or wid)
    from server.api.routes.worlds import api_worlds_open

    with scope_override(state, "versions"):
        result = api_worlds_open({"world_id": wid, "storage_target": _world_storage(world)}) or {}
    if not result.get("ok"):
        print_error(result.get("error") or "Could not open the world folder.")
        return
    print_success(f"Opened the folder for '{name}' in your file manager.")


def _resolve_export_dest(dest: str, filename: str) -> str:
    if not dest:
        out_dir = os.path.expanduser("~/Downloads")
        if not os.path.isdir(out_dir):
            out_dir = os.path.expanduser("~")
        return os.path.join(out_dir, filename)
    dest = os.path.expanduser(dest.strip().strip('"'))
    if os.path.isdir(dest):
        return os.path.join(dest, filename)
    return dest


def _looks_like_path(token: str) -> bool:
    t = token.lower()
    return t.endswith(".zip") or "/" in token or os.sep in token or t.endswith(".hlvdf")


def _cmd_export_world(state: CliState, args: list[str]) -> None:
    if not args:
        print_error("Usage: export-world <world name or id> [destination folder or .zip path]")
        print_hint("With no destination, the world is saved to your Downloads folder.")
        return
    dest = ""
    ident_parts = args
    if len(args) >= 2 and _looks_like_path(args[-1]):
        dest = args[-1]
        ident_parts = args[:-1]
    ident = " ".join(ident_parts).strip()
    world = _resolve_world(state, ident)
    if not world:
        print_error(f"World '{ident}' not found. Run 'list-worlds' to see worlds.")
        return
    wid = str(world.get("world_id") or "")
    name = str(world.get("title") or world.get("name") or wid)
    from server.api.routes.worlds import api_worlds_export

    with scope_override(state, "versions"):
        result = api_worlds_export({"world_id": wid, "storage_target": _world_storage(world)}) or {}
    if not result.get("ok"):
        print_error(result.get("error") or "Export failed.")
        return
    import base64

    try:
        raw = base64.b64decode(result.get("zip_b64") or "")
    except Exception as exc:
        print_error(f"Export produced invalid data: {exc}")
        return
    filename = str(result.get("suggested_filename") or result.get("filename") or f"{wid or name}.zip")
    out_path = _resolve_export_dest(dest, filename)
    try:
        with open(out_path, "wb") as fh:
            fh.write(raw)
    except Exception as exc:
        print_error(f"Could not write export file: {exc}")
        return
    print_success(f"Exported '{name}' to {out_path}")


def _cmd_import_world(state: CliState, args: list[str]) -> None:
    if not args:
        print_error("Usage: import-world <path to world .zip>")
        return
    path = os.path.expanduser(" ".join(args).strip().strip('"'))
    if not os.path.isfile(path):
        print_error(f"File not found: {path}")
        return
    from server.api.file_dialogs import remember_pending_import_file
    from server.api.routes.worlds import api_worlds_import

    try:
        token = remember_pending_import_file("world", path)
    except Exception as exc:
        print_error(f"Could not stage the import file: {exc}")
        return
    with scope_override(state, "versions"):
        result = api_worlds_import({"import_token": token, "storage_target": "default"}) or {}
    if not result.get("ok"):
        print_error(result.get("error") or "Import failed.")
        return
    print_success("World imported into the current versions profile.")


def _cmd_delete_screenshot(state: CliState, args: list[str]) -> None:
    if not args:
        print_error("Usage: delete-screenshot <file name>")
        return
    ident = " ".join(args).strip().lower()
    from server.api.routes.screenshots import api_screenshots_installed

    with scope_override(state, "versions"):
        listing = api_screenshots_installed() or {}
    shot = None
    for s in listing.get("screenshots") or []:
        if not isinstance(s, dict):
            continue
        rel = str(s.get("relative_path") or "")
        fname = str(s.get("file_name") or s.get("title") or "")
        if ident in (rel.lower(), fname.lower()):
            shot = s
            break
    if not shot:
        print_error(f"Screenshot '{' '.join(args)}' not found. Run 'list-screenshots'.")
        return
    rel = str(shot.get("relative_path") or "")
    name = str(shot.get("file_name") or shot.get("title") or rel)
    if not confirm("Delete screenshot",
                   f"Permanently delete screenshot '{name}'?",
                   yes_label="Delete", no_label="Keep", default_yes=False, kind="warn"):
        print_info("Cancelled.")
        return
    from server.api.routes.screenshots import api_screenshots_delete

    target = str(shot.get("storage_target") or "default")
    with scope_override(state, "versions"):
        result = api_screenshots_delete({"relative_path": rel, "storage_target": target}) or {}
    if not result.get("ok"):
        print_error(result.get("error") or "Delete failed.")
        return
    print_success(f"Deleted screenshot '{name}'.")


def _cmd_open_screenshot(state: CliState, args: list[str]) -> None:
    from server.api.routes.screenshots import api_screenshots_installed, api_screenshots_open

    with scope_override(state, "versions"):
        listing = api_screenshots_installed() or {}
    shots = listing.get("screenshots") or []
    if args:
        ident = " ".join(args).strip().lower()
        shot = next(
            (s for s in shots if isinstance(s, dict)
             and ident in (str(s.get("relative_path") or "").lower(), str(s.get("file_name") or s.get("title") or "").lower())),
            None,
        )
    else:
        shot = next((s for s in shots if isinstance(s, dict)), None)
    if not shot:
        print_error("Screenshot not found. Run 'list-screenshots' to see file names.")
        return
    rel = str(shot.get("relative_path") or "")
    name = str(shot.get("file_name") or shot.get("title") or rel)
    target = str(shot.get("storage_target") or "default")
    with scope_override(state, "versions"):
        result = api_screenshots_open({"relative_path": rel, "storage_target": target}) or {}
    if not result.get("ok"):
        print_error(result.get("error") or "Could not open the screenshot.")
        return
    print_success(f"Opened '{name}'.")


def _cmd_fix_corrupted(state: CliState, args: list[str]) -> None:
    from server.api._state import STATE
    from server.api.routes.corrupted import (
        api_corrupted_versions, api_delete_corrupted_versions,
    )

    STATE.corrupted_versions_checked = False
    result = api_corrupted_versions() or {}
    corrupted = [v for v in (result.get("corrupted") or []) if isinstance(v, dict)]
    if not corrupted:
        print_success("No corrupted versions found.")
        return
    print_section(f"Corrupted versions ({len(corrupted)})")
    print_table(
        ("Category", "Version"),
        [(str(v.get("category") or ""), str(v.get("folder") or v.get("display") or "")) for v in corrupted],
    )
    if not confirm("Fix corrupted versions",
                   f"Remove {len(corrupted)} broken version folder(s)?\n"
                   f"They are missing data and cannot launch.",
                   yes_label="Remove", no_label="Keep", default_yes=False, kind="warn"):
        print_info("Cancelled.")
        return
    payload = {"versions": [{"category": v.get("category"), "folder": v.get("folder")} for v in corrupted]}
    del_result = api_delete_corrupted_versions(payload) or {}
    deleted = del_result.get("deleted") or []
    failed = del_result.get("failed") or []
    print_success(f"Removed {len(deleted)} corrupted version(s).")
    if failed:
        print_error(f"{len(failed)} could not be removed.")


def _cmd_diagnostics(state: CliState, args: list[str]) -> None:
    from server.api.routes.diagnostics import api_diagnostics_report

    result = api_diagnostics_report({"include_text": True}) or {}
    if not result.get("ok"):
        print_error(result.get("error") or "Failed to build the diagnostics report.")
        return
    text = str(result.get("report_text") or "").rstrip()
    print_section("Diagnostics report")
    for line in text.splitlines():
        writeln("  " + line)
    print_hint("Copy the text above when reporting a problem.")


def _cmd_status(state: CliState, args: list[str]) -> None:
    print_section("Local server")
    if state.server_port:
        print_info(f"Listening on http://127.0.0.1:{state.server_port}/")
    else:
        print_info("Not running.")

    print_section("Background activity")
    from core.downloader.progress import list_progress_files

    try:
        entries = list_progress_files() or []
    except Exception:
        entries = []
    rows = []
    for key, info in entries:
        info = info or {}
        try:
            pct = float(info.get("overall_percent") or info.get("progress") or 0)
        except (TypeError, ValueError):
            pct = 0.0
        rows.append((str(key)[:40],
                     str(info.get("status") or "?")[:12],
                     f"{pct:.1f}%",
                     str(info.get("stage") or info.get("message") or "")[:32]))
    if rows:
        print_table(("Key", "Status", "Progress", "Phase"), rows)
    else:
        print_info("No active downloads.")


register(Command(
    name="dataFolder",
    summary="Show the launcher data folder path and open it in your file manager.",
    handler=_cmd_open_data_folder,
    usage="dataFolder",
    aliases=("openDataFolder",),
    category="System",
))
register(Command(
    name="listJava",
    summary="List detected Java runtimes.",
    handler=_cmd_list_java,
    usage="listJava",
    category="System",
))
register(Command(
    name="installJava",
    summary="List or install a managed Java runtime.",
    handler=_cmd_install_java,
    usage="installJava [version]",
    details="With no argument, lists installable runtimes. Pass a version number (e.g. 21) to download and install one.",
    category="System",
))
register(Command(
    name="diagnostics",
    summary="Print a diagnostics report you can share when reporting a problem.",
    handler=_cmd_diagnostics,
    usage="diagnostics",
    category="System",
))
register(Command(
    name="fixCorrupted",
    summary="Find and remove broken version folders that can no longer launch.",
    handler=_cmd_fix_corrupted,
    usage="fixCorrupted",
    category="System",
))
register(Command(
    name="status",
    summary="Show current downloads and background tasks.",
    handler=_cmd_status,
    usage="status",
    category="System",
))
register(Command(
    name="listWorlds",
    summary="List installed Minecraft worlds for the current versions profile.",
    handler=_cmd_list_worlds,
    usage="listWorlds",
    category="Worlds",
))
register(Command(
    name="openWorld",
    summary="Open a world's folder in your file manager.",
    handler=_cmd_open_world,
    usage="openWorld <world name or id>",
    category="Worlds",
))
register(Command(
    name="deleteWorld",
    summary="Permanently delete an installed world.",
    handler=_cmd_delete_world,
    usage="deleteWorld <world name or id>",
    aliases=("removeWorld",),
    category="Worlds",
))
register(Command(
    name="exportWorld",
    summary="Export a world to a .zip file you can back up or share.",
    handler=_cmd_export_world,
    usage="exportWorld <world name or id> [destination folder or .zip path]",
    details="With no destination, the world is saved to your Downloads folder.",
    category="Worlds",
))
register(Command(
    name="importWorld",
    summary="Import a world from a .zip file into the current versions profile.",
    handler=_cmd_import_world,
    usage="importWorld <path to world .zip>",
    category="Worlds",
))
register(Command(
    name="listScreenshots",
    summary="List screenshots saved by the current versions profile.",
    handler=_cmd_list_screenshots,
    usage="listScreenshots",
    category="Screenshots",
))
register(Command(
    name="openScreenshot",
    summary="Open a screenshot (or the latest one) in your image viewer.",
    handler=_cmd_open_screenshot,
    usage="openScreenshot [file name]",
    category="Screenshots",
))
register(Command(
    name="deleteScreenshot",
    summary="Permanently delete a screenshot.",
    handler=_cmd_delete_screenshot,
    usage="deleteScreenshot <file name>",
    aliases=("removeScreenshot",),
    category="Screenshots",
))
