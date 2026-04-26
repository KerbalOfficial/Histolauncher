from __future__ import annotations

import json
import os
import shutil
import threading
import time
import zipfile
from typing import Any, Dict, List, Optional

from core import manifest
from core.downloader._paths import (
    ASSETS_INDEXES_DIR,
    ASSETS_OBJECTS_DIR,
    LIBRARY_STORE_DIR,
    ensure_install_dirs,
)
from core.downloader.errors import DownloadCancelled, DownloadFailed
from core.downloader.http import CLIENT, DownloadTask
from core.downloader.jobs import REGISTRY, Job, JobState
from core.downloader.library_store import link_into_version, store_path_for
from core.downloader.pipeline import FunctionStage, StageContext, StageRunner
from core.downloader.progress import (
    VANILLA_STAGES,
    ProgressTracker,
    delete_progress,
    write_progress_dict,
)
from core.logger import colorize_log
from core.notifications import send_desktop_notification
from core.settings import get_versions_profile_dir

from core.downloader._legacy.version_helpers import (
    _choose_asset_threads,
    _compute_total_size,
    _ensure_legacy_launchwrapper,
    _extract_extra_args,
    _extract_os_from_classifier_key,
    _infer_main_class_from_client_jar,
    _is_legacy_launchwrapper_family,
    _is_modern_assets,
    _normalize_storage_category,
    _parse_lwjgl_version,
    _resolve_library_artifact,
    _should_skip_library_for_version,
    _wiki_image_url,
)
from core.zip_utils import safe_extract_zip


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def vanilla_job_key(version_id: str, storage_category: str) -> str:
    return f"{storage_category}/{version_id}"


def _patch_progress_status(key: str, status: str, message: str) -> None:
    from core.downloader.progress import read_progress_dict, write_progress_dict

    existing = read_progress_dict(key) or {}
    existing.update({
        "status": status,
        "message": message,
    })
    write_progress_dict(key, existing)


def _version_dir_for_install(version_id: str, storage_category: str) -> str:
    storage_fs = _normalize_storage_category(storage_category)
    return os.path.join(get_versions_profile_dir(), storage_fs, version_id)


