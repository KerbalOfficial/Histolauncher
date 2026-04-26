from __future__ import annotations

import json
import os
import shutil
import tempfile
import urllib.parse
from typing import Dict, List, Optional, Tuple

from core.downloader.errors import DownloadCancelled, DownloadFailed
from core.downloader.http import CLIENT
from core.downloader.installers.loaders import _lib_harvest, fake_mc_dir as fake_mc_mod
from core.downloader.installers.loaders.installer_runner import run_installer_jar
from core.downloader.jobs import Job
from core.downloader.progress import LOADER_STAGES, ProgressTracker
from core.logger import colorize_log
from core.zip_utils import safe_extract_zip


# Substrings that, when present in installer output, indicate the run failed
# because of a network/proxy/certificate problem rather than a real error.
_NETWORK_FAILURE_MARKERS: Tuple[str, ...] = (
    "failed to validate certificates",
    "unsupported or unrecognized ssl message",
    "error checking https://",
    "sslhandshakeexception",
    "unable to tunnel through proxy",
)

# JAR paths the installer always re-emits with patched bytes — these MUST
# overwrite any earlier copy from the bundled installer ZIP.
def _neoforge_overwrite_predicate(rel: str, src: str, dest: str) -> bool:
    norm = rel.replace("\\", "/").lower()
    if norm.startswith("net/minecraft/client/") and (
        norm.endswith("-srg.jar")
        or norm.endswith("-slim.jar")
        or norm.endswith("-extra.jar")
    ):
        return True
    if norm.startswith("net/neoforged/neoforge/") and norm.endswith("-client.jar"):
        return True
    try:
        return os.path.getsize(src) != os.path.getsize(dest)
    except OSError:
        return True


def _try_download_installer(
    artifact_urls: List[str],
    *,
    dest_dir: str,
    job: Job,
    tracker: ProgressTracker,
) -> Tuple[str, str]:
    last_error: Optional[BaseException] = None
    for url in artifact_urls:
        name = (
            os.path.basename(urllib.parse.urlparse(url).path)
            or "neoforge-artifact.jar"
        )
        if "-installer.jar" not in name.lower():
            print(colorize_log(
                f"[neoforge] skipping non-installer artifact {name}"
            ))
            continue
        path = os.path.join(dest_dir, name)
        print(colorize_log(f"[neoforge] downloading installer from {url}"))

        def _progress(done: int, total: int, *, _name: str = name) -> None:
            job.checkpoint()
            pct = (done / total * 100) if total > 0 else 0
            tracker.update(
                "download", min(pct, 99.0),
                f"Downloading {_name} {int(pct)}%",
                bytes_done=done, bytes_total=total,
            )

        try:
            CLIENT.download(
                url, path,
                progress_cb=_progress,
                cancel_check=job.checkpoint,
            )
            if os.path.getsize(path) > 0:
                return (path, name)
        except DownloadCancelled:
            raise
        except Exception as exc:
            last_error = exc
            print(colorize_log(f"[neoforge] {url} failed: {exc}"))
            try:
                os.remove(path)
            except OSError:
                pass

    raise DownloadFailed(
        f"Could not download any NeoForge installer artifact "
        f"(last error: {last_error or 'all URLs failed'})",
        url=None,
    )


def _pre_stage_bundled_libs(
    *, installer_jar: str, fake_libs_dir: str, loader_libs_dir: str,
) -> Tuple[int, int]:
    with tempfile.TemporaryDirectory(prefix="neoforge-zip-") as extract:
        try:
            safe_extract_zip(installer_jar, extract)
        except Exception as exc:
            raise DownloadFailed(
                f"Failed to extract NeoForge installer: {exc}", url=None,
            ) from exc

        jars_staged = 0
        for root, _, files in os.walk(extract):
            for fn in files:
                if not fn.endswith(".jar"):
                    continue
                src = os.path.join(root, fn)
                rel = os.path.relpath(src, extract).replace("\\", "/")
                if rel.upper().startswith("META-INF/"):
                    continue
                for base in (fake_libs_dir, loader_libs_dir):
                    dst = os.path.join(base, rel.replace("/", os.sep))
                    if os.path.exists(dst):
                        continue
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    try:
                        shutil.copy2(src, dst)
                    except Exception as exc:
                        print(colorize_log(
                            f"[neoforge] could not stage {fn}: {exc}"
                        ))
                jars_staged += 1

        configs_copied = 0
        for root, _, files in os.walk(extract):
            for fn in files:
                lower = fn.lower()
                if lower in (
                    "log4j2.xml", "log4j.properties", "log4j.xml",
                    "bootstrap-shim.list",
                ) or lower.endswith(".properties"):
                    src = os.path.join(root, fn)
                    dst = os.path.join(loader_libs_dir, "..", fn)
                    try:
                        shutil.copy2(src, os.path.normpath(dst))
                        configs_copied += 1
                    except Exception:
                        pass

        # Read profile_id from version.json or install_profile.json so the
        # caller knows where the installer will write the profile.
        return (jars_staged, configs_copied)


