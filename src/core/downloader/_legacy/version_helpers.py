from __future__ import annotations

import json
import os
import re
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from core.downloader._legacy._constants import (
    ASSETS_INDEXES_DIR,
    ASSET_THREADS_HIGH,
    ASSET_THREADS_LOW,
    ASSET_THREADS_MED,
    CACHE_LIBRARIES_DIR,
    DOWNLOAD_CHUNK_SIZE,
)
from core.downloader._legacy.progress import _maybe_abort
from core.downloader._legacy.transport import _is_fast_download_enabled, download_file
from core.logger import colorize_log
from core.settings import load_global_settings


# ---------------------------------------------------------------------------
# Version-json argument helpers
# ---------------------------------------------------------------------------


def _flatten_arguments_list(arg_list: List[Any]) -> List[str]:
    result: List[str] = []
    for item in arg_list or []:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            val = item.get("value")
            if isinstance(val, str):
                result.append(val)
            elif isinstance(val, list):
                for v in val:
                    if isinstance(v, str):
                        result.append(v)
    return result


def _extract_extra_args(vjson: Dict[str, Any]) -> Optional[str]:
    args = vjson.get("arguments")
    if isinstance(args, dict):
        game_args = _flatten_arguments_list(args.get("game", []))
        if game_args:
            return " ".join(game_args)

    legacy = vjson.get("minecraftArguments")
    if isinstance(legacy, str) and legacy.strip():
        return legacy.strip()

    return None


# ---------------------------------------------------------------------------
# Library artifact resolution
# ---------------------------------------------------------------------------


