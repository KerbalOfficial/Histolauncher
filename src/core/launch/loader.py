from __future__ import annotations

import json
import os
import platform
import re
import zipfile

from core.logger import colorize_log
from core.settings import get_base_dir, load_global_settings

from core.launch.args import (
    _extract_tweak_class_from_arg_list,
    _extract_tweak_class_from_arg_string,
)
from core.launch.natives import (
    _native_subfolder_for_platform,
    _prune_neoforge_runtime_jars,
)
from core.launch.paths import (
    _extract_mc_version_string,
    _load_data_ini,
    _resolve_game_dir,
)


__all__ = [
    "_compare_mc_versions",
    "_expand_forge_metadata_args",
    "_expand_loader_metadata_args",
    "_fabric_uses_intermediary_namespace",
    "_get_forge_fml_metadata",
    "_get_forge_metadata_args",
    "_get_forge_tweak_class_from_metadata",
    "_get_jar_main_class",
    "_get_loader_jars",
    "_get_loader_main_class",
    "_get_loader_metadata_args",
    "_get_loader_version",
    "_get_mods_dir",
    "_normalize_forge_mc_version",
    "_normalize_forge_mcp_version",
    "_parse_version",
    "_version_satisfies",
    "check_mod_loader_compatibility",
]


def _get_loader_jars(version_dir: str, loader_type: str, loader_version: str = None) -> list:
    loaders_dir = os.path.join(version_dir, "loaders", loader_type.lower())
    jar_paths: list = []

    if not os.path.isdir(loaders_dir):
        return jar_paths

    try:
        version_path = None
        if loader_version:
            version_path = os.path.join(loaders_dir, loader_version)
            if not os.path.isdir(version_path):
                return jar_paths
        else:
            versions = [d for d in sorted(os.listdir(loaders_dir)) if os.path.isdir(os.path.join(loaders_dir, d))]
            if not versions:
                return jar_paths
            version_path = os.path.join(loaders_dir, versions[-1])

        if loader_type.lower() in ("forge", "neoforge"):
            try:
                metadata_dir = os.path.join(version_path, ".metadata")
                version_json_path = os.path.join(metadata_dir, "version.json")
                if os.path.exists(version_json_path):
                    with open(version_json_path, "r", encoding="utf-8") as f:
                        version_data = json.load(f)

                    libraries = version_data.get("libraries", []) or []
                    metadata_main_class = (version_data.get("mainClass") or "").strip().lower()
                    has_modlauncher_lib = any(
                        isinstance(lib, dict) and ":modlauncher:" in (lib.get("name") or "")
                        for lib in libraries
                    )
                    has_bootstrap_main = (
                        metadata_main_class.startswith("cpw.mods.bootstraplauncher")
                        or metadata_main_class.startswith("net.minecraftforge.bootstrap")
                    )

                    if has_modlauncher_lib or has_bootstrap_main:
                        ordered_paths: list = []
                        seen_paths: set = set()
                        loader_version_name = os.path.basename(version_path)
                        libraries_root_rel = os.path.join(
                            "loaders", loader_type.lower(), loader_version_name, "libraries"
                        )

                        def _add_rel_if_exists(rel_path: str):
                            rel_norm = rel_path.replace("\\", "/")
                            if rel_norm in seen_paths:
                                return
                            abs_path = os.path.join(version_dir, rel_path)
                            if os.path.isfile(abs_path):
                                seen_paths.add(rel_norm)
                                ordered_paths.append(rel_norm)

                        for lib in libraries:
                            if not isinstance(lib, dict):
                                continue

                            downloads = lib.get("downloads") or {}
                            artifact = downloads.get("artifact") or {}
                            artifact_path = artifact.get("path")
                            if artifact_path:
                                _add_rel_if_exists(os.path.join(libraries_root_rel, artifact_path))
                                continue

                            lib_name = lib.get("name", "")
                            parts = lib_name.split(":")
                            if len(parts) < 3:
                                continue
                            group, artifact_name, artifact_version = parts[0], parts[1], parts[2]
                            classifier = ""
                            if len(parts) >= 4:
                                classifier = parts[3].split("@", 1)[0]
                            artifact_dir = os.path.join(
                                libraries_root_rel,
                                group.replace(".", os.sep),
                                artifact_name,
                                artifact_version,
                            )
                            artifact_dir_abs = os.path.join(version_dir, artifact_dir)
                            if not os.path.isdir(artifact_dir_abs):
                                continue

                            jar_files = [
                                n for n in os.listdir(artifact_dir_abs) if n.endswith(".jar")
                            ]
                            if not jar_files:
                                continue

                            if classifier:
                                expected_name = f"{artifact_name}-{artifact_version}-{classifier}.jar"
                                if expected_name in jar_files:
                                    _add_rel_if_exists(os.path.join(artifact_dir, expected_name))
                                    continue

                            base_name = f"{artifact_name}-{artifact_version}.jar"
                            if base_name in jar_files:
                                _add_rel_if_exists(os.path.join(artifact_dir, base_name))
                                continue

                            jar_files.sort()
                            _add_rel_if_exists(os.path.join(artifact_dir, jar_files[0]))

                        if loader_type.lower() == "neoforge":
                            ordered_paths = _prune_neoforge_runtime_jars(ordered_paths)

                        if ordered_paths:
                            print(colorize_log(
                                f"[launcher] Using {len(ordered_paths)} {loader_type} ModLauncher libraries from metadata order"
                            ))
                            return ordered_paths
            except Exception as e:
                print(colorize_log(
                    f"[launcher] Warning: Could not build {loader_type} metadata classpath, falling back to scan: {e}"
                ))

        bootstrap_shim_path = os.path.join(version_path, "bootstrap-shim.list")
        bootstrap_libs: set = set()

        if loader_type.lower() in ("forge", "neoforge") and os.path.exists(bootstrap_shim_path):
            try:
                with open(bootstrap_shim_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "#" in line:
                            lib_path = line.split("#")[0]
                            lib_name = os.path.basename(lib_path)
                            bootstrap_libs.add(lib_name)

                if bootstrap_libs:
                    print(colorize_log(
                        f"[launcher] Loaded bootstrap-shim.list with {len(bootstrap_libs)} libraries"
                    ))
            except Exception as e:
                print(colorize_log(f"[launcher] Warning: Could not parse bootstrap-shim.list: {e}"))

        found_jars: list = []
        missing_libs: list = []

        for root, dirs, files in os.walk(version_path):
            for filename in sorted(files):
                if not filename.endswith(".jar"):
                    continue
                fullpath = os.path.join(root, filename)
                rel_from_version = os.path.relpath(fullpath, version_dir)
                found_jars.append(filename)

                rel_path = rel_from_version.replace("\\", "/")
                jar_paths.append(rel_path)

        if loader_type.lower() in ("forge", "neoforge") and len(found_jars) < 5:
            print(colorize_log(
                f"[launcher] Debug: Found {len(found_jars)} JAR files in {os.path.basename(version_path)}:"
            ))
            for jar in found_jars[:10]:
                print(f"  [launcher]   - {jar}")

        if bootstrap_libs:
            for expected_lib in sorted(bootstrap_libs):
                if expected_lib not in found_jars:
                    missing_libs.append(expected_lib)

            if missing_libs:
                print(colorize_log(
                    f"[launcher] Warning: {len(missing_libs)} libraries from bootstrap-shim.list are missing:"
                ))
                for lib in missing_libs[:5]:
                    print(f"  [launcher] Missing: {lib}")
                if len(missing_libs) > 5:
                    print(f"  [launcher] ... and {len(missing_libs)-5} more")
            else:
                print(colorize_log(f"[launcher] All {len(bootstrap_libs)} bootstrap libraries found"))

        if loader_type.lower() in ("forge", "neoforge"):
            maven_libs_path = os.path.join(version_path, "libraries")
            maven_libs_count = 0
            if os.path.isdir(maven_libs_path):
                for root, dirs, files in os.walk(maven_libs_path):
                    for filename in sorted(files):
                        if filename.endswith(".jar"):
                            fullpath = os.path.join(root, filename)
                            rel_from_version = os.path.relpath(fullpath, version_dir)
                            rel_path = rel_from_version.replace("\\", "/")
                            if rel_path not in jar_paths:
                                jar_paths.append(rel_path)
                                maven_libs_count += 1

            if maven_libs_count > 0:
                print(colorize_log(
                    f"[launcher] Added {maven_libs_count} Maven libraries from loader/libraries/"
                ))

        if loader_type.lower() == "neoforge":
            jar_paths = _prune_neoforge_runtime_jars(jar_paths)

        print(colorize_log(f"[launcher] Using {len(jar_paths)} {loader_type} libraries for classpath"))

    except Exception as e:
        print(colorize_log(f"[launcher] Error scanning loader JARs: {e}"))

    return jar_paths


def _parse_version(version_str: str) -> tuple:
    parts = re.split(r"[.\-+]", version_str)
    result = []
    for part in parts:
        try:
            result.append(int(part))
        except ValueError:
            result.append(part)
    return tuple(result)


def _get_loader_version(version_dir: str, loader_type: str) -> str:
    loaders_dir = os.path.join(version_dir, "loaders", loader_type.lower())
    if not os.path.isdir(loaders_dir):
        return ""
    versions = [d for d in os.listdir(loaders_dir) if os.path.isdir(os.path.join(loaders_dir, d))]
    if not versions:
        return ""
    versions.sort(key=_parse_version)
    return versions[-1]


def _fabric_uses_intermediary_namespace(mc_version: str) -> bool:
    version = (mc_version or "").strip().lower()
    if not version:
        return True

    snapshot_match = re.search(r"(\d{2})w\d+[a-z]", version)
    if snapshot_match:
        try:
            return int(snapshot_match.group(1)) < 26
        except ValueError:
            return True

    version = version.split("-", 1)[0]
    if version.startswith("1."):
        return True

    release_match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.\d+)?$", version)
    if release_match:
        try:
            major = int(release_match.group(1))
            minor_raw = release_match.group(2)
            minor = int(minor_raw) if minor_raw is not None else None
        except ValueError:
            return True

        if major < 26:
            return True
        if major > 26:
            return False

        if minor is None:
            return False

        return minor < 1

    return False


