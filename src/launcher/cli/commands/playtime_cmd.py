from __future__ import annotations

from launcher.cli.commands import Command, register
from launcher.cli.state import CliState
from launcher.cli.terminal import (
    BOLD, FG, c, print_info, print_section, print_table, writeln,
)


def _cmd_playtime(state: CliState, args: list[str]) -> None:
    from server.api.routes.playtime import api_playtime_stats

    result = api_playtime_stats(None) or {}
    stats = result.get("stats") or {}

    if not stats.get("has_data"):
        print_info("No playtime recorded yet. Launch a version to start tracking.")
        return

    print_section("Playtime summary")
    writeln("  " + c("Total played   : ", FG["muted"])
            + c(str(stats.get("total_duration_formatted") or "0m"), BOLD, FG["accent"]))
    writeln("  " + c("Sessions       : ", FG["muted"])
            + c(str(stats.get("total_sessions") or 0), FG["value"]))
    writeln("  " + c("Average session: ", FG["muted"])
            + c(str(stats.get("average_session_formatted") or "0m"), FG["value"]))
    writeln("  " + c("Longest session: ", FG["muted"])
            + c(str(stats.get("longest_session_formatted") or "0m"), FG["value"]))
    if stats.get("most_played_version"):
        writeln("  " + c("Most played    : ", FG["muted"])
                + c(str(stats.get("most_played_version")), FG["tag"])
                + c(f"  ({stats.get('most_played_version_formatted')})", FG["muted"]))

    by_version = stats.get("by_version") or []
    if by_version:
        rows = [
            (str(v.get("version") or "Unknown")[:24], str(v.get("duration_formatted") or "0m"))
            for v in by_version if isinstance(v, dict)
        ]
        print_section("By version")
        print_table(("Version", "Played"), rows)


register(Command(
    name="playtime",
    summary="Show total playtime, sessions, and a per-version breakdown.",
    handler=_cmd_playtime,
    usage="playtime",
    details="Reads the active profile's recorded sessions and prints overall "
            "stats plus the time played on each Minecraft version.",
    category="Playtime",
))
