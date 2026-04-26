from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol

from core.downloader.errors import DownloadCancelled
from core.downloader.http import CLIENT, HttpClient
from core.downloader.jobs import Job
from core.downloader.progress import ProgressTracker


@dataclass
class StageContext:
    job: Job
    tracker: ProgressTracker
    http: HttpClient = field(default=CLIENT)

    data: Dict[str, Any] = field(default_factory=dict)

    # ---- conveniences ------------------------------------------------------

    def checkpoint(self) -> None:
        self.job.checkpoint()

    def update(
        self,
        stage: str,
        percent: float,
        message: str,
        *,
        bytes_done: Optional[int] = None,
        bytes_total: Optional[int] = None,
    ) -> None:
        self.tracker.update(
            stage, percent, message,
            bytes_done=bytes_done, bytes_total=bytes_total,
        )

    def cancel_check(self) -> Callable[[], None]:
        return self.job.checkpoint


class Stage(Protocol):
    name: str

    def run(self, ctx: StageContext) -> None:  # pragma: no cover - protocol
        ...


@dataclass
class FunctionStage:
    name: str
    func: Callable[[StageContext], None]

    def run(self, ctx: StageContext) -> None:
        self.func(ctx)


class StageRunner:
    def __init__(self, stages: Iterable[Stage]) -> None:
        self._stages: List[Stage] = list(stages)

    def run(self, ctx: StageContext) -> None:
        for stage in self._stages:
            ctx.checkpoint()
            try:
                stage.run(ctx)
            except DownloadCancelled:
                raise
            except Exception:
                # Stages are responsible for setting tracker error state if
                # they want a custom message; the runner just re-raises so
                # the JobRegistry can transition to FAILED.
                raise


__all__ = [
    "FunctionStage",
    "Stage",
    "StageContext",
    "StageRunner",
]
