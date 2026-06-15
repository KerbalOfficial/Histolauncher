from __future__ import annotations

from launcher.cli.commands import ArgSpec, Command, register
from launcher.cli.dialogs import confirm
from launcher.cli.scopes import scope_override
from launcher.cli.state import CliState
from launcher.cli.terminal import (
    FG, c, print_error, print_hint, print_info, print_section, print_success,
    print_table, writeln,
)


_LOADERS = ("fabric", "babric", "ornithe", "forge", "modloader", "neoforge", "quilt")


def _cmd_list_loaders(state: CliState, args: list[str]) -> None:
    if not args:
        print_error("Usage: list-loaders <version>")
        return
    version = args[0]
    if "/" in version:
        cat, folder = version.split("/", 1)
        version_key = f"{cat}/{folder}"
    else:
        version_key = f"Release/{version}"
    with scope_override(state, "versions"):
        from server.api.routes.loaders import api_loaders, api_loaders_installed

        available = api_loaders(version_key)
        installed = api_loaders_installed(version_key)

    if isinstance(available, dict) and not available.get("ok", True):
        print_error(available.get("error") or "Failed to load loaders.")
        return

    print_section(f"Loaders available for {version_key}")
    rows: list[tuple[str, str, str]] = []
    loaders_map = (available or {}).get("available") or {}
    if isinstance(loaders_map, dict):
        for loader_type in _LOADERS:
            versions = loaders_map.get(loader_type) or []
            if isinstance(versions, list):
                for entry in versions[:5]:
                    if isinstance(entry, dict):
                        v = entry.get("version") or entry.get("id") or ""
                    else:
                        v = str(entry)
                    rows.append((loader_type, v, "available"))
                if len(versions) > 5:
                    rows.append((loader_type, f"… ({len(versions) - 5} more)", "available"))
    if not rows:
        print_info("No loaders available for this Minecraft version.")
    else:
        print_table(("Loader", "Version", "Status"), rows)

    installed_map = (installed or {}).get("installed") if isinstance(installed, dict) else None
    if installed_map:
        print_section("Installed loaders")
        irows = []
        for loader_type, versions in installed_map.items():
            if isinstance(versions, list):
                for v in versions:
                    name = v.get("version") if isinstance(v, dict) else str(v)
                    irows.append((loader_type, name))
        if irows:
            print_table(("Loader", "Version"), irows)


def _cmd_install_loader(state: CliState, args: list[str]) -> None:
    if len(args) < 3:
        print_error("Usage: install-loader <version> <loader> <loaderVersion>")
        return
    version, loader, lver = args[0], args[1], args[2]
    if "/" in version:
        cat, folder = version.split("/", 1)
    else:
        cat, folder = "Release", version
    payload = {"category": cat, "folder": folder, "loader_type": loader, "loader_version": lver}
    with scope_override(state, "versions"):
        from server.api.routes.loaders import api_install_loader

        result = api_install_loader(payload)
    if not result.get("ok"):
        print_error(result.get("error") or result.get("message") or "Install failed.")
        return
    print_success(result.get("message") or f"Loader install started: {loader} {lver} for {cat}/{folder}.")
    if not result.get("already_running"):
        print_hint("The install continues in the background; a notification is sent when it finishes.")


def _cmd_delete_loader(state: CliState, args: list[str]) -> None:
    if len(args) < 3:
        print_error("Usage: delete-loader <version> <loader> <loaderVersion>")
        return
    version, loader, lver = args[0], args[1], args[2]
    if "/" in version:
        cat, folder = version.split("/", 1)
    else:
        cat, folder = "Release", version
    if not confirm("Delete loader", f"Delete {loader} {lver} from {cat}/{folder}?",
                   yes_label="Delete", no_label="Keep", default_yes=False, kind="warn"):
        print_info("Cancelled.")
        return
    with scope_override(state, "versions"):
        from server.api.routes.loaders import api_delete_loader

        result = api_delete_loader({"category": cat, "folder": folder, "loader_type": loader, "loader_version": lver})
    if not result.get("ok"):
        print_error(result.get("error") or "Delete failed.")
        return
    print_success(f"Removed {loader} {lver}.")


register(Command(
    name="listLoaders",
    summary="List available and installed modloaders for a Minecraft version.",
    handler=_cmd_list_loaders,
    usage="listLoaders <version>",
    category="Loaders",
))
register(Command(
    name="installLoader",
    summary="Install a modloader (fabric/forge/etc.) for an installed version.",
    handler=_cmd_install_loader,
    usage="installLoader <version> <loader> <loaderVersion>",
    category="Loaders",
    args=(ArgSpec("version"), ArgSpec("loader", _LOADERS)),
))
register(Command(
    name="deleteLoader",
    summary="Remove an installed modloader from a version.",
    handler=_cmd_delete_loader,
    usage="deleteLoader <version> <loader> <loaderVersion>",
    category="Loaders",
    args=(ArgSpec("version"), ArgSpec("loader", _LOADERS)),
))
