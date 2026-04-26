from __future__ import annotations

import hashlib
import json
import os
import traceback
from typing import Any, List, Optional

from core.downloader._legacy.progress import _maybe_abort, _update_progress
from core.downloader._legacy.transport import _safe_remove_file, download_file
from core.logger import colorize_log

from core.downloader._legacy.loaders.forge._const import MAVEN_REPOS
from core.downloader._legacy.loaders.forge._context import ForgeContext


def _read_libraries_metadata(ctx: ForgeContext) -> List[Any]:
    version_json_path = os.path.join(ctx.extraction_dir, "version.json")
    install_profile_path = os.path.join(ctx.extraction_dir, "install_profile.json")

    libraries: List[Any] = []

    if os.path.exists(version_json_path):
        try:
            with open(version_json_path, "r") as f:
                version_data = json.load(f)
            libraries = version_data.get("libraries", [])
            print(
                f"[forge] Found {len(libraries)} libraries in version.json "
                "(new format)"
            )
        except Exception as e:
            print(f"[forge] WARNING: Could not parse version.json: {e}")

    if not libraries and os.path.exists(install_profile_path):
        try:
            with open(install_profile_path, "r") as f:
                install_data = json.load(f)
            version_info = install_data.get("versionInfo", {})
            libraries = version_info.get("libraries", [])
            if libraries:
                print(
                    f"[forge] Found {len(libraries)} libraries in "
                    "install_profile.json versionInfo (old format)"
                )
        except Exception as e:
            print(
                f"[forge] WARNING: Could not parse install_profile.json: {e}"
            )

    return libraries


def _coord_to_paths(
    lib_name: str, loader_libraries_dir: str
) -> Optional[tuple[str, str, list[str]]]:
    parts = lib_name.split(":")
    if len(parts) < 3:
        return None
    group, artifact, version = parts[0].replace(".", "/"), parts[1], parts[2]
    jar_name = f"{artifact}-{version}.jar"
    jar_path = os.path.join(
        loader_libraries_dir, group, artifact, version, jar_name
    )
    maven_path = f"{group}/{artifact}/{version}/{jar_name}"
    return jar_path, maven_path, list(MAVEN_REPOS)


