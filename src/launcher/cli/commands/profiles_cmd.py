from __future__ import annotations

from launcher.cli.commands import ArgSpec, Command, register
from launcher.cli.dialogs import confirm
from launcher.cli.state import CliState
from launcher.cli.terminal import (
    FG, c, print_error, print_hint, print_info, print_section, print_success,
    print_table, writeln,
)


_SCOPES = ("versions", "addons", "settings")


def _normalize_scope(raw: str) -> str | None:
    s = (raw or "").strip().lower()
    if s in ("version", "versions"):
        return "versions"
    if s in ("mod", "mods", "addon", "addons"):
        return "addons"
    if s in ("setting", "settings"):
        return "settings"
    return None


def _cmd_list_profiles(state: CliState, args: list[str]) -> None:
    from core.settings import get_active_scope_profile_id, list_scope_profiles

    for scope in _SCOPES:
        try:
            profiles = list_scope_profiles(scope)
            active = get_active_scope_profile_id(scope)
        except Exception as exc:
            print_error(f"Failed to read {scope} profiles: {exc}")
            continue
        override = state.scope_id(scope)
        title = scope.capitalize() + " profiles"
        if override:
            title += f"  (CLI override: {override})"
        print_section(title)
        rows = []
        for profile in profiles:
            pid = str(profile.get("id") or "")
            name = str(profile.get("name") or pid)
            markers = []
            if pid == active:
                markers.append("active")
            if override and pid == override:
                markers.append("cli-scope")
            rows.append((pid, name, ", ".join(markers) or "-"))
        if not rows:
            writeln("  " + c("(no profiles)", FG["muted"]))
            continue
        print_table(("ID", "Display name", "Status"), rows)


def _set_scope_cmd(scope: str):
    def handler(state: CliState, args: list[str]) -> None:
        from core.settings import get_active_scope_profile_id, list_scope_profiles

        if not args:
            override = state.scope_id(scope)
            active = get_active_scope_profile_id(scope)
            print_info(f"Currently scoped to: {override or active} ({'override' if override else 'active'})")
            print_hint(f"Pass an id to override, or 'reset' to clear: {scope}Profile <id|reset>")
            return

        target = args[0].strip()
        if target.lower() == "reset":
            state.set_scope(scope, None)
            print_success(f"Cleared CLI scope override for {scope} profiles.")
            return

        profile_ids = {str(p.get("id")) for p in list_scope_profiles(scope)}
        if target not in profile_ids:
            print_error(f"Profile id '{target}' not found in {scope}.")
            print_hint("Run 'list-profiles' to see available ids.")
            return
        state.set_scope(scope, target)
        print_success(f"CLI {scope} commands now use profile '{target}'.")

    return handler


def _cmd_new_profile(state: CliState, args: list[str]) -> None:
    if len(args) < 2:
        print_error("Usage: new-profile <versions|addons|settings> <display name>")
        return
    scope = _normalize_scope(args[0])
    if scope is None:
        print_error(f"Unknown profile type: {args[0]}")
        return
    name = " ".join(args[1:]).strip()
    if not name:
        print_error("Display name is required.")
        return
    try:
        from core.settings import create_scope_profile

        profile = create_scope_profile(scope, name)
    except Exception as exc:
        print_error(f"Failed to create profile: {exc}")
        return
    pid = str(profile.get("id") or "")
    print_success(f"Created {scope} profile '{profile.get('name')}' (id: {pid}).")


def _cmd_delete_profile(state: CliState, args: list[str]) -> None:
    if len(args) < 2:
        print_error("Usage: delete-profile <versions|addons|settings> <id>")
        return
    scope = _normalize_scope(args[0])
    if scope is None:
        print_error(f"Unknown profile type: {args[0]}")
        return
    pid = args[1].strip()
    if not confirm("Delete profile",
                   f"Permanently delete {scope} profile '{pid}'?\n"
                   f"This removes its settings/data on disk.",
                   yes_label="Delete", no_label="Keep", default_yes=False, kind="warn"):
        print_info("Cancelled.")
        return
    try:
        from core.settings import delete_scope_profile

        ok = delete_scope_profile(scope, pid)
    except Exception as exc:
        print_error(f"Failed to delete profile: {exc}")
        return
    if not ok:
        print_error("Could not delete profile (cannot delete the Default or last profile).")
        return
    print_success(f"Deleted {scope} profile '{pid}'.")
    if state.scope_id(scope) == pid:
        state.set_scope(scope, None)


