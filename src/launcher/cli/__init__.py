from __future__ import annotations

__all__ = ["run_cli"]


def run_cli(debug: bool = False) -> int:
    from launcher.cli.argv import extract_cli_command, has_debug_flag
    from launcher.cli.runtime import run, run_once

    debug = debug or has_debug_flag()
    _is_cli, command = extract_cli_command()
    if command:
        return run_once(command_tokens=command, debug=debug)
    return run(debug=debug)
