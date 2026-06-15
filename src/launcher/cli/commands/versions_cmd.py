from __future__ import annotations

import time

from launcher.cli.commands import ArgSpec, Command, register
from launcher.cli.dialogs import confirm, select_one
from launcher.cli.scopes import scope_override
from launcher.cli.state import CliState
from launcher.cli.terminal import (
    BOLD, DIM, FG, c, newline, overwrite_line, print_error, print_hint,
    print_info, print_section, print_success, print_table, render_progress,
    writeln,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _normalize_provider(value: str | None) -> str:
    val = (value or "all").strip().lower()
    if val in ("all", "any", "*"):
        return "all"
    if val in ("mojang", "official"):
        return "mojang"
    if val in ("omni", "omniarchive", "third", "third_party", "third-party"):
        return "omniarchive"
    return val


def _entry_provider(entry: dict) -> str:
    source = str(entry.get("source") or "mojang").strip().lower()
    if source in ("mojang", "official"):
        return "mojang"
    return "omniarchive"


def _filter_provider(entries: list[dict], provider: str) -> list[dict]:
    if provider == "all":
        return entries
    return [e for e in entries if _entry_provider(e) == provider]


def _resolve_version(state: CliState, version_id: str, *, provider: str = "all",
                     local_only: bool = False) -> tuple[str, str] | None:
    if "/" in version_id:
        cat, folder = version_id.split("/", 1)
        return cat.strip(), folder.strip()

    if local_only:
        return _resolve_local_version(version_id, provider=provider)

    try:
        from server.api.routes.versions import api_versions

        with scope_override(state, "versions"):
            data = api_versions("* All")
    except Exception as exc:
        print_error(f"Failed to read version list: {exc}")
        return None

    target = version_id.strip().lower()
    candidates: list[tuple[str, str, dict]] = []
    for src_name, src in (("installed", data.get("installed") or []),
                          ("available", data.get("available") or [])):
        for entry in src:
            if not isinstance(entry, dict):
                continue
            if provider != "all" and _entry_provider(entry) != provider:
                continue
            for field in ("folder", "display", "display_name"):
                val = str(entry.get(field) or "").strip().lower()
                if val == target:
                    cat = str(entry.get("category") or "Release").strip()
                    folder = str(entry.get("folder") or entry.get("display") or "").strip()
                    return cat, folder
            display = str(entry.get("folder") or entry.get("display") or "").strip().lower()
            if display.startswith(target) or target in display:
                cat = str(entry.get("category") or "Release").strip()
                folder = str(entry.get("folder") or entry.get("display") or "").strip()
                candidates.append((cat, folder, entry))

    if len(candidates) == 1:
        return candidates[0][0], candidates[0][1]
    if not candidates:
        print_error(f"Version '{version_id}' not found.")
        return None
    print_error(f"Ambiguous version '{version_id}'. Candidates:")
    for cat, folder, _ in candidates[:10]:
        writeln(f"    {cat}/{folder}")
    print_hint("Re-run with a more specific name, or use 'category/folder' form.")
    return None


def _resolve_local_version(version_id: str, *, provider: str = "all") -> tuple[str, str] | None:
    try:
        from core.version_manager import scan_categories

        local_versions = scan_categories().get("* All", [])
    except Exception as exc:
        print_error(f"Failed to read installed versions: {exc}")
        return None

    target = version_id.strip().lower()
    candidates: list[tuple[str, str]] = []
    for entry in local_versions:
        if not isinstance(entry, dict):
            continue
        if provider != "all" and _entry_provider(entry) != provider:
            continue
        cat = str(entry.get("category") or "Release").strip()
        folder = str(entry.get("folder") or entry.get("display") or "").strip()
        for field in ("folder", "display", "display_name"):
            val = str(entry.get(field) or "").strip().lower()
            if val == target:
                return cat, folder
        display = folder.lower()
        if display.startswith(target) or target in display:
            candidates.append((cat, folder))

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        print_error(f"Version '{version_id}' is not installed.")
        print_hint("Use 'list-versions installed' to see installed versions, "
                   "or 'install-version <version>' to install it first.")
        return None
    print_error(f"Ambiguous version '{version_id}'. Candidates:")
    for cat, folder in candidates[:10]:
        writeln(f"    {cat}/{folder}")
    print_hint("Re-run with a more specific name, or use 'category/folder' form.")
    return None


# ---------------------------------------------------------------------------
# listVersions
# ---------------------------------------------------------------------------


def _cmd_list_versions(state: CliState, args: list[str]) -> None:
    if not args:
        print_error("Usage: list-versions [provider: all|mojang|omniarchive] <installed|available> [category]")
        return

    provider = "all"
    list_type: str | None = None
    category = ""
    rest = list(args)
    first = rest[0].lower()
    if first in ("all", "mojang", "omni", "omniarchive", "third_party", "third", "official", "any"):
        provider = _normalize_provider(rest.pop(0))
    if not rest:
        print_error("Specify either 'installed' or 'available'.")
        return
    list_type = rest.pop(0).lower()
    if list_type not in ("installed", "available"):
        print_error("Type must be 'installed' or 'available'.")
        return
    if rest:
        category = " ".join(rest).strip()

    try:
        from server.api.routes.versions import api_versions

        with scope_override(state, "versions"):
            data = api_versions(category or "* All")
    except Exception as exc:
        print_error(f"Failed to fetch versions: {exc}")
        return

    if data.get("manifest_error"):
        print_hint("Note: remote manifest unavailable. Showing cached / installed data only.")

    entries = data.get(list_type) or []
    entries = _filter_provider(entries, provider)
    if not entries:
        print_info(f"No {list_type} versions match.")
        return

    rows = []
    for entry in entries:
        folder = str(entry.get("folder") or entry.get("display") or "")
        display = str(entry.get("display_name") or entry.get("display") or folder)
        cat = str(entry.get("category") or "")
        src = _entry_provider(entry)
        flags = []
        if entry.get("recommended"):
            flags.append("recommended")
        if entry.get("installed_local"):
            flags.append("already installed")
        rows.append((f"{cat}/{folder}", display, src, ", ".join(flags) or "-"))

    print_section(f"{list_type.capitalize()} versions  ({provider}, {len(rows)} shown)")
    print_table(("Key", "Display", "Source", "Notes"), rows, max_widths=(40, 28, 12, 30))


# ---------------------------------------------------------------------------
# installVersion
# ---------------------------------------------------------------------------


def _cmd_install_version(state: CliState, args: list[str]) -> None:
    if not args:
        print_error("Usage: install-version [provider] <version>")
        return
    provider = "all"
    rest = list(args)
    first = rest[0].lower()
    if first in ("all", "mojang", "omni", "omniarchive", "third_party", "third", "official", "any"):
        provider = _normalize_provider(rest.pop(0))
    if not rest:
        print_error("Version is required.")
        return
    version = " ".join(rest).strip()

    resolved = _resolve_version(state, version, provider=provider)
    if not resolved:
        return
    category, folder = resolved

    print_info(f"Starting install: {category}/{folder}")

    with scope_override(state, "versions"):
        from server.api.routes.installer import api_install, api_status

        result = api_install({"version": folder, "category": category})
        if result.get("error"):
            print_error(result["error"])
            return

        version_key = result.get("version") or f"{category.lower()}/{folder}"
        _follow_install(version_key, api_status)


def _follow_install(version_key: str, api_status) -> None:
    last_status = ""
    last_log_line = 0
    try:
        while True:
            status = api_status(version_key) or {}
            state_name = str(status.get("status") or "").lower()
            ratio = float(status.get("progress") or 0.0) / 100.0 if status.get("progress") else 0.0
            phase = str(status.get("phase") or status.get("message") or state_name or "working").strip()

            overwrite_line(render_progress(f"  {phase[:32]:32}", ratio,
                                           extra=f"{state_name}"))

            if state_name in ("completed", "done", "ready", "complete", "success"):
                newline()
                print_success(f"Installed {version_key}.")
                return
            if state_name in ("failed", "error"):
                newline()
                print_error(status.get("message") or status.get("error") or "Install failed.")
                return
            if state_name in ("cancelled", "canceled"):
                newline()
                print_info("Install cancelled.")
                return
            if state_name in ("unknown", ""):
                newline()
                print_info("Install finished or status unavailable.")
                return

            time.sleep(0.4)
    except KeyboardInterrupt:
        newline()
        print_info("Detached from progress (install continues in the background).")


# ---------------------------------------------------------------------------
# launchVersion
# ---------------------------------------------------------------------------


def _cmd_launch_version(state: CliState, args: list[str]) -> None:
    if not args:
        print_error("Usage: launch-version <version>  [loader] [loaderVersion]")
        return
    version = args[0]
    loader = args[1] if len(args) > 1 else None
    loader_version = args[2] if len(args) > 2 else None

    resolved = _resolve_version(state, version, provider="all", local_only=True)
    if not resolved:
        return
    category, folder = resolved

    from core.settings import load_global_settings
    from core.version_manager import get_version_loaders
    from server.api.routes.launch import api_launch

    with scope_override(state, "settings"):
        settings = load_global_settings() or {}
    username = (settings.get("username") or "Player").strip()

    if loader is None:
        try:
            available = get_version_loaders(category, folder) or {}
        except Exception:
            available = {}
        installed_loaders: list[tuple[str, list[dict]]] = [
            (lt, lst) for lt, lst in available.items()
            if isinstance(lst, list) and lst
        ]
        if installed_loaders:
            options = ["Vanilla (no loader)"]
            for lt, lst in installed_loaders:
                count = len(lst)
                options.append(f"{lt}  ({count} version{'s' if count != 1 else ''})")
            choice = select_one(
                f"Launch {folder}",
                "Choose how to launch this version. Use ↑/↓ + Enter.",
                options,
                default=0,
            )
            if choice is None:
                print_info("Cancelled.")
                return
            if choice > 0:
                loader, lst = installed_loaders[choice - 1]
                if len(lst) > 1:
                    sub_opts = []
                    for entry in lst:
                        v = entry.get("version") if isinstance(entry, dict) else str(entry)
                        sub_opts.append(str(v or "?"))
                    sub_choice = select_one(
                        f"{loader} version",
                        f"Pick which installed {loader} version to use.",
                        sub_opts,
                        default=0,
                    )
                    if sub_choice is None:
                        print_info("Cancelled.")
                        return
                    loader_version = sub_opts[sub_choice]
                else:
                    entry = lst[0]
                    loader_version = (
                        entry.get("version") if isinstance(entry, dict) else str(entry)
                    )

    target_desc = f"{category}/{folder}"
    if loader:
        target_desc += f"  [{loader}"
        if loader_version:
            target_desc += f" {loader_version}"
        target_desc += "]"
    print_info(f"Launching {target_desc} as {username}…")

    payload = {"category": category, "folder": folder, "username": username}
    if loader:
        payload["loader"] = loader
    if loader_version:
        payload["loader_version"] = loader_version

    with scope_override(state, "versions"):
        result = api_launch(payload)

    if not result.get("ok"):
        print_error(result.get("message") or "Launch failed.")
        return

    process_id = result.get("process_id")
    print_success(result.get("message") or "Launched.")
    print_hint(f"Process: {process_id}")
    print_hint("Use 'list-games' to see running games, 'game-status <id>' to check one.")


# ---------------------------------------------------------------------------
# uninstallVersion
# ---------------------------------------------------------------------------


def _cmd_uninstall_version(state: CliState, args: list[str]) -> None:
    if not args:
        print_error("Usage: delete-version <version>")
        return
    resolved = _resolve_version(state, args[0], local_only=True)
    if not resolved:
        return
    category, folder = resolved
    if not confirm("Delete installed version",
                   f"Permanently delete {category}/{folder} from disk?",
                   yes_label="Delete", no_label="Keep", default_yes=False, kind="warn"):
        print_info("Cancelled.")
        return
    with scope_override(state, "versions"):
        from server.api.routes.installer import api_delete_version

        result = api_delete_version({"category": category, "folder": folder})
    if not result.get("ok") and result.get("error"):
        print_error(result["error"])
        return
    print_success(f"Removed {category}/{folder}.")


def _cmd_cancel_install(state: CliState, args: list[str]) -> None:
    if not args:
        print_error("Usage: cancel-install <version>")
        return
    resolved = _resolve_version(state, args[0])
    if not resolved:
        return
    category, folder = resolved
    with scope_override(state, "versions"):
        from server.api.routes.installer import api_cancel

        result = api_cancel(f"{category.lower()}/{folder}")
    if result.get("ok"):
        print_success(f"Cancelled install of {category}/{folder}.")
    else:
        print_error(result.get("error") or "Cancel failed.")


# ---------------------------------------------------------------------------
# running game processes
# ---------------------------------------------------------------------------


def _cmd_list_games(state: CliState, args: list[str]) -> None:
    try:
        from core.launch.state import STATE
    except Exception as exc:
        print_error(f"Could not read launch state: {exc}")
        return

    with STATE.process_lock:
        snapshot = list(STATE.active_processes.items())

    if not snapshot:
        print_info("No games running.")
        return

    rows = []
    for pid, info in snapshot:
        proc = info.get("process") if isinstance(info, dict) else None
        running = True
        try:
            if proc is not None and proc.poll() is not None:
                running = False
        except Exception:
            pass
        version = str(info.get("version") or "?") if isinstance(info, dict) else "?"
        start = info.get("start_time") if isinstance(info, dict) else None
        elapsed = ""
        try:
            if start:
                elapsed = f"{int(time.time() - float(start))}s"
        except Exception:
            elapsed = ""
        rows.append((pid, version, "running" if running else "exiting", elapsed))

    print_section("Running games")
    print_table(("Process ID", "Version", "Status", "Uptime"), rows)


def _cmd_game_status(state: CliState, args: list[str]) -> None:
    if not args:
        print_error("Usage: game-status <process_id>")
        print_hint("Run 'list-games' to see process IDs.")
        return
    process_id = args[0]
    from server.api.routes.launch import api_launch_status

    status = api_launch_status(process_id) or {}
    if not status.get("ok") and status.get("status") not in ("crashed", "exited"):
        print_error(status.get("error") or "Status unavailable.")
        return
    name = str(status.get("status") or "?")
    print_section(f"Game {process_id}")
    writeln("  " + c("Status   : ", FG["muted"]) + c(name, BOLD, FG["accent"]))
    if status.get("elapsed"):
        writeln("  " + c("Uptime   : ", FG["muted"]) + c(f"{int(status['elapsed'])}s", FG["value"]))
    if status.get("exit_code") is not None:
        writeln("  " + c("Exit code: ", FG["muted"]) + c(str(status["exit_code"]), FG["value"]))
    if status.get("log_path"):
        writeln("  " + c("Log file : ", FG["muted"]) + c(str(status["log_path"]), FG["muted"]))


def _cmd_export_version(state: CliState, args: list[str]) -> None:
    if not args:
        print_error("Usage: export-version <version> [destination folder or .hlvdf path]")
        print_hint("With no destination, the version is saved to your Downloads folder.")
        return
    dest = ""
    ident_parts = args
    last = args[-1].lower()
    if len(args) >= 2 and (last.endswith(".hlvdf") or "/" in args[-1] or "\\" in args[-1]):
        dest = args[-1]
        ident_parts = args[:-1]
    resolved = _resolve_version(state, " ".join(ident_parts).strip(), local_only=True)
    if not resolved:
        return
    category, folder = resolved

    import os

    if dest:
        dest = os.path.expanduser(dest.strip().strip('"'))
        out_path = os.path.join(dest, f"{folder}.hlvdf") if os.path.isdir(dest) else dest
    else:
        out_dir = os.path.expanduser("~/Downloads")
        if not os.path.isdir(out_dir):
            out_dir = os.path.expanduser("~")
        out_path = os.path.join(out_dir, f"{folder}.hlvdf")

    print_info(f"Exporting {category}/{folder}…")
    from server.api.file_dialogs import dialog_path_override
    from server.api.routes.versions_io import api_export_versions

    with scope_override(state, "versions"):
        with dialog_path_override(out_path):
            result = api_export_versions({"category": category, "folder": folder}) or {}
    if not result.get("ok"):
        print_error(result.get("error") or "Export failed.")
        return
    print_success(f"Exported {category}/{folder} to {result.get('filepath') or out_path}")


def _cmd_import_version(state: CliState, args: list[str]) -> None:
    if not args:
        print_error("Usage: import-version <path to .hlvdf file>")
        return
    import os

    path = os.path.expanduser(" ".join(args).strip().strip('"'))
    if not os.path.isfile(path):
        print_error(f"File not found: {path}")
        return
    print_info(f"Importing {os.path.basename(path)}…")
    from server.api.routes.versions_io import api_import_versions

    with scope_override(state, "versions"):
        result = api_import_versions({"zip_path": path}) or {}
    if not result.get("ok"):
        print_error(result.get("error") or "Import failed.")
        return
    name = result.get("version_name") or result.get("folder") or os.path.basename(path)
    print_success(f"Imported version '{name}'.")


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


register(Command(
    name="listVersions",
    summary="List installed or available Minecraft versions.",
    handler=_cmd_list_versions,
    usage="listVersions [provider] <installed|available> [category]",
    details="provider: all | mojang | omniarchive   (defaults to 'all')\n"
            "type    : installed | available\n"
            "category: optional category filter (e.g. Release, Beta, Alpha)",
    category="Versions",
    args=(
        ArgSpec("provider", ("all", "mojang", "omniarchive")),
        ArgSpec("type", ("installed", "available")),
    ),
))
register(Command(
    name="installVersion",
    summary="Download and install a Minecraft version.",
    handler=_cmd_install_version,
    usage="installVersion [provider] <version>",
    details="provider is optional and defaults to 'all'. The version can be a folder name "
            "(e.g. 1.20.4) or 'category/folder' (e.g. Beta/b1.7.3).",
    category="Versions",
    args=(ArgSpec("provider", ("all", "mojang", "omniarchive")),),
))
register(Command(
    name="launchVersion",
    summary="Launch an installed Minecraft version.",
    handler=_cmd_launch_version,
    usage="launchVersion <version> [loader] [loaderVersion]",
    details="Uses the current settings profile's username and JVM options.\n"
            "Optional loader: fabric | babric | forge | neoforge | quilt | modloader",
    category="Versions",
    aliases=("launch",),
    args=(
        ArgSpec("version"),
        ArgSpec("loader", ("fabric", "babric", "ornithe", "forge", "neoforge", "quilt", "modloader")),
    ),
))
register(Command(
    name="deleteVersion",
    summary="Delete an installed Minecraft version.",
    handler=_cmd_uninstall_version,
    usage="deleteVersion <version>",
    category="Versions",
    aliases=("uninstallVersion",),
))
register(Command(
    name="exportVersion",
    summary="Export an installed version to a .hlvdf file you can back up or share.",
    handler=_cmd_export_version,
    usage="exportVersion <version> [destination folder or .hlvdf path]",
    details="With no destination, the version is saved to your Downloads folder.",
    category="Versions",
))
register(Command(
    name="importVersion",
    summary="Import a version from a .hlvdf file.",
    handler=_cmd_import_version,
    usage="importVersion <path to .hlvdf file>",
    category="Versions",
))
register(Command(
    name="cancelInstall",
    summary="Cancel an in-progress version install.",
    handler=_cmd_cancel_install,
    usage="cancelInstall <version>",
    category="Versions",
))
register(Command(
    name="listGames",
    summary="List currently-running Minecraft processes.",
    handler=_cmd_list_games,
    usage="listGames",
    category="Versions",
))
register(Command(
    name="gameStatus",
    summary="Show status of a running or recently-exited game.",
    handler=_cmd_game_status,
    usage="gameStatus <process_id>",
    category="Versions",
))
