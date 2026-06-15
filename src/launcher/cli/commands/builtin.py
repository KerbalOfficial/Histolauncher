from __future__ import annotations

from launcher.cli.commands import ArgSpec, Command, REGISTRY, register
from launcher.cli.state import CliState
from launcher.cli.terminal import (
    BOLD, DIM, FG, c, clear_screen, print_error, print_hint, print_info,
    print_section, writeln,
)


def _cmd_help(state: CliState, args: list[str]) -> None:
    if args:
        target = args[0]
        cmd = REGISTRY.get(target)
        if not cmd:
            print_error(f"No such command: {target}")
            return
        print_section(cmd.name)
        writeln("  " + c(cmd.summary, FG["fg"]))
        if cmd.usage:
            writeln("")
            writeln("  " + c("Usage:", BOLD, FG["muted"]))
            writeln("    " + c(cmd.usage, FG["accent"]))
        if cmd.aliases:
            writeln("")
            writeln("  " + c("Aliases:", BOLD, FG["muted"]) + " " + c(", ".join(cmd.aliases), FG["tag"]))
        if cmd.details:
            writeln("")
            writeln("  " + c("Details:", BOLD, FG["muted"]))
            for line in cmd.details.splitlines():
                writeln("    " + c(line, FG["fg"]))
        return

    groups = REGISTRY.by_category()
    for category in sorted(groups):
        print_section(category)
        for cmd in groups[category]:
            name = c(cmd.name.ljust(22), BOLD, FG["primary"])
            summary = c(cmd.summary, FG["fg"])
            writeln(f"  {name} {summary}")
    writeln("")
    print_hint("Run 'help <command>' for usage details.")


def _cmd_clear(state: CliState, args: list[str]) -> None:
    clear_screen()


def _cmd_logs(state: CliState, args: list[str]) -> None:
    from launcher.cli import tui

    if not state.debug:
        print_error("The logs panel is only available in debug mode!")
        return
    if not args:
        pos = tui.get_logs_position()
        writeln("  " + c("Logs panel: ", FG["muted"]) + c(pos, BOLD, FG["accent"]))
        writeln("  " + c("Use: ", DIM, FG["muted"]) + c("logs <hide|show|toggle|bottom|top|left|right>", FG["fg"]))
        return
    action = args[0].lower()
    valid = {"hide", "show", "toggle", "bottom", "top", "left", "right"}
    if action not in valid:
        print_error(f"Unknown logs action: {action!r}. Try one of: {', '.join(sorted(valid))}.")
        return
    current = tui.get_logs_position()
    if action == "hide":
        target = "hidden"
    elif action == "show":
        target = "bottom" if current == "hidden" else current
    elif action == "toggle":
        target = "hidden" if current != "hidden" else "bottom"
    else:
        target = action
    tui.set_logs_position(target)
    print_info(f"Logs panel: {tui.get_logs_position()}")


def _cmd_mouse(state: CliState, args: list[str]) -> None:
    from launcher.cli import tui

    if not args:
        cur = "on" if tui.get_mouse_capture() else "off"
        writeln("  " + c("Mouse capture: ", FG["muted"]) + c(cur, BOLD, FG["accent"]))
        writeln("  " + c("Use: ", DIM, FG["muted"]) + c("mouse <on|off|toggle>", FG["fg"]))
        writeln("  " + c("When OFF you can click & drag to select text natively;", DIM, FG["muted"]))
        writeln("  " + c("wheel scrolling stops affecting the TUI (use PgUp/PgDn).", DIM, FG["muted"]))
        writeln("  " + c("(In Windows Terminal you can also hold Shift to select.)", DIM, FG["muted"]))
        return
    action = args[0].lower()
    if action == "on":
        tui.set_mouse_capture(True)
    elif action == "off":
        tui.set_mouse_capture(False)
    elif action == "toggle":
        tui.set_mouse_capture(not tui.get_mouse_capture())
    else:
        print_error(f"Unknown mouse action: {action!r}. Use on, off, or toggle.")
        return
    print_info(f"Mouse capture: {'on' if tui.get_mouse_capture() else 'off'}")


def _cmd_exit(state: CliState, args: list[str]) -> None:
    state.stop()


def _cmd_version(state: CliState, args: list[str]) -> None:
    mode = "debug" if state.debug else "user"
    writeln("  " + c(f"Histolauncher {state.version}", BOLD, FG["header"])
            + c(f"  ·  CLI ({mode} mode)", FG["muted"]))


def _cmd_about(state: CliState, args: list[str]) -> None:
    print_section("Histolauncher CLI")
    writeln("  An interactive command-line frontend for Histolauncher.")
    writeln("  Provides the same actions as the graphical launcher without")
    writeln("  requiring Tk/Tkinter, a webview runtime, or a desktop session.")
    writeln("")
    writeln("  " + c("Website:", BOLD, FG["muted"]) + " https://histolauncher.org/")
    writeln("  " + c("GitHub :", BOLD, FG["muted"]) + " https://github.com/KerbalOfficial/Histolauncher")
    writeln("  " + c("Wiki   :", BOLD, FG["muted"]) + " https://wiki.histolauncher.org/")


register(Command(
    name="help",
    summary="List commands, or show details about one command.",
    handler=_cmd_help,
    usage="help [command]",
    details="Without arguments, lists every command grouped by category.\n"
            "With a command name, prints the usage, aliases, and detailed help for that command.",
    category="General",
    aliases=("?",),
    args=(ArgSpec("command", lambda state: [c.name for c in REGISTRY.all()], required=False),),
))
register(Command(
    name="clear",
    summary="Clear the terminal screen.",
    handler=_cmd_clear,
    usage="clear",
    category="General",
    aliases=("cls",),
))
register(Command(
    name="logs",
    summary="Move, hide, or show the Logs panel (debug mode only).",
    handler=_cmd_logs,
    usage="logs [hide|show|toggle|bottom|top|left|right]",
    details="Run 'logs' with no arguments to print the current position.\n"
            "Positions: bottom (default), top, left, right.\n"
            "Use 'logs hide' / 'logs show' to collapse or restore the panel.\n"
            "In debug mode press Tab to switch keyboard scroll focus between\n"
            "the Output and Logs panels; the mouse wheel always scrolls the\n"
            "panel under the cursor.",
    category="General",
    args=(ArgSpec("action",
                  ("hide", "show", "toggle", "bottom", "top", "left", "right"),
                  required=False),),
))
register(Command(
    name="mouse",
    summary="Toggle mouse capture (turn off to select & copy text natively).",
    handler=_cmd_mouse,
    usage="mouse [on|off|toggle]",
    details="With mouse capture ON (default) the wheel scrolls the TUI buffers.\n"
            "Turn it OFF to fall back to native terminal click-drag selection;\n"
            "wheel scrolling then no longer affects the TUI (use PgUp/PgDn).\n"
            "In Windows Terminal you can also hold Shift while clicking to\n"
            "select text without turning capture off.",
    category="General",
    args=(ArgSpec("action", ("on", "off", "toggle"), required=False),),
))
register(Command(
    name="exit",
    summary="Quit Histolauncher CLI.",
    handler=_cmd_exit,
    usage="exit",
    category="General",
    aliases=("quit", "q"),
))
register(Command(
    name="version",
    summary="Print the Histolauncher version and CLI mode.",
    handler=_cmd_version,
    usage="version",
    category="General",
))
register(Command(
    name="about",
    summary="About Histolauncher and useful links.",
    handler=_cmd_about,
    usage="about",
    category="General",
))
