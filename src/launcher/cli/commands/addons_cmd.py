from __future__ import annotations

from launcher.cli.commands import ArgSpec, Command, register
from launcher.cli.dialogs import confirm, select_one
from launcher.cli.scopes import scope_override
from launcher.cli.state import CliState
from launcher.cli.terminal import (
    BOLD, DIM, FG, c, print_error, print_hint, print_info, print_section,
    print_success, print_table, writeln,
)


_TYPE_MAP = {
    "mod": "mods",
    "mods": "mods",
    "modpack": "modpacks",
    "modpacks": "modpacks",
    "resourcepack": "resourcepacks",
    "resourcepacks": "resourcepacks",
    "rp": "resourcepacks",
    "shaderpack": "shaderpacks",
    "shaderpacks": "shaderpacks",
    "shader": "shaderpacks",
    "datapack": "datapacks",
    "datapacks": "datapacks",
    "dp": "datapacks",
}

_LOADER_VALUES = ("all", "fabric", "legacyfabric", "babric", "ornithe", "forge", "liteloader", "modloader", "neoforge", "quilt")


def _normalize_type(raw: str | None) -> str | None:
    if not raw:
        return None
    return _TYPE_MAP.get(raw.strip().lower())


def _normalize_provider(raw: str | None) -> str | None:
    if not raw:
        return None
    p = raw.strip().lower()
    if p in ("modrinth", "curseforge"):
        return p
    return None


def _normalize_loader(raw: str | None) -> str | None:
    if not raw:
        return "all"
    val = raw.strip().lower()
    if val in _LOADER_VALUES:
        return val
    return None


def _installed_version_values(state: CliState) -> list[str]:
    values = ["all"]
    try:
        from core.version_manager import scan_categories

        seen: set[str] = set()
        for entry in scan_categories().get("* All", []):
            if not isinstance(entry, dict):
                continue
            name = str(
                entry.get("folder")
                or entry.get("display")
                or entry.get("display_name")
                or ""
            ).strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                values.append(name)
    except Exception:
        pass
    return values



# ---------------------------------------------------------------------------
# listAddons
# ---------------------------------------------------------------------------


def _cmd_list_addons(state: CliState, args: list[str]) -> None:
    if not args:
        print_error("Usage: list-addons <available|installed> <type> [provider] [modloader] [query] [page]")
        print_hint("available: search Modrinth/CurseForge   installed: show local addons")
        return
    mode = args[0].strip().lower()
    if mode in ("installed", "local"):
        _list_installed_addons(state, args[1:])
        return
    if mode in ("available", "search", "remote"):
        _list_available_addons(state, args[1:])
        return
    print_error("First argument must be 'available' or 'installed'.")


def _list_available_addons(state: CliState, args: list[str]) -> None:
    if len(args) < 2:
        print_error("Usage: list-addons available <type> <provider> [modloader] [mc-version] [query] [page]")
        print_hint("type: mod | modpack | resourcepack | shaderpack | datapack")
        print_hint("provider: modrinth | curseforge")
        print_hint("mc-version: an installed version or 'all' (default: all)")
        return

    addon_type = _normalize_type(args[0])
    provider = _normalize_provider(args[1])
    if not addon_type:
        print_error(f"Unknown addon type: {args[0]}")
        return
    if not provider:
        print_error(f"Unknown provider: {args[1]}")
        return

    loader = _normalize_loader(args[2]) if len(args) >= 3 else "all"
    if loader is None:
        print_error(f"Unknown modloader: {args[2]}")
        return

    game_version = None
    if len(args) >= 4:
        mc = args[3].strip()
        if mc.lower() not in ("all", "*", ""):
            game_version = mc

    query = ""
    page_index = 0
    if len(args) > 4:
        try:
            page_index = int(args[-1])
            tail = args[4:-1]
        except ValueError:
            tail = args[4:]
        query = " ".join(tail).strip()

    payload = {
        "addon_type": addon_type,
        "provider": provider,
        "search_query": query,
        "mod_loader": None if loader == "all" else loader,
        "game_version": game_version,
        "page_size": 25,
        "page_index": page_index,
    }

    with scope_override(state, "addons"):
        from server.api.routes.mods import api_mods_search

        result = api_mods_search(payload)

    if not result.get("ok"):
        print_error(result.get("error") or "Search failed.")
        return

    hits = result.get("hits") or result.get("results") or result.get("mods") or []
    if not hits:
        print_info("No results.")
        return

    rows = []
    for item in hits[:25]:
        if not isinstance(item, dict):
            continue
        slug_or_id = (
            item.get("mod_slug")
            or item.get("slug")
            or item.get("mod_id")
            or item.get("id")
            or item.get("project_id")
            or ""
        )
        title = item.get("name") or item.get("title") or ""
        summary = item.get("summary") or item.get("description") or ""
        downloads = (
            item.get("download_count")
            if item.get("download_count") is not None
            else item.get("downloads", "")
        )
        rows.append((
            str(slug_or_id)[:28],
            str(title)[:32],
            str(summary)[:46],
            str(downloads),
        ))
    total = result.get("total_count") or result.get("total") or len(rows)
    mc_suffix = f" · mc {game_version}" if game_version else ""
    print_section(f"{addon_type.capitalize()} · {provider}{mc_suffix} · page {page_index} ({total} total)")
    print_table(("ID/Slug", "Title", "Summary", "Downloads"), rows)
    print_hint("Use 'addon-details <type> <provider> <ID/Slug>' for full info and files.")


