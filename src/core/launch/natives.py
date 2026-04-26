from __future__ import annotations

import os
import platform
import shutil
import zipfile

from core.logger import colorize_log

__all__ = [
    "_FALLBACK_LOG4J_XML",
    "_append_system_property_if_missing",
    "_create_fallback_log4j2_config",
    "_current_runtime_arch",
    "_current_runtime_os",
    "_extract_current_platform_native_binaries",
    "_filter_conflicting_classpath_entries",
    "_filter_platform_specific_classpath_entries",
    "_is_platform_specific_runtime_jar",
    "_is_runtime_jar_for_current_platform",
    "_join_classpath",
    "_native_directory_has_binaries",
    "_native_subfolder_for_platform",
    "_prune_forge_root_jars_for_modlauncher",
    "_prune_legacy_launchwrapper_bootstrap_jars",
    "_prune_neoforge_runtime_jars",
    "_prune_vanilla_client_jar",
    "_set_or_append_cli_arg",
]


_FALLBACK_LOG4J_XML = """<?xml version="1.0" encoding="UTF-8"?>
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
</Configuration>"""


def _native_subfolder_for_platform():
    system = platform.system().lower()
    if "windows" in system:
        return os.path.join("native", "windows")
    if "linux" in system:
        return os.path.join("native", "linux")
    if "darwin" in system or "mac" in system:
        return os.path.join("native", "mac")

    return os.path.join("native", "linux")


def _current_runtime_os() -> str:
    system = platform.system().lower()
    if "windows" in system:
        return "windows"
    if "linux" in system:
        return "linux"
    if "darwin" in system or "mac" in system:
        return "mac"
    return system


def _current_runtime_arch() -> str:
    machine = platform.machine().lower()
    if any(token in machine for token in ("arm64", "aarch64")):
        return "arm64"
    if machine in ("x86", "i386", "i486", "i586", "i686", "x86_32"):
        return "x86"
    return "x64"


def _is_platform_specific_runtime_jar(filename: str) -> bool:
    lower = str(filename or "").lower()
    return (
        "-natives-" in lower
        or lower.endswith("-natives.jar")
        or lower.startswith("java-objc-bridge-")
        or lower.startswith("netty-transport-native-")
    )


def _is_runtime_jar_for_current_platform(filename: str) -> bool:
    lower = str(filename or "").lower()
    if not lower:
        return True

    current_os = _current_runtime_os()
    current_arch = _current_runtime_arch()

    if lower.startswith("java-objc-bridge-"):
        return current_os == "mac"

    jar_os = None
    if "macos" in lower or "osx" in lower or "darwin" in lower:
        jar_os = "mac"
    elif "windows" in lower or "-win-" in lower or lower.endswith("-win.jar") or "natives-win" in lower:
        jar_os = "windows"
    elif "linux" in lower:
        jar_os = "linux"
    elif lower.endswith("-mac.jar") or "natives-mac" in lower:
        jar_os = "mac"

    if jar_os and jar_os != current_os:
        return False

    if any(token in lower for token in ("arm64", "aarch64", "aarch_64")):
        return current_arch == "arm64"

    if any(token in lower for token in ("windows-x86", "linux-x86", "osx-x86", "-x86.jar", "i386", "i486", "i586", "i686")):
        return current_arch == "x86"

    if any(token in lower for token in ("x64", "x86_64", "amd64")):
        return current_arch == "x64"

    if "-natives-" in lower or lower.endswith("-natives.jar"):
        if current_os in ("windows", "mac"):
            return current_arch == "x64"

    return True


def _filter_platform_specific_classpath_entries(classpath_entries: list) -> list:
    filtered: list[str] = []
    removed: list[str] = []

    for entry in classpath_entries:
        filename = os.path.basename(entry)
        if not _is_platform_specific_runtime_jar(filename):
            filtered.append(entry)
            continue

        if _is_runtime_jar_for_current_platform(filename):
            filtered.append(entry)
        else:
            removed.append(filename or entry)

    if removed:
        print(colorize_log(
            f"[launcher] Filtered out {len(removed)} platform-incompatible classpath entr"
            f"{'y' if len(removed) == 1 else 'ies'}"
        ))
        for name in removed[:8]:
            print(colorize_log(f"[launcher] Skipping non-matching runtime JAR: {name}"))
        if len(removed) > 8:
            print(colorize_log(f"[launcher] ... and {len(removed) - 8} more"))

    return filtered


