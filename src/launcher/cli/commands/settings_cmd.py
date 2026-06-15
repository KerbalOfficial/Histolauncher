from __future__ import annotations

from launcher.cli.commands import ArgSpec, Command, register
from launcher.cli.scopes import scope_override
from launcher.cli.state import CliState
from launcher.cli.terminal import (
    BOLD, DIM, FG, c, print_error, print_hint, print_info, print_section,
    print_success, print_table, writeln,
)


_SETTING_META: dict[str, dict[str, str]] = {
    "username": {
        "display": "Username",
        "section": "Account",
        "type": "string",
        "details": "Minecraft display name used when launching the game (local accounts).",
    },
    "account_type": {
        "display": "Account type",
        "section": "Account",
        "type": "enum: Local | Histolauncher | Microsoft",
        "details": "Which authentication backend to use when launching the game.",
    },
    "min_ram": {
        "display": "Minimum RAM",
        "section": "Client",
        "type": "memory string (e.g. 2048M, 4G)",
        "details": "Minimum heap size passed to the JVM (-Xms).",
    },
    "max_ram": {
        "display": "Maximum RAM",
        "section": "Client",
        "type": "memory string (e.g. 4096M, 8G)",
        "details": "Maximum heap size passed to the JVM (-Xmx).",
    },
    "game_resolution_width": {
        "display": "Window width", "section": "Client", "type": "integer pixels",
    },
    "game_resolution_height": {
        "display": "Window height", "section": "Client", "type": "integer pixels",
    },
    "game_demo_mode": {
        "display": "Demo mode", "section": "Client", "type": "0 / 1",
    },
    "auto_optimize_launch_settings": {
        "display": "Auto-optimize launch settings",
        "section": "Client",
        "type": "0 / 1",
        "details": "Let Histolauncher pick smart JVM tuning based on installed RAM and version.",
    },
    "extra_jvm_args": {
        "display": "Extra JVM arguments", "section": "Client", "type": "string (space-separated)",
    },
    "selected_version": {
        "display": "Selected version", "section": "Client", "type": "string (category/folder)",
    },
    "favorite_versions": {
        "display": "Favorite versions", "section": "Client", "type": "comma-separated string",
    },
    "storage_directory": {
        "display": "Storage directory mode",
        "section": "Client",
        "type": "enum: global | version | custom",
    },
    "custom_storage_directory": {
        "display": "Custom storage directory", "section": "Client", "type": "string (path)",
    },
    "launcher_theme": {
        "display": "Launcher theme",
        "section": "Appearance",
        "type": "enum: dark | light | system | auto",
    },
    "launcher_ui_size": {
        "display": "Launcher UI size", "section": "Appearance", "type": "enum: compact | normal | large",
    },
    "launcher_language": {
        "display": "Launcher language", "section": "Appearance", "type": "ISO 639-1 code (e.g. en, es)",
    },
    "layout_density": {
        "display": "Layout density", "section": "Appearance", "type": "enum: compact | comfortable | spacious",
    },
    "compact_sidebar": {
        "display": "Compact sidebar", "section": "Appearance", "type": "0 / 1",
    },
    "player_preview_mode": {
        "display": "Player preview mode", "section": "Appearance", "type": "enum: 2d | 3d",
    },
    "allow_override_classpath_all_modloaders": {
        "display": "Allow classpath override for all modloaders",
        "section": "Mods",
        "type": "0 / 1",
    },
    "java_path": {
        "display": "Java path",
        "section": "Launcher",
        "type": "string (path or 'auto')",
        "details": "Custom Java executable. Use 'auto' to let Histolauncher detect a runtime.",
    },
    "url_proxy": {
        "display": "URL proxy",
        "section": "Launcher",
        "type": "string (http/https proxy URL)",
    },
    "low_data_mode": {
        "display": "Low data mode", "section": "Launcher", "type": "0 / 1",
    },
    "show_third_party_versions": {
        "display": "Show third-party versions",
        "section": "Launcher",
        "type": "0 / 1",
        "details": "Surface Omniarchive / community-curated versions in addition to Mojang.",
    },
    "discord_rpc_enabled": {
        "display": "Discord Rich Presence", "section": "Launcher", "type": "0 / 1",
    },
    "desktop_notifications_enabled": {
        "display": "Desktop notifications", "section": "Launcher", "type": "0 / 1",
    },
    "ygg_port": {
        "display": "Yggdrasil proxy port", "section": "Launcher", "type": "integer 1-65535",
    },
    "versions_view": {
        "display": "Versions view", "section": "Launcher", "type": "enum: grid | list",
    },
    "addons_view": {
        "display": "Addons view", "section": "Launcher", "type": "enum: grid | list",
    },
    "worlds_view": {
        "display": "Worlds view", "section": "Launcher", "type": "enum: grid | list",
    },
}