def _read_profile_id(
    installer_jar: str, *, fallback: str,
) -> Tuple[str, Optional[Dict]]:
    profile_data: Optional[Dict] = None
    version_data: Optional[Dict] = None
    with tempfile.TemporaryDirectory(prefix="neoforge-meta-") as extract:
        try:
            safe_extract_zip(installer_jar, extract)
        except Exception:
            return (fallback, None)
        v_path = os.path.join(extract, "version.json")
        p_path = os.path.join(extract, "install_profile.json")
        if os.path.isfile(v_path):
            try:
                with open(v_path, "r", encoding="utf-8") as fp:
                    version_data = json.load(fp)
            except Exception:
                pass
        if os.path.isfile(p_path):
            try:
                with open(p_path, "r", encoding="utf-8") as fp:
                    profile_data = json.load(fp)
            except Exception:
                pass

    profile_id = (
        str((version_data or {}).get("id") or "").strip()
        or str((profile_data or {}).get("version") or "").strip()
        or fallback
    )
    return (profile_id, version_data)


def _snapshot_lib_sizes(libs_dir: str) -> Dict[str, int]:
    snap: Dict[str, int] = {}
    if not os.path.isdir(libs_dir):
        return snap
    for root, _, files in os.walk(libs_dir):
        for fn in files:
            if not fn.endswith(".jar"):
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, libs_dir).replace("\\", "/")
            try:
                snap[rel] = os.path.getsize(p)
            except OSError:
                snap[rel] = -1
    return snap


def _has_installer_output(
    *,
    expected_profile_json: str,
    fake_libs_dir: str,
    before_snapshot: Dict[str, int],
) -> bool:
    if os.path.isfile(expected_profile_json):
        return True
    after = _snapshot_lib_sizes(fake_libs_dir)
    for rel, size in after.items():
        if rel not in before_snapshot or before_snapshot.get(rel) != size:
            return True
    return False


_INSTALLER_ARG_VARIANTS = (
    ("--installClient", "{fake_mc}"),
    ("--installClient", "--installDir", "{fake_mc}"),
    ("--installClient",),
)


