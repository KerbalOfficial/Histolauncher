from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile

from core.java import (
    JAVA_RUNTIME_MODE_AUTO,
    JAVA_RUNTIME_MODE_PATH,
    get_path_java_executable,
    suggest_java_feature_version,
)
from core.subprocess_utils import no_window_kwargs
from core.logger import colorize_log
from core.settings import get_base_dir, load_global_settings

from core.launch.args import (
    _classpath_has_class,
    _expand_placeholders,
    _extract_tweak_class_from_arg_list,
    _is_legacy_http_proxy_needed,
    _is_legacy_pre16_runtime,
    _parse_mc_version,
    _resolve_runtime_main_class,
)
from core.launch.legacy import (
    _find_forge_core_jar,
    _find_modloader_runtime_jar,
    _has_modloader_runtime,
    _is_legacy_forge_runtime,
    _legacy_forge_has_fml,
    _legacy_forge_requires_modloader,
    _prepare_legacy_applet_window_patch,
    _prepare_legacy_assets_directory,
    _prepare_legacy_client_resources,
    _prepare_legacy_direct_buffer_sound_patch,
    _prepare_legacy_forge_merged_client_jar,
    _prepare_legacy_forge_runtime_files,
    _prepare_legacy_modloader_runtime_directory,
    _prepare_legacy_options_file,
    _stage_legacy_fml_libraries,
)
from core.launch.loader import (
    _expand_forge_metadata_args,
    _expand_loader_metadata_args,
    _fabric_uses_intermediary_namespace,
    _get_forge_fml_metadata,
    _get_forge_metadata_args,
    _get_forge_tweak_class_from_metadata,
    _get_loader_jars,
    _get_loader_main_class,
    _get_loader_metadata_args,
    _get_loader_version,
    _normalize_forge_mc_version,
    _normalize_forge_mcp_version,
)
from core.launch.mods import (
    _cleanup_copied_mods,
    _is_truthy_setting,
    _prepare_modloader_overwrite_layer,
    _stage_addons_for_launch,
)
from core.launch.natives import (
    _append_system_property_if_missing,
    _create_fallback_log4j2_config,
    _extract_current_platform_native_binaries,
    _filter_conflicting_classpath_entries,
    _filter_platform_specific_classpath_entries,
    _is_platform_specific_runtime_jar,
    _join_classpath,
    _native_directory_has_binaries,
    _native_subfolder_for_platform,
    _prune_forge_root_jars_for_modlauncher,
    _prune_legacy_launchwrapper_bootstrap_jars,
    _prune_vanilla_client_jar,
    _set_or_append_cli_arg,
)
from core.launch.paths import (
    _ensure_neoforge_early_window_disabled,
    _extract_mc_version_string,
    _load_data_ini,
    _resolve_game_dir,
    _resolve_game_dir_with_error,
    _resolve_version_dir,
)
from core.launch.process import (
    _attach_copied_mods_to_process,
    _create_version_log_file,
    _get_process_status,
    _output_reader_thread,
    _register_process,
    _resolve_java_launch_candidates,
    _set_last_launch_error,
    _set_last_launch_diagnostic,
    _wait_for_launch_stability,
    consume_last_launch_error,
)
from core.launch.state import STATE


__all__ = ["_launch_version_once", "launch_version"]


def _is_direct_legacy_forge_launch(loader_key: str, legacy_runtime: bool, main_class: str) -> bool:
    return (
        loader_key == "forge"
        and legacy_runtime
        and str(main_class or "").strip() == "net.minecraft.client.Minecraft"
    )


def _prepare_legacy_forge_appdata_shim(game_dir: str) -> str:
    if os.name != "nt" or not game_dir or not os.path.isdir(game_dir):
        return ""

    current_appdata = os.environ.get("APPDATA") or ""
    if current_appdata:
        default_game_dir = os.path.join(current_appdata, ".minecraft")
        try:
            if os.path.normcase(os.path.realpath(default_game_dir)) == os.path.normcase(os.path.realpath(game_dir)):
                return ""
        except Exception:
            pass

    shim_root = tempfile.mkdtemp(prefix="hl_legacy_forge_appdata_")
    link_path = os.path.join(shim_root, ".minecraft")
    try:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", link_path, game_dir],
            capture_output=True,
            text=True,
            timeout=10,
            **no_window_kwargs(),
        )
        if result.returncode == 0 and os.path.isdir(link_path):
            print(colorize_log(
                f"[launcher] Created legacy Forge APPDATA shim: {link_path} -> {game_dir}"
            ))
            return shim_root
        detail = (result.stderr or result.stdout or "junction command failed").strip()
        print(colorize_log(f"[launcher] Warning: Could not create legacy Forge APPDATA shim: {detail}"))
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: Could not create legacy Forge APPDATA shim: {e}"))

    _cleanup_legacy_forge_appdata_shim(shim_root)
    return ""


def _cleanup_legacy_forge_appdata_shim(shim_root: str) -> None:
    if not shim_root:
        return
    link_path = os.path.join(shim_root, ".minecraft")
    try:
        if os.path.isdir(link_path):
            subprocess.run(
                ["cmd", "/c", "rmdir", link_path],
                capture_output=True,
                text=True,
                timeout=10,
                **no_window_kwargs(),
            )
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: Could not remove legacy Forge APPDATA junction: {e}"))
    if os.path.isdir(link_path):
        try:
            os.rmdir(shim_root)
        except Exception:
            pass
        return
    try:
        shutil.rmtree(shim_root, ignore_errors=True)
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: Could not remove legacy Forge APPDATA shim: {e}"))


def _cleanup_legacy_forge_appdata_shim_after_exit(process, shim_root: str) -> None:
    try:
        process.wait()
    except Exception:
        pass
    finally:
        _cleanup_legacy_forge_appdata_shim(shim_root)