def _all_known_keys() -> list[str]:
    from core.settings.defaults import DEFAULTS

    keys: list[str] = []
    for section in DEFAULTS.values():
        keys.extend(section.keys())
    return sorted(keys)


def _meta(key: str) -> dict[str, str]:
    base = {"display": key, "section": "Other", "type": "string", "details": ""}
    base.update(_SETTING_META.get(key, {}))
    return base


def _cmd_help_settings(state: CliState, args: list[str]) -> None:
    if args:
        key = args[0]
        if key not in _all_known_keys():
            print_error(f"Unknown setting: {key}")
            print_hint("Run 'list-settings' to list every settings id.")
            return
        meta = _meta(key)
        print_section(f"Setting · {meta['display']}")
        writeln("  " + c("ID    : ", FG["muted"]) + c(key, BOLD, FG["accent"]))
        writeln("  " + c("Group : ", FG["muted"]) + c(meta["section"], FG["tag"]))
        writeln("  " + c("Type  : ", FG["muted"]) + c(meta["type"], FG["value"]))
        if meta["details"]:
            writeln("")
            writeln("  " + c(meta["details"], FG["fg"]))
        return

    rows = []
    for key in _all_known_keys():
        meta = _meta(key)
        rows.append((key, meta["display"], meta["section"], meta["type"]))
    print_section("All settings")
    print_table(("ID", "Display name", "Group", "Type"), rows)
    print_hint("Run 'list-settings <id>' for details, or 'get-setting <id>' to see the current value.")


def _cmd_show_setting(state: CliState, args: list[str]) -> None:
    if not args:
        print_error("Usage: get-setting <settingID>")
        return
    key = args[0]
    from core.settings import load_global_settings

    with scope_override(state, "settings"):
        settings = load_global_settings() or {}
    value = settings.get(key)
    if value is None:
        print_info(f"{key} = (not set; using default)")
        return
    writeln("  " + c(key, BOLD, FG["accent"]) + c(" = ", FG["muted"]) + c(str(value), FG["value"]))


def _cmd_set_setting(state: CliState, args: list[str]) -> None:
    if len(args) < 2:
        print_error('Usage: set-setting <settingID> <value>     (wrap strings in "quotes")')
        return
    key = args[0]
    if key not in _all_known_keys():
        print_error(f"Unknown setting: {key}")
        print_hint("Run 'list-settings' to see valid ids.")
        return
    value = args[1]
    try:
        from server.api.routes.settings import api_settings

        with scope_override(state, "settings"):
            result = api_settings({key: value})
    except Exception as exc:
        print_error(f"Failed to save: {exc}")
        return
    if not result.get("ok"):
        print_error(result.get("error") or result.get("message") or "Save failed.")
        return
    saved_settings = result.get("settings") or {}
    saved_value = saved_settings.get(key, value)
    print_success(f"{key} = {saved_value}")
    if key == "launcher_theme":
        try:
            from launcher.cli import cli_theme, tui
            applied = cli_theme.apply_theme(str(saved_value))
            tui.full_repaint()
            print_info(f"Applied theme: {applied}")
        except Exception as exc:
            print_error(f"Failed to apply theme: {exc}")


register(Command(
    name="listSettings",
    summary="List every setting id with its display name, group, and type.",
    handler=_cmd_help_settings,
    usage="listSettings [settingID]",
    details="With no argument, prints a table of every setting. Pass an id to see "
            "a detailed description.",
    category="Settings",
    aliases=("helpSettings",),
    args=(ArgSpec("settingID", lambda state: _all_known_keys(), required=False),),
))
register(Command(
    name="getSetting",
    summary="Print the current value of a setting.",
    handler=_cmd_show_setting,
    usage="getSetting <settingID>",
    category="Settings",
    aliases=("showSettingValue",),
    args=(ArgSpec("settingID", lambda state: _all_known_keys()),),
))
register(Command(
    name="setSetting",
    summary="Change a setting on the active (or scoped) settings profile.",
    handler=_cmd_set_setting,
    usage='setSetting <settingID> <value>',
    details='Wrap string values in double quotes, e.g. set-setting username "Player One".\n'
            'For booleans use 0 or 1.',
    category="Settings",
    args=(ArgSpec("settingID", lambda state: _all_known_keys()),),
))
