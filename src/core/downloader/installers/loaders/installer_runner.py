from __future__ import annotations

import subprocess
import threading
from typing import Callable, List, Optional

from core.downloader.errors import DownloadCancelled, DownloadFailed
from core.downloader.installers.loaders._java import get_java_executable
from core.logger import safe_print
from core.subprocess_utils import no_window_kwargs


CancelCheck = Callable[[], None]
LineSink = Callable[[str], None]

DEFAULT_TIMEOUT_SECONDS: int = 600
KILL_GRACE_SECONDS: float = 5.0
CANCEL_POLL_INTERVAL: float = 0.25


def run_installer_jar(
    installer_jar: str,
    args: List[str],
    *,
    cwd: str,
    cancel_check: Optional[CancelCheck] = None,
    line_sink: Optional[LineSink] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    raise_on_failure: bool = True,
    output_lines_out: Optional[List[str]] = None,
) -> int:
    java = get_java_executable()
    if not java:
        raise DownloadFailed(
            "Java is required to run the loader installer but was not found. "
            "Please download Java and try again!",
            url=None,
        )

    cmd = [java, "-jar", installer_jar, *args]
    if line_sink:
        line_sink(f"[runner] {' '.join(cmd)}")
    else:
        safe_print(f"[loader-installer] {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            **no_window_kwargs(),
        )
    except OSError as exc:
        raise DownloadFailed(
            f"Could not start Java subprocess: {exc}", url=None
        ) from exc

    cancel_event = threading.Event()
    output_lines: List[str] = []

    # ---- stdout reader -------------------------------------------------------
    def _read_output() -> None:
        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                output_lines.append(line)
                if line_sink:
                    try:
                        line_sink(line)
                    except Exception:
                        pass
                else:
                    safe_print(f"[installer] {line}")
        except Exception:
            pass

    reader = threading.Thread(target=_read_output, daemon=True)
    reader.start()

    # ---- cancel watchdog -----------------------------------------------------
    def _watch_cancel() -> None:
        while not cancel_event.is_set() and proc.poll() is None:
            try:
                if cancel_check is not None:
                    cancel_check()
            except DownloadCancelled:
                cancel_event.set()
                _terminate(proc)
                return
            cancel_event.wait(CANCEL_POLL_INTERVAL)

    watcher = threading.Thread(target=_watch_cancel, daemon=True)
    if cancel_check is not None:
        watcher.start()

    # ---- wait for completion -------------------------------------------------
    try:
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        cancel_event.set()
        _terminate(proc)
        try:
            if proc.stdout is not None:
                proc.stdout.close()
        except Exception:
            pass
        try:
            if proc.stderr is not None:
                proc.stderr.close()
        except Exception:
            pass
        reader.join(timeout=1.0)
        raise DownloadFailed(
            f"Installer JAR timed out after {timeout}s", url=None
        )

    cancel_event.set()
    try:
        if proc.stdout is not None:
            proc.stdout.close()
    except Exception:
        pass
    try:
        if proc.stderr is not None:
            proc.stderr.close()
    except Exception:
        pass
    reader.join(timeout=2.0)
    if cancel_check is not None:
        watcher.join(timeout=1.0)

    if cancel_check is not None:
        try:
            cancel_check()
        except DownloadCancelled:
            raise

    if rc != 0:
        if output_lines_out is not None:
            output_lines_out.extend(output_lines)
        if not raise_on_failure:
            return rc
        tail = "\n".join(output_lines[-20:]) or "<no output>"
        raise DownloadFailed(
            f"Installer JAR failed (exit code {rc}). Last output:\n{tail}",
            url=None,
        )
    if output_lines_out is not None:
        output_lines_out.extend(output_lines)
    return rc


def _terminate(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=KILL_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=2.0)
    except Exception:
        pass


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "KILL_GRACE_SECONDS",
    "run_installer_jar",
]