def _launch_version_once(
    version_identifier,
    username_override=None,
    loader=None,
    loader_version=None,
    java_runtime_override=None,
    copied_mods_override=None,
    modloader_overwrite_dir_override=None,
    track_copied_mods=True,
):
    base_dir = get_base_dir()
    version_dir = _resolve_version_dir(version_identifier)
    if not version_dir:
        print("ERROR: Version directory not found for", version_identifier)
        _set_last_launch_error(version_identifier, f"Version directory not found for {version_identifier}")
        return False
    meta = _load_data_ini(version_dir)
    classpath_entries = [p.strip() for p in (meta.get("classpath") or "client.jar").split(",") if p.strip()]
    main_class = _resolve_runtime_main_class(
        version_identifier,
        version_dir,
        classpath_entries,
        meta.get("main_class") or "net.minecraft.client.Minecraft",
    )
    modloader_overwrite_dir = str(modloader_overwrite_dir_override or "").strip()
    global_settings = load_global_settings() or {}
    loader_key = str(loader or "").strip().lower()
    legacy_runtime = _is_legacy_pre16_runtime(version_identifier)
    allow_override_for_all_modloaders = _is_truthy_setting(
        global_settings.get("allow_override_classpath_all_modloaders", "0")
    )
    allow_overwrite_classpath_for_loader = bool(
        loader_key and (loader_key == "modloader" or allow_override_for_all_modloaders)
    )

    if loader:
        loader_jars = _get_loader_jars(version_dir, loader, loader_version)

        if loader.lower() == "forge" and not loader_version:
            actual_version = _get_loader_version(version_dir, loader)
            if actual_version:
                forge_dir = os.path.join(version_dir, "loaders", "forge", actual_version)
                libraries_dir = os.path.join(forge_dir, "libraries")

                has_launchwrapper = False
                if os.path.isdir(libraries_dir):
                    for root, dirs, files in os.walk(libraries_dir):
                        if any(f.startswith("launchwrapper") and f.endswith(".jar") for f in files):
                            has_launchwrapper = True
                            break
                else:
                    for jar in os.listdir(forge_dir) if os.path.isdir(forge_dir) else []:
                        if jar.endswith(".jar"):
                            try:
                                with zipfile.ZipFile(os.path.join(forge_dir, jar), "r") as z:
                                    if any("launchwrapper" in name.lower() for name in z.namelist()):
                                        has_launchwrapper = True
                                        break
                            except Exception:
                                pass

                if not has_launchwrapper and actual_version.startswith("14"):
                    print(colorize_log(
                        f"[launcher] Warning: Forge {actual_version} appears incomplete (missing LaunchWrapper)"
                    ))
                    print(colorize_log("[launcher] Attempting to use a compatible newer version instead..."))

                    loaders_dir = os.path.join(version_dir, "loaders", "forge")
                    if os.path.isdir(loaders_dir):
                        versions = sorted(
                            [d for d in os.listdir(loaders_dir) if os.path.isdir(os.path.join(loaders_dir, d))],
                            key=lambda x: tuple(map(int, x.split(".")[:3])) if x[0].isdigit() else (0,),
                        )
                        fallback_version = None
                        for v in reversed(versions):
                            if v.startswith("14.23.") or v.startswith("14.22.") or v == "14.23.5.2864":
                                fallback_version = v
                                break

                        if fallback_version and fallback_version != actual_version:
                            print(colorize_log(f"[launcher] Trying fallback: Forge {fallback_version}"))
                            loader_jars = _get_loader_jars(version_dir, loader, fallback_version)
                            if loader_jars:
                                print(colorize_log(
                                    f"[launcher] Fallback successful - using Forge {fallback_version}"
                                ))
                                loader_version = fallback_version
                                actual_version = fallback_version

        if loader_jars:
            lookup_version = loader_version or _get_loader_version(version_dir, loader)
            loader_main = _get_loader_main_class(version_dir, loader, lookup_version)
            if loader_main:
                main_class = loader_main
                print(colorize_log(f"[launcher] Using {loader} main class: {main_class}"))

            preserve_forge_client = True
            if loader.lower() in ("forge", "neoforge"):
                if main_class.startswith("cpw.mods.bootstraplauncher") or main_class.startswith("net.minecraftforge.bootstrap"):
                    preserve_forge_client = False

            classpath_entries = _filter_conflicting_classpath_entries(
                classpath_entries,
                loader_jars,
                preserve_forge_client=preserve_forge_client,
            )

            classpath_entries = loader_jars + classpath_entries
            print(colorize_log(f"[launcher] Injected {len(loader_jars)} {loader} JAR(s) into classpath"))

            if loader.lower() in ("forge", "neoforge"):
                actual_loader_version = loader_version or _get_loader_version(version_dir, loader)
                if actual_loader_version:
                    libraries_dir_rel = os.path.join(
                        "loaders", loader.lower(), actual_loader_version, "libraries"
                    )
                    loader_full_path = os.path.join(
                        version_dir, "loaders", loader.lower(), actual_loader_version
                    )
                    if os.path.isdir(os.path.join(loader_full_path, "libraries")) and libraries_dir_rel not in classpath_entries:
                        classpath_entries.insert(len(loader_jars), libraries_dir_rel)
                        print(colorize_log(f"[launcher] Added {loader} libraries/ to classpath"))
                if main_class == "cpw.mods.modlauncher.Launcher":
                    classpath_entries = _prune_forge_root_jars_for_modlauncher(classpath_entries)
                if main_class.startswith("cpw.mods.bootstraplauncher"):
                    classpath_entries = _prune_vanilla_client_jar(classpath_entries)
            if loader.lower() == "babric" and not main_class.startswith("net.minecraft.launchwrapper."):
                classpath_entries = _prune_legacy_launchwrapper_bootstrap_jars(classpath_entries)

    if loader_key == "modloader" and legacy_runtime:
        modloader_runtime_jar = _find_modloader_runtime_jar(version_dir)
        extracted_runtime_rel = _prepare_legacy_modloader_runtime_directory(version_dir)
        if modloader_runtime_jar and extracted_runtime_rel:
            modloader_runtime_rel = os.path.relpath(modloader_runtime_jar, version_dir).replace("\\", "/")
            updated_entries = []
            inserted_runtime = False

            for entry in classpath_entries:
                entry_norm = entry.replace("\\", "/")
                if entry_norm == modloader_runtime_rel:
                    if not inserted_runtime:
                        updated_entries.append(extracted_runtime_rel)
                        inserted_runtime = True
                    continue
                updated_entries.append(entry)

            if not inserted_runtime:
                updated_entries.insert(0, extracted_runtime_rel)

            classpath_entries = updated_entries
            print(colorize_log(
                "[launcher] Using extracted legacy ModLoader runtime directory for compatibility"
            ))

    if allow_overwrite_classpath_for_loader:
        if not modloader_overwrite_dir:
            modloader_overwrite_dir = _prepare_modloader_overwrite_layer(loader_key)

        if modloader_overwrite_dir and os.path.isdir(modloader_overwrite_dir):
            overlay_real = os.path.normcase(os.path.normpath(modloader_overwrite_dir))
            existing_real = {
                os.path.normcase(os.path.normpath(os.path.join(version_dir, e)))
                for e in classpath_entries
            }
            if overlay_real not in existing_real:
                classpath_entries.insert(0, modloader_overwrite_dir)
                print(colorize_log(f"[launcher] Added {loader_key} overwrite classpath layer"))

    classpath_entries = _filter_platform_specific_classpath_entries(classpath_entries)

    if loader and loader.lower() == "forge":
        major, minor = _parse_mc_version(version_identifier)
        if major == 1 and minor is not None and minor < 6:
            actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
            merged_jar_rel = _prepare_legacy_forge_merged_client_jar(version_dir, actual_loader_version)
            forge_core_abs = _find_forge_core_jar(version_dir, actual_loader_version) if actual_loader_version else ""
            forge_core_rel = (
                os.path.relpath(forge_core_abs, version_dir).replace("\\", "/")
                if forge_core_abs
                else ""
            )
            if merged_jar_rel:
                fml_jar_rel = ""
                if actual_loader_version:
                    forge_loader_path = os.path.join(version_dir, "loaders", "forge", actual_loader_version)
                    if os.path.isdir(forge_loader_path):
                        for fname in os.listdir(forge_loader_path):
                            if fname.startswith("fml-") and fname.endswith(".jar"):
                                fml_jar_rel = os.path.relpath(
                                    os.path.join(forge_loader_path, fname), version_dir
                                ).replace("\\", "/")
                                break

                updated_entries = []
                inserted_merged = False
                for entry in classpath_entries:
                    entry_norm = entry.replace("\\", "/")
                    if entry_norm == merged_jar_rel:
                        if not inserted_merged:
                            updated_entries.append(merged_jar_rel)
                            inserted_merged = True
                        continue
                    if entry_norm == "client.jar" or (forge_core_rel and entry_norm == forge_core_rel):
                        if not inserted_merged:
                            updated_entries.append(merged_jar_rel)
                            inserted_merged = True
                        continue
                    if fml_jar_rel and entry_norm == fml_jar_rel:
                        continue
                    updated_entries.append(entry)

                if not inserted_merged:
                    updated_entries.insert(0, merged_jar_rel)

                classpath_entries = updated_entries
                print(colorize_log(
                    "[launcher] Using merged legacy Forge/client jar for pre-1.6 compatibility"
                ))

    legacy_direct_buffer_patch = ""
    if _is_legacy_pre16_runtime(version_identifier):
        legacy_applet_window_patch = _prepare_legacy_applet_window_patch(version_dir)
        if legacy_applet_window_patch and legacy_applet_window_patch not in classpath_entries:
            classpath_entries.insert(0, legacy_applet_window_patch)

        legacy_direct_buffer_patch = _prepare_legacy_direct_buffer_sound_patch(version_dir)
        if legacy_direct_buffer_patch and legacy_direct_buffer_patch not in classpath_entries:
            classpath_entries.insert(0, legacy_direct_buffer_patch)

    classpath = _join_classpath(version_dir, classpath_entries)
    username = username_override or global_settings.get("username", "Player")
    min_ram = global_settings.get("min_ram", "2048M")
    max_ram = global_settings.get("max_ram", "4096M")
    selected_java_setting = (global_settings.get("java_path") or "").strip()
    if java_runtime_override:
        java_executable = str(java_runtime_override).strip()
    elif (
        selected_java_setting
        and selected_java_setting not in (JAVA_RUNTIME_MODE_AUTO, JAVA_RUNTIME_MODE_PATH)
        and os.path.isfile(selected_java_setting)
    ):
        java_executable = selected_java_setting
    else:
        java_executable = get_path_java_executable()
    global_extra_jvm_args_raw = (global_settings.get("extra_jvm_args") or "").strip()
    game_dir = _resolve_game_dir(global_settings, version_dir)
    if loader and loader.lower() == "neoforge":
        _ensure_neoforge_early_window_disabled(game_dir)

    assets_root_override = _prepare_legacy_assets_directory(version_identifier, version_dir, game_dir, meta)
    if assets_root_override:
        _prepare_legacy_client_resources(version_dir, assets_root_override)

    _prepare_legacy_options_file(version_identifier, game_dir)

    if loader and loader.lower() == "forge":
        major_pre, minor_pre = _parse_mc_version(version_identifier)
        if major_pre == 1 and minor_pre is not None and minor_pre < 6 and _legacy_forge_has_fml(version_dir, loader_version):
            _stage_legacy_fml_libraries(game_dir)

    cmd = [java_executable, f"-Xms{min_ram}", f"-Xmx{max_ram}"]

    if global_extra_jvm_args_raw:
        try:
            parsed_extra_args = shlex.split(global_extra_jvm_args_raw, posix=False)
        except Exception:
            parsed_extra_args = global_extra_jvm_args_raw.split()
        if parsed_extra_args:
            cmd.extend(parsed_extra_args)
            print(colorize_log(
                f"[launcher] Added {len(parsed_extra_args)} user-configured JVM argument(s)"
            ))

    try:
        if _is_legacy_pre16_runtime(version_identifier):
            legacy_flag = "-Djava.util.Arrays.useLegacyMergeSort=true"
            if not any(str(a).strip().startswith("-Djava.util.Arrays.useLegacyMergeSort") for a in cmd):
                cmd.append(legacy_flag)
                print(colorize_log(f"[launcher] Added JVM arg for legacy sorting: {legacy_flag}"))
    except Exception:
        pass

    forge_fml_metadata: dict = {}
    neoforge_profile_version = ""
    babric_metadata_game_args: list = []

    if loader and loader.lower() == "forge":
        mc_version_str = version_identifier.split("/")[-1].split("-")[0]

        is_modlauncher = main_class == "cpw.mods.modlauncher.Launcher"
        is_launchwrapper = main_class == "net.minecraft.launchwrapper.Launch"

        if _is_legacy_forge_runtime(version_identifier):
            _prepare_legacy_forge_runtime_files(version_dir, game_dir, loader_version)

        metadata_jvm_args_raw = _get_forge_metadata_args(version_dir, loader_version, "jvm")
        metadata_jvm_args = (
            _expand_forge_metadata_args(metadata_jvm_args_raw, version_dir, loader_version, version_identifier)
            if metadata_jvm_args_raw
            else []
        )

        if metadata_jvm_args:
            cmd.extend(metadata_jvm_args)
            print(colorize_log(
                f"[launcher] Added {len(metadata_jvm_args)} Forge metadata JVM argument(s)"
            ))
        else:
            try:
                java_version_output = subprocess.check_output(
                    [java_executable, "-version"],
                    stderr=subprocess.STDOUT,
                    **no_window_kwargs(),
                ).decode("utf-8", errors="ignore")
                if "1.8" not in java_version_output:
                    cmd.extend([
                        "--add-exports=java.base/sun.security.util=ALL-UNNAMED",
                        "--add-exports=jdk.naming.dns/com.sun.jndi.dns=java.naming",
                        "--add-opens=java.base/java.util.jar=ALL-UNNAMED",
                        "--add-opens=java.base/java.lang.invoke=ALL-UNNAMED",
                    ])
                    print(colorize_log("[launcher] Added Java 9+ Forge compatibility arguments"))
            except Exception:
                pass

        if is_modlauncher:
            print(colorize_log(
                "[launcher] Detected ModLauncher-based Forge, will add FML properties as command-line arguments"
            ))

            forge_fml_metadata = _get_forge_fml_metadata(version_dir, loader_version)

            if "mc_version" not in forge_fml_metadata:
                forge_fml_metadata["mc_version"] = mc_version_str

            if "forge_version" not in forge_fml_metadata and loader_version:
                forge_fml_metadata["forge_version"] = loader_version
            elif "forge_version" not in forge_fml_metadata:
                forge_fml_metadata["forge_version"] = _get_loader_version(version_dir, "forge")

            if "forge_group" not in forge_fml_metadata:
                forge_fml_metadata["forge_group"] = "net.minecraftforge"

        elif is_launchwrapper:
            print(colorize_log("[launcher] Detected LaunchWrapper-based Forge, skipping FML properties"))

    elif loader and loader.lower() == "neoforge":
        metadata_jvm_args_raw = _get_loader_metadata_args(version_dir, "neoforge", loader_version, "jvm")
        metadata_jvm_args = (
            _expand_loader_metadata_args(
                metadata_jvm_args_raw, version_dir, "neoforge", loader_version, version_identifier
            )
            if metadata_jvm_args_raw
            else []
        )

        if metadata_jvm_args:
            cmd.extend(metadata_jvm_args)
            print(colorize_log(
                f"[launcher] Added {len(metadata_jvm_args)} NeoForge metadata JVM argument(s)"
            ))

        try:
            actual_loader_version = loader_version or _get_loader_version(version_dir, "neoforge")
            if actual_loader_version:
                metadata_version_path = os.path.join(
                    version_dir, "loaders", "neoforge", actual_loader_version, ".metadata", "version.json"
                )
                if os.path.exists(metadata_version_path):
                    import json as _json

                    with open(metadata_version_path, "r", encoding="utf-8") as f:
                        neoforge_version_data = _json.load(f)
                    neoforge_profile_version = str(neoforge_version_data.get("id") or "").strip()
        except Exception as e:
            print(colorize_log(
                f"[launcher] Warning: Could not read NeoForge metadata version id: {e}"
            ))

    ygg_port = 0
    port_str = os.environ.get("HISTOLAUNCHER_PORT")
    if port_str:
        try:
            ygg_port = int(port_str)
        except ValueError:
            ygg_port = 0

    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    authlib_path = os.path.join(project_root, "assets", "authlib-injector.jar")
    if os.path.exists(authlib_path):
        if ygg_port > 0:
            ygg_url = f"http://127.0.0.1:{ygg_port}/authserver"
            cmd.append(f"-javaagent:{authlib_path}={ygg_url}")

    if ygg_port > 0 and _is_legacy_http_proxy_needed(version_identifier):
        cmd.extend([
            "-Dhttp.proxyHost=127.0.0.1",
            f"-Dhttp.proxyPort={ygg_port}",
            "-Dhttps.proxyHost=127.0.0.1",
            f"-Dhttps.proxyPort={ygg_port}",
            "-Dhttp.nonProxyHosts=localhost|127.*",
            "-Dhttps.nonProxyHosts=localhost|127.*",
        ])
        print(colorize_log(
            f"[launcher] Enabled legacy HTTP proxy bridge via 127.0.0.1:{ygg_port}"
        ))

    native_folder = meta.get("native_subfolder") or _native_subfolder_for_platform()
    native_path = os.path.join(version_dir, native_folder)
    if any(_is_platform_specific_runtime_jar(os.path.basename(entry)) for entry in classpath_entries):
        if not _native_directory_has_binaries(native_path):
            used_jars, extracted_files = _extract_current_platform_native_binaries(
                version_dir, classpath_entries, native_path,
            )
            if extracted_files:
                print(colorize_log(
                    f"[launcher] Prepared native runtime directory with {extracted_files} binary file(s) "
                    f"from {used_jars} JAR(s)"
                ))

        native_props_added = 0
        if os.path.isdir(native_path):
            native_props_added += int(_append_system_property_if_missing(cmd, "java.library.path", native_path))
            native_props_added += int(_append_system_property_if_missing(cmd, "jna.tmpdir", native_path))
            native_props_added += int(_append_system_property_if_missing(cmd, "org.lwjgl.system.SharedLibraryExtractPath", native_path))
            native_props_added += int(_append_system_property_if_missing(cmd, "io.netty.native.workdir", native_path))
            if native_props_added:
                print(colorize_log(
                    f"[launcher] Added {native_props_added} native runtime JVM propert"
                    f"{'y' if native_props_added == 1 else 'ies'}"
                ))
    elif os.path.isdir(native_path):
        _append_system_property_if_missing(cmd, "java.library.path", native_path)

    if loader and loader.lower() == "fabric":
        from core.downloader.yarn import _download_yarn_mappings

        mc_version = _extract_mc_version_string(version_identifier)
        uses_intermediary = _fabric_uses_intermediary_namespace(mc_version)

        if uses_intermediary:
            yarn_mappings = _download_yarn_mappings(version_dir, mc_version, "launch")
            if not yarn_mappings:
                print(colorize_log("[launcher] WARNING: Yarn mappings not available for Fabric"))
                print(colorize_log("[launcher] Some mods may not work properly without Yarn mappings"))
            classpath_file = os.path.join(version_dir, ".fabric_remap_classpath.txt")
            classpath_entries = []
            try:
                with open(classpath_file, "w") as f:
                    for entry in classpath.split(os.pathsep):
                        entry = entry.strip()
                        if entry:
                            abs_path = os.path.abspath(entry)
                            f.write(abs_path + "\n")
                            classpath_entries.append(abs_path)
                print(colorize_log(
                    f"[launcher] Created Fabric remapping classpath file ({len(classpath_entries)} entries)"
                ))
            except Exception as e:
                print(colorize_log(f"[launcher] ERROR creating Fabric remapping classpath file: {e}"))
                _set_last_launch_error(
                    version_identifier,
                    f"Could not prepare Fabric runtime remap classpath: {e}",
                )
                return False

            cmd.append("-Dfabric.gameMappingNamespace=official")
            cmd.append("-Dfabric.runtimeMappingNamespace=intermediary")
            cmd.append("-Dfabric.defaultModDistributionNamespace=intermediary")

            if yarn_mappings:
                cmd.append(f"-Dfabric.mappingPath={yarn_mappings}")

            cmd.append(f"-Dfabric.remapClasspathFile={classpath_file}")
            cmd.append(f"-Dfabric.gameJarPath={os.path.join(version_dir, 'client.jar')}")

            print("[launcher] Fabric runtime remapping configured:")
            if yarn_mappings:
                print(f"  [OK] Yarn mappings: {os.path.basename(yarn_mappings)}")
            else:
                print("  [NO] Yarn mappings: Not available (mods may warn or fail)")
            print(f"  [OK] Remapping classpath: {len(classpath_entries)} JARs")
            print("  [OK] Namespace: official -> intermediary")
        else:
            print("[launcher] Fabric intermediary mappings not detected; using official runtime namespace")
            print("  [OK] Namespace: official")

        cmd.append("-Dfabric.development=false")

    if loader and loader.lower() == "babric":
        metadata_jvm_args_raw = _get_loader_metadata_args(version_dir, "babric", loader_version, "jvm")
        metadata_jvm_args = []
        skip_next = False
        for raw_arg in metadata_jvm_args_raw or []:
            arg = str(raw_arg or "")
            if skip_next:
                skip_next = False
                continue
            if arg == "-cp":
                skip_next = True
                continue
            arg = arg.replace("${classpath}", classpath)
            arg = arg.replace("${natives_directory}", native_path)
            arg = arg.strip()
            arg = re.sub(r"^(-D[^=\s]+)=\s+(.+)$", r"\1=\2", arg)
            if not arg or arg.startswith("-Djava.library.path="):
                continue
            metadata_jvm_args.append(arg)

        if metadata_jvm_args:
            cmd.extend(metadata_jvm_args)
            print(colorize_log(
                f"[launcher] Added {len(metadata_jvm_args)} Babric metadata JVM argument(s)"
            ))

        metadata_game_args_raw = _get_loader_metadata_args(version_dir, "babric", loader_version, "game")
        if metadata_game_args_raw:
            babric_metadata_game_args = _expand_loader_metadata_args(
                metadata_game_args_raw,
                version_dir,
                "babric",
                loader_version,
                version_identifier,
                assets_root_override=assets_root_override,
            )
            if babric_metadata_game_args:
                print(colorize_log(
                    f"[launcher] Prepared {len(babric_metadata_game_args)} Babric metadata game argument(s)"
                ))

        cmd.append("-Dfabric.development=false")

    if loader and loader.lower() == "quilt":
        cmd.append("-Dloader.development=false")

    if loader and loader.lower() in ("forge", "neoforge"):
        print(f"[launcher] Configuring {loader} environment...")

        loader_version = loader_version or _get_loader_version(version_dir, loader.lower())
        if loader_version:
            forge_loader_dir = os.path.join(version_dir, "loaders", loader.lower(), loader_version)

            log4j_config = None
            for config_file in ["log4j2.xml", "log4j.properties", "log4j.xml"]:
                config_path = os.path.join(forge_loader_dir, config_file)
                if os.path.exists(config_path):
                    log4j_config = config_path
                    print(colorize_log(f"[launcher] Found {loader} log4j config: {config_file}"))
                    break

            if log4j_config:
                if log4j_config.endswith(".xml"):
                    cmd.append(f"-Dlog4j.configurationFile=file:///{log4j_config.replace(chr(92), '/')}")
                else:
                    cmd.append(f"-Dlog4j.configuration=file:///{log4j_config.replace(chr(92), '/')}")
                print(colorize_log(f"[launcher] Set log4j configuration: {log4j_config}"))
            else:
                fallback_log4j_path = os.path.join(forge_loader_dir, "log4j2.xml")
                if _create_fallback_log4j2_config(fallback_log4j_path):
                    log4j_config = fallback_log4j_path
                    cmd.append(f"-Dlog4j.configurationFile=file:///{log4j_config.replace(chr(92), '/')}")
                    print(colorize_log(
                        f"[launcher] Created fallback {loader} log4j config: {log4j_config}"
                    ))
                else:
                    print(colorize_log(
                        f"[launcher] WARNING: No log4j configuration found in {loader} directory"
                    ))
                    print(colorize_log(
                        f"[launcher] {loader} may have startup issues without proper logging configuration"
                    ))

        if loader.lower() == "forge" and (not main_class or main_class == ""):
            main_class = "net.minecraft.client.main.Main"
            print(colorize_log(f"[launcher] Using vanilla main class for Forge: {main_class}"))

    cmd.extend(["-cp", classpath])
    cmd.append(main_class)

    if loader and loader.lower() == "forge" and main_class == "cpw.mods.modlauncher.Launcher":
        cmd.extend(["--launchTarget", "fmlclient"])
        print(colorize_log("[launcher] Added launch target: --launchTarget fmlclient"))

        if forge_fml_metadata.get("mc_version"):
            mc_ver = _normalize_forge_mc_version(forge_fml_metadata["mc_version"])
            cmd.extend(["--fml.mcVersion", mc_ver])
            print(colorize_log(f"[launcher] Added FML argument: --fml.mcVersion {mc_ver}"))

        if forge_fml_metadata.get("forge_version"):
            cmd.extend(["--fml.forgeVersion", forge_fml_metadata["forge_version"]])
            print(colorize_log(
                f"[launcher] Added FML argument: --fml.forgeVersion {forge_fml_metadata['forge_version']}"
            ))

        forge_group = forge_fml_metadata.get("forge_group") or "net.minecraftforge"
        cmd.extend(["--fml.forgeGroup", forge_group])
        print(colorize_log(f"[launcher] Added FML argument: --fml.forgeGroup {forge_group}"))

        mcp_version = _normalize_forge_mcp_version(
            forge_fml_metadata.get("mcp_version", ""),
            forge_fml_metadata.get("mc_version", ""),
        )

        if mcp_version:
            cmd.extend(["--fml.mcpVersion", mcp_version])
            print(colorize_log(f"[launcher] Added FML argument: --fml.mcpVersion {mcp_version}"))
        else:
            print(colorize_log(
                "[launcher] WARNING: Forge MCP version metadata is missing; launching without --fml.mcpVersion"
            ))

    if loader and loader.lower() == "forge" and (
        main_class.startswith("cpw.mods.bootstraplauncher")
        or main_class.startswith("net.minecraftforge.bootstrap")
    ):
        metadata_game_args_raw = _get_forge_metadata_args(version_dir, loader_version, "game")
        metadata_game_args = (
            _expand_forge_metadata_args(metadata_game_args_raw, version_dir, loader_version, version_identifier)
            if metadata_game_args_raw
            else []
        )
        if metadata_game_args:
            has_launch_target = any(arg == "--launchTarget" for arg in cmd)
            if not has_launch_target:
                cmd.extend(metadata_game_args)
                print(colorize_log(
                    f"[launcher] Added {len(metadata_game_args)} Forge metadata game argument(s) for bootstrap launch"
                ))

    if loader and loader.lower() == "neoforge":
        metadata_game_args_raw = _get_loader_metadata_args(version_dir, "neoforge", loader_version, "game")
        metadata_game_args = (
            _expand_loader_metadata_args(
                metadata_game_args_raw, version_dir, "neoforge", loader_version, version_identifier
            )
            if metadata_game_args_raw
            else []
        )
        if metadata_game_args:
            has_launch_target = any(arg == "--launchTarget" for arg in cmd)
            if not has_launch_target:
                cmd.extend(metadata_game_args)
                print(colorize_log(
                    f"[launcher] Added {len(metadata_game_args)} NeoForge metadata game argument(s)"
                ))

    if loader and loader.lower() == "forge" and main_class == "net.minecraft.launchwrapper.Launch":
        tweak_class = None

        major_mc, minor_mc = _parse_mc_version(version_identifier)
        is_pre_16_forge = (major_mc == 1 and minor_mc is not None and minor_mc < 6)
        try:
            actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
            if actual_loader_version:
                forge_loader_path = os.path.join(version_dir, "loaders", "forge", actual_loader_version)

                jars_checked = []
                for root, dirs, files in os.walk(forge_loader_path):
                    for filename in sorted(files):
                        is_forge_core_jar = (
                            filename.endswith(".jar")
                            and (
                                filename.startswith("forge-")
                                or filename.startswith("minecraftforge-")
                            )
                        )
                        if not is_forge_core_jar:
                            continue

                        forge_jar = os.path.join(root, filename)
                        jars_checked.append(filename)
                        print(colorize_log(
                            f"[launcher] Debug: Checking JAR for Tweak-Class: {filename}"
                        ))
                        try:
                            with zipfile.ZipFile(forge_jar, "r") as jar:
                                try:
                                    manifest_data = jar.read("META-INF/MANIFEST.MF").decode("utf-8")
                                    for line in manifest_data.split("\n"):
                                        line = line.strip()
                                        if line.startswith("Tweak-Class:"):
                                            tweak_class = line.split(":", 1)[1].strip()
                                            print(colorize_log(
                                                f"[launcher] Found Tweak-Class in {filename}: {tweak_class}"
                                            ))
                                            break
                                        elif line.startswith("TweakClass:"):
                                            tweak_class = line.split(":", 1)[1].strip()
                                            print(colorize_log(
                                                f"[launcher] Found TweakClass (old format) in {filename}: {tweak_class}"
                                            ))
                                            break
                                except KeyError:
                                    print(colorize_log(
                                        f"[launcher] Debug: No META-INF/MANIFEST.MF in {filename}"
                                    ))
                                    pass

                            if tweak_class:
                                break
                        except Exception as jar_err:
                            print(colorize_log(
                                f"[launcher] Debug: Could not read {filename}: {jar_err}"
                            ))

                    if tweak_class:
                        break

                if not tweak_class and jars_checked:
                    print(colorize_log(
                        f"[launcher] Debug: Checked {len(jars_checked)} JAR(s) but no Tweak-Class found"
                    ))
                elif not jars_checked:
                    print(colorize_log(
                        f"[launcher] Debug: No Forge core JAR files found in {forge_loader_path}"
                    ))

                if not tweak_class:
                    metadata_tweak = _get_forge_tweak_class_from_metadata(version_dir, actual_loader_version)
                    if metadata_tweak:
                        tweak_class = metadata_tweak
                        print(colorize_log(
                            f"[launcher] Using Forge tweak class from metadata: {tweak_class}"
                        ))

                if tweak_class and not _classpath_has_class(version_dir, classpath_entries, tweak_class):
                    print(colorize_log(
                        f"[launcher] Ignoring Forge tweak class not found on classpath: {tweak_class}"
                    ))
                    tweak_class = None

                if not tweak_class:
                    for fallback_tweak in (
                        "net.minecraftforge.fml.common.launcher.FMLTweaker",
                        "cpw.mods.fml.common.launcher.FMLTweaker",
                    ):
                        if _classpath_has_class(version_dir, classpath_entries, fallback_tweak):
                            tweak_class = fallback_tweak
                            print(colorize_log(
                                f"[launcher] Falling back to detected Forge tweak class: {tweak_class}"
                            ))
                            break

        except Exception as e:
            print(colorize_log(f"[launcher] Warning: Could not extract tweak class: {e}"))

        if tweak_class:
            cmd.extend(["--tweakClass", tweak_class])
            print(colorize_log(f"[launcher] Added Forge tweaker: {tweak_class}"))
        else:
            print(colorize_log(
                "[launcher] Warning: Could not determine Forge tweak class (mods may not load)"
            ))

    if loader and loader.lower() == "forge" and not main_class:
        print(colorize_log("[launcher] ERROR: Could not determine Forge main class!"))
        print(colorize_log("[launcher] This Forge version may not be properly supported yet."))
        print(colorize_log("[launcher] Attempting to use vanilla launcher as fallback..."))
        main_class = "net.minecraft.client.Minecraft"
        cmd[-1] = main_class

    from server.yggdrasil import _get_username_and_uuid

    username, auth_uuid_raw = _get_username_and_uuid()
    auth_uuid = (
        f"{auth_uuid_raw[0:8]}-{auth_uuid_raw[8:12]}-{auth_uuid_raw[12:16]}-"
        f"{auth_uuid_raw[16:20]}-{auth_uuid_raw[20:]}"
    )

    expanded_game_args: list = []
    extra = meta.get("extra_jvm_args")
    if extra:
        expanded = _expand_placeholders(
            extra,
            version_identifier,
            game_dir,
            version_dir,
            global_settings,
            meta,
            assets_root_override=assets_root_override,
        )
        expanded_game_args = expanded.split()

    if not expanded_game_args and loader and loader.lower() == "babric" and babric_metadata_game_args:
        expanded_game_args = list(babric_metadata_game_args)
        print(colorize_log("[launcher] Using Babric metadata game arguments"))

    if not expanded_game_args and main_class == "net.minecraft.launchwrapper.Launch" and _is_legacy_pre16_runtime(version_identifier):
        legacy_assets_dir = assets_root_override or os.path.join(game_dir, "resources")
        if loader and loader.lower() == "forge":
            expanded_game_args = [
                "--username",
                username,
                "--session",
                "0",
                "--version",
                _extract_mc_version_string(version_identifier) or version_identifier,
                "--assetsDir",
                legacy_assets_dir,
                "--gameDir",
                game_dir,
            ]
            print(colorize_log("[launcher] Applied legacy Forge LaunchWrapper args"))
        else:
            expanded_game_args = [
                username,
                "0",
                "--assetsDir",
                legacy_assets_dir,
                "--tweakClass",
                "net.minecraft.launchwrapper.AlphaVanillaTweaker",
                "--gameDir",
                game_dir,
            ]
            print(colorize_log("[launcher] Applied runtime fallback legacy LaunchWrapper args"))

    if expanded_game_args:
        if (
            main_class == "net.minecraft.launchwrapper.Launch"
            and _is_legacy_pre16_runtime(version_identifier)
            and not (loader and loader.lower() == "forge")
        ):
            tweak = _extract_tweak_class_from_arg_list(expanded_game_args)
            if not tweak:
                expanded_game_args.extend(["--tweakClass", "net.minecraft.launchwrapper.AlphaVanillaTweaker"])
                print(colorize_log(
                    "[launcher] Added missing legacy --tweakClass AlphaVanillaTweaker"
                ))
        cmd.extend(expanded_game_args)
    else:
        cmd.append(username)

    has_flag_style_game_args = any(arg.startswith("--") for arg in expanded_game_args)
    if game_dir is not None and has_flag_style_game_args:
        _set_or_append_cli_arg(cmd, "--gameDir", game_dir)

    if loader and loader.lower() == "forge" and main_class == "cpw.mods.modlauncher.Launcher":
        mc_ver = (
            _normalize_forge_mc_version(forge_fml_metadata.get("mc_version", ""))
            or _extract_mc_version_string(version_identifier)
        )
        forge_ver = (forge_fml_metadata.get("forge_version") or "").strip()
        if mc_ver and forge_ver:
            forge_profile_version = f"{mc_ver}-forge-{forge_ver}"
            _set_or_append_cli_arg(cmd, "--version", forge_profile_version)
            print(colorize_log(
                f"[launcher] Set Forge profile --version argument: {forge_profile_version}"
            ))

    if loader and loader.lower() == "neoforge":
        if neoforge_profile_version:
            _set_or_append_cli_arg(cmd, "--version", neoforge_profile_version)
            print(colorize_log(
                f"[launcher] Set NeoForge profile --version argument: {neoforge_profile_version}"
            ))

    if loader and loader.lower() == "forge":
        print("[launcher] Validating Forge configuration...")
        actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
        if actual_loader_version:
            forge_loader_dir = os.path.join(version_dir, "loaders", "forge", actual_loader_version)

            if not os.path.isdir(forge_loader_dir):
                print(colorize_log(
                    f"[launcher] ERROR: Forge loader directory not found: {forge_loader_dir}"
                ))
                _set_last_launch_error(
                    version_identifier,
                    f"Forge loader directory not found: {forge_loader_dir}",
                )
                return False

            root_jar_files = [f for f in os.listdir(forge_loader_dir) if f.endswith(".jar")]
            runtime_jar_entries = _get_loader_jars(version_dir, "forge", actual_loader_version)
            recursive_jar_count = 0
            for root, _, files in os.walk(forge_loader_dir):
                recursive_jar_count += sum(1 for f in files if f.endswith(".jar"))

            uses_library_only_layout = bool(
                main_class
                and (
                    main_class == "cpw.mods.modlauncher.Launcher"
                    or main_class.startswith("cpw.mods.bootstraplauncher")
                    or main_class.startswith("net.minecraftforge.bootstrap")
                )
            )

            if not root_jar_files:
                if uses_library_only_layout and runtime_jar_entries:
                    print(colorize_log(
                        f"[launcher] [OK] Forge library-only layout valid "
                        f"({len(runtime_jar_entries)} runtime JARs from metadata, {recursive_jar_count} total on disk)"
                    ))
                else:
                    print(colorize_log("[launcher] ERROR: No JAR files found in Forge directory"))
                    _set_last_launch_error(
                        version_identifier,
                        "No JAR files were found in the Forge loader directory.",
                    )
                    return False

            if _legacy_forge_requires_modloader(version_dir, actual_loader_version) and not _has_modloader_runtime(version_dir):
                print(colorize_log(
                    "[launcher] ERROR: This pre-FML Forge build requires ModLoader, but no ModLoader runtime was found."
                ))
                print(colorize_log(
                    "[launcher] Forge 1.1-era builds are ModLoader addons and cannot function as standalone Forge installs."
                ))
                print(colorize_log(
                    "[launcher] Add a matching ModLoader jar (containing BaseMod.class and ModLoader.class) "
                    "to the version root, e.g. clients/<category>/<version>/modloader-<version>.jar, then relaunch Forge."
                ))
                _set_last_launch_error(
                    version_identifier,
                    "This pre-FML Forge build requires ModLoader runtime classes, but no compatible ModLoader runtime was found.",
                )
                return False

            if root_jar_files:
                print(colorize_log(
                    f"[launcher] [OK] Forge loader directory valid "
                    f"({len(root_jar_files)} root JARs, {recursive_jar_count} total)"
                ))

            if main_class and main_class == "cpw.mods.modlauncher.Launcher":
                print(colorize_log("[launcher] Setting up ModLauncher forge JAR paths..."))
                try:
                    universal_jar = None
                    for jar_file in root_jar_files:
                        if jar_file.startswith("forge-") and jar_file.endswith("-universal.jar"):
                            universal_jar = jar_file
                            break

                    if universal_jar:
                        jar_base = universal_jar.replace("forge-", "").replace("-universal.jar", "")
                        parts = jar_base.rsplit("-", 1)
                        if len(parts) == 2:
                            mc_ver, forge_ver = parts
                            maven_path = os.path.join(
                                forge_loader_dir, "libraries", "net", "minecraftforge", "forge",
                                f"{mc_ver}-{forge_ver}",
                            )

                            print(colorize_log(
                                f"[launcher] Forge JAR: {universal_jar} -> MC:{mc_ver} Forge:{forge_ver}"
                            ))

                            os.makedirs(maven_path, exist_ok=True)

                            src_jar = os.path.join(forge_loader_dir, universal_jar)
                            dst_jar = os.path.join(maven_path, universal_jar)

                            try:
                                if os.path.exists(dst_jar):
                                    print(colorize_log("[launcher] Maven universal JAR already exists"))
                                else:
                                    try:
                                        os.link(src_jar, dst_jar)
                                        print(colorize_log("[launcher] Linked universal JAR to Maven path"))
                                    except (OSError, NotImplementedError):
                                        shutil.copy2(src_jar, dst_jar)
                                        print(colorize_log("[launcher] Copied universal JAR to Maven path"))
                            except Exception as link_err:
                                print(colorize_log(
                                    f"[launcher] Warning: Could not link/copy universal JAR: {link_err}"
                                ))

                            client_jar_name = f"forge-{mc_ver}-{forge_ver}.jar"
                            client_jar_path = os.path.join(forge_loader_dir, client_jar_name)

                            if os.path.exists(client_jar_path):
                                dst_client_jar = os.path.join(
                                    maven_path, f"forge-{mc_ver}-{forge_ver}-client.jar"
                                )
                                try:
                                    if not os.path.exists(dst_client_jar):
                                        try:
                                            os.link(client_jar_path, dst_client_jar)
                                            print(colorize_log("[launcher] Linked client JAR to Maven path"))
                                        except (OSError, NotImplementedError):
                                            shutil.copy2(client_jar_path, dst_client_jar)
                                            print(colorize_log("[launcher] Copied client JAR to Maven path"))
                                except Exception as e:
                                    print(colorize_log(
                                        f"[launcher] Warning: Could not link/copy client JAR: {e}"
                                    ))

                            try:
                                raw_mcp = _normalize_forge_mcp_version(
                                    forge_fml_metadata.get("mcp_version", ""), mc_ver,
                                )
                                if raw_mcp:
                                    token = f"{mc_ver}-{raw_mcp}"
                                    client_mcp_dir = os.path.join(
                                        forge_loader_dir,
                                        "libraries",
                                        "net",
                                        "minecraft",
                                        "client",
                                        token,
                                    )
                                    os.makedirs(client_mcp_dir, exist_ok=True)

                                    plain_extra = os.path.join(
                                        forge_loader_dir,
                                        "libraries",
                                        "net",
                                        "minecraft",
                                        "client",
                                        mc_ver,
                                        f"client-{mc_ver}-extra.jar",
                                    )
                                    base_client_jar = os.path.join(version_dir, "client.jar")
                                    source_client = plain_extra if os.path.exists(plain_extra) else base_client_jar

                                    for suffix in ("extra", "srg"):
                                        target_jar = os.path.join(
                                            client_mcp_dir, f"client-{token}-{suffix}.jar"
                                        )
                                        if os.path.exists(target_jar):
                                            continue
                                        if not os.path.exists(source_client):
                                            continue
                                        try:
                                            os.link(source_client, target_jar)
                                        except (OSError, NotImplementedError):
                                            shutil.copy2(source_client, target_jar)
                                        print(colorize_log(
                                            f"[launcher] Staged missing ModLauncher MCP client resource: "
                                            f"libraries/net/minecraft/client/{token}/client-{token}-{suffix}.jar"
                                        ))
                            except Exception as e:
                                print(colorize_log(
                                    f"[launcher] Warning: Could not stage MCP client resources: {e}"
                                ))
                        else:
                            print(colorize_log(
                                f"[launcher] Warning: Could not parse forge JAR version from {universal_jar}"
                            ))
                except Exception as maven_err:
                    print(colorize_log(
                        f"[launcher] Warning: Could not set up Maven path: {maven_err}"
                    ))

            has_log4j = any(
                f in os.listdir(forge_loader_dir)
                for f in ["log4j2.xml", "log4j.properties", "log4j.xml"]
            )
            if has_log4j:
                print(colorize_log("[launcher] [OK] Log4j configuration found"))
            else:
                print(colorize_log(
                    "[launcher] [WARN] No log4j configuration found (may cause startup warnings)"
                ))
        else:
            print(colorize_log("[launcher] ERROR: Could not determine Forge version"))
            return False

    if loader and loader.lower() == "fabric":
        remap_classpath_arg = next(
            (arg for arg in cmd if arg.startswith("-Dfabric.remapClasspathFile=")),
            "",
        )

        if remap_classpath_arg:
            classpath_file = remap_classpath_arg.split("=", 1)[1]
            if not os.path.exists(classpath_file):
                print(colorize_log("[launcher] ERROR: Fabric remapping classpath file missing"))
                print(colorize_log(f"[launcher] Expected: {classpath_file}"))
                return False

            with open(classpath_file, "r") as f:
                classpath_lines = [line.strip() for line in f if line.strip()]

            if not classpath_lines:
                print(colorize_log("[launcher] ERROR: Fabric remapping classpath file is empty"))
                return False

            relative_entries = []
            for path in classpath_lines:
                if not os.path.isabs(path):
                    relative_entries.append(path)

            if relative_entries:
                print(colorize_log(
                    "[launcher] ERROR: Relative paths in classpath file (must be absolute):"
                ))
                for path in relative_entries[:3]:
                    print(f"    {path}")
                return False

            print(colorize_log(
                f"[launcher] [OK] Fabric configuration validated ({len(classpath_lines)} JARs"
            ))
        else:
            print(colorize_log(
                "[launcher] Fabric remapping classpath not required for this namespace"
            ))

    skins_cache_dir = os.path.join(base_dir, "assets", "skins")
    if os.path.isdir(skins_cache_dir):
        try:
            shutil.rmtree(skins_cache_dir)
            print(colorize_log("[launcher] Cleared skin texture cache"))
        except Exception as e:
            print(colorize_log(f"[launcher] Warning: could not clear skin cache: {e}"))

    copied_mods = list(copied_mods_override or [])
    if copied_mods_override is None and game_dir:
        copied_mods = _stage_addons_for_launch(game_dir, loader)
    if modloader_overwrite_dir and os.path.isdir(modloader_overwrite_dir):
        if modloader_overwrite_dir not in copied_mods:
            copied_mods.append(modloader_overwrite_dir)

    print("Launching version:", version_identifier)
    print("Version dir:", version_dir)
    if loader:
        print(f"Mod loader: {loader}")
    launch_cwd = game_dir if (game_dir and os.path.isdir(game_dir)) else version_dir
    print("Working dir:", launch_cwd)
    print("Command:", " ".join(cmd))
    # Suppress the stray Windows console java.exe would otherwise allocate
    # when pythonw (no console) is the parent process.
    _popen_kwargs = no_window_kwargs()
    legacy_forge_appdata_shim = ""
    if _is_direct_legacy_forge_launch(loader_key, legacy_runtime, main_class):
        legacy_forge_appdata_shim = _prepare_legacy_forge_appdata_shim(game_dir)
        if legacy_forge_appdata_shim:
            launch_env = os.environ.copy()
            launch_env["APPDATA"] = legacy_forge_appdata_shim
            _popen_kwargs["env"] = launch_env
            print(colorize_log(
                f"[launcher] Redirecting legacy Forge APPDATA to selected game directory via {legacy_forge_appdata_shim}"
            ))
    try:
        log_file_path, log_file = _create_version_log_file(version_identifier)

        if log_file:
            process = subprocess.Popen(
                cmd,
                cwd=launch_cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **_popen_kwargs,
            )
        else:
            process = subprocess.Popen(cmd, cwd=launch_cwd, **_popen_kwargs)

        version_name = (
            version_identifier.split("/", 1)[1] if "/" in version_identifier else version_identifier
        )

        if log_file and process.stdout:
            reader_thread = threading.Thread(
                target=_output_reader_thread,
                args=(process, log_file, version_name),
                daemon=True,
            )
            reader_thread.start()
            print(colorize_log("[launcher] Output reader thread started"))

        if legacy_forge_appdata_shim:
            threading.Thread(
                target=_cleanup_legacy_forge_appdata_shim_after_exit,
                args=(process, legacy_forge_appdata_shim),
                daemon=True,
            ).start()

        process_id = hashlib.sha1(
            f"{time.time()}{process.pid}".encode()
        ).hexdigest()[:16]

        tracked_copied_mods = copied_mods if track_copied_mods else []
        _register_process(process_id, process, version_identifier, log_file_path, tracked_copied_mods)

        print(colorize_log(f"[launcher] Process launched with ID: {process_id}"))
        return process_id
    except Exception as e:
        if legacy_forge_appdata_shim:
            _cleanup_legacy_forge_appdata_shim(legacy_forge_appdata_shim)
        print("ERROR launching:", e)
        _set_last_launch_error(version_identifier, f"Could not start Java process: {e}")
        return None