def install_neoforge(
    job: Job,
    *,
    mc_version: str,
    loader_version: str,
    install_dir: str,
    category: str,
    folder: str,
    version_key: str,
) -> None:
    from core.modloaders import get_neoforge_artifact_urls

    tracker = ProgressTracker(version_key, kind="loader", stages=LOADER_STAGES)
    tracker.set_status("running")

    # ---- prepare_vanilla --------------------------------------------------
    # We import here lazily to avoid a circular import chain on package init.
    from core.downloader.installers.loaders.pipeline import _ensure_vanilla_installed

    tracker.update("download", 0,
                   f"Starting NeoForge {loader_version} install...")
    _ensure_vanilla_installed(
        job=job, mc_version=mc_version, category=category, tracker=tracker,
    )

    # ---- resolve installer URLs ------------------------------------------
    job.checkpoint()
    tracker.update("download", 5, "Resolving NeoForge installer URLs...")
    artifact_urls = get_neoforge_artifact_urls(mc_version, loader_version)
    if not artifact_urls:
        raise DownloadFailed(
            f"Could not resolve NeoForge installer URLs for {mc_version}/{loader_version}",
            url=None,
        )

    fake_dir: Optional[str] = None
    try:
        with tempfile.TemporaryDirectory(prefix="histolauncher-neoforge-dl-") as dl_dir:
            installer_path, installer_name = _try_download_installer(
                artifact_urls, dest_dir=dl_dir, job=job, tracker=tracker,
            )

            # ---- build fake mc dir + pre-stage bundled libs --------------
            job.checkpoint()
            tracker.update("downloading_libs", 0,
                           "Preparing NeoForge install context...")
            fake_dir = tempfile.mkdtemp(prefix="histolauncher-neoforge-")
            fake_mc_mod.build(
                fake_mc_dir=fake_dir, mc_version=mc_version, category=category,
            )
            fake_libs_dir = os.path.join(fake_dir, "libraries")
            os.makedirs(fake_libs_dir, exist_ok=True)
            loader_libs_dir = os.path.join(install_dir, "libraries")
            os.makedirs(loader_libs_dir, exist_ok=True)
            metadata_dir = os.path.join(install_dir, ".metadata")
            os.makedirs(metadata_dir, exist_ok=True)

            tracker.update("downloading_libs", 5,
                           "Pre-staging NeoForge bundled libraries...")
            jars_staged, _configs = _pre_stage_bundled_libs(
                installer_jar=installer_path,
                fake_libs_dir=fake_libs_dir,
                loader_libs_dir=loader_libs_dir,
            )
            print(colorize_log(
                f"[neoforge] staged {jars_staged} embedded JARs"
            ))

            # ---- predict profile id --------------------------------------
            fallback_id = f"neoforge-{loader_version}"
            profile_id, embedded_version_data = _read_profile_id(
                installer_path, fallback=fallback_id,
            )
            if embedded_version_data is not None:
                # Persist a copy of the embedded version.json so the launch
                # system can read it even if the online installer step fails
                # outright (it usually still produces useful output).
                try:
                    with open(
                        os.path.join(metadata_dir, "version.json"),
                        "w", encoding="utf-8",
                    ) as fp:
                        json.dump(embedded_version_data, fp)
                except Exception:
                    pass

            expected_profile_json = os.path.join(
                fake_dir, "versions", profile_id, f"{profile_id}.json",
            )
            before_snapshot = _snapshot_lib_sizes(fake_libs_dir)

            # ---- run installer (variants + offline fallback) -------------
            installer_success, network_failure = _run_with_variants(
                installer_path=installer_path,
                fake_dir=fake_dir,
                fake_libs_dir=fake_libs_dir,
                expected_profile_json=expected_profile_json,
                before_snapshot=before_snapshot,
                tracker=tracker,
                job=job,
            )

            installer_output_ready = installer_success or _has_installer_output(
                expected_profile_json=expected_profile_json,
                fake_libs_dir=fake_libs_dir,
                before_snapshot=before_snapshot,
            )
            if not installer_output_ready:
                msg = (
                    "NeoForge installer did not produce a usable client "
                    "profile or runtime libraries"
                )
                if network_failure:
                    msg += "; check network/proxy/certificate access"
                raise DownloadFailed(msg, url=None)

            # ---- harvest produced libs into store + version dir ----------
            job.checkpoint()
            tracker.update("extracting_loader", 60,
                           "Harvesting NeoForge libraries into store...")

            def _harvest_progress(done: int, total: int) -> None:
                job.checkpoint()
                pct = 60 + 30 * (done / max(1, total))
                tracker.update(
                    "extracting_loader", pct,
                    f"Linking libraries {done}/{total}",
                )

            new_jars, replaced_jars = _lib_harvest.harvest_libraries(
                source_libraries_dir=fake_libs_dir,
                dest_libraries_dir=loader_libs_dir,
                overwrite_predicate=_neoforge_overwrite_predicate,
                cancel_check=job.checkpoint,
                progress_cb=_harvest_progress,
            )

            # ---- copy final profile JSON to .metadata/version.json -------
            if os.path.isfile(expected_profile_json):
                shutil.copy2(
                    expected_profile_json,
                    os.path.join(metadata_dir, "version.json"),
                )

            # ---- write metadata + data.ini -------------------------------
            mc_inherits = mc_version
            if embedded_version_data:
                mc_inherits = str(
                    embedded_version_data.get("inheritsFrom") or mc_version
                )
            main_class: Optional[str] = None
            try:
                with open(
                    os.path.join(metadata_dir, "version.json"),
                    "r", encoding="utf-8",
                ) as fp:
                    profile_doc = json.load(fp)
                main_class = profile_doc.get("mainClass") or None
            except Exception:
                profile_doc = None

            with open(
                os.path.join(install_dir, "neoforge_metadata.json"),
                "w", encoding="utf-8",
            ) as fp:
                json.dump(
                    {
                        "loader_type": "neoforge",
                        "neoforge_version": loader_version,
                        "mc_version": mc_inherits,
                        "profile_id": profile_id,
                        "embedded_jars": jars_staged,
                        "harvested_new_jars": new_jars,
                        "harvested_replaced_jars": replaced_jars,
                        "installer_success": installer_success,
                        "installer_artifact": installer_name,
                    },
                    fp, indent=2,
                )

            _write_data_ini(
                install_dir=install_dir,
                loader_version=loader_version,
                mc_version=mc_inherits,
                profile_id=profile_id,
                main_class=main_class,
            )

        tracker.finish(
            status="installed" if installer_success else "installed_with_warnings",
            message=(
                f"NeoForge {loader_version} installed "
                f"({new_jars} new / {replaced_jars} updated libs)"
            ),
        )
        print(colorize_log(
            f"[neoforge] {loader_version} installed: "
            f"{new_jars} new, {replaced_jars} replaced"
        ))

    except DownloadCancelled:
        tracker.finish(status="cancelled",
                       message=f"NeoForge {loader_version} install cancelled")
        raise
    except Exception as exc:
        tracker.finish(status="failed",
                       message=f"NeoForge install failed: {exc}")
        raise
    finally:
        if fake_dir and os.path.isdir(fake_dir):
            shutil.rmtree(fake_dir, ignore_errors=True)