def _sha1_of(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def _record_cached_lib(
    ctx: ForgeContext, jar_path: str, lib_name: str,
    libs_count: int, total: int, bytes_done: int, bytes_total: int,
    downloaded_libs: set[str],
) -> tuple[int, int]:
    libs_count += 1
    pct = (libs_count * 100.0) / max(1, total)
    try:
        bytes_done += os.path.getsize(jar_path)
    except Exception:
        pass
    _update_progress(
        ctx.version_key, "downloading_libs", pct,
        f"Libraries {libs_count}/{total}",
        bytes_done, bytes_total,
    )
    downloaded_libs.add(lib_name)
    if libs_count <= 15:
        print(f"[forge] Already cached: {lib_name}")
    return libs_count, bytes_done


def download_metadata_libraries(ctx: ForgeContext) -> Optional[str]:
    os.makedirs(ctx.loader_libraries_dir, exist_ok=True)

    libraries = _read_libraries_metadata(ctx)
    if not libraries:
        print(
            "[forge] WARNING: No library metadata found "
            "(version.json or install_profile.json)!"
        )
        return None

    try:
        print(
            f"[forge] Processing {len(libraries)} libraries from Forge metadata"
        )
        downloaded_libs: set[str] = set()
        libs_count = 0

        bytes_done = 0
        bytes_total = 0
        for lib in libraries:
            try:
                if isinstance(lib, dict):
                    artifact_info = (
                        (lib.get("downloads") or {}).get("artifact") or {}
                    )
                    size_hint = artifact_info.get("size")
                    if size_hint is not None:
                        bytes_total += int(size_hint)
            except Exception:
                continue

        for lib in libraries:
            lib_name = lib.get("name", "") if isinstance(lib, dict) else lib
            if not lib_name or (
                "net.minecraftforge:forge:" in lib_name and ":client" in lib_name
            ):
                continue
            if lib_name in downloaded_libs:
                continue

            download_url: Optional[str] = None
            expected_sha1: Optional[str] = None
            jar_path: Optional[str] = None
            maven_repos: List[str] = []
            maven_path = ""

            if isinstance(lib, dict) and lib.get("downloads"):
                artifact_info = lib.get("downloads", {}).get("artifact")
                if artifact_info:
                    download_url = artifact_info.get("url", "")
                    expected_sha1 = artifact_info.get("sha1", "")
                    artifact_path = artifact_info.get("path", "")
                    if artifact_path:
                        jar_path = os.path.join(
                            ctx.loader_libraries_dir, artifact_path
                        )
            else:
                resolved = _coord_to_paths(lib_name, ctx.loader_libraries_dir)
                if resolved is not None:
                    jar_path, maven_path, maven_repos = resolved
                    download_url = maven_repos[0] + maven_path

            if not jar_path:
                resolved = _coord_to_paths(lib_name, ctx.loader_libraries_dir)
                if resolved is None:
                    print(f"[forge] WARNING: Invalid library name: {lib_name}")
                    continue
                jar_path, _, _ = resolved

            if not download_url:
                print(f"[forge] WARNING: No download URL for {lib_name}")
                continue

            os.makedirs(os.path.dirname(jar_path), exist_ok=True)

            # already-on-disk handling (with optional sha verify)
            if os.path.exists(jar_path):
                if expected_sha1:
                    try:
                        if _sha1_of(jar_path) == expected_sha1:
                            libs_count, bytes_done = _record_cached_lib(
                                ctx, jar_path, lib_name, libs_count,
                                len(libraries), bytes_done, bytes_total,
                                downloaded_libs,
                            )
                            continue
                    except Exception as e:
                        print(
                            f"[forge] WARNING: Could not verify {lib_name}: {e}"
                        )
                else:
                    libs_count, bytes_done = _record_cached_lib(
                        ctx, jar_path, lib_name, libs_count,
                        len(libraries), bytes_done, bytes_total,
                        downloaded_libs,
                    )
                    continue

            # build the URL fallback list
            urls_to_try: List[str] = [download_url] if download_url else []
            if maven_repos and maven_path and len(urls_to_try) > 0:
                for repo in maven_repos[1:]:
                    urls_to_try.append(repo + maven_path)

            for try_idx, try_url in enumerate(urls_to_try):
                try:
                    _maybe_abort(ctx.version_key)
                    pct = (libs_count * 100.0) / max(1, len(libraries))
                    _update_progress(
                        ctx.version_key, "downloading_libs", pct,
                        f"Downloading {lib_name} "
                        f"({libs_count + 1}/{len(libraries)})...",
                        bytes_done, bytes_total,
                    )

                    if try_idx == 0:
                        print(colorize_log(f"[forge] Downloading: {lib_name}"))
                    else:
                        print(colorize_log(
                            f"[forge] Retrying {lib_name} from different repo..."
                        ))

                    download_file(
                        try_url, jar_path,
                        version_key=ctx.version_key, progress_cb=None,
                    )

                    if expected_sha1:
                        actual_sha1 = _sha1_of(jar_path)
                        if actual_sha1 != expected_sha1:
                            print(colorize_log(
                                f"[forge] ERROR: SHA1 mismatch for {lib_name}"
                            ))
                            print(colorize_log(f"[forge] Expected: {expected_sha1}"))
                            print(colorize_log(f"[forge] Got: {actual_sha1}"))
                            os.remove(jar_path)
                            continue

                    ctx.jars_copied += 1
                    downloaded_libs.add(lib_name)
                    libs_count += 1
                    pct = (libs_count * 100.0) / max(1, len(libraries))
                    try:
                        bytes_done += os.path.getsize(jar_path)
                    except Exception:
                        pass
                    _update_progress(
                        ctx.version_key, "downloading_libs", pct,
                        f"Libraries {libs_count}/{len(libraries)}",
                        bytes_done, bytes_total,
                    )
                    if libs_count <= 15:
                        print(colorize_log(
                            f"[forge] Downloaded to: "
                            f"{os.path.relpath(jar_path, ctx.loader_dest_dir)}"
                        ))
                    break

                except RuntimeError as e:
                    if "cancel" in str(e).lower():
                        print(colorize_log(
                            "[forge] Download cancelled - cleaning up"
                        ))
                        _safe_remove_file(jar_path)
                        raise
                    if try_url == urls_to_try[-1]:
                        print(colorize_log(
                            f"[forge] ERROR: Failed to download {lib_name} "
                            f"from any repo: {e}"
                        ))
                except Exception as e:
                    if try_url == urls_to_try[-1]:
                        print(colorize_log(
                            f"[forge] ERROR: Failed to download {lib_name} "
                            f"from any repo: {e}"
                        ))

        print(colorize_log(
            f"[forge] Successfully downloaded {ctx.jars_copied} libraries "
            "from Forge metadata"
        ))
        return None

    except RuntimeError as e:
        if "cancel" in str(e).lower():
            print(colorize_log("[forge] Library download cancelled"))
            raise
        print(colorize_log(
            f"[forge] ERROR: Could not process Forge metadata: {e}"
        ))
        traceback.print_exc()
        return f"Failed to download Forge libraries: {e}"
    except Exception as e:
        print(colorize_log(
            f"[forge] ERROR: Could not process Forge metadata: {e}"
        ))
        traceback.print_exc()
        return None


__all__ = ["download_metadata_libraries"]