def _get_mods_dir(version_dir: str) -> str:
    global_settings = load_global_settings()
    game_dir = _resolve_game_dir(global_settings, version_dir)
    if not game_dir:
        return ""
    return os.path.join(game_dir, "mods")


def _version_satisfies(loader_ver: str, requirement: str) -> bool:
    if not requirement or requirement.strip() == "*":
        return True

    for part in requirement.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^([<>!=]+)\s*(.+)$", part)
        if m:
            op, ver = m.groups()
        else:
            op, ver = "==", part
        try:
            left = _parse_version(loader_ver)
            right = _parse_version(ver)
        except Exception:
            continue
        if op in ("==", "=") and not (left == right):
            return False
        if op == ">=" and not (left >= right):
            return False
        if op == "<=" and not (left <= right):
            return False
        if op == ">" and not (left > right):
            return False
        if op == "<" and not (left < right):
            return False
        if op == "!=" and not (left != right):
            return False
    return True


def check_mod_loader_compatibility(version_dir: str, loader_type: str) -> list:
    issues: list = []
    loader_ver = _get_loader_version(version_dir, loader_type)
    if not loader_ver:
        return issues

    mods_dir = _get_mods_dir(version_dir)
    if not os.path.isdir(mods_dir):
        return issues

    loader_type = str(loader_type or "").strip().lower()

    for fname in os.listdir(mods_dir):
        if not fname.endswith(".jar"):
            continue
        path = os.path.join(mods_dir, fname)
        try:
            with zipfile.ZipFile(path, "r") as jar:
                modinfo = None
                requirement = ""
                mod_id = "<unknown>"

                if loader_type in ("fabric", "babric"):
                    if "fabric.mod.json" not in jar.namelist():
                        continue
                    data = jar.read("fabric.mod.json").decode("utf-8")
                    modinfo = json.loads(data)
                    deps = modinfo.get("depends", {}) or {}
                    requirement = deps.get("fabricloader") or deps.get("fabric-loader") or ""
                    mod_id = modinfo.get("id", "<unknown>")
                elif loader_type == "quilt":
                    if "quilt.mod.json" not in jar.namelist():
                        continue
                    data = jar.read("quilt.mod.json").decode("utf-8")
                    modinfo = json.loads(data)
                    quilt_loader_meta = modinfo.get("quilt_loader", {}) or {}
                    mod_id = quilt_loader_meta.get("id", "<unknown>")
                    for dep in quilt_loader_meta.get("depends", []) or []:
                        if not isinstance(dep, dict):
                            continue
                        dep_id = str(dep.get("id") or "").strip().lower()
                        if dep_id not in ("quilt_loader", "fabric_loader", "fabricloader", "fabric-loader"):
                            continue
                        versions = dep.get("versions") or dep.get("version") or ""
                        if isinstance(versions, list):
                            requirement = ",".join(str(v).strip() for v in versions if str(v).strip())
                        else:
                            requirement = str(versions or "").strip()
                        if requirement:
                            break
                else:
                    continue
        except Exception:
            continue
        if requirement and not _version_satisfies(loader_ver, requirement):
            issues.append((mod_id, fname, requirement))
            print(colorize_log(
                f"[launcher] compatibility issue: mod {mod_id} ({fname}) requires loader {requirement}, current is {loader_ver}"
            ))
    return issues