def _remove_cancelled_version_dir(version_id: str, storage_category: str) -> None:
    versions_root = os.path.realpath(get_versions_profile_dir())
    version_dir = os.path.realpath(_version_dir_for_install(version_id, storage_category))
    try:
        if os.path.commonpath([versions_root, version_dir]) != versions_root:
            return
    except ValueError:
        return

    if os.path.isdir(version_dir):
        shutil.rmtree(version_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def _stage_fetch_manifest(ctx: StageContext) -> None:
    ensure_install_dirs()
    version_id: str = ctx.data["version_id"]
    storage_category: str = ctx.data["storage_category"]
    include_third_party: bool = ctx.data["include_third_party"]

    ctx.update("version_json", 0, "Fetching version metadata...")
    print(colorize_log(f"[install] Starting install for {ctx.tracker.key}"))

    try:
        entry = manifest.get_version_entry(
            version_id, include_third_party=include_third_party,
        )
    except Exception as exc:  # noqa: BLE001
        raise DownloadFailed(f"failed to find version in manifest: {exc}") from exc

    version_url = entry.get("url")
    if not version_url:
        raise DownloadFailed("manifest entry missing version URL")

    try:
        vjson = manifest.fetch_version_json(version_url)
    except Exception as exc:  # noqa: BLE001
        raise DownloadFailed(f"failed to fetch version json: {exc}") from exc
    if not isinstance(vjson, dict):
        raise DownloadFailed("version json is not an object")

    full_assets: bool = ctx.data["full_assets"]
    total_size = _compute_total_size(vjson, version_id, full_assets)

    version_dir = _version_dir_for_install(version_id, storage_category)
    os.makedirs(version_dir, exist_ok=True)

    ctx.data.update({
        "entry": entry,
        "vjson": vjson,
        "version_dir": version_dir,
        "total_size": total_size,
        "bytes_done": 0,
        "copied_lib_basenames": [],
        "asset_index_name": None,
    })
    ctx.update(
        "version_json", 100, "Version metadata loaded",
        bytes_done=0, bytes_total=total_size,
    )


def _stage_download_client(ctx: StageContext) -> None:
    vjson: Dict[str, Any] = ctx.data["vjson"]
    version_dir: str = ctx.data["version_dir"]
    total_size: int = ctx.data["total_size"]
    bytes_done: int = ctx.data["bytes_done"]
    force_redownload: bool = ctx.data["force_redownload"]

    client_info = (vjson.get("downloads") or {}).get("client")
    if not client_info or not client_info.get("url"):
        raise DownloadFailed("version json missing client download info")

    client_size = int(client_info.get("size") or 0)
    client_path = os.path.join(version_dir, "client.jar")

    ctx.update(
        "client", 0, "Downloading client.jar...",
        bytes_done=bytes_done, bytes_total=total_size,
    )
    print(colorize_log(
        f"[install] Downloading client.jar ({client_size} bytes)"
    ))

    def cb(done: int, total: Optional[int]) -> None:
        ctx.checkpoint()
        pct = (done * 100.0 / total) if (total and total > 0) else 0.0
        ctx.update(
            "client", pct, "Downloading client.jar...",
            bytes_done=bytes_done + min(done, client_size),
            bytes_total=total_size,
        )

    ctx.http.download(
        client_info["url"], client_path,
        expected_sha1=client_info.get("sha1"),
        expected_size=client_size or None,
        progress_cb=cb,
        cancel_check=ctx.cancel_check(),
        force=force_redownload,
    )

    bytes_done += client_size
    ctx.data["bytes_done"] = bytes_done
    ctx.data["client_path"] = client_path
    ctx.update(
        "client", 100, "client.jar downloaded",
        bytes_done=bytes_done, bytes_total=total_size,
    )


def _stage_download_libraries(ctx: StageContext) -> None:
    vjson: Dict[str, Any] = ctx.data["vjson"]
    version_id: str = ctx.data["version_id"]
    version_dir: str = ctx.data["version_dir"]
    total_size: int = ctx.data["total_size"]
    bytes_done: int = ctx.data["bytes_done"]
    copied: List[str] = ctx.data["copied_lib_basenames"]
    force_redownload: bool = ctx.data["force_redownload"]

    libs: List[Dict[str, Any]] = vjson.get("libraries") or []
    total_libs = len(libs)

    highest_versions: Dict[str, int] = {}
    for lib in libs:
        artifact = _resolve_library_artifact(lib)
        if not artifact:
            continue
        base = os.path.basename(artifact.get("path") or "")
        ver = _parse_lwjgl_version(base)
        if ver is None:
            continue
        module = base.split("-")[0]
        if module not in highest_versions or ver > highest_versions[module]:
            highest_versions[module] = ver

    if total_libs == 0:
        ctx.update(
            "libraries", 100, "No libraries to download",
            bytes_done=bytes_done, bytes_total=total_size,
        )
        return

    print(colorize_log(f"[install] Downloading {total_libs} libraries"))
    done_libs = 0
    for lib in libs:
        ctx.checkpoint()

        artifact = _resolve_library_artifact(lib)
        if artifact:
            a_url = artifact.get("url")
            a_sha1 = artifact.get("sha1")
            a_path = artifact.get("path") or ""
            a_size = int(artifact.get("size") or 0)
            base_name = os.path.basename(a_path)

            if _should_skip_library_for_version(version_id, base_name, highest_versions):
                done_libs += 1
                ctx.update(
                    "libraries",
                    (done_libs * 100.0) / max(1, total_libs),
                    f"Libraries {done_libs}/{total_libs}",
                    bytes_done=bytes_done, bytes_total=total_size,
                )
                continue

            if a_url and a_path:
                store_file = store_path_for(a_path)

                def lib_cb(done_bytes: int, _total: Optional[int]) -> None:
                    ctx.checkpoint()
                    ctx.update(
                        "libraries",
                        (done_libs * 100.0) / max(1, total_libs),
                        f"Downloading library {done_libs + 1}/{total_libs}",
                        bytes_done=bytes_done + min(done_bytes, a_size),
                        bytes_total=total_size,
                    )

                ctx.http.download(
                    a_url, store_file,
                    expected_sha1=a_sha1,
                    expected_size=a_size or None,
                    progress_cb=lib_cb,
                    cancel_check=ctx.cancel_check(),
                    force=force_redownload,
                )
                bytes_done += a_size

                dest_lib = os.path.join(version_dir, base_name)
                link_into_version(store_file=store_file, version_dest=dest_lib)
                copied.append(base_name)

        done_libs += 1
        ctx.update(
            "libraries",
            (done_libs * 100.0) / max(1, total_libs),
            f"Libraries {done_libs}/{total_libs}",
            bytes_done=bytes_done, bytes_total=total_size,
        )

    ctx.data["bytes_done"] = bytes_done
    ctx.update(
        "libraries", 100, "Libraries downloaded",
        bytes_done=bytes_done, bytes_total=total_size,
    )

    _ensure_legacy_launchwrapper(version_id, version_dir, copied, ctx.tracker.key)


def _stage_download_natives(ctx: StageContext) -> None:
    vjson: Dict[str, Any] = ctx.data["vjson"]
    version_dir: str = ctx.data["version_dir"]
    total_size: int = ctx.data["total_size"]
    bytes_done: int = ctx.data["bytes_done"]
    libs: List[Dict[str, Any]] = vjson.get("libraries") or []
    force_redownload: bool = ctx.data["force_redownload"]

    total_natives = sum(
        len(((lib.get("downloads") or {}).get("classifiers") or {})) for lib in libs
    )
    if total_natives == 0:
        ctx.update(
            "natives", 100, "No natives to download",
            bytes_done=bytes_done, bytes_total=total_size,
        )
        return

    print(colorize_log(f"[install] Downloading {total_natives} native entries"))
    done = 0
    for lib in libs:
        classifiers = ((lib.get("downloads") or {}).get("classifiers") or {})
        for key, nat in classifiers.items():
            ctx.checkpoint()
            n_url = nat.get("url")
            n_sha1 = nat.get("sha1")
            n_path = nat.get("path") or ""
            n_size = int(nat.get("size") or 0)
            if not (n_url and n_path):
                done += 1
                continue

            store_file = store_path_for(n_path)

            def nat_cb(done_bytes: int, _total: Optional[int]) -> None:
                ctx.checkpoint()
                ctx.update(
                    "natives",
                    (done * 100.0) / max(1, total_natives),
                    f"Downloading natives {done + 1}/{total_natives}",
                    bytes_done=bytes_done + min(done_bytes, n_size),
                    bytes_total=total_size,
                )

            ctx.http.download(
                n_url, store_file,
                expected_sha1=n_sha1,
                expected_size=n_size or None,
                progress_cb=nat_cb,
                cancel_check=ctx.cancel_check(),
                force=force_redownload,
            )
            bytes_done += n_size

            os_name = _extract_os_from_classifier_key(key) or "unknown"
            target_dir = os.path.join(version_dir, "native", os_name)
            os.makedirs(target_dir, exist_ok=True)
            try:
                with zipfile.ZipFile(store_file, "r") as zf:
                    safe_extract_zip(zf, target_dir)
            except Exception as exc:  # noqa: BLE001
                raise DownloadFailed(
                    f"failed to extract natives from {n_path}: {exc}"
                ) from exc

            done += 1
            ctx.update(
                "natives",
                (done * 100.0) / max(1, total_natives),
                f"Natives {done}/{total_natives}",
                bytes_done=bytes_done, bytes_total=total_size,
            )

    ctx.data["bytes_done"] = bytes_done
    ctx.update(
        "natives", 100, "Natives downloaded",
        bytes_done=bytes_done, bytes_total=total_size,
    )


def _stage_download_assets(ctx: StageContext) -> None:
    vjson: Dict[str, Any] = ctx.data["vjson"]
    version_id: str = ctx.data["version_id"]
    full_assets: bool = ctx.data["full_assets"]
    total_size: int = ctx.data["total_size"]
    bytes_done: int = ctx.data["bytes_done"]
    force_redownload: bool = ctx.data["force_redownload"]

    assets_info = vjson.get("assetIndex") or {}
    assets_url = assets_info.get("url")
    asset_index_name = assets_info.get("id") or None
    assets_sha1 = assets_info.get("sha1")
    modern = _is_modern_assets(version_id)
    ctx.data["asset_index_name"] = asset_index_name

    if not (assets_url and asset_index_name):
        ctx.update(
            "assets", 100, "No assets required",
            bytes_done=bytes_done, bytes_total=total_size,
        )
        return

    ctx.update(
        "assets", 0, "Downloading asset index...",
        bytes_done=bytes_done, bytes_total=total_size,
    )
    index_path = os.path.join(ASSETS_INDEXES_DIR, f"{asset_index_name}.json")
    os.makedirs(os.path.dirname(index_path), exist_ok=True)

    ctx.http.download(
        assets_url, index_path,
        expected_sha1=assets_sha1,
        cancel_check=ctx.cancel_check(),
        force=force_redownload,
    )

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            idx_json = json.load(f)
    except Exception as exc:  # noqa: BLE001
        raise DownloadFailed(f"failed to read asset index: {exc}") from exc

    objects: Dict[str, Dict[str, Any]] = idx_json.get("objects") or {}
    keys = list(objects.keys())

    if full_assets and modern:
        asset_total = sum(int(obj.get("size") or 0) for obj in objects.values())
        total_size = bytes_done + asset_total
        ctx.data["total_size"] = total_size

    if modern and not full_assets:
        ctx.update(
            "assets", 100,
            "Assets will be downloaded by the game at runtime",
            bytes_done=bytes_done, bytes_total=total_size,
        )
        return

    total_assets = len(keys)
    if total_assets == 0:
        ctx.update(
            "assets", 100, "No assets to download",
            bytes_done=bytes_done, bytes_total=total_size,
        )
        return

    print(colorize_log(f"[install] Downloading {total_assets} assets"))

    progress_lock = threading.Lock()
    asset_count_done = 0
    asset_bytes_done = 0

    def make_cb(size: int):
        def _cb(done_bytes: int, _total: Optional[int]) -> None:
            ctx.checkpoint()
        return _cb

    tasks: List[DownloadTask] = []
    for k in keys:
        obj = objects[k]
        h = obj.get("hash")
        size = int(obj.get("size") or 0)
        if not h:
            continue
        subdir = h[0:2]
        obj_path = os.path.join(ASSETS_OBJECTS_DIR, subdir, h)
        obj_url = f"https://resources.download.minecraft.net/{subdir}/{h}"
        tasks.append(DownloadTask(
            url=obj_url, dest_path=obj_path,
            expected_sha1=h, expected_size=size or None,
            progress_cb=make_cb(size),
            force=force_redownload,
        ))

    asset_threads = _choose_asset_threads()

    def progress_after_task(size: int) -> None:
        nonlocal asset_count_done, asset_bytes_done
        with progress_lock:
            asset_count_done += 1
            asset_bytes_done += size
            ctx.update(
                "assets",
                (asset_count_done * 100.0) / max(1, total_assets),
                f"Assets {asset_count_done}/{total_assets}",
                bytes_done=bytes_done + asset_bytes_done,
                bytes_total=total_size,
            )

    for task in tasks:
        size = task.expected_size or 0
        latch = {"fired": False}
        def cb_for(s=size, l=latch):
            def _cb(done_bytes: int, _total: Optional[int]) -> None:
                ctx.checkpoint()
                if not l["fired"] and (s == 0 or done_bytes >= s):
                    l["fired"] = True
                    progress_after_task(s)
            return _cb
        task.progress_cb = cb_for()

    try:
        ctx.http.download_many(
            tasks,
            max_workers=asset_threads,
            cancel_check=ctx.cancel_check(),
        )
    except DownloadCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        print(colorize_log(f"[install] Asset batch reported error: {exc}"))

    ctx.data["bytes_done"] = bytes_done + asset_bytes_done
    ctx.update(
        "assets", 100, "Assets downloaded",
        bytes_done=ctx.data["bytes_done"], bytes_total=total_size,
    )


def _stage_finalize(ctx: StageContext) -> None:
    entry: Dict[str, Any] = ctx.data["entry"]
    vjson: Dict[str, Any] = ctx.data["vjson"]
    version_id: str = ctx.data["version_id"]
    version_dir: str = ctx.data["version_dir"]
    total_size: int = ctx.data["total_size"]
    bytes_done: int = ctx.data["bytes_done"]
    full_assets: bool = ctx.data["full_assets"]
    copied: List[str] = ctx.data["copied_lib_basenames"]
    asset_index_name: Optional[str] = ctx.data.get("asset_index_name")
    client_path: str = ctx.data.get("client_path") or os.path.join(version_dir, "client.jar")

    # Display image
    vtype = entry.get("type", "")
    img_url = _wiki_image_url(version_id, vtype)
    if img_url:
        try:
            ctx.update(
                "finalize", 0, "Downloading display image...",
                bytes_done=bytes_done, bytes_total=total_size,
            )
            display_path = os.path.join(version_dir, "display.png")
            ctx.http.download(
                img_url, display_path,
                cancel_check=ctx.cancel_check(),
                force=bool(ctx.data.get("force_redownload")),
            )
        except Exception:  # noqa: BLE001
            pass

    ctx.update(
        "finalize", 50, "Writing metadata...",
        bytes_done=bytes_done, bytes_total=total_size,
    )

    main_class = (vjson.get("mainClass") or "").strip()
    if not main_class:
        if _is_legacy_launchwrapper_family(version_id):
            main_class = "net.minecraft.launchwrapper.Launch"
        else:
            main_class = _infer_main_class_from_client_jar(client_path, version_id)

    extra_args = _extract_extra_args(vjson)
    if (
        not extra_args
        and main_class == "net.minecraft.launchwrapper.Launch"
        and _is_legacy_launchwrapper_family(version_id)
    ):
        extra_args = (
            "${auth_player_name} 0 "
            "--assetsDir ${game_assets} "
            "--tweakClass net.minecraft.launchwrapper.AlphaVanillaTweaker "
            "--gameDir ${game_directory}"
        )

    version_type = entry.get("type", "") or vjson.get("type", "")

    seen: set[str] = set()
    unique_libs: List[str] = []
    for name in copied:
        if name not in seen:
            seen.add(name)
            unique_libs.append(name)

    if _is_legacy_launchwrapper_family(version_id):
        priority = {
            "launchwrapper-1.6.jar": 0,
            "launchwrapper-1.5.jar": 1,
            "jopt-simple-4.5.jar": 2,
            "asm-all-4.1.jar": 3,
        }
        pos = {name: idx for idx, name in enumerate(unique_libs)}
        unique_libs = sorted(
            unique_libs,
            key=lambda n: (priority.get(str(n).lower(), 50), pos.get(n, 9999)),
        )

    cp_entries = ["client.jar"] + unique_libs
    classpath_str = ",".join(cp_entries)

    data_ini_path = os.path.join(version_dir, "data.ini")
    lines = [
        f"main_class={main_class}",
        f"classpath={classpath_str}",
        f"asset_index={asset_index_name or ''}",
        f"version_type={version_type}",
        f"full_assets={'true' if full_assets else 'false'}",
        f"total_size_bytes={total_size}",
    ]
    if extra_args:
        lines.append(f"extra_jvm_args={extra_args}")
    lines.append("launch_disabled=false")

    with open(data_ini_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    ctx.update(
        "finalize", 100, "Installation complete",
        bytes_done=bytes_done, bytes_total=total_size,
    )

    ctx.tracker.finish(
        status="installed",
        message="Installation complete",
        keep_seconds=0.5,
    )

    try:
        send_desktop_notification(
            title=f"[{version_id}] Installation complete!",
            message=f"Minecraft {version_id} has installed successfully!",
        )
    except Exception as exc:  # noqa: BLE001
        print(colorize_log(f"[install] Could not send notification: {exc}"))

    print(colorize_log(f"[install] Installation complete for {ctx.tracker.key}"))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


VANILLA_PIPELINE: List = [
    FunctionStage("version_json", _stage_fetch_manifest),
    FunctionStage("client", _stage_download_client),
    FunctionStage("libraries", _stage_download_libraries),
    FunctionStage("natives", _stage_download_natives),
    FunctionStage("assets", _stage_download_assets),
    FunctionStage("finalize", _stage_finalize),
]


def run_vanilla_install(
    job: Job,
    *,
    version_id: str,
    storage_category: str,
    full_assets: bool,
    include_third_party: bool,
    force_redownload: bool,
) -> None:
    tracker = ProgressTracker(
        key=job.key, kind="vanilla", stages=VANILLA_STAGES,
    )
    ctx = StageContext(
        job=job, tracker=tracker, http=CLIENT,
        data={
            "version_id": version_id,
            "storage_category": storage_category,
            "full_assets": full_assets,
            "include_third_party": include_third_party,
            "force_redownload": force_redownload,
        },
    )
    runner = StageRunner(VANILLA_PIPELINE)

    try:
        runner.run(ctx)
    except DownloadCancelled:
        if not force_redownload:
            _remove_cancelled_version_dir(version_id, storage_category)
        ctx.tracker.finish(
            status="cancelled",
            message="Installation cancelled",
            keep_seconds=0.5,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        write_progress_dict(job.key, {
            "status": "failed",
            "stage": "error",
            "stage_percent": 0,
            "overall_percent": 0,
            "message": str(exc),
            "bytes_done": 0,
            "bytes_total": 0,
        })

        def cleanup_failed() -> None:
            time.sleep(2.0)
            delete_progress(job.key)

        threading.Thread(target=cleanup_failed, daemon=True).start()
        raise


def install_version(
    version_id: str,
    storage_category: str = "Release",
    *,
    full_assets: bool = True,
    background: bool = True,
    include_third_party: bool = False,
    force_redownload: bool = False,
) -> Optional[Job]:
    key = vanilla_job_key(version_id, storage_category)

    def target(job: Job) -> None:
        run_vanilla_install(
            job,
            version_id=version_id,
            storage_category=storage_category,
            full_assets=full_assets,
            include_third_party=include_third_party,
            force_redownload=force_redownload,
        )

    if not background:
        from core.downloader.jobs import Job as _Job
        synthetic = _Job(key=key, kind="vanilla")
        synthetic._mark_running()
        try:
            target(synthetic)
        except DownloadCancelled:
            synthetic._mark_cancelled()
            raise
        except Exception:
            synthetic._mark_failed("install failed")
            raise
        else:
            synthetic._mark_completed()
        return None

    return REGISTRY.submit(key, "vanilla", target)


# ---- Control surface (cancel/pause/resume/status) -------------------------


def cancel_install(version_id: str, storage_category: str, *, wait_seconds: float = 0.0) -> bool:
    key = vanilla_job_key(version_id, storage_category)
    job = REGISTRY.get(key)
    ok = REGISTRY.cancel(key)
    _patch_progress_status(key, "cancelled", "Cancelling install...")
    if ok and job and wait_seconds > 0:
        job.wait(wait_seconds)
    return ok


def pause_install(version_id: str, storage_category: str) -> bool:
    key = vanilla_job_key(version_id, storage_category)
    ok = REGISTRY.pause(key)
    _patch_progress_status(key, "paused", "Install paused")
    return ok


def resume_install(version_id: str, storage_category: str) -> bool:
    key = vanilla_job_key(version_id, storage_category)
    ok = REGISTRY.resume(key)
    _patch_progress_status(key, "downloading", "Resuming install...")
    return ok


def is_installing(version_id: str, storage_category: str) -> bool:
    return REGISTRY.is_active(vanilla_job_key(version_id, storage_category))


def get_install_status(version_id: str, storage_category: str) -> Optional[Dict[str, Any]]:
    from core.downloader.progress import read_progress_dict

    key = vanilla_job_key(version_id, storage_category)
    data = read_progress_dict(key)
    if data:
        return data
    job = REGISTRY.get(key)
    if not job or job.state in (JobState.COMPLETED, JobState.CANCELLED, JobState.FAILED):
        return None
    return {
        "status": str(job.state.value),
        "stage": "version_json",
        "stage_percent": 0,
        "overall_percent": 0,
        "message": "",
        "bytes_done": 0,
        "bytes_total": 0,
    }


__all__ = [
    "VANILLA_PIPELINE",
    "cancel_install",
    "get_install_status",
    "install_version",
    "is_installing",
    "pause_install",
    "resume_install",
    "run_vanilla_install",
    "vanilla_job_key",
]
