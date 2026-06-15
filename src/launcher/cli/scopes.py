from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, TypeVar

from launcher.cli.state import CliState


T = TypeVar("T")


@contextmanager
def scope_override(state: CliState, scope: str):
    override = state.scope_id(scope)
    if not override:
        yield
        return

    from core.settings import (
        get_active_scope_profile_id,
        set_active_scope_profile,
    )

    original = get_active_scope_profile_id(scope)
    swapped = False
    if str(original) != str(override):
        if set_active_scope_profile(scope, override):
            swapped = True
    try:
        yield
    finally:
        if swapped:
            try:
                set_active_scope_profile(scope, original)
            except Exception:
                pass


def with_scope(state: CliState, scope: str, fn: Callable[..., T], *args, **kwargs) -> T:
    with scope_override(state, scope):
        return fn(*args, **kwargs)