# ---------------------------------------------------------------------------
# addonDetails
# ---------------------------------------------------------------------------


def _cmd_addon_details(state: CliState, args: list[str]) -> None:
    if len(args) < 3:
        print_error("Usage: addon-details <type> <provider> <addonID>")
        return
    addon_type = _normalize_type(args[0])
    provider = _normalize_provider(args[1])
    if not addon_type or not provider:
        print_error("Invalid type or provider.")
        return
    addon_id = args[2]

    with scope_override(state, "addons"):
        from server.api.routes.mods import api_mods_detail, api_mods_versions

        detail = api_mods_detail({
            "addon_type": addon_type,
            "provider": provider,
            "mod_id": addon_id,
        })
        result = api_mods_versions({
            "addon_type": addon_type,
            "provider": provider,
            "mod_id": addon_id,
        })

    # --- project info ------------------------------------------------------
    if detail and detail.get("ok"):
        title = detail.get("title") or detail.get("name") or addon_id
        slug = detail.get("mod_slug") or addon_id
        downloads = detail.get("downloads") or detail.get("download_count") or 0
        categories = detail.get("categories") or []
        summary = (detail.get("description") or "").strip()
        body = (detail.get("body") or "").strip()
        source = detail.get("source_url") or ""
        issues = detail.get("issues_url") or ""
        wiki = detail.get("wiki_url") or ""

        print_section(f"{title}  ({slug})")
        if summary:
            writeln("  " + summary)
            writeln("")
        meta_lines = [
            ("Downloads", f"{downloads:,}" if isinstance(downloads, int) else str(downloads)),
            ("Categories", ", ".join(str(c) for c in categories) if categories else "—"),
        ]
        if source:
            meta_lines.append(("Source", source))
        if issues:
            meta_lines.append(("Issues", issues))
        if wiki:
            meta_lines.append(("Wiki", wiki))
        for label, value in meta_lines:
            writeln("  " + c(f"{label:<12}", FG["muted"]) + c(str(value), FG["value"]))

        if body and body != summary:
            preview = body.replace("\r", "")
            if len(preview) > 800:
                preview = preview[:800].rstrip() + "  …"
            writeln("")
            writeln("  " + c("Description", BOLD))
            for line in preview.splitlines():
                writeln("    " + line)
        writeln("")
    elif detail and detail.get("error"):
        print_hint(f"(Could not load project metadata: {detail['error']})")

    # --- file list ---------------------------------------------------------
    if not result.get("ok"):
        print_error(result.get("error") or "Failed to fetch addon files.")
        return
    versions = result.get("versions") or result.get("files") or []
    if not versions:
        print_info("No files available for this addon.")
        return
    rows = []
    for v in versions[:25]:
        if not isinstance(v, dict):
            continue
        file_id = (
            v.get("version_id")
            or v.get("id")
            or v.get("file_id")
            or ""
        )
        rows.append((
            str(file_id)[:24],
            str(v.get("name") or v.get("file_name") or v.get("version_number") or "")[:36],
            ", ".join(v.get("game_versions") or [])[:24],
            ", ".join(v.get("loaders") or [])[:16],
            str(v.get("file_size") or v.get("size") or ""),
        ))
    print_section(f"Files · {provider} · {addon_id}")
    print_table(("FileID", "Name", "Game versions", "Loaders", "Size"), rows)
    print_hint("Install with: install-addon <type> <provider> <addonID> <fileID>")