def _run_with_variants(
    *,
    installer_path: str,
    fake_dir: str,
    fake_libs_dir: str,
    expected_profile_json: str,
    before_snapshot: Dict[str, int],
    tracker: ProgressTracker,
    job: Job,
) -> Tuple[bool, bool]:
    network_failure = False

    def _format_args(template: Tuple[str, ...]) -> List[str]:
        return [
            seg.replace("{fake_mc}", fake_dir) for seg in template
        ]

    # --- online attempts -------------------------------------------------
    for i, variant in enumerate(_INSTALLER_ARG_VARIANTS, 1):
        job.checkpoint()
        args = _format_args(variant)
        tracker.update(
            "downloading_libs",
            10 + 10 * i,
            f"Running NeoForge installer (variant {i}/{len(_INSTALLER_ARG_VARIANTS)})...",
        )
        out_lines: List[str] = []
        try:
            rc = run_installer_jar(
                installer_path, args,
                cwd=fake_dir,
                cancel_check=job.checkpoint,
                line_sink=lambda ln: tracker.update(
                    "downloading_libs", 10 + 10 * i,
                    f"NeoForge: {ln[:80]}",
                ),
                raise_on_failure=False,
                output_lines_out=out_lines,
            )
        except DownloadCancelled:
            raise
        except DownloadFailed:
            # Java missing or timeout — bubble up.
            raise

        combined = "\n".join(out_lines).lower()
        if any(m in combined for m in _NETWORK_FAILURE_MARKERS):
            network_failure = True

        if rc == 0 and _has_installer_output(
            expected_profile_json=expected_profile_json,
            fake_libs_dir=fake_libs_dir,
            before_snapshot=before_snapshot,
        ):
            return (True, network_failure)

    # --- offline retries -------------------------------------------------
    if network_failure:
        tracker.update("downloading_libs", 50,
                       "Re-running NeoForge installer in offline mode...")
        for i, variant in enumerate(_INSTALLER_ARG_VARIANTS, 1):
            job.checkpoint()
            args = ["--offline", *_format_args(variant)]
            try:
                rc = run_installer_jar(
                    installer_path, args,
                    cwd=fake_dir,
                    cancel_check=job.checkpoint,
                    line_sink=lambda ln: tracker.update(
                        "downloading_libs", 50,
                        f"NeoForge offline: {ln[:80]}",
                    ),
                    raise_on_failure=False,
                )
            except DownloadCancelled:
                raise
            except DownloadFailed:
                raise

            if rc == 0 and _has_installer_output(
                expected_profile_json=expected_profile_json,
                fake_libs_dir=fake_libs_dir,
                before_snapshot=before_snapshot,
            ):
                return (True, network_failure)

    return (False, network_failure)


def _write_data_ini(
    *,
    install_dir: str,
    loader_version: str,
    mc_version: str,
    profile_id: str,
    main_class: Optional[str],
) -> None:
    path = os.path.join(install_dir, "data.ini")
    lines = [
        "loader_type=neoforge",
        f"loader_version={loader_version}",
        f"mc_version={mc_version}",
        f"profile_id={profile_id}",
    ]
    if main_class:
        lines.append(f"main_class={main_class}")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")


__all__ = ["install_neoforge"]