def _get_jar_main_class(jar_path: str) -> str:
    try:
        with zipfile.ZipFile(jar_path, "r") as jar:
            manifest_data = jar.read("META-INF/MANIFEST.MF").decode("utf-8")
            lines = manifest_data.split("\n")
            for i, line in enumerate(lines):
                if line.startswith("Main-Class:"):
                    main_class = line[len("Main-Class:"):].strip()
                    while i + 1 < len(lines) and lines[i + 1].startswith(" "):
                        main_class += lines[i + 1].strip()
                        i += 1
                    return main_class
    except Exception:
        pass

    return ""


def _compare_mc_versions(version_a: str, version_b: str) -> int:
    try:
        def parse_version(v):
            return tuple(map(int, v.split(".")))

        a_parts = parse_version(version_a)
        b_parts = parse_version(version_b)

        if a_parts < b_parts:
            return -1
        elif a_parts > b_parts:
            return 1
        else:
            return 0
    except Exception:
        if version_a < version_b:
            return -1
        elif version_a > version_b:
            return 1
        else:
            return 0


def _normalize_forge_mc_version(mc_version: str) -> str:
    value = (mc_version or "").strip().strip("'\"")
    if not value:
        return ""

    if "-forge-" in value:
        return value.split("-forge-", 1)[0]

    if "-" in value:
        candidate = value.split("-", 1)[0]
        if re.match(r"^\d+\.\d+(?:\.\d+)?$", candidate):
            return candidate

    return value