# ---------------------------------------------------------------------------
# installAddon
# ---------------------------------------------------------------------------


def _cmd_install_addon(state: CliState, args: list[str]) -> None:
    if len(args) < 4:
        print_error("Usage: install-addon <type> <provider> <addonID> <fileID>")
        return
    addon_type = _normalize_type(args[0])
    provider = _normalize_provider(args[1])
    if not addon_type or not provider:
        print_error("Invalid type or provider.")
        return
    addon_id = args[2]
    file_id = args[3]

    with scope_override(state, "addons"):
        from server.api.routes.mods import (
            api_mods_detail, api_mods_install, api_mods_versions,
        )

        detail = api_mods_detail({
            "addon_type": addon_type,
            "provider": provider,
            "mod_id": addon_id,
        }) or {}
        if detail.get("ok"):
            resolved_project_id = detail.get("mod_id") or addon_id
            resolved_slug = detail.get("mod_slug") or addon_id
            resolved_name = detail.get("title") or detail.get("name") or resolved_slug
        else:
            resolved_project_id = addon_id
            resolved_slug = addon_id
            resolved_name = addon_id

        versions = api_mods_versions({
            "addon_type": addon_type,
            "provider": provider,
            "mod_id": addon_id,
        })
        if not versions.get("ok"):
            print_error(versions.get("error") or "Failed to fetch file list.")
            return
        items = versions.get("versions") or versions.get("files") or []
        chosen = None
        for v in items:
            if not isinstance(v, dict):
                continue
            if (
                str(v.get("version_id") or "") == str(file_id)
                or str(v.get("id") or "") == str(file_id)
                or str(v.get("file_id") or "") == str(file_id)
            ):
                chosen = v
                break
        if chosen is None:
            print_error(f"File '{file_id}' not found for addon {addon_id}.")
            return

        download_url = chosen.get("download_url") or chosen.get("url")
        file_name = chosen.get("file_name") or chosen.get("name")
        loaders = chosen.get("loaders") or []
        mod_loader = (loaders[0] if loaders else "").lower()
        payload = {
            "addon_type": addon_type,
            "provider": provider,
            "mod_id": resolved_project_id,
            "mod_slug": resolved_slug,
            "mod_name": resolved_name,
            "mod_loader": mod_loader or "fabric",
            "download_url": download_url,
            "file_name": file_name,
            "file_id": str(chosen.get("version_id") or chosen.get("id") or file_id),
            "game_versions": chosen.get("game_versions") or [],
            "loaders": loaders,
            "version": chosen.get("version_number") or chosen.get("name") or "unknown",
            "sha1": chosen.get("sha1") or "",
            "file_size": chosen.get("file_size") or chosen.get("size") or 0,
        }
        print_info(f"Installing {resolved_name} ({file_name})…")
        result = api_mods_install(payload)

    if not result.get("ok"):
        print_error(result.get("error") or "Install failed.")
        return
    print_success(f"Installed {file_name}.")


# ---------------------------------------------------------------------------
# listInstalledAddons / deleteAddon / toggleAddon
# ---------------------------------------------------------------------------


