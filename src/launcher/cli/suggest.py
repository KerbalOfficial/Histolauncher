from __future__ import annotations

import re
from typing import Callable, Optional

from launcher.cli.commands import ArgSpec, Registry
from launcher.cli.state import CliState

_TOKEN_RE = re.compile(r"\S+")
_MAX_ITEMS = 200


def _tokens(text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group()) for m in _TOKEN_RE.finditer(text)]


def _active_token(text: str, cursor: int) -> tuple[int, int, str]:
    toks = _tokens(text)
    for idx, (start, end, _tok) in enumerate(toks):
        if start <= cursor <= end:
            return idx, start, text[start:cursor]
    idx = sum(1 for (_s, end, _t) in toks if end <= cursor)
    return idx, cursor, ""


def _resolve_choices(spec: ArgSpec, state: CliState, cache: dict) -> list[str]:
    choices = spec.choices
    if callable(choices):
        key = id(spec)
        if key not in cache:
            try:
                cache[key] = list(choices(state) or [])
            except Exception:
                cache[key] = []
        return cache[key]
    return list(choices)


def _filter(values: list[str], prefix: str, make_item) -> list[dict]:
    if not prefix:
        return [make_item(v) for v in values]
    low = prefix.lower()
    starts = [make_item(v) for v in values if v.lower().startswith(low)]
    if starts:
        return starts
    return [make_item(v) for v in values if low in v.lower()]


def _payload(start: int, items: list[dict], title: str) -> Optional[dict]:
    if not items:
        return None
    return {"start": start, "items": items[:_MAX_ITEMS], "title": title}


def build_suggester(
    registry: Registry, state: CliState
) -> Callable[[str, int], Optional[dict]]:
    cache: dict = {}

    def suggest(buffer: str, cursor: int) -> Optional[dict]:
        try:
            return _suggest(registry, state, buffer, cursor, cache)
        except Exception:
            return None

    return suggest


def _suggest(
    registry: Registry,
    state: CliState,
    buffer: str,
    cursor: int,
    cache: dict,
) -> Optional[dict]:
    if not buffer or cursor <= 0 and not buffer[:cursor].strip():
        if not buffer.strip():
            return None

    idx, start, prefix = _active_token(buffer, cursor)

    # --- command name completion (first token) -----------------------------
    if idx == 0:
        items = _filter(
            [c.name for c in registry.all()],
            prefix,
            lambda name: {
                "label": name,
                "desc": (registry.get(name).summary if registry.get(name) else ""),
                "insert": name,
            },
        )
        return _payload(start, items, "")

    # --- argument completion (enum-style choices) --------------------------
    toks = _tokens(buffer)
    if not toks:
        return None
    cmd = registry.get(toks[0][2])
    if cmd is None or not cmd.args:
        return None
    arg_index = idx - 1
    if arg_index >= len(cmd.args):
        return None
    spec = cmd.args[arg_index]
    choices = _resolve_choices(spec, state, cache)
    if not choices:
        return None
    items = _filter(
        choices,
        prefix,
        lambda value: {"label": value, "desc": "", "insert": value},
    )
    return _payload(start, items, spec.name)