def _cmd_switch_profile(state: CliState, args: list[str]) -> None:
    if len(args) < 2:
        print_error("Usage: switch-profile <versions|addons|settings> <id>")
        return
    scope = _normalize_scope(args[0])
    if scope is None:
        print_error(f"Unknown profile type: {args[0]}")
        return
    pid = args[1].strip()
    try:
        from core.settings import set_active_scope_profile

        ok = set_active_scope_profile(scope, pid)
    except Exception as exc:
        print_error(f"Failed to switch profile: {exc}")
        return
    if not ok:
        print_error(f"Profile '{pid}' not found in {scope}.")
        return
    print_success(f"Active {scope} profile is now '{pid}'.")


def _cmd_rename_profile(state: CliState, args: list[str]) -> None:
    if len(args) < 3:
        print_error('Usage: rename-profile <versions|addons|settings> <id> "New Name"')
        return
    scope = _normalize_scope(args[0])
    if scope is None:
        print_error(f"Unknown profile type: {args[0]}")
        return
    pid = args[1].strip()
    new_name = " ".join(args[2:]).strip()
    if not new_name:
        print_error("A new display name is required.")
        return
    try:
        from core.settings import rename_scope_profile

        ok = rename_scope_profile(scope, pid, new_name)
    except Exception as exc:
        print_error(f"Failed to rename profile: {exc}")
        return
    if not ok:
        print_error(f"Profile '{pid}' not found in {scope}.")
        return
    print_success(f"Renamed {scope} profile '{pid}' to '{new_name}'.")



register(Command(
    name="listProfiles",
    summary="List Versions / Addons / Settings profiles with their IDs.",
    handler=_cmd_list_profiles,
    usage="listProfiles",
    category="Profiles",
))
register(Command(
    name="versionsProfile",
    summary="Set the CLI scope for Versions commands.",
    handler=_set_scope_cmd("versions"),
    usage="versionsProfile <id|reset>",
    details="Affects launch-version / list-versions / install-version. Use 'reset' to clear the override.",
    category="Profiles",
    args=(ArgSpec("id", ("reset",), required=False),),
))
register(Command(
    name="addonsProfile",
    summary="Set the CLI scope for Addons commands.",
    handler=_set_scope_cmd("addons"),
    usage="addonsProfile <id|reset>",
    details="Affects list-addons / install-addon / addon-details. Use 'reset' to clear the override.",
    category="Profiles",
    args=(ArgSpec("id", ("reset",), required=False),),
))
register(Command(
    name="settingsProfile",
    summary="Set the CLI scope for Settings commands.",
    handler=_set_scope_cmd("settings"),
    usage="settingsProfile <id|reset>",
    details="Affects set-setting / get-setting. Use 'reset' to clear the override.",
    category="Profiles",
    args=(ArgSpec("id", ("reset",), required=False),),
))
register(Command(
    name="newProfile",
    summary="Create a new Versions / Addons / Settings profile.",
    handler=_cmd_new_profile,
    usage='newProfile <versions|addons|settings> "Display Name"',
    aliases=("createProfile",),
    category="Profiles",
    args=(ArgSpec("scope", ("versions", "addons", "settings")),),
))
register(Command(
    name="renameProfile",
    summary="Rename a Versions / Addons / Settings profile.",
    handler=_cmd_rename_profile,
    usage='renameProfile <versions|addons|settings> <id> "New Name"',
    category="Profiles",
    args=(ArgSpec("scope", ("versions", "addons", "settings")),),
))
register(Command(
    name="deleteProfile",
    summary="Delete a Versions / Addons / Settings profile by id.",
    handler=_cmd_delete_profile,
    usage="deleteProfile <versions|addons|settings> <id>",
    details="Asks for confirmation. The Default profile and last remaining profile cannot be deleted.",
    category="Profiles",
    args=(ArgSpec("scope", ("versions", "addons", "settings")),),
))
register(Command(
    name="switchProfile",
    summary="Switch the active profile for a scope (persists across launches).",
    handler=_cmd_switch_profile,
    usage="switchProfile <versions|addons|settings> <id>",
    details="Unlike versions-profile/addons-profile/settings-profile (which only override for this CLI session), "
            "this writes the active profile to disk like the UI's profile switcher.",
    category="Profiles",
    args=(ArgSpec("scope", ("versions", "addons", "settings")),),
))