def _list_installed_addons(state: CliState, args: list[str]) -> None:
    addon_type = _normalize_type(args[0]) if args else "mods"
    if addon_type is None:
        print_error(f"Unknown addon type: {args[0]}")
        return
    with scope_override(state, "addons"):
        from server.api.routes.mods import api_mods_installed

        result = api_mods_installed({"addon_type": addon_type})
    if not result.get("ok"):
        print_error(result.get("error") or "Failed to list installed addons.")
        return
    items = result.get("addons") or result.get("mods") or []
    if not items:
        print_info(f"No installed {addon_type}.")
        return

    def _row_for(item: dict) -> tuple[str, str, str, str]:
        slug = item.get("mod_slug") or item.get("slug") or ""
        project_id = item.get("mod_id") or item.get("id") or ""
        if slug and project_id and str(project_id) != str(slug):
            id_cell = f"{slug} ({project_id})"
        else:
            id_cell = str(slug or project_id or "")
        name = (
            item.get("mod_name")
            or item.get("name")
            or item.get("display_name")
            or slug
            or "?"
        )
        active = item.get("active_version") or ""
        if not active:
            versions = item.get("versions") or []
            if versions and isinstance(versions[0], dict):
                active = versions[0].get("version") or versions[0].get("version_label") or ""
        status_parts = []
        status_parts.append("disabled" if item.get("disabled") else "enabled")
        if item.get("is_imported"):
            status_parts.append("imported")
        provider = item.get("provider") or ""
        if provider and provider != "unknown":
            status_parts.append(provider)
        return (id_cell[:32], str(name)[:34], str(active)[:24], " · ".join(status_parts))

    has_loader_dim = addon_type in ("mods",)

    if not has_loader_dim:
        rows = [_row_for(it) for it in items if isinstance(it, dict)]
        print_section(f"Installed {addon_type}")
        print_table(("ID/Slug", "Name", "Version", "Status"), rows)
        return

    by_loader: dict[str, list[dict]] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        loaders = it.get("compatibility_types") or []
        if not loaders:
            loaders = [it.get("mod_loader") or "unknown"]
        for lt in loaders:
            by_loader.setdefault(str(lt or "unknown"), []).append(it)

    loader_order = ["fabric", "legacyfabric", "babric", "ornithe", "quilt", "forge", "neoforge", "liteloader", "modloader", "unknown"]
    sorted_loaders = sorted(
        by_loader.keys(),
        key=lambda k: (loader_order.index(k) if k in loader_order else 99, k),
    )

    print_section(f"Installed {addon_type}")
    for loader_name in sorted_loaders:
        bucket = by_loader[loader_name]
        rows = [_row_for(it) for it in bucket]
        writeln("")
        writeln("  " + c(f"› {loader_name}  ", BOLD, FG["accent"])
                + c(f"({len(bucket)})", DIM, FG["muted"]))
        print_table(("ID/Slug", "Name", "Version", "Status"), rows)


