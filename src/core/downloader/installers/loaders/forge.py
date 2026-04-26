from __future__ import annotations

import json
import os
import shutil
import tempfile
import urllib.parse
import zipfile
from typing import Dict, List, Optional, Tuple

from core.downloader.errors import DownloadCancelled, DownloadFailed
from core.downloader.http import CLIENT
from core.downloader.installers.loaders import _lib_harvest, fake_mc_dir as fake_mc_mod
from core.downloader.installers.loaders.installer_runner import run_installer_jar
from core.downloader.jobs import Job
from core.downloader.progress import LOADER_STAGES, ProgressTracker
from core.logger import colorize_log
from core.zip_utils import safe_extract_zip


_NETWORK_FAILURE_MARKERS: Tuple[str, ...] = (
    "failed to validate certificates",
    "unsupported or unrecognized ssl message",
    "error checking https://",
    "sslhandshakeexception",
    "unable to tunnel through proxy",
)


_LOG4J_INCOMPATIBLE_MARKERS: Tuple[str, ...] = (
    "TerminalConsole",
    "LoggerNamePatternSelector",
    "%highlightForge",
    "%minecraftFormatting",
    "net.minecrell.terminalconsole",
)


_FALLBACK_LOG4J_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<Configuration status="warn" packages="net.minecraftforge.fml.loading.moddiscovery" shutdownHook="disable">
    <Appenders>
        <Console name="Console" target="SYSTEM_OUT" follow="true">
            <PatternLayout pattern="[%d{HH:mm:ss}] [%t/%level] [%c{1.}]: %msg%n" />
        </Console>
        <RollingRandomAccessFile name="File" fileName="logs/latest.log" filePattern="logs/%d{yyyy-MM-dd}-%i.log.gz">
            <PatternLayout pattern="[%d{ddMMMyyyy HH:mm:ss.SSS}] [%t/%level] [%c{2.}]: %msg%n" />
            <Policies>
                <TimeBasedTriggeringPolicy />
                <OnStartupTriggeringPolicy />
            </Policies>
            <DefaultRolloverStrategy max="99" fileIndex="min" />
        </RollingRandomAccessFile>
    </Appenders>
    <Loggers>
        <Root level="info">
            <AppenderRef ref="Console" />
            <AppenderRef ref="File" />
        </Root>
    </Loggers>
