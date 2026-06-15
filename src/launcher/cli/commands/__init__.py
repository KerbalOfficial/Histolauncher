from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Sequence, Union

from launcher.cli.state import CliState


ChoiceProvider = Union[Sequence[str], Callable[[CliState], Sequence[str]]]


@dataclass
class ArgSpec:
    name: str
    choices: ChoiceProvider = ()
    required: bool = True


@dataclass
class Command:
    name: str
    summary: str
    handler: Callable[[CliState, list[str]], None]
    usage: str = ""
    details: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    category: str = "General"
    args: tuple[ArgSpec, ...] = field(default_factory=tuple)


class Registry:
    def __init__(self) -> None:
        self._by_name: dict[str, Command] = {}
        self._ordered: list[Command] = []

    def register(self, cmd: Command) -> None:
        keys = [cmd.name.lower(), *(a.lower() for a in cmd.aliases)]
        for key in keys:
            self._by_name[key] = cmd
        self._ordered.append(cmd)

    def get(self, name: str) -> Command | None:
        return self._by_name.get((name or "").lower())

    def all(self) -> list[Command]:
        return list(self._ordered)

    def by_category(self) -> dict[str, list[Command]]:
        groups: dict[str, list[Command]] = {}
        for cmd in self._ordered:
            groups.setdefault(cmd.category, []).append(cmd)
        return groups


REGISTRY = Registry()


_KEBAB_RE = re.compile(r"(?<=[a-z0-9])([A-Z])")


def to_kebab(name: str) -> str:
    return _KEBAB_RE.sub(r"-\1", name).lower()


def register(cmd: Command) -> Command:
    old_name = cmd.name
    primary = to_kebab(old_name)

    aliases: list[str] = []

    def _add(alias: str) -> None:
        if alias and alias != primary and alias not in aliases:
            aliases.append(alias)

    _add(primary.replace("-", ""))
    for alias in cmd.aliases:
        alias_kebab = to_kebab(alias)
        _add(alias_kebab)
        _add(alias_kebab.replace("-", ""))

    cmd.name = primary
    cmd.aliases = tuple(aliases)

    if cmd.usage:
        head, sep, tail = cmd.usage.partition(" ")
        if head == old_name:
            cmd.usage = primary + sep + tail

    REGISTRY.register(cmd)
    return cmd


def build_registry() -> Registry:
    from launcher.cli.commands import (  # noqa: F401
        builtin,
        profiles_cmd,
        settings_cmd,
        versions_cmd,
        addons_cmd,
        loaders_cmd,
        account_cmd,
        system_cmd,
        playtime_cmd,
    )

    return REGISTRY