def _cmd_delete_addon(state: CliState, args: list[str]) -> None:
    if len(args) < 2:
        print_error("Usage: delete-addon <type> <addonID> [loader]")
        return
    addon_type = _normalize_type(args[0])
    if not addon_type:
        print_error(f"Unknown addon type: {args[0]}")
        return
    addon_id = args[1]
    loader_arg = args[2].lower() if len(args) >= 3 else None

    if addon_type == "mods":
        with scope_override(state, "addons"):
            from server.api.routes.mods import api_mods_installed
            result = api_mods_installed({"addon_type": "mods"}) or {}
        items = result.get("addons") or result.get("mods") or []
        matches = [
            it for it in items
            if isinstance(it, dict) and (
                str(it.get("mod_slug") or "").lower() == addon_id.lower()
                or str(it.get("mod_id") or "").lower() == addon_id.lower()
            )
        ]
        if not matches:
            print_error(f"No installed mod with id/slug '{addon_id}'.")
            return

        if loader_arg:
            loader_matches = [
                m for m in matches
                if str(m.get("mod_loader") or "").lower() == loader_arg
            ]
            if not loader_matches:
                avail = sorted({str(m.get("mod_loader") or "?") for m in matches})
                print_error(
                    f"Mod '{addon_id}' is not installed for loader '{loader_arg}'."
                )
                print_hint("Installed loaders: " + ", ".join(avail))
                return
            matches = loader_matches
        elif len({(m.get("mod_loader") or "").lower() for m in matches}) > 1:
            avail = sorted({str(m.get("mod_loader") or "?") for m in matches})
            print_error(
                f"Mod '{addon_id}' is installed for multiple loaders. "
                f"Pick one with: delete-addon mod {addon_id} <loader>"
            )
            print_hint("Loaders: " + ", ".join(avail))
            return

        target = matches[0]
        mod_loader = str(target.get("mod_loader") or "").lower()
        mod_slug = str(target.get("mod_slug") or addon_id)

        version_label: str | None = None
        versions = [v for v in (target.get("versions") or []) if isinstance(v, dict)]
        if len(versions) > 1:
            labels = [
                str(v.get("version_label") or v.get("version") or "?") for v in versions
            ]
            options = [f"(all {len(versions)} versions)"] + labels
            choice = select_one(
                "Delete addon",
                f"Delete which version of {mod_slug}?",
                options,
                default=0,
            )
            if choice is None:
                print_info("Cancelled.")
                return
            if choice > 0:
                version_label = labels[choice - 1]

        what = mod_slug + (f"/{version_label}" if version_label else "")
        if not confirm(
            "Delete addon",
            f"Delete mod {what} ({mod_loader})?",
            yes_label="Delete", no_label="Keep",
            default_yes=False, kind="warn",
        ):
            print_info("Cancelled.")
            return

        payload = {
            "addon_type": "mods",
            "mod_id": mod_slug,
            "mod_slug": mod_slug,
            "mod_loader": mod_loader,
        }
        if version_label:
            payload["version_label"] = version_label
        with scope_override(state, "addons"):
            from server.api.routes.mods import api_mods_delete
            result = api_mods_delete(payload)
        if not result.get("ok"):
            print_error(result.get("error") or "Delete failed.")
            return
        print_success(f"Deleted mod {what} ({mod_loader}).")
        return

    if not confirm(
        "Delete addon",
        f"Delete {addon_type} '{addon_id}'?",
        yes_label="Delete", no_label="Keep",
        default_yes=False, kind="warn",
    ):
        print_info("Cancelled.")
        return
    with scope_override(state, "addons"):
        from server.api.routes.mods import api_mods_delete
        result = api_mods_delete({
            "addon_type": addon_type,
            "mod_id": addon_id,
            "mod_slug": addon_id,
        })
    if not result.get("ok"):
        print_error(result.get("error") or "Delete failed.")
        return
    print_success(f"Deleted {addon_type} '{addon_id}'.")


def _cmd_toggle_addon(state: CliState, args: list[str]) -> None:
    if len(args) < 2:
        print_error("Usage: toggle-addon <type> <addonID>")
        return
    addon_type = _normalize_type(args[0])
    if not addon_type:
        print_error(f"Unknown addon type: {args[0]}")
        return
    addon_id = args[1]
    with scope_override(state, "addons"):
        from server.api.routes.mods import api_mods_toggle

        result = api_mods_toggle({"addon_type": addon_type, "mod_id": addon_id, "mod_slug": addon_id})
    if not result.get("ok"):
        print_error(result.get("error") or "Toggle failed.")
        return
    print_success(f"Toggled {addon_type} '{addon_id}'.")


def _cmd_import_addon(state: CliState, args: list[str]) -> None:
    import os

    if len(args) < 2:
        print_error("Usage: import-addon <type> [loader] <path to file>")
        print_hint("type: mod | resourcepack | shaderpack | datapack | modpack")
        print_hint("loader (mods only): fabric | babric | forge | modloader | neoforge | quilt")
        return
    addon_type = _normalize_type(args[0])
    if not addon_type:
        print_error(f"Unknown addon type: {args[0]}")
        return
    rest = args[1:]
    mod_loader = ""
    if addon_type == "mods":
        loader = _normalize_loader(rest[0]) if rest else None
        if not loader or loader == "all":
            print_error("Mods require a loader: fabric | babric | forge | modloader | neoforge | quilt")
            return
        mod_loader = loader
        rest = rest[1:]
    path = os.path.expanduser(" ".join(rest).strip().strip('"'))
    if not path or not os.path.isfile(path):
        print_error(f"File not found: {path}")
        return
    payload = {"addon_type": addon_type, "file_path": path}
    if mod_loader:
        payload["mod_loader"] = mod_loader
    with scope_override(state, "addons"):
        from server.api.routes.mods import api_mods_import

        result = api_mods_import(payload) or {}
    if not result.get("ok"):
        print_error(result.get("error") or "Import failed.")
        return
    print_success(result.get("message") or f"Imported {addon_type} from {os.path.basename(path)}.")