def _artifact_from_legacy_library_entry(lib: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(lib, dict):
        return None

    name = str(lib.get("name") or "").strip()
    if not name or ":" not in name:
        return None

    parts = name.split(":")
    if len(parts) < 3:
        return None

    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = parts[3] if len(parts) >= 4 else ""

    group_path = group.replace(".", "/")
    file_base = f"{artifact}-{version}"
    if classifier:
        file_base += f"-{classifier}"
    file_name = f"{file_base}.jar"
    rel_path = f"{group_path}/{artifact}/{version}/{file_name}"

    base_url = str(lib.get("url") or "https://libraries.minecraft.net/").strip()
    if not base_url:
        base_url = "https://libraries.minecraft.net/"
    if not base_url.endswith("/"):
        base_url += "/"

    return {
        "path": rel_path,
        "url": base_url + rel_path,
        "sha1": lib.get("sha1") or None,
        "size": int(lib.get("size") or 0),
    }


def _resolve_library_artifact(lib: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    downloads = (lib or {}).get("downloads") or {}
    artifact = downloads.get("artifact")
    if isinstance(artifact, dict) and artifact.get("path") and artifact.get("url"):
        return artifact

    classifiers = downloads.get("classifiers") or {}
    if classifiers and not artifact:
        return None

    return _artifact_from_legacy_library_entry(lib)


# ---------------------------------------------------------------------------
# Legacy LaunchWrapper handling
# ---------------------------------------------------------------------------


def _is_legacy_launchwrapper_family(version_id: str) -> bool:
    v = str(version_id or "").strip().lower()
    return bool(re.match(r"^(?:b1|a1|c0|inf-|in-|rd-)", v))


def _ensure_legacy_launchwrapper(
    version_id: str,
    version_dir: str,
    copied_lib_basenames: List[str],
    version_key: str,
) -> None:
    if not _is_legacy_launchwrapper_family(version_id):
        return

    preferred = {
        "url": "https://libraries.minecraft.net/net/minecraft/launchwrapper/1.6/launchwrapper-1.6.jar",
        "path": "net/minecraft/launchwrapper/1.6/launchwrapper-1.6.jar",
    }
    fallback = {
        "url": "https://libraries.minecraft.net/net/minecraft/launchwrapper/1.5/launchwrapper-1.5.jar",
        "path": "net/minecraft/launchwrapper/1.5/launchwrapper-1.5.jar",
    }
    companions = [
        {
            "url": "https://libraries.minecraft.net/net/sf/jopt-simple/jopt-simple/4.5/jopt-simple-4.5.jar",
            "path": "net/sf/jopt-simple/jopt-simple/4.5/jopt-simple-4.5.jar",
            "required": True,
        },
        {
            "url": "https://libraries.minecraft.net/org/ow2/asm/asm-all/4.1/asm-all-4.1.jar",
            "path": "org/ow2/asm/asm-all/4.1/asm-all-4.1.jar",
            "required": True,
        },
    ]

    def _seed_runtime_jar(runtime: Dict[str, Any]) -> bool:
        rel_path = runtime["path"]
        base_name = os.path.basename(rel_path)
        cache_path = os.path.join(CACHE_LIBRARIES_DIR, rel_path)
        dest_path = os.path.join(version_dir, base_name)
        already_names = {str(x).strip().lower() for x in copied_lib_basenames if str(x).strip()}

        if base_name.lower() in already_names:
            return True
        if os.path.isfile(dest_path):
            copied_lib_basenames.append(base_name)
            return True

        try:
            print(colorize_log(f"[install] Ensuring legacy runtime dependency: {base_name}"))
            download_file(
                runtime["url"],
                cache_path,
                expected_sha1=None,
                progress_cb=None,
                version_key=version_key,
            )

            if os.path.abspath(cache_path) != os.path.abspath(dest_path):
                with open(cache_path, "rb") as src, open(dest_path, "wb") as dst:
                    while True:
                        _maybe_abort(version_key)
                        chunk = src.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        dst.write(chunk)

            copied_lib_basenames.append(base_name)
            print(colorize_log(f"[install] Added legacy runtime dependency: {base_name}"))
            return True
        except Exception as e:
            print(colorize_log(f"[install] Failed to fetch {base_name}: {e}"))
            return False

    lw_ok = False
    for candidate in (preferred, fallback):
        if _seed_runtime_jar(candidate):
            lw_ok = True
            break
    if not lw_ok:
        raise RuntimeError("Could not download LaunchWrapper runtime (tried 1.6 and 1.5)")

    for dep in companions:
        ok = _seed_runtime_jar(dep)
        if not ok and dep.get("required"):
            raise RuntimeError(
                f"Could not download required legacy dependency: "
                f"{os.path.basename(dep['path'])}"
            )


# ---------------------------------------------------------------------------
# Main-class inference
# ---------------------------------------------------------------------------


def _infer_main_class_from_client_jar(client_jar_path: str, version_id: str = "") -> str:
    default_main = "net.minecraft.client.Minecraft"

    if not client_jar_path or not os.path.isfile(client_jar_path):
        return default_main

    try:
        with zipfile.ZipFile(client_jar_path, "r") as jf:
            entries = set(jf.namelist())

            if "META-INF/MANIFEST.MF" in entries:
                try:
                    mf = jf.read("META-INF/MANIFEST.MF").decode("utf-8", errors="ignore")
                    for line in mf.splitlines():
                        if line.startswith("Main-Class:"):
                            manifest_main = line.split(":", 1)[1].strip()
                            if manifest_main:
                                return manifest_main
                except Exception:
                    pass

            def _has(class_name: str) -> bool:
                return class_name.replace(".", "/") + ".class" in entries

            legacy_hint = bool(re.match(r"^(?:b1|a1|c0|inf-|in-|rd-)", str(version_id or "").lower()))
            if legacy_hint:
                for candidate in (
                    "net.minecraft.client.MinecraftApplet",
                    "com.mojang.minecraft.MinecraftApplet",
                    "net.minecraft.client.Minecraft",
                    "com.mojang.minecraft.Minecraft",
                ):
                    if _has(candidate):
                        return candidate

            for candidate in (
                "net.minecraft.client.main.Main",
                "net.minecraft.client.Minecraft",
                "net.minecraft.client.MinecraftApplet",
                "com.mojang.minecraft.Minecraft",
                "com.mojang.minecraft.MinecraftApplet",
            ):
                if _has(candidate):
                    return candidate
    except Exception:
        pass

    return default_main


# ---------------------------------------------------------------------------
# Asset / version helpers
# ---------------------------------------------------------------------------


def _choose_asset_threads() -> int:
    if _is_fast_download_enabled():
        return ASSET_THREADS_HIGH
    threads = os.cpu_count() or 1
    if threads >= 12:
        return ASSET_THREADS_HIGH
    if threads >= 6:
        return ASSET_THREADS_MED
    return ASSET_THREADS_LOW


def _is_modern_assets(version_id: str) -> bool:
    base = (version_id or "").split("-", 1)[0]
    parts = base.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        return True
    if major > 1:
        return True
    return major == 1 and minor >= 6


def _extract_os_from_classifier_key(key: str) -> Optional[str]:
    k = key.lower()
    if "windows" in k or "win" in k:
        return "windows"
    if "linux" in k:
        return "linux"
    if "osx" in k or "mac" in k:
        return "mac"
    return None


def _parse_mc_version(version_id: str) -> Optional[Tuple[int, int]]:
    base = (version_id or "").split("-", 1)[0]
    parts = base.split(".")
    if not parts:
        return None
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return major, minor
    except Exception:
        return None


def _is_at_least(version_id: str, major_req: int, minor_req: int) -> bool:
    parsed = _parse_mc_version(version_id)
    if not parsed:
        return False
    major, minor = parsed
    if major > major_req:
        return True
    return major == major_req and minor >= minor_req


def _parse_lwjgl_version(lib_basename: str) -> Optional[int]:
    name = lib_basename.lower()
    if not name.startswith("lwjgl"):
        return None

    parts = name.split("-")
    if len(parts) < 2:
        return None

    ver_part = parts[-1].replace(".jar", "")
    digits = ver_part.replace(".", "")
    return int(digits) if digits.isdigit() else None


def _should_skip_library_for_version(
    version_id: str, lib_basename: str, highest_versions: Dict[str, int]
) -> bool:
    ver = _parse_lwjgl_version(lib_basename)
    if ver is None:
        return False

    module = lib_basename.split("-")[0]
    highest = highest_versions.get(module)
    return highest is not None and ver < highest


def _compute_total_size(
    vjson: Dict[str, Any], version_id: str, full_assets: bool
) -> int:
    total = 0

    client_info = (vjson.get("downloads") or {}).get("client")
    if client_info:
        total += int(client_info.get("size") or 0)

    libs = vjson.get("libraries") or []
    for lib in libs:
        artifact = _resolve_library_artifact(lib)
        if artifact:
            total += int(artifact.get("size") or 0)
        downloads = lib.get("downloads") or {}
        classifiers = downloads.get("classifiers") or {}
        for nat in classifiers.values():
            total += int(nat.get("size") or 0)

    assets_info = vjson.get("assetIndex") or {}
    assets_url = assets_info.get("url")
    if assets_url and full_assets and _is_modern_assets(version_id):
        try:
            index_path = os.path.join(
                ASSETS_INDEXES_DIR, f"{assets_info.get('id', '')}.json"
            )
            if os.path.exists(index_path):
                with open(index_path, "r", encoding="utf-8") as f:
                    idx_json = json.load(f)
            else:
                idx_json = {}
        except Exception:
            idx_json = {}
        objects = idx_json.get("objects") or {}
        for obj in objects.values():
            total += int(obj.get("size") or 0)

    return total


def _normalize_storage_category(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return "release"
    return n.lower()


# ---------------------------------------------------------------------------
# Wiki display image URL
# ---------------------------------------------------------------------------


def _wiki_image_url(version_id: str, version_type: str) -> Optional[str]:
    settings = load_global_settings()
    low_data = settings.get("low_data_mode") == "1"
    pixel_res = round(260 / (2 if low_data else 1))
    version_id_str = str(version_id or "")

    prefix = "Java_Edition_"
    clean_id = version_id_str
    lid = version_id_str.lower()

    if lid.startswith("combat"):
        match = re.search(r"(\d)(?!.*\d)", version_id_str)
        version_num = int(match.group(1)) if match else 0
        if version_num <= 6:
            prefix = "Release_"
        clean_id = f"Combat_Test_{version_id_str[6:]}"
        if version_num == 1:
            prefix = "Release_1.14.3_"
            clean_id = "Combat_Test"
    elif lid.startswith("13w12~"):
        clean_id = version_id_str[:6]
    elif lid.startswith("1.5-pre"):
        clean_id = version_id_str.replace("-pre", "")
    elif lid == "1.0":
        clean_id = "1.0.0"
    elif lid.startswith("inf-"):
        prefix = "Infdev_"
        clean_id = version_id_str[4:12] + "_menu"
    elif lid.startswith("in-"):
        prefix = "Indev_"
        clean_id = version_id_str[3:11] + "_menu"
    elif lid.startswith("a1"):
        prefix = "Alpha_v"
        clean_id = (version_id_str[1:] if version_id_str.startswith("a") else version_id_str) + "_menu"
    elif lid.startswith("b1"):
        prefix = "Beta_"
        clean_id = (version_id_str[1:] if version_id_str.startswith("b") else version_id_str) + "_menu"
    elif lid.startswith("c0"):
        prefix = "Classic_"
        clean_id = version_id_str[1:]

    clean_id = (
        clean_id
        .replace("-", "_")
        .replace("pre_", "Pre-Release_")
        .replace("pre", "Pre-Release_")
        .replace("rc_", "Release_Candidate_")
        .replace("rc", "Release_Candidate_")
        .replace("snapshot", "Snapshot")
        .replace("_unobf", "")
        .replace("_whitelinefix", "")
        .replace("_whitetexturefix", "")
        .replace("_tominecon", "")
    )

    return f"https://minecraft.wiki/images/thumb/{prefix}{clean_id}.png/{pixel_res}px-.png"


__all__ = [
    "_artifact_from_legacy_library_entry",
    "_choose_asset_threads",
    "_compute_total_size",
    "_ensure_legacy_launchwrapper",
    "_extract_extra_args",
    "_extract_os_from_classifier_key",
    "_flatten_arguments_list",
    "_infer_main_class_from_client_jar",
    "_is_at_least",
    "_is_legacy_launchwrapper_family",
    "_is_modern_assets",
    "_normalize_storage_category",
    "_parse_lwjgl_version",
    "_parse_mc_version",
    "_resolve_library_artifact",
    "_should_skip_library_for_version",
    "_wiki_image_url",
]