def _read_log_tail(log_path: str, max_chars: int = 65536) -> str:
    path = str(log_path or "").strip()
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as log_file:
            content = log_file.read()
        return content[-max(1024, int(max_chars or 0)):]
    except Exception:
        return ""


def _classify_auto_java_attempt_failure(log_text: str) -> str:
    lower = str(log_text or "").lower()
    if not lower:
        return "unknown"
    if (
        "unsupportedclassversionerror" in lower
        or "has been compiled by a more recent version" in lower
        or "class file version" in lower and "only recognizes class file versions up to" in lower
    ):
        return "java_too_old"
    if (
        "unrecognized vm option" in lower
        or "unrecognized option:" in lower
        or "invalid maximum heap size" in lower
        or "could not reserve enough space for object heap" in lower
        or "could not create the java virtual machine" in lower
    ):
        return "jvm_configuration"
    if (
        "---- minecraft crash report ----" in lower
        or "exception in thread" in lower
        or "net.minecraftforge.fml.loading.modloadingworker" in lower
        or "modloadingexception" in lower
        or "fabricloader" in lower and "exception" in lower
    ):
        return "minecraft_crash"
    return "unknown"


def _auto_java_attempt_message(failure_kind: str, java_display: str, log_path: str) -> str:
    if failure_kind == "jvm_configuration":
        return (
            f"Auto Java selected {java_display}, but the JVM rejected the launch options.\n"
            "Changing Java versions is unlikely to help until the JVM settings are fixed."
        )
    if failure_kind == "minecraft_crash":
        return (
            f"Auto Java selected {java_display}, but Minecraft crashed during startup.\n"
            "This does not look like a Java version mismatch, so Auto stopped trying other runtimes."
        )
    return (
        f"Auto Java selected {java_display}, but the game exited during startup.\n"
        "Auto stopped here so the first useful crash log is easier to debug."
    ) + (f"\nCrash log: {log_path}" if log_path else "")


