from __future__ import annotations

import os
import shutil
import subprocess
from typing import List

from core.downloader._legacy.installer_subprocess import (
    _build_java_installer_command,
    _get_java_executable,
    _is_url_proxy_enabled,
)
from core.subprocess_utils import no_window_kwargs

from core.downloader._legacy.loaders.forge._context import ForgeContext
from core.downloader._legacy.loaders.forge._jar_inspect import find_runtime_jars


def run_legacy_installer_if_needed(ctx: ForgeContext) -> None:
    existing = find_runtime_jars([ctx.loader_dest_dir])
    if existing or not ctx.is_installer_archive:
        return

    print(
        "[forge] LaunchWrapper not found, attempting to run installer to "
        "finish installation"
    )
    try:
        java_exe = _get_java_executable() or "java"
        proxy_jvm_args: List[str] = []
        if _is_url_proxy_enabled():
            print(
                "[forge] URL proxy mode detected; installer JVM proxy flags "
                "disabled (online default, offline fallback enabled)"
            )

        candidate_arg_variants = [
            ["--installClient"],
            ["--installClient", ctx.version_dir],
            ["--installClient", "--installDir", ctx.version_dir],
        ]
        candidate_cmds = [
            _build_java_installer_command(
                java_exe, ctx.downloaded_artifact_path,
                args, proxy_jvm_args,
            )
            for args in candidate_arg_variants
        ]
        for cmd in candidate_cmds:
            try:
                print(
                    f"[forge] Running installer: {' '.join(cmd)} "
                    f"(cwd={ctx.version_dir})"
                )
                proc = subprocess.run(
                    cmd, cwd=ctx.version_dir,
                    capture_output=True, text=True, timeout=180,
                    **no_window_kwargs(),
                )
                print(
                    f"[forge] Installer exit {proc.returncode}; "
                    f"stdout[:1024]: {proc.stdout[:1024]!r}"
                )
                if proc.stderr:
                    print(
                        f"[forge] Installer stderr[:1024]: "
                        f"{proc.stderr[:1024]!r}"
                    )
                if proc.returncode == 0:
                    break
            except Exception as e:
                print(f"[forge] Installer invocation failed: {e}")
    except Exception as e:
        print(f"[forge] Error attempting to run installer: {e}")

    search_paths = [ctx.loader_dest_dir, ctx.version_dir]
    try:
        appdata = os.environ.get("APPDATA")
        if appdata:
            search_paths.append(
                os.path.join(appdata, ".minecraft", "libraries")
            )
    except Exception:
        pass

    found_runtimes = find_runtime_jars(search_paths)
    for src in found_runtimes:
        try:
            dst = os.path.join(ctx.loader_dest_dir, os.path.basename(src))
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                ctx.jars_copied += 1
                print(
                    "[forge] Copied runtime jar from installer output: "
                    f"{os.path.basename(src)}"
                )
        except Exception as e:
            print(
                f"[forge] Warning: could not copy runtime jar {src}: {e}"
            )

    if not found_runtimes:
        print(
            "[forge] Installer did not produce LaunchWrapper jars in known "
            "locations"
        )


__all__ = ["run_legacy_installer_if_needed"]
