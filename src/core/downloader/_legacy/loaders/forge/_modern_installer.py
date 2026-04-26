from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

from core import manifest
from core.downloader._legacy._constants import CACHE_LIBRARIES_DIR
from core.downloader._legacy.installer_subprocess import (
    _build_java_installer_command,
    _get_java_executable,
    _is_url_proxy_enabled,
    _parse_maven_library_name,
)
from core.downloader._legacy.progress import _update_progress
from core.downloader._legacy.transport import _safe_remove_file, download_file
from core.subprocess_utils import no_window_kwargs

from core.downloader._legacy.loaders.forge._const import NETWORK_FAILURE_MARKERS
from core.downloader._legacy.loaders.forge._context import ForgeContext


def is_new_format_installer(ctx: ForgeContext) -> bool:
    return bool(ctx.profile_data and ctx.profile_data.get("processors"))


def prepare_fake_minecraft_dir(ctx: ForgeContext) -> None:
    _update_progress(
        ctx.version_key, "extracting_loader", 40,
        "Running Forge installer (applying patches)...",
    )

    ctx.fake_mc_dir = os.path.join(ctx.temp_dir, "fake_mc")
    os.makedirs(ctx.fake_mc_dir, exist_ok=True)

    mc_ver_dir = os.path.join(ctx.fake_mc_dir, "versions", ctx.mc_version)
    os.makedirs(mc_ver_dir, exist_ok=True)

    ctx.client_jar_src = os.path.join(ctx.version_dir, "client.jar")
    ctx.client_jar_dst = os.path.join(mc_ver_dir, f"{ctx.mc_version}.jar")
    if os.path.exists(ctx.client_jar_src):
        try:
            shutil.copy2(ctx.client_jar_src, ctx.client_jar_dst)
            print(
                f"[forge] Placed client.jar "
                f"({os.path.getsize(ctx.client_jar_dst) // 1024} KB) for installer"
            )
        except Exception as e:
            print(f"[forge] WARNING: Could not place client.jar: {e}")
    else:
        print(
            f"[forge] WARNING: client.jar not found at {ctx.client_jar_src}, "
            "installer will try to download it"
        )

    version_json_dst = os.path.join(mc_ver_dir, f"{ctx.mc_version}.json")
    try:
        mc_version_entry = manifest.get_version_entry(ctx.mc_version)
        mc_version_url = mc_version_entry.get("url")
        if mc_version_url:
            ctx.mc_version_data = manifest.fetch_version_json(mc_version_url)
            with open(version_json_dst, "w") as vf:
                json.dump(ctx.mc_version_data, vf)
            print(
                f"[forge] Placed MC {ctx.mc_version} version JSON for installer"
            )
    except Exception as e:
        print(
            f"[forge] WARNING: Could not fetch Mojang version JSON ({e}), "
            "installer will try to download it"
        )

    launcher_profiles_path = os.path.join(
        ctx.fake_mc_dir, "launcher_profiles.json"
    )
    try:
        with open(launcher_profiles_path, "w") as lpf:
            json.dump(
                {
                    "profiles": {
                        "(Default)": {
                            "name": "(Default)",
                            "type": "latest-release",
                        }
                    },
                    "selectedProfile": "(Default)",
                    "authenticationDatabase": {},
                    "clientToken": "histolauncher-fake-token",
                    "launcherVersion": {
                        "format": 21,
                        "name": "2.2.1234",
                        "profilesFormat": 2,
                    },
                },
                lpf,
                indent=2,
            )
        print("[forge] Created launcher_profiles.json stub for installer")
    except Exception as e:
        print(f"[forge] WARNING: Could not create launcher_profiles.json: {e}")

    ctx.installer_maven = os.path.join(ctx.extraction_dir, "maven")
    ctx.fake_libs_dir = os.path.join(ctx.fake_mc_dir, "libraries")
    if os.path.isdir(ctx.installer_maven):
        try:
            shutil.copytree(
                ctx.installer_maven, ctx.fake_libs_dir, dirs_exist_ok=True
            )
            print(
                "[forge] Pre-populated installer libraries from embedded "
                "maven/ directory"
            )
        except Exception as e:
            print(f"[forge] Warning: Could not pre-populate libraries: {e}")

    ctx.downloaded_lib_cache = os.path.join(ctx.loader_dest_dir, "libraries")
    if os.path.isdir(ctx.downloaded_lib_cache):
        try:
            shutil.copytree(
                ctx.downloaded_lib_cache, ctx.fake_libs_dir, dirs_exist_ok=True
            )
            print(
                "[forge] Merged pre-downloaded libraries into installer cache"
            )
        except Exception as e:
            print(
                "[forge] Warning: Could not merge pre-downloaded libraries: "
                f"{e}"
            )


