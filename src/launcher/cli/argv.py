from __future__ import annotations

import sys

_CLI_FLAGS = frozenset({"--cli", "-c", "--cli-mode"})
_OPTION_FLAGS = frozenset({"--debug"})


def has_debug_flag(argv: list[str] | None = None) -> bool:
    args = argv if argv is not None else sys.argv[1:]
    return "--debug" in args


def extract_cli_command(argv: list[str] | None = None) -> tuple[bool, list[str]]:
    args = list(argv if argv is not None else sys.argv[1:])
    is_cli = False
    rest = []
    i = 0
    while i < len(args):
        if args[i] in _CLI_FLAGS:
            is_cli = True
            i += 1
            continue
        if args[i] in _OPTION_FLAGS:
            i += 1
            continue
        rest.append(args[i])
        i += 1
    if not is_cli:
        return False, []
    if rest and rest[0] == "--":
        rest = rest[1:]
    return True, rest


__all__ = ["extract_cli_command", "has_debug_flag"]
