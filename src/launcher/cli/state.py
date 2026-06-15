from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CliState:
    debug: bool = False
    version: str = "unknown"
    one_shot: bool = False
    scope_overrides: dict[str, str] = field(default_factory=dict)
    running: bool = True
    server_port: int | None = None
    server: object | None = None
    server_error: str | None = None
    history: list[str] = field(default_factory=list)

    def scope_id(self, scope: str) -> str | None:
        return self.scope_overrides.get(scope)

    def set_scope(self, scope: str, profile_id: str | None) -> None:
        if profile_id is None:
            self.scope_overrides.pop(scope, None)
        else:
            self.scope_overrides[scope] = profile_id

    def stop(self) -> None:
        self.running = False