def _extract_profile_artifact_notation(raw_value: object) -> str:
    token = str(raw_value or "").strip()
    if not token:
        return ""
    token = token.strip("'\"")
    if token.startswith("[") and token.endswith("]"):
        token = token[1:-1].strip()
    token = token.strip("'\"")
    if not token or ":" not in token or token.startswith("{"):
        return ""
    return token


def seed_processor_artifacts_for_offline(ctx: ForgeContext) -> None:
    profile_obj = ctx.profile_data or {}
    data_section = profile_obj.get("data") or {}
    processors_section = profile_obj.get("processors") or []
    libraries_section = profile_obj.get("libraries") or []

    requested_coords: List[str] = []
    seen_coords: set[str] = set()
    library_hints: Dict[str, Dict[str, str]] = {}

    def _enqueue_coord(raw_coord: object) -> None:
        coord = _extract_profile_artifact_notation(raw_coord)
        if not coord:
            return
        norm = coord.strip()
        if not norm or norm in seen_coords:
            return
        seen_coords.add(norm)
        requested_coords.append(norm)

    def _register_library_hint(
        raw_coord: object, lib_entry: Dict[str, object]
    ) -> None:
        coord = _extract_profile_artifact_notation(raw_coord)
        if not coord:
            return
        downloads_obj = lib_entry.get("downloads") or {}
        artifact_obj = downloads_obj.get("artifact") or {}
        if not isinstance(artifact_obj, dict):
            return
        hint: Dict[str, str] = {}
        path_hint = str(artifact_obj.get("path") or "").strip()
        if path_hint:
            hint["path"] = path_hint.replace("\\", "/")
        url_hint = str(artifact_obj.get("url") or "").strip()
        if url_hint:
            hint["url"] = url_hint
        sha1_hint = str(artifact_obj.get("sha1") or "").strip()
        if sha1_hint:
            hint["sha1"] = sha1_hint
        if hint:
            library_hints[coord] = hint

    if isinstance(data_section, dict):
        for _, data_entry in data_section.items():
            if not isinstance(data_entry, dict):
                continue
            _enqueue_coord(data_entry.get("client"))

    if isinstance(processors_section, list):
        for processor in processors_section:
            if not isinstance(processor, dict):
                continue
            _enqueue_coord(processor.get("jar"))
            classpath_entries = processor.get("classpath") or []
            if isinstance(classpath_entries, list):
                for cp_entry in classpath_entries:
                    _enqueue_coord(cp_entry)
            processor_args = processor.get("args") or []
            if isinstance(processor_args, list):
                for arg_entry in processor_args:
                    _enqueue_coord(arg_entry)

    if isinstance(libraries_section, list):
        for lib_entry in libraries_section:
            if isinstance(lib_entry, dict):
                lib_name = lib_entry.get("name")
                _enqueue_coord(lib_name)
                _register_library_hint(lib_name, lib_entry)
            elif isinstance(lib_entry, str):
                _enqueue_coord(lib_entry)

    if not requested_coords:
        return

    seeded = 0
    downloaded = 0
    failed = 0
    failed_coords: List[str] = []

    for coord in requested_coords:
        parsed = _parse_maven_library_name(coord)
        if not parsed:
            continue
        group, artifact, version, classifier, file_name = parsed
        coord_hint = library_hints.get(coord) or {}
        group_norm = group.replace("\\", "/").lower()
        artifact_norm = str(artifact or "").strip().lower()
        classifier_norm = str(classifier or "").strip().lower()
        file_name_lower = file_name.lower()
        rel_parts: List[str] = [group, artifact, version, file_name]
        hinted_path = str(coord_hint.get("path") or "").strip()
        if hinted_path:
            hinted_parts = [
                p for p in hinted_path.replace("\\", "/").split("/") if p
            ]
            if len(hinted_parts) >= 4:
                rel_parts = hinted_parts
        rel_path = "/".join(rel_parts)
        dst_path = os.path.join(ctx.fake_libs_dir, *rel_parts)
        expected_sha1 = (
            str(coord_hint.get("sha1") or "").strip() or None
        )

        if os.path.exists(dst_path):
            continue

        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        copied = False

        source_candidates = [
            os.path.join(ctx.downloaded_lib_cache, *rel_parts),
            os.path.join(ctx.installer_maven, *rel_parts),
            os.path.join(CACHE_LIBRARIES_DIR, *rel_parts),
        ]
        for src_path in source_candidates:
            if src_path and os.path.isfile(src_path):
                try:
                    shutil.copy2(src_path, dst_path)
                    seeded += 1
                    copied = True
                    break
                except Exception:
                    pass

        if copied:
            continue

        if (
            group_norm == "net/minecraft"
            and artifact_norm == "client"
            and classifier_norm in {"slim", "extra", "srg"}
            and file_name_lower.endswith(".jar")
        ):
            source_client = (
                ctx.client_jar_dst
                if os.path.isfile(ctx.client_jar_dst)
                else ctx.client_jar_src
            )
            if os.path.isfile(source_client):
                try:
                    shutil.copy2(source_client, dst_path)
                    seeded += 1
                    copied = True
                except Exception:
                    copied = False
            if copied:
                continue

        if (
            group_norm == "net/minecraft"
            and artifact_norm == "server"
            and classifier_norm in {"slim", "extra", "srg"}
        ):
            continue

        if (
            group_norm == "net/minecraftforge"
            and artifact_norm == "forge"
            and classifier_norm in {"client", "server"}
        ):
            continue

        urls_to_try: List[str] = []
        hinted_url = str(coord_hint.get("url") or "").strip()
        if hinted_url:
            urls_to_try.append(hinted_url)
        is_mcp_mappings_text = (
            group_norm == "de/oceanlabs/mcp"
            and artifact_norm == "mcp_config"
            and classifier_norm == "mappings"
            and file_name_lower.endswith(".txt")
        )
        if is_mcp_mappings_text:
            try:
                downloads_obj = (
                    (ctx.mc_version_data or {}).get("downloads") or {}
                )
                mappings_url = (
                    (downloads_obj.get("client_mappings") or {})
                    .get("url") or ""
                ).strip()
                if mappings_url:
                    urls_to_try.append(mappings_url)
            except Exception:
                pass

        if not is_mcp_mappings_text:
            urls_to_try.extend([
                f"https://maven.minecraftforge.net/{rel_path}",
                f"https://libraries.minecraft.net/{rel_path}",
                f"https://repo1.maven.org/maven2/{rel_path}",
            ])

        deduped_urls: List[str] = []
        for candidate_url in urls_to_try:
            if candidate_url and candidate_url not in deduped_urls:
                deduped_urls.append(candidate_url)
        urls_to_try = deduped_urls

        for candidate_url in urls_to_try:
            try:
                download_file(
                    candidate_url, dst_path,
                    expected_sha1=expected_sha1,
                    version_key=ctx.version_key, progress_cb=None,
                )
                downloaded += 1
                copied = True
                break
            except Exception:
                _safe_remove_file(dst_path)

        if not copied:
            failed += 1
            failed_coords.append(coord)

    if seeded or downloaded:
        print(
            f"[forge] Seeded {seeded} cached and {downloaded} downloaded "
            "processor artifact(s) for offline fallback"
        )
    if failed:
        print(
            f"[forge] Warning: Could not seed {failed} processor artifact(s) "
            "for offline fallback"
        )
        preview = failed_coords[:15]
        for missing_coord in preview:
            print(f"[forge] Missing processor artifact: {missing_coord}")
        if failed > len(preview):
            print(
                f"[forge] ... plus {failed - len(preview)} more missing "
                "processor artifact(s)"
            )


