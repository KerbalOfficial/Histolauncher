from __future__ import annotations

import errno
import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol

from core.downloader.errors import DownloadCancelled
from core.downloader.http import CLIENT, HttpClient
from core.downloader.jobs import Job
from core.downloader.progress import ProgressTracker
from core.logger import safe_print


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


STORAGE_HEADROOM_BYTES = 5 * 1024 * 1024
_MB = 1024 * 1024  # matches the UI's MB


def _disk_full_error(exc: Optional[BaseException]) -> Optional[OSError]:
    """The ENOSPC OSError behind exc (directly, as DownloadFailed.cause, or chained)."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, OSError) and (
            exc.errno == errno.ENOSPC or getattr(exc, "winerror", None) in (39, 112)
        ):
            return exc
        exc = getattr(exc, "cause", None) or exc.__cause__ or exc.__context__
    return None


def _free_bytes_near(path: str) -> int:
    path = os.path.abspath(path or ".")
    while not os.path.isdir(path) and os.path.dirname(path) != path:
        path = os.path.dirname(path)
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


class StageRunner:
    def __init__(self, stages: Iterable[Stage]) -> None:
        self._stages: List[Stage] = list(stages)

    def run(self, ctx: StageContext) -> None:
        for stage in self._stages:
            while True:
                ctx.checkpoint()
                if ctx.tracker.snapshot().get("error") == "insufficient_storage":
                    ctx.tracker.set_status("downloading", "Retrying...")  # clears the red state
                try:
                    stage.run(ctx)
                    break
                except DownloadCancelled:
                    raise
                except Exception as exc:
                    full = _disk_full_error(exc)
                    if full is None:
                        raise
                    # Pause instead of failing; Retry (resume) re-runs the stage,
                    # which skips files that already downloaded and verified.
                    self._pause_for_storage(ctx, full)

    @staticmethod
    def _pause_for_storage(ctx: StageContext, err: OSError) -> None:
        snap = ctx.tracker.snapshot()
        remaining = max(0, int(snap.get("bytes_total") or 0) - int(snap.get("bytes_done") or 0))
        free = _free_bytes_near(err.filename or ctx.data.get("version_dir") or "")
        need = max(remaining + STORAGE_HEADROOM_BYTES - free, STORAGE_HEADROOM_BYTES)
        message = f"Insufficient storage, need {need / _MB:.2f}MB more storage"
        safe_print(f"[install] {message} ({err})")
        ctx.tracker.set_status(
            "paused", message,
            extra={"error": "insufficient_storage", "storage_needed_bytes": need},
        )
        ctx.job.pause()


__all__ = [
    "FunctionStage",
    "Stage",
    "StageContext",
    "StageRunner",
]