register(Command(
    name="listAddons",
    summary="Search available addons or list installed ones.",
    handler=_cmd_list_addons,
    usage="listAddons <available|installed> <type> [provider] [modloader] [mc-version] [query] [page]",
    details="mode: available (search Modrinth/CurseForge) | installed (local addons)\n"
            "type: mod | modpack | resourcepack | shaderpack | datapack\n"
            "provider: modrinth | curseforge   (available only)\n"
            "modloader: all | fabric | babric | forge | modloader | neoforge | quilt\n"
            "mc-version: an installed version or 'all' (available only, default: all)",
    category="Addons",
    args=(
        ArgSpec("mode", ("available", "installed")),
        ArgSpec("type", ("mod", "modpack", "resourcepack", "shaderpack", "datapack")),
        ArgSpec("provider", ("modrinth", "curseforge")),
        ArgSpec("modloader", _LOADER_VALUES),
        ArgSpec("mcVersion", lambda state: _installed_version_values(state), required=False),
    ),
))
register(Command(
    name="addonDetails",
    summary="Show available files for an addon (use the addon's id).",
    handler=_cmd_addon_details,
    usage="addonDetails <type> <provider> <addonID>",
    category="Addons",
    args=(
        ArgSpec("type", ("mod", "modpack", "resourcepack", "shaderpack", "datapack")),
        ArgSpec("provider", ("modrinth", "curseforge")),
    ),
))
register(Command(
    name="installAddon",
    summary="Install a specific file of an addon by id.",
    handler=_cmd_install_addon,
    usage="installAddon <type> <provider> <addonID> <fileID>",
    category="Addons",
    args=(
        ArgSpec("type", ("mod", "modpack", "resourcepack", "shaderpack", "datapack")),
        ArgSpec("provider", ("modrinth", "curseforge")),
    ),
))
register(Command(
    name="deleteAddon",
    summary="Delete an installed addon by id.",
    handler=_cmd_delete_addon,
    usage="deleteAddon <type> <addonID> [loader]",
    category="Addons",
    args=(
        ArgSpec("type", ("mod", "modpack", "resourcepack", "shaderpack", "datapack")),
        ArgSpec("addonID"),
        ArgSpec("loader", _LOADER_VALUES, required=False),
    ),
))
register(Command(
    name="importAddon",
    summary="Install an addon from a local file (no store account needed).",
    handler=_cmd_import_addon,
    usage="importAddon <type> [loader] <path to file>",
    details="type: mod | resourcepack | shaderpack | datapack | modpack\n"
            "loader is only required for mods (fabric | babric | forge | modloader | neoforge | quilt).",
    category="Addons",
    args=(
        ArgSpec("type", ("mod", "modpack", "resourcepack", "shaderpack", "datapack")),
        ArgSpec("loader", _LOADER_VALUES, required=False),
    ),
))
register(Command(
    name="toggleAddon",
    summary="Enable or disable an installed addon.",
    handler=_cmd_toggle_addon,
    usage="toggleAddon <type> <addonID>",
    category="Addons",
    args=(ArgSpec("type", ("mod", "modpack", "resourcepack", "shaderpack", "datapack")),),
))