def _snapshot_installer_jars(root_dir: str) -> Dict[str, Tuple[int, int]]:
    snapshot: Dict[str, Tuple[int, int]] = {}
    if not os.path.isdir(root_dir):
        return snapshot
    for root, _, files in os.walk(root_dir):
        for name in files:
            if not name.endswith(".jar"):
                continue
            full_path = os.path.join(root, name)
            rel = os.path.relpath(full_path, root_dir).replace("\\", "/")
            try:
                st = os.stat(full_path)
                mtime_ns = int(getattr(
                    st, "st_mtime_ns",
                    int(st.st_mtime * 1000000000),
                ))
                snapshot[rel] = (int(st.st_size), mtime_ns)
            except Exception:
                continue
    return snapshot


def _find_generated_forge_profile_json(ctx: ForgeContext) -> Optional[str]:
    versions_root = os.path.join(ctx.fake_mc_dir, "versions")
    if not os.path.isdir(versions_root):
        return None

    preferred_profile_id = (
        f"{ctx.mc_version}-forge-{ctx.loader_version}".lower()
    )

    for entry in os.listdir(versions_root):
        entry_dir = os.path.join(versions_root, entry)
        if not os.path.isdir(entry_dir):
            continue
        if entry.lower() != preferred_profile_id:
            continue
        candidate = os.path.join(entry_dir, f"{entry}.json")
        if os.path.isfile(candidate):
            return candidate

    forge_candidates: List[Tuple[float, str]] = []
    for entry in os.listdir(versions_root):
        entry_dir = os.path.join(versions_root, entry)
        if not os.path.isdir(entry_dir):
            continue
        if "forge" not in entry.lower():
            continue
        candidate = os.path.join(entry_dir, f"{entry}.json")
        if os.path.isfile(candidate):
            try:
                mtime = os.path.getmtime(candidate)
            except Exception:
                mtime = 0
            forge_candidates.append((mtime, candidate))

    if forge_candidates:
        forge_candidates.sort(key=lambda t: t[0], reverse=True)
        return forge_candidates[0][1]

    return None