def _native_directory_has_binaries(native_path: str) -> bool:
    if not os.path.isdir(native_path):
        return False

    for root, _, files in os.walk(native_path):
        for filename in files:
            if filename.lower().endswith((".dll", ".so", ".dylib", ".jnilib")):
                return True
    return False


def _extract_current_platform_native_binaries(version_dir: str, classpath_entries: list,
                                              native_path: str) -> tuple:
    os.makedirs(native_path, exist_ok=True)

    extracted_files = 0
    used_jars = 0
    native_suffixes = (".dll", ".so", ".dylib", ".jnilib")

    for entry in classpath_entries:
        abs_path = os.path.normpath(os.path.join(version_dir, entry))
        filename = os.path.basename(abs_path)
        lower = filename.lower()

        if (
            not os.path.isfile(abs_path)
            or not lower.endswith(".jar")
            or ("-natives-" not in lower and not lower.endswith("-natives.jar"))
            or not _is_runtime_jar_for_current_platform(filename)
        ):
            continue

        try:
            jar_extracted = 0
            with zipfile.ZipFile(abs_path, "r") as zf:
                for member in zf.infolist():
                    if member.is_dir():
                        continue

                    member_name = member.filename.replace("\\", "/")
                    if member_name.startswith("META-INF/"):
                        continue

                    basename = os.path.basename(member_name)
                    if not basename or not basename.lower().endswith(native_suffixes):
                        continue

                    target_path = os.path.join(native_path, basename)
                    with zf.open(member, "r") as src, open(target_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    jar_extracted += 1

            if jar_extracted:
                used_jars += 1
                extracted_files += jar_extracted
        except Exception as e:
            print(colorize_log(f"[launcher] Warning: Could not extract natives from {filename}: {e}"))

    return used_jars, extracted_files


def _append_system_property_if_missing(cmd: list, key: str, value: str) -> bool:
    prefix = f"-D{key}="
    if any(str(arg).startswith(prefix) for arg in cmd):
        return False
    cmd.append(f"{prefix}{value}")
    return True


def _create_fallback_log4j2_config(config_path: str) -> bool:
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(_FALLBACK_LOG4J_XML)
        return True
    except Exception:
        return False


def _join_classpath(base_dir, entries):
    sep = os.pathsep
    abs_entries = [os.path.normpath(os.path.join(base_dir, e)) for e in entries]
    return sep.join(abs_entries)


def _filter_conflicting_classpath_entries(
    classpath_entries: list,
    loader_jars: list,
    preserve_forge_client: bool = True,
) -> list:
    def _artifact_conflict_family(name: str) -> str:
        normalized = str(name or "").strip().lower()
        if not normalized:
            return ""

        if normalized == "asm-all":
            return "asm-all"

        if normalized == "asm" or normalized.startswith("asm-"):
            return "asm-modern"

        return normalized

    def jar_artifact_name(filename: str) -> str:
        stem = filename[:-4] if filename.endswith(".jar") else filename
        parts = stem.split("-")
        name_parts: list[str] = []
        for part in parts:
            if part and part[0].isdigit():
                break
            name_parts.append(part)
        return "-".join(name_parts) if name_parts else stem

    loader_artifact_names: set[str] = set()
    loader_filenames: set[str] = set()
    loader_conflict_families: set[str] = set()
    for jar_path in loader_jars:
        loader_filename = os.path.basename(jar_path)
        loader_filenames.add(loader_filename.lower())
        name = jar_artifact_name(loader_filename)
        if name:
            loader_artifact_names.add(name)
            family = _artifact_conflict_family(name)
            if family:
                loader_conflict_families.add(family)

    if not loader_artifact_names:
        return classpath_entries

    def _is_loader_runtime_path(path_str: str) -> bool:
        normalized = path_str.replace("\\", "/").lower().lstrip("./")
        return "loaders/forge/" in normalized or "loaders/neoforge/" in normalized

    is_loader_runtime = any(_is_loader_runtime_path(p) for p in loader_jars)

    filtered: list[str] = []
    preserved_client = False
    for entry in classpath_entries:
        filename = os.path.basename(entry)
        filename_lower = filename.lower()
        name = jar_artifact_name(filename)
        family = _artifact_conflict_family(name)

        if "-natives-" in filename_lower or filename_lower.endswith("-natives.jar"):
            filtered.append(entry)
            continue

        if is_loader_runtime and preserve_forge_client and filename_lower == "client.jar":
            if not preserved_client:
                print(colorize_log(
                    "[launcher] Preserving vanilla client.jar in classpath for loader runtime compatibility"
                ))
                preserved_client = True
            filtered.append(entry)
            continue

        conflict_reason = name
        conflicts_with_loader = filename_lower in loader_filenames or name in loader_artifact_names
        if not conflicts_with_loader and family == "asm-all" and "asm-modern" in loader_conflict_families:
            conflicts_with_loader = True
            conflict_reason = "modern ASM runtime"

        if conflicts_with_loader:
            print(colorize_log(
                f"[launcher] Filtering out conflicting classpath entry: {filename} "
                f"(loader provides {conflict_reason})"
            ))
        else:
            filtered.append(entry)

    return filtered


def _prune_neoforge_runtime_jars(classpath_entries: list) -> list:
    pruned: list[str] = []
    deferred_runtime: list[str] = []
    removed_tooling: list[str] = []

    for entry in classpath_entries:
        normalized = entry.replace("\\", "/").lower().lstrip("./")
        filename = os.path.basename(normalized)

        is_installertools_fatjar = (
            "/net/neoforged/installertools/installertools/" in normalized
            and filename.endswith("-fatjar.jar")
        )

        is_patched_minecraft_runtime = "/net/neoforged/minecraft-client-patched/" in normalized
        is_neoforge_runtime_mod = (
            "/net/neoforged/neoforge/" in normalized
            and (filename.endswith("-universal.jar") or filename.endswith("-client.jar"))
        )

        if is_installertools_fatjar:
            removed_tooling.append(filename or entry)
            continue

        if is_patched_minecraft_runtime or is_neoforge_runtime_mod:
            deferred_runtime.append(filename or entry)
            continue

        pruned.append(entry)

    if deferred_runtime:
        print(colorize_log(
            f"[launcher] Deferred {len(deferred_runtime)} NeoForge production runtime JAR(s) "
            f"to libraryDirectory discovery"
        ))

    if removed_tooling:
        print(colorize_log(
            f"[launcher] Excluded {len(removed_tooling)} NeoForge tooling JAR(s) from runtime classpath"
        ))

    return pruned


def _set_or_append_cli_arg(args: list, flag: str, value: str) -> None:
    for i, arg in enumerate(args):
        if arg == flag and i + 1 < len(args):
            args[i + 1] = value
            return
        if arg.startswith(flag + "="):
            args[i] = f"{flag}={value}"
            return
    args.extend([flag, value])


def _prune_forge_root_jars_for_modlauncher(classpath_entries: list) -> list:
    pruned: list[str] = []
    removed: list[str] = []

    for entry in classpath_entries:
        norm = entry.replace("\\", "/").lower().lstrip("./")
        base = os.path.basename(norm)
        is_root_forge_loader_jar = (
            norm.startswith("loaders/forge/")
            and "/libraries/" not in norm
            and base.startswith("forge-")
            and base.endswith(".jar")
        )
        if is_root_forge_loader_jar:
            removed.append(entry)
            continue
        pruned.append(entry)

    if removed:
        print(colorize_log(
            f"[launcher] Removed {len(removed)} root Forge loader JAR(s) for ModLauncher classpath hygiene"
        ))

    return pruned


def _prune_vanilla_client_jar(classpath_entries: list) -> list:
    pruned: list[str] = []
    removed = 0
    for entry in classpath_entries:
        norm = entry.replace("\\", "/").lower().lstrip("./")
        if norm == "client.jar":
            removed += 1
            continue
        pruned.append(entry)
    if removed:
        print(colorize_log("[launcher] Removed vanilla client.jar from classpath for Forge bootstrap launch"))
    return pruned


def _prune_legacy_launchwrapper_bootstrap_jars(classpath_entries: list) -> list:
    removable_prefixes = (
        "launchwrapper-",
        "jopt-simple-",
        "asm-all-",
    )
    pruned: list[str] = []
    removed: list[str] = []

    for entry in classpath_entries:
        filename = os.path.basename(entry).lower()
        if any(filename.startswith(prefix) and filename.endswith(".jar") for prefix in removable_prefixes):
            removed.append(os.path.basename(entry))
            continue
        pruned.append(entry)

    if removed:
        print(colorize_log(
            f"[launcher] Removed {len(removed)} legacy LaunchWrapper bootstrap JAR(s) "
            f"for non-LaunchWrapper loader compatibility"
        ))

    return pruned
