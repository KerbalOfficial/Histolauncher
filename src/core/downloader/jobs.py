from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from core.downloader.errors import DownloadCancelled


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


JobListener = Callable[["Job", str], None]


@dataclass
class Job:
    key: str
    kind: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: JobState = JobState.PENDING
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    started_at: float = 0.0
    finished_at: float = 0.0

    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _pause: threading.Event = field(default_factory=threading.Event, repr=False)
    _finished: threading.Event = field(default_factory=threading.Event, repr=False)
    _state_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _listeners: List[JobListener] = field(default_factory=list, repr=False)

    # ---- Cancellation / pause ------------------------------------------------

    def cancel(self) -> None:
        self._cancel.set()
        self._pause.clear()

    def pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def is_paused(self) -> bool:
        return self._pause.is_set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        return self._finished.wait(timeout)

    def checkpoint(self) -> None:
        if self._cancel.is_set():
            raise DownloadCancelled()
        if self._pause.is_set():
            with self._state_lock:
                self.state = JobState.PAUSED
            self._notify("paused")
            while self._pause.is_set():
                if self._cancel.is_set():
                    raise DownloadCancelled()
                time.sleep(0.1)
            with self._state_lock:
                if self.state == JobState.PAUSED:
                    self.state = JobState.RUNNING
            self._notify("resumed")

    # ---- Listeners -----------------------------------------------------------

    def subscribe(self, listener: JobListener) -> None:
        with self._state_lock:
            self._listeners.append(listener)

    def _notify(self, event: str) -> None:
        with self._state_lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(self, event)
            except Exception:  # noqa: BLE001
                pass

    # ---- State transitions (driven by JobRegistry / runner) ------------------

    def _mark_running(self) -> None:
        with self._state_lock:
            self.state = JobState.RUNNING
            self.started_at = time.time()
        self._notify("started")

    def _mark_completed(self) -> None:
        with self._state_lock:
            self.state = JobState.COMPLETED
            self.finished_at = time.time()
        self._finished.set()
        self._notify("completed")

    def _mark_cancelled(self) -> None:
        with self._state_lock:
            self.state = JobState.CANCELLED
            self.finished_at = time.time()
        self._finished.set()
        self._notify("cancelled")

    def _mark_failed(self, error: str) -> None:
        with self._state_lock:
            self.state = JobState.FAILED
            self.error = error
            self.finished_at = time.time()
        self._finished.set()
        self._notify("failed")


class JobRegistry:
    def __init__(self, *, max_workers: Optional[int] = None) -> None:
        self._lock = threading.RLock()
        self._jobs: Dict[str, Job] = {}  # key -> latest job
        self._threads: Dict[str, threading.Thread] = {}
        self._max_workers = max_workers  # currently advisory; future use

    # ---- Submission ----------------------------------------------------------

    def submit(
        self,
        key: str,
        kind: str,
        target: Callable[[Job], None],
        *,
        metadata: Optional[Dict[str, Any]] = None,
        listeners: Optional[List[JobListener]] = None,
    ) -> Job:
        with self._lock:
            existing = self._jobs.get(key)
            if existing and existing.state in (JobState.RUNNING, JobState.PAUSED, JobState.PENDING):
                thread = self._threads.get(key)
                if thread and thread.is_alive():
                    return existing

            job = Job(key=key, kind=kind, metadata=dict(metadata or {}))
            for listener in listeners or ():
                job.subscribe(listener)
            self._jobs[key] = job

            def runner() -> None:
                job._mark_running()
                try:
                    target(job)
                except DownloadCancelled:
                    job._mark_cancelled()
                except Exception as exc:  # noqa: BLE001
                    job._mark_failed(str(exc))
                else:
                    if job.is_cancelled():
                        job._mark_cancelled()
                    else:
                        job._mark_completed()

            thread = threading.Thread(
                target=runner, name=f"job-{kind}-{key}", daemon=True
            )
            self._threads[key] = thread
            thread.start()
            return job

    # ---- Lookup --------------------------------------------------------------

    def get(self, key: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(key)

    def is_active(self, key: str) -> bool:
        job = self.get(key)
        if not job:
            return False
        return job.state in (JobState.RUNNING, JobState.PAUSED, JobState.PENDING)

    def all(self) -> List[Job]:
        with self._lock:
            return list(self._jobs.values())

    # ---- Control -------------------------------------------------------------

    def cancel(self, key: str) -> bool:
        job = self.get(key)
        if not job:
            return False
        job.cancel()
        return True

    def pause(self, key: str) -> bool:
        job = self.get(key)
        if not job:
            return False
        job.pause()
        return True

    def resume(self, key: str) -> bool:
        job = self.get(key)
        if not job:
            return False
        job.resume()
        return True

    # ---- Maintenance ---------------------------------------------------------

    def prune_finished(self, *, max_age_seconds: float = 3600.0) -> int:
        now = time.time()
        removed = 0
        with self._lock:
            for key in list(self._jobs.keys()):
                job = self._jobs[key]
                if job.state in (JobState.COMPLETED, JobState.CANCELLED, JobState.FAILED):
                    if job.finished_at and (now - job.finished_at) > max_age_seconds:
                        self._jobs.pop(key, None)
                        thread = self._threads.pop(key, None)
                        if thread is not None and not thread.is_alive():
                            pass
                        removed += 1
        return removed


REGISTRY = JobRegistry()


__all__ = [
    "Job",
    "JobListener",
    "JobRegistry",
    "JobState",
    "REGISTRY",
]