def _normalize_forge_mcp_version(mcp_version: str, mc_version: str = "") -> str:
    value = (mcp_version or "").strip().strip("'\"")
    if not value:
        return ""

    mc_ver = _normalize_forge_mc_version(mc_version)
    if mc_ver and value.startswith(mc_ver + "-"):
        value = value[len(mc_ver) + 1:]

    return value


def _get_loader_main_class(version_dir: str, loader_type: str, loader_version: str = None) -> str:
    loader_type_lower = loader_type.lower()

    if loader_type_lower == "forge":
        loaders_dir = os.path.join(version_dir, "loaders", "forge")
        version_path = None
        if loader_version:
            version_path = os.path.join(loaders_dir, loader_version)
        else:
            try:
                versions = [d for d in sorted(os.listdir(loaders_dir)) if os.path.isdir(os.path.join(loaders_dir, d))]
                if versions:
                    version_path = os.path.join(loaders_dir, versions[-1])
            except Exception:
                version_path = None

        try:
            if version_path and os.path.isdir(version_path):
                version_json_path = os.path.join(version_path, ".metadata", "version.json")
                if os.path.exists(version_json_path):
                    with open(version_json_path, "r", encoding="utf-8") as f:
                        metadata_version = json.load(f)
                    declared_main = (metadata_version.get("mainClass") or "").strip()
                    if declared_main:
                        print(f"[launcher] Using Forge mainClass from metadata: {declared_main}")
                        return declared_main
        except Exception as e:
            print(f"[launcher] Warning: Could not read Forge metadata mainClass: {e}")

        version_dir_name = os.path.basename(version_dir.rstrip(os.sep))
        legacy_launchwrapper_only = False
        try:
            vparts = version_dir_name.split(".")
            vmajor = int(vparts[0]) if len(vparts) > 0 else 0
            vminor = int(vparts[1]) if len(vparts) > 1 else 0
            legacy_launchwrapper_only = (vmajor == 1 and vminor < 13)
        except Exception:
            legacy_launchwrapper_only = False

        def _jar_contains_class(search_class_path: str) -> bool:
            try:
                if not (version_path and os.path.isdir(version_path)):
                    return False
                for root, dirs, files in os.walk(version_path):
                    for fname in files:
                        if not fname.endswith(".jar"):
                            continue
                        jarp = os.path.join(root, fname)
                        try:
                            with zipfile.ZipFile(jarp, "r") as jar:
                                if search_class_path in jar.namelist():
                                    return True
                        except Exception:
                            continue
            except Exception:
                return False
            return False

        if version_path and os.path.isdir(version_path):
            try:
                for root, dirs, files in os.walk(version_path):
                    for fname in files:
                        if not fname.endswith(".jar"):
                            continue
                        jarp = os.path.join(root, fname)
                        try:
                            with zipfile.ZipFile(jarp, "r") as jar:
                                try:
                                    mf = jar.read("META-INF/MANIFEST.MF").decode("utf-8")
                                except Exception:
                                    mf = ""
                                if "Tweak-Class:" in mf:
                                    if _jar_contains_class("net/minecraft/launchwrapper/Launch.class"):
                                        return "net.minecraft.launchwrapper.Launch"
                                    else:
                                        print("[launcher] Detected Tweak-Class but LaunchWrapper class not found in extracted JARs")
                        except Exception:
                            continue
            except Exception:
                pass

        if legacy_launchwrapper_only:
            from core.launch.legacy import _legacy_forge_has_fml

            if not _legacy_forge_has_fml(version_dir, loader_version):
                print("[launcher] Pre-FML Forge detected (no cpw/mods/fml/ classes), launching directly")
                return "net.minecraft.client.Minecraft"

            has_launchwrapper_tweaker = (
                _jar_contains_class("cpw/mods/fml/common/launcher/FMLTweaker.class")
                or _jar_contains_class("net/minecraftforge/fml/common/launcher/FMLTweaker.class")
            )
            if not has_launchwrapper_tweaker:
                print("[launcher] Legacy FML relauncher detected (no FMLTweaker), launching merged client directly")
                return "net.minecraft.client.Minecraft"

            if _jar_contains_class("net/minecraft/launchwrapper/Launch.class"):
                print("[launcher] Legacy Forge version detected - forcing LaunchWrapper main class")
                return "net.minecraft.launchwrapper.Launch"
            print("[launcher] Legacy Forge version detected - using LaunchWrapper fallback")
            return "net.minecraft.launchwrapper.Launch"

        if version_path and os.path.isdir(version_path):
            shim_main = None
            for fname in os.listdir(version_path):
                if fname.endswith("-shim.jar"):
                    try:
                        shim_path = os.path.join(version_path, fname)
                        with zipfile.ZipFile(shim_path, "r") as jar:
                            try:
                                mf = jar.read("META-INF/MANIFEST.MF").decode("utf-8")
                                for line in mf.split("\n"):
                                    if "Main-Class:" in line:
                                        shim_main = line.split("Main-Class:")[1].strip()
                                        print(f"[launcher] Found Forge shim Main-Class: {shim_main}")
                                        return shim_main
                            except Exception:
                                pass
                    except Exception:
                        pass

            if _jar_contains_class("cpw/mods/modlauncher/Launcher.class"):
                print("[launcher] Found ModLauncher class, using ModLauncher")
                return "cpw.mods.modlauncher.Launcher"

            try:
                for root, dirs, files in os.walk(version_path):
                    for fname in files:
                        if not fname.endswith(".jar"):
                            continue
                        jarp = os.path.join(root, fname)
                        try:
                            with zipfile.ZipFile(jarp, "r") as jar:
                                try:
                                    mf = jar.read("META-INF/MANIFEST.MF").decode("utf-8")
                                except Exception:
                                    mf = ""
                                if "cpw.mods.modlauncher.Launcher" in mf or "ModLauncher" in mf or "modlauncher" in mf.lower():
                                    if _jar_contains_class("cpw/mods/modlauncher/Launcher.class"):
                                        return "cpw.mods.modlauncher.Launcher"
                        except Exception:
                            continue
            except Exception:
                pass

        try:
            services_dir = os.path.join(version_path, "META-INF", "services") if version_path else None
            if services_dir and os.path.isdir(services_dir):
                for svc in os.listdir(services_dir):
                    svc_path = os.path.join(services_dir, svc)
                    try:
                        with open(svc_path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                            if "cpw.mods.modlauncher" in content or "ILaunchHandlerService" in svc or "ITransformerDiscoveryService" in svc:
                                if _jar_contains_class("cpw/mods/modlauncher/Launcher.class"):
                                    return "cpw.mods.modlauncher.Launcher"
                    except Exception:
                        continue
        except Exception:
            pass

        try:
            if version_path and os.path.isdir(version_path):
                jars_in_loader = []
                for root, dirs, files in os.walk(version_path):
                    for f in files:
                        if f.endswith(".jar"):
                            jars_in_loader.append(f)

                if jars_in_loader and any("forge" in j.lower() for j in jars_in_loader):
                    try:
                        parts = version_dir.split(os.sep)
                        mc_version_str = parts[-1] if len(parts) >= 1 else ""

                        if mc_version_str and mc_version_str[0].isdigit():
                            version_parts = mc_version_str.split(".")
                            major = int(version_parts[0]) if len(version_parts) > 0 else 0
                            minor = int(version_parts[1]) if len(version_parts) > 1 else 0

                            if major > 1 or (major == 1 and minor >= 13):
                                print(f"[launcher] MC version {mc_version_str} detected - using ModLauncher")
                                return "cpw.mods.modlauncher.Launcher"
                            else:
                                print(f"[launcher] MC version {mc_version_str} detected - using LaunchWrapper")
                                return "net.minecraft.launchwrapper.Launch"
                    except Exception as e:
                        print(f"[launcher] Could not parse MC version for version detection: {e}")

                    print(f"[launcher] Warning: ModLauncher class not found, but found {len(jars_in_loader)} Forge JARs")
                    print("[launcher] Attempting ModLauncher as fallback")
                    return "cpw.mods.modlauncher.Launcher"
        except Exception:
            pass

        return ""

    elif loader_type_lower == "neoforge":
        try:
            loaders_dir = os.path.join(version_dir, "loaders", "neoforge")
            version_path = os.path.join(loaders_dir, loader_version) if loader_version else None
            if not version_path or not os.path.isdir(version_path):
                versions = [d for d in sorted(os.listdir(loaders_dir)) if os.path.isdir(os.path.join(loaders_dir, d))]
                if versions:
                    version_path = os.path.join(loaders_dir, versions[-1])
            if version_path and os.path.isdir(version_path):
                version_json_path = os.path.join(version_path, ".metadata", "version.json")
                if os.path.exists(version_json_path):
                    with open(version_json_path, "r", encoding="utf-8") as f:
                        metadata_version = json.load(f)
                    declared_main = (metadata_version.get("mainClass") or "").strip()
                    if declared_main:
                        print(f"[launcher] Using NeoForge mainClass from metadata: {declared_main}")
                        return declared_main
        except Exception as e:
            print(f"[launcher] Warning: Could not read NeoForge metadata mainClass: {e}")
        return "cpw.mods.bootstraplauncher.BootstrapLauncher"

    elif loader_type_lower == "fabric":
        return "net.fabricmc.loader.launch.knot.KnotClient"

    elif loader_type_lower == "babric":
        try:
            loaders_dir = os.path.join(version_dir, "loaders", "babric")
            version_path = os.path.join(loaders_dir, loader_version) if loader_version else None
            if not version_path or not os.path.isdir(version_path):
                versions = [d for d in sorted(os.listdir(loaders_dir)) if os.path.isdir(os.path.join(loaders_dir, d))]
                if versions:
                    version_path = os.path.join(loaders_dir, versions[-1])
            if version_path and os.path.isdir(version_path):
                version_json_path = os.path.join(version_path, ".metadata", "version.json")
                if os.path.exists(version_json_path):
                    with open(version_json_path, "r", encoding="utf-8") as f:
                        metadata_version = json.load(f)
                    declared_main = (metadata_version.get("mainClass") or "").strip()
                    if declared_main:
                        print(f"[launcher] Using Babric mainClass from metadata: {declared_main}")
                        return declared_main
        except Exception as e:
            print(f"[launcher] Warning: Could not read Babric metadata mainClass: {e}")
        return "net.fabricmc.loader.impl.launch.knot.KnotClient"

    elif loader_type_lower == "quilt":
        return "org.quiltmc.loader.impl.launch.knot.KnotClient"

    return ""


def _get_forge_fml_metadata(version_dir: str, loader_version: str = None) -> dict:
    try:
        actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
        if not actual_loader_version:
            return {}

        forge_loader_dir = os.path.join(version_dir, "loaders", "forge", actual_loader_version)
        metadata_dir = os.path.join(forge_loader_dir, ".metadata")

        metadata: dict = {}

        forge_metadata_path = os.path.join(forge_loader_dir, "forge_metadata.json")
        if os.path.exists(forge_metadata_path):
            try:
                with open(forge_metadata_path, "r", encoding="utf-8") as f:
                    forge_meta = json.load(f)
                if forge_meta.get("mc_version"):
                    metadata["mc_version"] = forge_meta["mc_version"]
                if forge_meta.get("forge_version"):
                    metadata["forge_version"] = forge_meta["forge_version"]
                if forge_meta.get("mcp_version"):
                    mcp_ver = forge_meta["mcp_version"]
                    mc_ver = forge_meta.get("mc_version", "")
                    if mc_ver and mcp_ver.startswith(mc_ver + "-"):
                        mcp_ver = mcp_ver[len(mc_ver) + 1:]
                    metadata["mcp_version"] = mcp_ver
                    print(colorize_log(
                        f"[launcher] Read MCP version from forge_metadata.json: {mcp_ver}"
                    ))
            except Exception as e:
                print(colorize_log(f"[launcher] Warning: Could not read forge_metadata.json: {e}"))

        version_json_path = os.path.join(metadata_dir, "version.json")
        if os.path.exists(version_json_path):
            try:
                with open(version_json_path, "r", encoding="utf-8") as f:
                    version_data = json.load(f)

                mc_version = version_data.get("id")

                if mc_version:
                    metadata["mc_version"] = mc_version
                    if "-forge-" in mc_version:
                        mc_v, forge_v = mc_version.split("-forge-", 1)
                        metadata["mc_version"] = mc_v
                        if forge_v and "forge_version" not in metadata:
                            metadata["forge_version"] = forge_v

                if "time" in version_data:
                    pass

                libraries = version_data.get("libraries", [])
                for lib in libraries:
                    lib_name = lib.get("name", "")
                    if "net.minecraftforge:forge:" in lib_name or "net.minecraftforge:fmlcore:" in lib_name:
                        parts = lib_name.split(":")
                        if len(parts) >= 3:
                            metadata["forge_group"] = parts[0] or "net.minecraftforge"
                            version_str = parts[2]
                            if "-" in version_str:
                                mc_v, forge_v = version_str.rsplit("-", 1)
                                metadata["mc_version"] = mc_v
                                metadata["forge_version"] = forge_v
                    elif "de.oceanlabs.mcp:mcp_config:" in lib_name or "de.oceanlabs.mcp:mcp_mappings:" in lib_name:
                        parts = lib_name.split(":")
                        if len(parts) >= 3:
                            mcp_ver = parts[2]
                            metadata["mcp_version"] = mcp_ver
                            print(colorize_log(f"[launcher] Extracted MCP Config version: {mcp_ver}"))
                    if "mc_version" in metadata and "forge_version" in metadata and "mcp_version" in metadata:
                        break

            except Exception as e:
                print(colorize_log(f"[launcher] Warning: Could not parse version.json: {e}"))

        profile_json_path = os.path.join(metadata_dir, "install_profile.json")
        if os.path.exists(profile_json_path) and ("mc_version" not in metadata or "mcp_version" not in metadata):
            try:
                with open(profile_json_path, "r", encoding="utf-8") as f:
                    profile_data = json.load(f)

                raw_version = profile_data.get("version", "")
                if isinstance(raw_version, dict):
                    raw_version = raw_version.get("id", "")

                mc_version = profile_data.get("minecraft")
                profile_path = profile_data.get("path", "")
                if isinstance(profile_path, str):
                    parts = profile_path.split(":")
                    if len(parts) >= 2 and parts[0]:
                        metadata["forge_group"] = parts[0]

                forge_version = ""
                if raw_version:
                    if "-forge-" in raw_version:
                        forge_version = raw_version.split("-forge-", 1)[1]
                    elif "-" in raw_version:
                        forge_version = raw_version.split("-", 1)[1]

                if mc_version and "mc_version" not in metadata:
                    metadata["mc_version"] = mc_version
                if forge_version and "forge_version" not in metadata:
                    metadata["forge_version"] = forge_version

                if "mcp_version" not in metadata:
                    profile_data_section = profile_data.get("data", {})
                    mcp_ver = ""

                    raw_mcp = (profile_data_section.get("MCP_VERSION") or {}).get("client", "")
                    if raw_mcp:
                        mcp_ver = raw_mcp.strip("'")

                    if not mcp_ver:
                        raw_srg = (profile_data_section.get("MC_SRG") or {}).get("client", "")
                        if raw_srg:
                            inner = raw_srg.strip("[]")
                            srg_parts = inner.split(":")
                            if len(srg_parts) >= 3:
                                mcp_ver = srg_parts[2]

                    if not mcp_ver:
                        raw_mappings = (profile_data_section.get("MAPPINGS") or {}).get("client", "")
                        if raw_mappings:
                            inner = raw_mappings.strip("[]").split("@")[0]
                            map_parts = inner.split(":")
                            if len(map_parts) >= 3:
                                mcp_ver = map_parts[2]

                    fallback_mc = metadata.get("mc_version") or profile_data.get("minecraft", "")
                    if mcp_ver and fallback_mc and mcp_ver.startswith(fallback_mc + "-"):
                        mcp_ver = mcp_ver[len(fallback_mc) + 1:]

                    if mcp_ver:
                        metadata["mcp_version"] = mcp_ver
                        print(colorize_log(
                            f"[launcher] Read MCP version from install_profile.json: {mcp_ver}"
                        ))

            except Exception as e:
                print(colorize_log(f"[launcher] Warning: Could not parse install_profile.json: {e}"))

        if "forge_version" not in metadata and actual_loader_version:
            metadata["forge_version"] = actual_loader_version

        if "forge_group" not in metadata:
            metadata["forge_group"] = "net.minecraftforge"

        if "mc_version" not in metadata:
            try:
                parts = version_dir.split(os.sep)
                if len(parts) >= 2:
                    potential_mc_version = parts[-1]
                    if potential_mc_version and potential_mc_version[0].isdigit() and "." in potential_mc_version:
                        metadata["mc_version"] = potential_mc_version
            except Exception:
                pass

        if "mc_version" in metadata:
            metadata["mc_version"] = _normalize_forge_mc_version(metadata["mc_version"])

        if "mcp_version" in metadata:
            metadata["mcp_version"] = _normalize_forge_mcp_version(
                metadata["mcp_version"], metadata.get("mc_version", "")
            )

        return metadata

    except Exception as e:
        print(colorize_log(f"[launcher] ERROR extracting Forge FML metadata: {e}"))
        return {}


def _get_loader_metadata_args(version_dir: str, loader_type: str, loader_version: str = None, key: str = "game") -> list:
    def _current_rule_os_name() -> str:
        system = platform.system().lower()
        if "windows" in system:
            return "windows"
        if "darwin" in system or "mac" in system:
            return "osx"
        if "linux" in system:
            return "linux"
        return system

    def _metadata_arg_rules_allow(entry: dict) -> bool:
        rules = entry.get("rules")
        if not isinstance(rules, list) or not rules:
            return True

        current_os = _current_rule_os_name()
        current_arch = platform.machine().lower()
        allowed = False

        for rule in rules:
            if not isinstance(rule, dict):
                continue

            matches = True
            os_rule = rule.get("os")
            if isinstance(os_rule, dict):
                os_name = str(os_rule.get("name") or "").strip().lower()
                if os_name and os_name != current_os:
                    matches = False

                os_arch = str(os_rule.get("arch") or "").strip().lower()
                if matches and os_arch and os_arch not in current_arch:
                    matches = False

                os_version = str(os_rule.get("version") or "").strip()
                if matches and os_version:
                    try:
                        if not re.search(os_version, platform.version(), re.IGNORECASE):
                            matches = False
                    except re.error:
                        matches = False

            features = rule.get("features")
            if matches and isinstance(features, dict) and features:
                matches = False

            if matches:
                allowed = str(rule.get("action") or "allow").strip().lower() != "disallow"

        return allowed

    def _flatten_metadata_arg_list(arg_list: list) -> list:
        flattened: list = []
        for entry in arg_list or []:
            if isinstance(entry, str):
                flattened.append(entry)
                continue
            if not isinstance(entry, dict) or not _metadata_arg_rules_allow(entry):
                continue

            value = entry.get("value")
            if isinstance(value, str):
                flattened.append(value)
            elif isinstance(value, list):
                flattened.extend(v for v in value if isinstance(v, str))
        return flattened

    try:
        loader_type = str(loader_type or "").strip().lower()
        actual_loader_version = loader_version or _get_loader_version(version_dir, loader_type)
        if not actual_loader_version:
            return []

        version_json_path = os.path.join(
            version_dir, "loaders", loader_type, actual_loader_version, ".metadata", "version.json"
        )
        if not os.path.exists(version_json_path):
            return []

        with open(version_json_path, "r", encoding="utf-8") as f:
            version_data = json.load(f)

        arg_list = ((version_data.get("arguments") or {}).get(key) or [])
        return _flatten_metadata_arg_list(arg_list)
    except Exception as e:
        print(colorize_log(
            f"[launcher] Warning: Could not read {loader_type} metadata {key} arguments: {e}"
        ))
        return []


def _expand_loader_metadata_args(
    args: list,
    version_dir: str,
    loader_type: str,
    loader_version: str = None,
    version_identifier: str = "",
    assets_root_override: str = "",
) -> list:
    from core.launch.auth import get_launch_auth_info

    loader_type = str(loader_type or "").strip().lower()
    actual_loader_version = loader_version or _get_loader_version(version_dir, loader_type)
    libraries_dir = (
        os.path.join(version_dir, "loaders", loader_type, actual_loader_version, "libraries")
        if actual_loader_version
        else ""
    )
    meta = _load_data_ini(version_dir)
    global_settings = load_global_settings() or {}
    game_dir = _resolve_game_dir(global_settings, version_dir) or ""
    native_folder = meta.get("native_subfolder") or _native_subfolder_for_platform()
    natives_directory = os.path.join(version_dir, native_folder)
    assets_root = assets_root_override or os.path.join(get_base_dir(), "assets")
    auth_info = get_launch_auth_info()
    username = auth_info["username"]
    auth_uuid = auth_info["uuid"]

    profile_version = ""
    try:
        if actual_loader_version:
            version_json_path = os.path.join(
                version_dir, "loaders", loader_type, actual_loader_version, ".metadata", "version.json"
            )
            if os.path.exists(version_json_path):
                with open(version_json_path, "r", encoding="utf-8") as f:
                    version_data = json.load(f)
                profile_version = (version_data.get("id") or "").strip()
    except Exception:
        pass

    if not profile_version and version_identifier:
        mc_ver = _extract_mc_version_string(version_identifier)
        if mc_ver and actual_loader_version:
            if loader_type == "forge":
                profile_version = f"{mc_ver}-forge-{actual_loader_version}"
            elif loader_type == "neoforge":
                profile_version = f"neoforge-{actual_loader_version}"

    replacements = {
        "${library_directory}": libraries_dir.replace("\\", "/"),
        "${classpath_separator}": os.pathsep,
        "${version_name}": profile_version,
        "${auth_player_name}": username,
        "${auth_session}": auth_info["access_token"],
        "${auth_access_token}": auth_info["access_token"],
        "${auth_uuid}": auth_uuid,
        "${user_type}": auth_info["user_type"],
        "${auth_player_type}": auth_info["user_type"],
        "${user_properties}": auth_info["user_properties"],
        "${auth_xuid}": auth_info.get("xuid", ""),
        "${xuid}": auth_info.get("xuid", ""),
        "${clientid}": auth_info.get("client_id", ""),
        "${client_id}": auth_info.get("client_id", ""),
        "${game_directory}": game_dir,
        "${natives_directory}": natives_directory,
        "${assets_root}": assets_root,
        "${game_assets}": assets_root,
    }

    expanded: list = []
    for arg in args:
        out = arg
        for k, v in replacements.items():
            out = out.replace(k, v)
        expanded.append(out)
    return expanded


def _get_forge_metadata_args(version_dir: str, loader_version: str = None, key: str = "game") -> list:
    return _get_loader_metadata_args(version_dir, "forge", loader_version, key)


def _expand_forge_metadata_args(
    args: list, version_dir: str, loader_version: str = None, version_identifier: str = ""
) -> list:
    return _expand_loader_metadata_args(args, version_dir, "forge", loader_version, version_identifier)


def _get_forge_tweak_class_from_metadata(version_dir: str, loader_version: str = None) -> str:
    actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
    if not actual_loader_version:
        return ""

    forge_loader_dir = os.path.join(version_dir, "loaders", "forge", actual_loader_version)
    candidate_files = [
        os.path.join(forge_loader_dir, ".metadata", "install_profile.json"),
        os.path.join(forge_loader_dir, ".metadata", "version.json"),
        os.path.join(forge_loader_dir, "forge_metadata.json"),
    ]

    for file_path in candidate_files:
        if not os.path.exists(file_path):
            continue
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        arg_strings: list = []
        arg_lists: list = []

        root_minecraft_args = data.get("minecraftArguments")
        if isinstance(root_minecraft_args, str):
            arg_strings.append(root_minecraft_args)

        root_args = data.get("arguments")
        if isinstance(root_args, dict):
            game_args = root_args.get("game")
            if isinstance(game_args, list):
                arg_lists.append(game_args)

        version_info = data.get("versionInfo")
        if isinstance(version_info, dict):
            vi_minecraft_args = version_info.get("minecraftArguments")
            if isinstance(vi_minecraft_args, str):
                arg_strings.append(vi_minecraft_args)

            vi_args = version_info.get("arguments")
            if isinstance(vi_args, dict):
                vi_game_args = vi_args.get("game")
                if isinstance(vi_game_args, list):
                    arg_lists.append(vi_game_args)

        for arg_string in arg_strings:
            tweak = _extract_tweak_class_from_arg_string(arg_string)
            if tweak:
                return tweak

        for arg_list in arg_lists:
            tweak = _extract_tweak_class_from_arg_list(arg_list)
            if tweak:
                return tweak

    return ""