def _cmd_apply_datapack(state: CliState, args: list[str]) -> None:
    from server.api.routes.datapacks import api_datapacks_apply

    if len(args) < 2:
        print_error("Usage: applyDatapack <slug> <world_id> [storage_target]")
        return

    mod_slug = args[0].strip().lower()
    world_id = args[1].strip()
    storage_target = args[2].strip() if len(args) > 2 else "default"

    with scope_override(state, "addons"):
        result = api_datapacks_apply({
            "mod_slug": mod_slug,
            "world_ids": [world_id],
            "storage_target": storage_target,
        }) or {}

    if not result.get("ok"):
        print_error(result.get("error") or "Failed to apply datapack.")
        if result.get("errors"):
            for entry in result.get("errors") or []:
                if isinstance(entry, dict):
                    print_error(f"  {entry.get('world_id')}: {entry.get('error')}")
        return

    applied = result.get("applied") or []
    print_success(f"Applied '{mod_slug}' to {len(applied)} world(s).")


def _cmd_remove_datapack(state: CliState, args: list[str]) -> None:
    from server.api.routes.datapacks import api_datapacks_remove

    if len(args) < 2:
        print_error("Usage: removeDatapack <slug> <world_id> [storage_target]")
        return

    mod_slug = args[0].strip().lower()
    world_id = args[1].strip()
    storage_target = args[2].strip() if len(args) > 2 else "default"

    with scope_override(state, "addons"):
        result = api_datapacks_remove({
            "mod_slug": mod_slug,
            "world_id": world_id,
            "storage_target": storage_target,
        }) or {}

    if not result.get("ok"):
        print_error(result.get("error") or "Failed to remove datapack from world.")
        return

    print_success(result.get("message") or f"Removed '{mod_slug}' from '{world_id}'.")


def _cmd_list_datapack_deployments(state: CliState, args: list[str]) -> None:
    from server.api.routes.datapacks import api_datapacks_deployments

    mod_slug = args[0].strip().lower() if len(args) > 0 and not args[0].startswith("world:") else ""
    world_id = ""
    storage_target = "default"
    if len(args) > 0 and args[0].startswith("world:"):
        world_id = args[0][6:].strip()
    elif len(args) > 1:
        world_id = args[1].strip()

    payload: dict = {}
    if mod_slug:
        payload["mod_slug"] = mod_slug
    elif world_id:
        payload["world_id"] = world_id
        payload["storage_target"] = storage_target
    else:
        print_error("Usage: listDatapackDeployments <slug> | listDatapackDeployments world:<world_id>")
        return

    with scope_override(state, "addons"):
        result = api_datapacks_deployments(payload) or {}

    if not result.get("ok"):
        print_error(result.get("error") or "Failed to list datapack deployments.")
        return

    if mod_slug:
        deployments = result.get("deployments") or []
        print_section(f"Deployments for {result.get('mod_name') or mod_slug}")
        if not deployments:
            print_info("No world deployments.")
            return
        print_table(
            ("World", "Version", "Storage", "Filename"),
            [
                (
                    str(entry.get("world_id") or ""),
                    str(entry.get("version_label") or ""),
                    str(entry.get("storage_target") or "default"),
                    str(entry.get("deployed_filename") or ""),
                )
                for entry in deployments
                if isinstance(entry, dict)
            ],
        )
        return

    deployments = result.get("deployments") or []
    print_section(f"Datapacks applied to {world_id}")
    if not deployments:
        print_info("No launcher-managed datapacks on this world.")
        return
    print_table(
        ("Datapack", "Version", "Filename"),
        [
            (
                str(entry.get("mod_name") or entry.get("mod_slug") or ""),
                str(entry.get("version_label") or ""),
                str(entry.get("deployed_filename") or ""),
            )
            for entry in deployments
            if isinstance(entry, dict)
        ],
    )


register(Command(
    name="applyDatapack",
    summary="Apply an installed datapack to a world.",
    handler=_cmd_apply_datapack,
    usage="applyDatapack <slug> <world_id> [storage_target]",
    category="Addons",
))
register(Command(
    name="removeDatapack",
    summary="Remove a launcher-managed datapack from a world.",
    handler=_cmd_remove_datapack,
    usage="removeDatapack <slug> <world_id> [storage_target]",
    category="Addons",
))
register(Command(
    name="listDatapackDeployments",
    summary="List datapack world deployments by slug or world.",
    handler=_cmd_list_datapack_deployments,
    usage="listDatapackDeployments <slug> | listDatapackDeployments world:<world_id>",
    category="Addons",
))