def _should_overwrite_from_installer(rel_path: str) -> bool:
    rel_norm = rel_path.replace("\\", "/").lower()
    if (
        "net/minecraftforge/forge/" in rel_norm
        and rel_norm.endswith("-client.jar")
    ):
        return True
    if rel_norm.startswith("net/minecraft/client/"):
        if (
            rel_norm.endswith("-srg.jar")
            or rel_norm.endswith("-slim.jar")
            or rel_norm.endswith("-extra.jar")
        ):
            return True
    return False


def run_modern_installer(ctx: ForgeContext) -> None:
    url_proxy_enabled = _is_url_proxy_enabled()

    java_exe = _get_java_executable() or "java"
    proxy_jvm_args: List[str] = []
    force_offline_installer = False
    if url_proxy_enabled:
        print(
            "[forge] URL proxy mode detected; installer JVM proxy flags "
            "disabled (online default, offline fallback enabled)"
        )

    installer_success = False
    expected_patched_client = os.path.join(
        ctx.fake_libs_dir,
        "net", "minecraftforge", "forge",
        f"{ctx.mc_version}-{ctx.loader_version}",
        f"forge-{ctx.mc_version}-{ctx.loader_version}-client.jar",
    )

    installer_arg_variants = [
        ["--installClient", ctx.fake_mc_dir],
        ["--installClient"],
    ]
    installer_candidates = []
    for args in installer_arg_variants:
        effective_args = (
            ["--offline"] + args if force_offline_installer else args
        )
        installer_candidates.append(
            _build_java_installer_command(
                java_exe, ctx.downloaded_artifact_path,
                effective_args, proxy_jvm_args,
            )
        )

    initial_installer_snapshot = _snapshot_installer_jars(ctx.fake_libs_dir)

    def _evaluate_installer_output() -> Tuple[bool, str]:
        if os.path.exists(expected_patched_client):
            return True, "patched Forge client JAR"
        generated_profile_json = _find_generated_forge_profile_json(ctx)
        if generated_profile_json:
            return True, "installer profile JSON"
        latest_snapshot = _snapshot_installer_jars(ctx.fake_libs_dir)
        changed = 0
        for rel, sig in latest_snapshot.items():
            if initial_installer_snapshot.get(rel) != sig:
                changed += 1
        for rel in initial_installer_snapshot:
            if rel not in latest_snapshot:
                changed += 1
        if changed > 0:
            return True, f"{changed} installer library change(s)"
        return False, ""

    network_failure_detected = False
    proc = None  # type: Optional[subprocess.CompletedProcess]

    for attempt, installer_cmd in enumerate(installer_candidates, start=1):
        attempt_label = (
            "offline installer" if force_offline_installer else "installer"
        )
        print(
            f"[forge] Running {attempt_label} attempt "
            f"{attempt}/{len(installer_candidates)}: {' '.join(installer_cmd)}"
        )
        try:
            proc = subprocess.run(
                installer_cmd, cwd=ctx.fake_mc_dir,
                capture_output=True, text=True, timeout=600,
                **no_window_kwargs(),
            )
            stdout_lines = proc.stdout.splitlines()
            for line in stdout_lines[:50]:
                print(f"[forge-installer] {line}")
            if proc.returncode != 0 and proc.stderr:
                for line in proc.stderr.splitlines()[:20]:
                    print(f"[forge-installer-err] {line}")
            if proc.returncode != 0 and len(stdout_lines) > 50:
                for line in stdout_lines[-25:]:
                    print(f"[forge-installer-tail] {line}")
            print(f"[forge] Installer exit code: {proc.returncode}")

            combined_output = f"{proc.stdout}\n{proc.stderr}".lower()
            if any(m in combined_output for m in NETWORK_FAILURE_MARKERS):
                network_failure_detected = True
                if not force_offline_installer:
                    print(
                        "[forge] Detected installer network/certificate "
                        "issue; will retry with --offline mode"
                    )
        except subprocess.TimeoutExpired:
            print("[forge] Installer timed out after 10 minutes")
            continue
        except Exception as e:
            print(f"[forge] Installer run error: {e}")
            continue

        if proc.returncode != 0:
            continue

        installer_success = True
        output_ok, output_reason = _evaluate_installer_output()
        if output_ok:
            print(
                f"[forge] Installer produced usable output ({output_reason})"
            )
            break
        installer_success = False
        print(
            "[forge] Installer exited successfully but produced no usable "
            "artifacts; trying next command form"
        )

    if (
        (not force_offline_installer)
        and (not installer_success)
        and not os.path.exists(expected_patched_client)
    ):
        if network_failure_detected:
            print(
                "[forge] Re-running Forge installer in offline mode after "
                "online network/certificate failure"
            )
        else:
            print(
                "[forge] Online installer produced no usable output; "
                "retrying in offline mode"
            )
        _update_progress(
            ctx.version_key, "extracting_loader", 55,
            "Re-running Forge installer in offline mode...",
        )

        for attempt, base_args in enumerate(installer_arg_variants, start=1):
            offline_cmd = _build_java_installer_command(
                java_exe, ctx.downloaded_artifact_path,
                ["--offline"] + base_args, proxy_jvm_args,
            )
            print(
                f"[forge] Running offline installer attempt "
                f"{attempt}/{len(installer_candidates)}: "
                f"{' '.join(offline_cmd)}"
            )
            try:
                proc = subprocess.run(
                    offline_cmd, cwd=ctx.fake_mc_dir,
                    capture_output=True, text=True, timeout=600,
                    **no_window_kwargs(),
                )
                offline_stdout_lines = proc.stdout.splitlines()
                for line in offline_stdout_lines[:50]:
                    print(f"[forge-installer-offline] {line}")
                if proc.returncode != 0 and proc.stderr:
                    for line in proc.stderr.splitlines()[:20]:
                        print(f"[forge-installer-offline-err] {line}")
                if proc.returncode != 0 and len(offline_stdout_lines) > 50:
                    for line in offline_stdout_lines[-25:]:
                        print(f"[forge-installer-offline-tail] {line}")
                print(
                    f"[forge] Offline installer exit code: {proc.returncode}"
                )
            except subprocess.TimeoutExpired:
                print("[forge] Offline installer timed out after 10 minutes")
                continue
            except Exception as e:
                print(f"[forge] Offline installer run error: {e}")
                continue

            if proc.returncode != 0:
                continue

            installer_success = True
            output_ok, output_reason = _evaluate_installer_output()
            if output_ok:
                print(
                    "[forge] Offline installer produced usable output "
                    f"({output_reason})"
                )
                break
            installer_success = False
            print(
                "[forge] Offline installer exited successfully but still "
                "produced no usable artifacts"
            )

        ctx.installer_completed_cleanly = installer_success

    # ---- harvest installer output back into the loader directory ------
    if os.path.isdir(ctx.fake_libs_dir):
        new_jars = 0
        replaced_jars = 0

        for root, _, files in os.walk(ctx.fake_libs_dir):
            for filename in files:
                if not filename.endswith(".jar"):
                    continue
                src_jar = os.path.join(root, filename)
                rel_path = os.path.relpath(src_jar, ctx.fake_libs_dir)
                dst_jar = os.path.join(
                    ctx.loader_dest_dir, "libraries", rel_path
                )
                os.makedirs(os.path.dirname(dst_jar), exist_ok=True)
                dst_exists = os.path.exists(dst_jar)
                should_overwrite = (
                    dst_exists and _should_overwrite_from_installer(rel_path)
                )

                if (not dst_exists) or should_overwrite:
                    try:
                        shutil.copy2(src_jar, dst_jar)
                        if dst_exists:
                            replaced_jars += 1
                        else:
                            ctx.jars_copied += 1
                            new_jars += 1
                    except Exception as e:
                        print(
                            f"[forge] Warning: Could not copy {filename}: {e}"
                        )
        print(
            f"[forge] Collected {new_jars} new and {replaced_jars} replaced "
            "JAR(s) from installer output into loader/libraries/"
        )

    if installer_success:
        try:
            generated_profile_json = _find_generated_forge_profile_json(ctx)
            if generated_profile_json:
                metadata_version_json = os.path.join(
                    ctx.loader_dest_dir, ".metadata", "version.json"
                )
                os.makedirs(
                    os.path.dirname(metadata_version_json), exist_ok=True
                )
                shutil.copy2(generated_profile_json, metadata_version_json)
                print(
                    "[forge] Updated metadata version.json from installer "
                    f"output: {os.path.basename(generated_profile_json)}"
                )
        except Exception as e:
            print(
                "[forge] Warning: Could not refresh metadata version.json "
                f"from installer output: {e}"
            )

        _update_progress(
            ctx.version_key, "extracting_loader", 80,
            f"Forge patches applied ({ctx.jars_copied} libraries)",
        )
    else:
        print(
            "[forge] Installer did not exit cleanly, some Forge features "
            "may not work correctly"
        )
        _update_progress(
            ctx.version_key, "extracting_loader", 70,
            "Installer finished (check logs if launch fails)",
        )


__all__ = [
    "is_new_format_installer",
    "prepare_fake_minecraft_dir",
    "run_modern_installer",
    "seed_processor_artifacts_for_offline",
]