</Configuration>
"""


def _forge_overwrite_predicate(rel: str, src: str, dest: str) -> bool:
    norm = rel.replace("\\", "/").lower()
    if norm.startswith("net/minecraft/client/") and (
        norm.endswith("-srg.jar")
        or norm.endswith("-slim.jar")
        or norm.endswith("-extra.jar")
    ):
        return True
    if norm.startswith("net/minecraftforge/forge/") and norm.endswith("-client.jar"):
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
            or "forge-artifact.jar"
        )
        if "-installer.jar" not in name.lower():
            print(colorize_log(
                f"[forge] skipping non-installer artifact {name}"
            ))
            continue
        path = os.path.join(dest_dir, name)
        print(colorize_log(f"[forge] downloading installer from {url}"))

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
            print(colorize_log(f"[forge] {url} failed: {exc}"))
            try:
                os.remove(path)
            except OSError:
                pass

    raise DownloadFailed(
        f"Could not download any Forge installer artifact "
        f"(last error: {last_error or 'all URLs failed'})",
        url=None,
    )


def _pre_stage_bundled_libs(
    *, installer_jar: str, fake_libs_dir: str, loader_libs_dir: str,
) -> Tuple[int, int]:
    with tempfile.TemporaryDirectory(prefix="forge-zip-") as extract:
        try:
            safe_extract_zip(installer_jar, extract)
        except Exception as exc:
            raise DownloadFailed(
                f"Failed to extract Forge installer: {exc}", url=None,
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
                stripped = rel
                for prefix in ("maven/", "libraries/"):
                    if stripped.startswith(prefix):
                        stripped = stripped[len(prefix):]
                        break
                else:
                    stripped = os.path.basename(stripped)

                for base in (fake_libs_dir, loader_libs_dir):
                    dst = os.path.join(base, stripped.replace("/", os.sep))
                    if os.path.exists(dst):
                        continue
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    try:
                        shutil.copy2(src, dst)
                    except Exception as exc:
                        print(colorize_log(
                            f"[forge] could not stage {fn}: {exc}"
                        ))
                jars_staged += 1

        configs_copied = 0
        install_root = os.path.dirname(loader_libs_dir)
        for root, _, files in os.walk(extract):
            for fn in files:
                lower = fn.lower()
                if lower in (
                    "log4j2.xml", "log4j.properties", "log4j.xml",
                    "bootstrap-shim.list",
                ) or lower.endswith(".properties"):
                    src = os.path.join(root, fn)
                    dst = os.path.join(install_root, fn)
                    if os.path.exists(dst):
                        continue
                    try:
                        shutil.copy2(src, dst)
                        configs_copied += 1
                    except Exception:
                        pass

        return (jars_staged, configs_copied)


def _read_profile_id(
    installer_jar: str, *, fallback: str,
) -> Tuple[str, Optional[Dict]]:
    profile_data: Optional[Dict] = None
    version_data: Optional[Dict] = None
    with tempfile.TemporaryDirectory(prefix="forge-meta-") as extract:
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


def _extract_mcp_version(install_profile: Optional[Dict]) -> Optional[str]:
    if not install_profile:
        return None
    data = install_profile.get("data") or {}

    mcp = data.get("MCP_VERSION") or {}
    raw = str(mcp.get("client") or "").strip()
    if raw:
        return raw.strip("'\"[]")

    for key in ("MC_SRG", "MAPPINGS"):
        entry = data.get(key) or {}
        raw = str(entry.get("client") or "").strip().strip("[]")
        if "@" in raw:
            raw = raw.split("@", 1)[0]
        parts = raw.replace(":", "/").split("/")
        if len(parts) >= 3 and parts[2]:
            return parts[2]
    return None


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


def _harden_log4j2(install_dir: str) -> None:
    for root, _, files in os.walk(install_dir):
        for fn in files:
            if fn.lower() != "log4j2.xml":
                continue
            path = os.path.join(root, fn)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fp:
                    content = fp.read()
            except OSError:
                continue
            if any(m in content for m in _LOG4J_INCOMPATIBLE_MARKERS):
                try:
                    with open(path, "w", encoding="utf-8") as fp:
                        fp.write(_FALLBACK_LOG4J_XML)
                    print(colorize_log(
                        f"[forge] hardened incompatible log4j2.xml at {path}"
                    ))
                except OSError as exc:
                    print(colorize_log(
                        f"[forge] could not harden {path}: {exc}"
                    ))


_MAVEN_REPO_FALLBACKS: Tuple[str, ...] = (
    "https://maven.minecraftforge.net/",
    "https://libraries.minecraft.net/",
    "https://repo1.maven.org/maven2/",
)


def _parse_maven_name(name: str) -> Optional[Tuple[str, str, str, str]]:
    raw = (name or "").strip()
    if not raw:
        return None
    ext = "jar"
    if "@" in raw:
        raw, ext = raw.split("@", 1)
    parts = raw.split(":")
    if len(parts) < 3:
        return None
    group = parts[0].replace(".", "/")
    artifact = parts[1]
    version = parts[2]
    classifier = parts[3] if len(parts) >= 4 else ""
    if classifier:
        jar_name = f"{artifact}-{version}-{classifier}.{ext}"
    else:
        jar_name = f"{artifact}-{version}.{ext}"
    return (group, artifact, version, jar_name)


def _download_metadata_libraries(
    *,
    version_data: Dict,
    dest_libs_dir: str,
    job: Job,
    tracker: ProgressTracker,
) -> Tuple[int, int]:
    libraries = version_data.get("libraries") or []
    if not libraries:
        return (0, 0)

    downloaded = 0
    skipped = 0
    total = len(libraries)
    print(colorize_log(
        f"[forge] resolving {total} libraries from version.json metadata"
    ))

    for idx, lib in enumerate(libraries, 1):
        job.checkpoint()
        if not isinstance(lib, dict):
            continue
        name = str(lib.get("name") or "").strip()
        if not name:
            continue

        # Skip Forge's own client artifact (the installer/processor produces it).
        lower = name.lower()
        if "net.minecraftforge:forge:" in lower and ":client" in lower:
            skipped += 1
            continue

        # Try the explicit download.artifact first; fall back to maven coords.
        artifact = (lib.get("downloads") or {}).get("artifact") or {}
        url = str(artifact.get("url") or "").strip()
        sha1 = str(artifact.get("sha1") or "").strip() or None
        rel_path = str(artifact.get("path") or "").strip()

        parsed = _parse_maven_name(name)
        if not rel_path and parsed:
            group, artname, ver, jar_name = parsed
            rel_path = f"{group}/{artname}/{ver}/{jar_name}"
        if not rel_path:
            print(colorize_log(f"[forge] skipping unparseable library: {name}"))
            skipped += 1
            continue

        dest = os.path.join(dest_libs_dir, rel_path.replace("/", os.sep))

        # Already present + valid → skip.
        if os.path.isfile(dest):
            if not sha1 or os.path.getsize(dest) > 0:
                if not sha1:
                    skipped += 1
                    continue
                try:
                    from core.downloader.http import hash_file
                    if hash_file(dest, "sha1").lower() == sha1.lower():
                        skipped += 1
                        continue
                except Exception:
                    pass

        os.makedirs(os.path.dirname(dest), exist_ok=True)

        # Build URL fallback list (explicit URL first, then standard repos).
        urls: List[str] = []
        if url:
            urls.append(url)
        if parsed:
            for repo in _MAVEN_REPO_FALLBACKS:
                candidate = repo + rel_path
                if candidate not in urls:
                    urls.append(candidate)
        if not urls:
            print(colorize_log(f"[forge] no URL for {name}"))
            skipped += 1
            continue

        pct = (idx / max(1, total)) * 100.0
        tracker.update(
            "downloading_libs", min(pct * 0.5, 49.0),
            f"Library {idx}/{total}: {name}",
        )

        last_err: Optional[BaseException] = None
        success = False
        for try_url in urls:
            try:
                CLIENT.download(
                    try_url, dest,
                    expected_sha1=sha1,
                    cancel_check=job.checkpoint,
                )
                success = True
                break
            except DownloadCancelled:
                raise
            except Exception as exc:
                last_err = exc
                continue

        if success:
            downloaded += 1
        else:
            print(colorize_log(
                f"[forge] could not download {name}: {last_err}"
            ))
            skipped += 1

    return (downloaded, skipped)


_INSTALLER_ARG_VARIANTS = (
    ("--installClient", "{fake_mc}"),
    ("--installClient", "--installDir", "{fake_mc}"),
    ("--installClient",),
)


def install_forge(
    job: Job,
    *,
    mc_version: str,
    loader_version: str,
    install_dir: str,
    category: str,
    folder: str,
    version_key: str,
) -> None:
    from core.modloaders import get_forge_artifact_urls

    tracker = ProgressTracker(version_key, kind="loader", stages=LOADER_STAGES)
    tracker.set_status("running")

    # ---- prepare_vanilla --------------------------------------------------
    from core.downloader.installers.loaders.pipeline import _ensure_vanilla_installed

    tracker.update("download", 0,
                   f"Starting Forge {loader_version} install...")
    _ensure_vanilla_installed(
        job=job, mc_version=mc_version, category=category, tracker=tracker,
    )

    # ---- resolve installer URLs ------------------------------------------
    job.checkpoint()
    tracker.update("download", 5, "Resolving Forge installer URLs...")
    artifact_urls = get_forge_artifact_urls(mc_version, loader_version)
    if not artifact_urls:
        raise DownloadFailed(
            f"Could not resolve Forge installer URLs for {mc_version}/{loader_version}",
            url=None,
        )

    fake_dir: Optional[str] = None
    try:
        with tempfile.TemporaryDirectory(prefix="histolauncher-forge-dl-") as dl_dir:
            installer_path, installer_name = _try_download_installer(
                artifact_urls, dest_dir=dl_dir, job=job, tracker=tracker,
            )

            # ---- build fake mc dir + pre-stage bundled libs --------------
            job.checkpoint()
            tracker.update("downloading_libs", 0,
                           "Preparing Forge install context...")
            fake_dir = tempfile.mkdtemp(prefix="histolauncher-forge-")
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
                           "Pre-staging Forge bundled libraries...")
            jars_staged, configs_copied = _pre_stage_bundled_libs(
                installer_jar=installer_path,
                fake_libs_dir=fake_libs_dir,
                loader_libs_dir=loader_libs_dir,
            )
            print(colorize_log(
                f"[forge] staged {jars_staged} embedded JARs, "
                f"{configs_copied} config files"
            ))

            # ---- predict profile id + persist install_profile.json -------
            fallback_id = f"{mc_version}-forge-{loader_version}"
            profile_id, embedded_version_data = _read_profile_id(
                installer_path, fallback=fallback_id,
            )

            # Re-extract just to grab install_profile.json for metadata.
            install_profile_data: Optional[Dict] = None
            try:
                with zipfile.ZipFile(installer_path, "r") as zf:
                    if "install_profile.json" in zf.namelist():
                        with zf.open("install_profile.json") as ip:
                            install_profile_data = json.load(ip)
                        with open(
                            os.path.join(metadata_dir, "install_profile.json"),
                            "w", encoding="utf-8",
                        ) as fp:
                            json.dump(install_profile_data, fp)
            except Exception:
                pass

            # Pre-download client.jar into fake_mc if needed (Forge installer processors need it)
            fake_client_jar = os.path.join(fake_dir, "versions", mc_version, f"{mc_version}.jar")
            if not os.path.exists(fake_client_jar):
                tracker.update("downloading_libs", 5, f"Downloading vanilla {mc_version}.jar for Forge installer...")
                try:
                    from core.downloader.http import CLIENT
                    from core.manifest import get_version_entry, fetch_version_json
                    entry = get_version_entry(mc_version)
                    if entry and isinstance(entry, dict) and entry.get("url"):
                        v_json = fetch_version_json(entry["url"])
                        client_dl_url = v_json.get("downloads", {}).get("client", {}).get("url")
                        if client_dl_url:
                            CLIENT.download(client_dl_url, fake_client_jar, cancel_check=job.checkpoint)
                except Exception as exc:
                    print(colorize_log(f"[forge] failed downloading vanilla client.jar: {exc}"))

            if embedded_version_data is not None:
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

            # ---- pre-download libraries declared in version.json ---------
            # The Java installer needs many libs at runtime; downloading them
            # ourselves ensures the install completes even if the installer
            # subprocess silently fails (wrong Java version, sandboxed net,
            # cert issues). Goes into fake_libs_dir so the installer sees
            # them as already-present; the post-install harvest pass moves
            # them into loader_libs_dir + the central library store.
            metadata_lib_downloads = 0
            metadata_lib_skipped = 0
            if embedded_version_data:
                tracker.update("downloading_libs", 8,
                               "Downloading libraries from Forge metadata...")
                d1, s1 = _download_metadata_libraries(
                    version_data=embedded_version_data,
                    dest_libs_dir=fake_libs_dir,
                    job=job,
                    tracker=tracker,
                )
                metadata_lib_downloads += d1
                metadata_lib_skipped += s1
                
            if install_profile_data:
                d2, s2 = _download_metadata_libraries(
                    version_data=install_profile_data,
                    dest_libs_dir=fake_libs_dir,
                    job=job,
                    tracker=tracker,
                )
                metadata_lib_downloads += d2
                metadata_lib_skipped += s2
                
            if embedded_version_data or install_profile_data:
                print(colorize_log(
                    f"[forge] metadata libs: {metadata_lib_downloads} downloaded, "
                    f"{metadata_lib_skipped} skipped"
                ))

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
            # Even if the Java installer failed entirely, we have a viable
            # install when the embedded version.json is present and we managed
            # to download (almost) every library it declares. The launch
            # system needs the profile + libs, not the installer's blessing.
            metadata_install_viable = bool(
                embedded_version_data
                and metadata_lib_downloads > 0
                and metadata_lib_skipped <= 1
            )
            if not installer_output_ready and not metadata_install_viable:
                msg = (
                    "Forge installer did not produce a usable client "
                    "profile or runtime libraries"
                )
                if network_failure:
                    msg += "; check network/proxy/certificate access"
                raise DownloadFailed(msg, url=None)

            # ---- harvest produced libs into store + version dir ----------
            job.checkpoint()
            tracker.update("extracting_loader", 60,
                           "Harvesting Forge libraries into store...")

            def _harvest_progress(done: int, total: int) -> None:
                job.checkpoint()
                pct = 60 + 25 * (done / max(1, total))
                tracker.update(
                    "extracting_loader", pct,
                    f"Linking libraries {done}/{total}",
                )

            new_jars, replaced_jars = _lib_harvest.harvest_libraries(
                source_libraries_dir=fake_libs_dir,
                dest_libraries_dir=loader_libs_dir,
                overwrite_predicate=_forge_overwrite_predicate,
                cancel_check=job.checkpoint,
                progress_cb=_harvest_progress,
            )

            # ---- copy final profile JSON to .metadata/version.json -------
            if os.path.isfile(expected_profile_json):
                shutil.copy2(
                    expected_profile_json,
                    os.path.join(metadata_dir, "version.json"),
                )

            # ---- harden log4j2.xml --------------------------------------
            job.checkpoint()
            tracker.update("extracting_loader", 90,
                           "Hardening log4j2 config...")
            _harden_log4j2(install_dir)

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

            mcp_version = _extract_mcp_version(install_profile_data)

            with open(
                os.path.join(install_dir, "forge_metadata.json"),
                "w", encoding="utf-8",
            ) as fp:
                json.dump(
                    {
                        "loader_type": "forge",
                        "forge_version": loader_version,
                        "mc_version": mc_inherits,
                        "profile_id": profile_id,
                        "mcp_version": mcp_version,
                        "embedded_jars": jars_staged,
                        "metadata_lib_downloads": metadata_lib_downloads,
                        "metadata_lib_skipped": metadata_lib_skipped,
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
                mcp_version=mcp_version,
            )

        tracker.finish(
            status="installed" if installer_success else "installed_with_warnings",
            message=(
                f"Forge {loader_version} installed "
                f"({new_jars} new / {replaced_jars} updated libs)"
            ),
        )
        print(colorize_log(
            f"[forge] {loader_version} installed: "
            f"{new_jars} new, {replaced_jars} replaced"
        ))

    except DownloadCancelled:
        tracker.finish(status="cancelled",
                       message=f"Forge {loader_version} install cancelled")
        raise
    except Exception as exc:
        tracker.finish(status="failed",
                       message=f"Forge install failed: {exc}")
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
        return [seg.replace("{fake_mc}", fake_dir) for seg in template]

    # --- online attempts -------------------------------------------------
    for i, variant in enumerate(_INSTALLER_ARG_VARIANTS, 1):
        job.checkpoint()
        args = _format_args(variant)
        tracker.update(
            "downloading_libs",
            10 + 10 * i,
            f"Running Forge installer (variant {i}/{len(_INSTALLER_ARG_VARIANTS)})...",
        )
        out_lines: List[str] = []
        try:
            rc = run_installer_jar(
                installer_path, args,
                cwd=fake_dir,
                cancel_check=job.checkpoint,
                line_sink=lambda ln: tracker.update(
                    "downloading_libs", 10 + 10 * i,
                    f"Forge: {ln[:80]}",
                ),
                raise_on_failure=False,
                output_lines_out=out_lines,
            )
        except DownloadCancelled:
            raise
        except DownloadFailed:
            raise

        if rc != 0 and out_lines:
            print(colorize_log(f"[forge] (variant {i}) Java installer failed with code {rc}. Output:\n" + "\n".join(out_lines)))

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
                       "Re-running Forge installer in offline mode...")
        out_lines_offline: List[str] = []
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
                        f"Forge offline: {ln[:80]}",
                    ),
                    raise_on_failure=False,
                    output_lines_out=out_lines_offline,
                )
            except DownloadCancelled:
                raise
            except DownloadFailed:
                raise

            if rc != 0 and out_lines_offline:
                print(colorize_log(f"[forge] (variant {i} offline) Java installer failed with code {rc}. Output:\n" + "\n".join(out_lines_offline)))

        if rc != 0 and out_lines:
            print(colorize_log(f"[forge] (variant {i} offline) Java installer failed with code {rc}. Output:\n" + "\n".join(out_lines)))
        
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
    mcp_version: Optional[str],
) -> None:
    path = os.path.join(install_dir, "data.ini")
    lines = [
        "loader_type=forge",
        f"loader_version={loader_version}",
        f"mc_version={mc_version}",
        f"profile_id={profile_id}",
    ]
    if main_class:
        lines.append(f"main_class={main_class}")
    if mcp_version:
        lines.append(f"mcp_version={mcp_version}")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")


__all__ = ["install_forge"]