def launch_version(version_identifier, username_override=None, loader=None, loader_version=None):
    version_dir = _resolve_version_dir(version_identifier)
    if not version_dir:
        _set_last_launch_error(
            version_identifier, f"Version directory not found for {version_identifier}"
        )
        return False

    try:
        from server import yggdrasil as _ygg
        from server.yggdrasil import _get_username_and_uuid

        try:
            _uname, _uhex = _get_username_and_uuid()
        except Exception:
            _uname, _uhex = "", ""
        threading.Thread(
            target=_ygg.cache_textures,
            args=(_uhex, _uname),
            kwargs={"probe_remote": True},
            daemon=True,
        ).start()
    except Exception:
        pass

    global_settings = load_global_settings() or {}
    game_dir, game_dir_error = _resolve_game_dir_with_error(global_settings, version_dir)
    if game_dir_error:
        _set_last_launch_error(version_identifier, game_dir_error)
        return False

    selected_java_setting = (global_settings.get("java_path") or "").strip()
    selected_mode = selected_java_setting or JAVA_RUNTIME_MODE_PATH
    loader_key = str(loader or "").strip().lower()
    allow_override_for_all_modloaders = _is_truthy_setting(
        global_settings.get("allow_override_classpath_all_modloaders", "0")
    )
    allow_overwrite_classpath_for_loader = bool(
        loader_key and (loader_key == "modloader" or allow_override_for_all_modloaders)
    )

    candidates, target_java_major = _resolve_java_launch_candidates(selected_mode, version_dir)
    if not candidates:
        if selected_mode == JAVA_RUNTIME_MODE_AUTO and target_java_major > 0:
            install_java_major = suggest_java_feature_version(target_java_major)
            _set_last_launch_diagnostic(
                version_identifier,
                {
                    "auto_java": True,
                    "java_required_major": target_java_major,
                    "java_download_major": install_java_major,
                    "java_failure_kind": "no_compatible_runtime",
                    "java_attempts": [],
                },
            )
            _set_last_launch_error(
                version_identifier,
                f"Auto Java selection could not find a compatible runtime for <b>{version_identifier}</b>.\n\n"
                f"The version targets <b>Java {target_java_major}</b>.\n\n"
                f"Open the Java Runtime dropdown in Settings and choose <i>'+ Install Java'</i> to install <b>Java {install_java_major}</b> or newer.",
            )
            return False
        _set_last_launch_error(
            version_identifier, "No Java runtime candidates were found for launch."
        )
        return False

    modloader_overwrite_dir = ""
    if allow_overwrite_classpath_for_loader:
        modloader_overwrite_dir = _prepare_modloader_overwrite_layer(loader_key)

    copied_mods = []
    if game_dir:
        copied_mods = _stage_addons_for_launch(game_dir, loader)
    if modloader_overwrite_dir and os.path.isdir(modloader_overwrite_dir):
        copied_mods.append(modloader_overwrite_dir)

    auto_mode = selected_mode == JAVA_RUNTIME_MODE_AUTO
    tried_labels: list = []
    attempt_details: list[str] = []
    attempt_records: list[dict] = []
    last_log_path = ""
    last_failure_kind = "unknown"
    last_error = ""

    for candidate in candidates:
        java_path = str(candidate.get("path") or "").strip() or get_path_java_executable()
        java_label = str(candidate.get("label") or os.path.basename(java_path) or "Java")
        java_version = str(candidate.get("version") or "").strip()
        java_major = int(candidate.get("major") or 0)
        java_display = java_label
        if java_version and java_version != "unknown":
            java_display = f"{java_label} ({java_version})"
        elif java_major > 0:
            java_display = f"{java_label} (major {java_major})"
        tried_labels.append(java_display)

        print(colorize_log(f"[launcher] Trying Java runtime: {java_label} -> {java_path}"))

        process_id = _launch_version_once(
            version_identifier,
            username_override=username_override,
            loader=loader,
            loader_version=loader_version,
            java_runtime_override=java_path,
            copied_mods_override=copied_mods,
            modloader_overwrite_dir_override=modloader_overwrite_dir,
            track_copied_mods=not auto_mode,
        )

        if not process_id:
            last_error = consume_last_launch_error(version_identifier) or ""
            attempt_records.append({
                "java": java_display,
                "path": java_path,
                "major": java_major,
                "version": java_version,
                "error": last_error or "Process did not start",
            })
            if last_error:
                attempt_details.append(f"{java_display}: {last_error}")
                if copied_mods:
                    _cleanup_copied_mods(copied_mods)
                if auto_mode:
                    _set_last_launch_diagnostic(
                        version_identifier,
                        {
                            "auto_java": True,
                            "java_required_major": target_java_major,
                            "java_attempts": attempt_records,
                            "java_failure_kind": "process_start_error",
                        },
                    )
                    _set_last_launch_error(
                        version_identifier,
                        f"Auto Java selection stopped while trying {java_display}.\n{last_error}",
                    )
                else:
                    _set_last_launch_error(version_identifier, last_error)
                return False
            if not auto_mode:
                if copied_mods:
                    _cleanup_copied_mods(copied_mods)
                return False
            continue

        if not auto_mode:
            return process_id

        with STATE.process_lock:
            proc_info = STATE.active_processes.get(process_id)
            process_obj = proc_info.get("process") if proc_info else None

        if not process_obj:
            continue

        launch_stable, exit_code = _wait_for_launch_stability(process_obj)
        if launch_stable:
            _attach_copied_mods_to_process(process_id, copied_mods)
            print(colorize_log(f"[launcher] Auto Java selection succeeded with {java_label}"))
            return process_id

        status_info = _get_process_status(process_id) or {}
        log_path = str(status_info.get("log_path") or "").strip()
        last_log_path = log_path or last_log_path
        failure_kind = _classify_auto_java_attempt_failure(_read_log_tail(log_path))
        last_failure_kind = failure_kind
        attempt_detail = f"{java_display}: exit code {exit_code if exit_code is not None else 'unknown'}"
        if log_path:
            attempt_detail += f", log: {log_path}"
            print(colorize_log(
                f"[launcher] Auto Java attempt failed with exit code {exit_code}; "
                f"log: {log_path}"
            ))
        else:
            print(colorize_log(
                f"[launcher] Auto Java attempt failed with exit code {exit_code}"
            ))
        attempt_details.append(attempt_detail)
        attempt_records.append({
            "java": java_display,
            "path": java_path,
            "major": java_major,
            "version": java_version,
            "exit_code": exit_code,
            "log_path": log_path,
            "failure_kind": failure_kind,
        })

        if log_path and failure_kind != "java_too_old":
            if copied_mods:
                _cleanup_copied_mods(copied_mods)
            message = _auto_java_attempt_message(failure_kind, java_display, log_path)
            if log_path and "Crash log:" not in message:
                message += f"\nCrash log: {log_path}"
            _set_last_launch_diagnostic(
                version_identifier,
                {
                    "auto_java": True,
                    "java_required_major": target_java_major,
                    "java_attempts": attempt_records,
                    "java_failure_kind": failure_kind,
                    "java_selected": java_display,
                    "log_path": log_path,
                },
            )
            _set_last_launch_error(version_identifier, message)
            return False

    if copied_mods:
        _cleanup_copied_mods(copied_mods)

    version_name = (
        version_identifier.split("/", 1)[1] if "/" in version_identifier else version_identifier
    )
    if auto_mode:
        tried_text = ", ".join(tried_labels) if tried_labels else "no detected Java runtimes"
        detail_text = ""
        if attempt_details:
            detail_text = "\nAttempts:\n" + "\n".join(f"- {detail}" for detail in attempt_details)
        diagnostic = {
            "auto_java": True,
            "java_required_major": target_java_major,
            "java_attempts": attempt_records,
            "java_failure_kind": last_failure_kind,
        }
        if last_log_path:
            diagnostic["log_path"] = last_log_path
        if target_java_major > 0:
            install_java_major = suggest_java_feature_version(target_java_major)
            diagnostic["java_download_major"] = install_java_major
            last_error = (
                f"Auto Java selection could not launch {version_name}.\n\n"
                f"The version appears to target Java {target_java_major}, but no compatible Java runtime launched successfully.\n"
                f"Tried: {tried_text}{detail_text}"
            )
        else:
            last_error = (
                f"Auto Java selection could not launch {version_name}.\n\n"
                f"No detected Java runtime stayed alive long enough to complete startup.\n"
                f"Tried: {tried_text}{detail_text}"
            )
        _set_last_launch_diagnostic(version_identifier, diagnostic)
        _set_last_launch_error(version_identifier, last_error)
        return False

    if last_error:
        _set_last_launch_error(version_identifier, last_error)
    return False
