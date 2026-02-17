# core/downloader.py
import hashlib
import json
import os
import shutil
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from typing import Any, Callable, Dict, List, Optional, Tuple

from core import manifest as core_manifest
from core.libraries.plyer import notification
from core.settings import get_base_dir, load_global_settings

BASE_DIR = get_base_dir()

DOWNLOAD_DIR = os.path.join(BASE_DIR, "clients")
PROGRESS_DIR = os.path.join(BASE_DIR, "cache", "progress")
CACHE_LIBRARIES_DIR = os.path.join(BASE_DIR, "cache", "libraries")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
ASSETS_INDEXES_DIR = os.path.join(ASSETS_DIR, "indexes")
ASSETS_OBJECTS_DIR = os.path.join(ASSETS_DIR, "objects")

# Download tuning
DOWNLOAD_CHUNK_SIZE = 64 * 1024  # 64 KB chunks
ASSET_THREADS_HIGH = 16
ASSET_THREADS_MED = 8
ASSET_THREADS_LOW = 4

_workers: Dict[str, threading.Thread] = {}
_cancel_flags: Dict[str, bool] = {}
_pause_flags: Dict[str, bool] = {}

STAGE_WEIGHTS = {
    "version_json": 5,
    "client": 20,
    "libraries": 25,
    "natives": 15,
    "assets": 25,
    "finalize": 10,
}


# ---------------- Filesystem / progress helpers ----------------


def ensure_dirs() -> None:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    os.makedirs(CACHE_LIBRARIES_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(ASSETS_INDEXES_DIR, exist_ok=True)
    os.makedirs(ASSETS_OBJECTS_DIR, exist_ok=True)


def encode_key(key: str) -> str:
    return urllib.parse.quote(key, safe="")


def progress_path(version_key: str) -> str:
    ensure_dirs()
    safe = encode_key(version_key)
    return os.path.join(PROGRESS_DIR, f"{safe}.json")


def write_progress(version_key: str, data: Dict[str, Any]) -> None:
    path = progress_path(version_key)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        # Progress is best-effort; ignore failures
        pass


def read_progress(version_key: str) -> Optional[Dict[str, Any]]:
    path = progress_path(version_key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def delete_progress(version_key: str) -> None:
    try:
        path = progress_path(version_key)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def list_progress_files() -> List[Tuple[str, Dict[str, Any]]]:
    ensure_dirs()
    out: List[Tuple[str, Dict[str, Any]]] = []
    for name in os.listdir(PROGRESS_DIR):
        if not name.endswith(".json"):
            continue
        path = os.path.join(PROGRESS_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = urllib.parse.unquote(name[:-5])
            out.append((key, data))
        except Exception:
            continue
    return out


# ---------------- Settings / proxy ----------------


def _get_url_proxy_prefix() -> str:
    try:
        settings = load_global_settings() or {}
    except Exception:
        settings = {}
    prefix = (settings.get("url_proxy") or "").strip()
    return prefix


def _apply_url_proxy(url: str) -> str:
    prefix = _get_url_proxy_prefix()
    if not prefix:
        return url
    return prefix + url


# ---------------- Cancellation / pause ----------------


def _check_pause(version_key: str) -> None:
    while _pause_flags.get(version_key):
        prog = read_progress(version_key) or {}
        write_progress(
            version_key,
            {
                "status": "paused",
                "stage": prog.get("stage", "downloading"),
                "stage_percent": prog.get("stage_percent", 0),
                "overall_percent": prog.get("overall_percent", 0),
                "message": "Paused",
                "bytes_done": prog.get("bytes_done", 0),
                "bytes_total": prog.get("bytes_total", 0),
            },
        )
        time.sleep(0.2)


def _maybe_abort(version_key: Optional[str]) -> None:
    if version_key and _cancel_flags.get(version_key):
        raise RuntimeError("cancelled")
    if version_key:
        _check_pause(version_key)


# ---------------- Hashing / integrity ----------------


def _sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(DOWNLOAD_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------- Download core ----------------


def download_file(
    url: str,
    dest_path: str,
    expected_sha1: Optional[str] = None,
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
    retries: int = 3,
    version_key: Optional[str] = None,
) -> None:
    """
    Download a file with optional SHA1 verification and progress callback.
    Respects cancel/pause flags via version_key.
    """
    _maybe_abort(version_key)

    url = _apply_url_proxy(url)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    print(f"[download] Starting: {url} -> {dest_path}")
    last_err: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher"})
            with urllib.request.urlopen(req) as resp:
                # Try to get total size from headers if length attribute is missing
                total = getattr(resp, "length", None)
                if total is None:
                    try:
                        total = int(resp.headers.get("Content-Length") or 0) or None
                    except Exception:
                        total = None

                tmp_path = dest_path + ".part"
                downloaded = 0

                with open(tmp_path, "wb") as f:
                    while True:
                        _maybe_abort(version_key)
                        chunk = resp.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb:
                            progress_cb(downloaded, total)

                if expected_sha1:
                    actual = _sha1_file(tmp_path)
                    if actual.lower() != expected_sha1.lower():
                        os.remove(tmp_path)
                        raise ValueError(
                            f"SHA1 mismatch for {dest_path}: expected {expected_sha1}, got {actual}"
                        )

                if os.path.exists(dest_path):
                    os.remove(dest_path)
                os.rename(tmp_path, dest_path)
                print(f"[download] Completed: {dest_path}")
                return
        except Exception as e:
            last_err = e
            print(f"[download] Error on attempt {attempt}/{retries} for {url}: {e}")
            _maybe_abort(version_key)

    raise last_err or RuntimeError(f"Failed to download {url}")


# ---------------- Progress computation ----------------


def _compute_overall(stage: str, stage_percent: float) -> float:
    total = 0.0
    for key, weight in STAGE_WEIGHTS.items():
        if key == stage:
            total += weight * (stage_percent / 100.0)
            break
        total += weight
    return min(100.0, max(0.0, total))


def _update_progress(
    version_key: str,
    stage: str,
    stage_percent: float,
    message: str,
    bytes_done: int = 0,
    bytes_total: int = 0,
) -> None:
    overall = _compute_overall(stage, stage_percent)
    write_progress(
        version_key,
        {
            "status": "downloading",
            "stage": stage,
            "stage_percent": int(stage_percent),
            "overall_percent": int(overall),
            "message": message,
            "bytes_done": int(bytes_done),
            "bytes_total": int(bytes_total),
        },
    )
    print(
        f"[progress] {version_key} | {stage} {stage_percent:.1f}% "
        f"(overall {overall:.1f}%) - {message}"
    )


# ---------------- Version / argument helpers ----------------


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


def _choose_asset_threads() -> int:
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
    if major == 1 and minor >= 6:
        return True
    return False


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
    if major == major_req and minor >= minor_req:
        return True
    return False


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
        downloads = lib.get("downloads") or {}
        artifact = downloads.get("artifact")
        if artifact:
            total += int(artifact.get("size") or 0)
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
        return "Release"
    return n[0].upper() + n[1:].lower()


def _wiki_image_url(version_id: str, version_type: str) -> Optional[str]:
    settings = load_global_settings()
    low_data = settings.get("low_data_mode") == "1"
    pixel_res = round(260/(2 if low_data else 1))

    t = (version_type or "").lower()
    if t == "release" or t == "snapshot":
        prefix = "Java_Edition_"
        clean_id = version_id \
            .replace("-", "_") \
            .replace("pre", "Pre-Release_") \
            .replace("rc", "Release_Candidate_") \
            .replace("snapshot", "Snapshot")
    elif t == "old_beta":
        prefix = "Beta_"
        clean_id = (version_id[1:] if version_id.startswith("b") else version_id) + "_menu"
    elif t == "old_alpha":
        if version_id.startswith("i"):
            prefix = "Infdev_"
            clean_id = version_id[4:] + "_menu"
        else:
            prefix = "Alpha_v"
            clean_id = (version_id[1:] if version_id.startswith("a") else version_id) + "_menu"
    else: return None

    return f"https://minecraft.wiki/images/thumb/{prefix}{clean_id}.png/{pixel_res}px-.png"


# ---------------- Core install pipeline ----------------


def _install_version(version_id: str, storage_category: str, full_assets: bool) -> None:
    ensure_dirs()

    version_key = f"{storage_category}/{version_id}"
    _cancel_flags.pop(version_key, None)
    _pause_flags.pop(version_key, None)

    print(f"[install] Starting install for {version_key} (full_assets={full_assets})")
    _update_progress(version_key, "version_json", 0, "Fetching version metadata...")

    try:
        entry = core_manifest.get_version_entry(version_id)
    except Exception as e:
        raise RuntimeError(f"failed to find version in manifest: {e}")

    version_url = entry.get("url")
    if not version_url:
        raise RuntimeError("manifest entry missing version URL")

    try:
        vjson = core_manifest.fetch_version_json(version_url)
    except Exception as e:
        raise RuntimeError(f"failed to fetch version json: {e}")

    if not isinstance(vjson, dict):
        raise RuntimeError("version json is not an object")

    total_size = _compute_total_size(vjson, version_id, full_assets)
    bytes_done = 0

    _update_progress(
        version_key,
        "version_json",
        100,
        "Version metadata loaded",
        bytes_done=bytes_done,
        bytes_total=total_size,
    )

    storage_fs = _normalize_storage_category(storage_category)
    version_dir = os.path.join(DOWNLOAD_DIR, storage_fs, version_id)
    os.makedirs(version_dir, exist_ok=True)

    _maybe_abort(version_key)

    # ---- Client JAR ----
    client_info = (vjson.get("downloads") or {}).get("client")
    if not client_info:
        raise RuntimeError("version json missing client download info")

    client_url = client_info.get("url")
    client_sha1 = client_info.get("sha1")
    client_size = int(client_info.get("size") or 0)
    if not client_url:
        raise RuntimeError("client download url missing")

    client_path = os.path.join(version_dir, "client.jar")
    _update_progress(
        version_key,
        "client",
        0,
        "Downloading client.jar...",
        bytes_done=bytes_done,
        bytes_total=total_size,
    )
    print(f"[install] Downloading client.jar for {version_key} ({client_size} bytes)")

    def client_cb(done: int, total: Optional[int]) -> None:
        _maybe_abort(version_key)
        pct = 0.0
        if total and total > 0:
            pct = done * 100.0 / total
        _update_progress(
            version_key,
            "client",
            pct,
            "Downloading client.jar...",
            bytes_done=bytes_done + min(done, client_size),
            bytes_total=total_size,
        )

    download_file(
        client_url,
        client_path,
        expected_sha1=client_sha1,
        progress_cb=client_cb,
        version_key=version_key,
    )
    bytes_done += client_size
    _update_progress(
        version_key,
        "client",
        100,
        "client.jar downloaded",
        bytes_done=bytes_done,
        bytes_total=total_size,
    )

    _maybe_abort(version_key)

    # ---- Libraries ----
    libs = vjson.get("libraries") or []
    total_libs = len(libs)
    done_libs = 0
    copied_lib_basenames: List[str] = []

    highest_versions: Dict[str, int] = {}
    for lib in libs:
        downloads = lib.get("downloads") or {}
        artifact = downloads.get("artifact")
        if not artifact:
            continue
        base_name = os.path.basename(artifact.get("path") or "")
        ver = _parse_lwjgl_version(base_name)
        if ver is None:
            continue
        module = base_name.split("-")[0]
        if module not in highest_versions or ver > highest_versions[module]:
            highest_versions[module] = ver

    if total_libs == 0:
        _update_progress(
            version_key,
            "libraries",
            100,
            "No libraries to download",
            bytes_done=bytes_done,
            bytes_total=total_size,
        )
    else:
        print(f"[install] Downloading {total_libs} libraries for {version_key}")
        for lib in libs:
            _maybe_abort(version_key)

            downloads = lib.get("downloads") or {}
            artifact = downloads.get("artifact")
            if artifact:
                a_url = artifact.get("url")
                a_sha1 = artifact.get("sha1")
                a_path = artifact.get("path") or ""
                a_size = int(artifact.get("size") or 0)
                cache_path = os.path.join(CACHE_LIBRARIES_DIR, a_path)
                msg = f"Downloading library {done_libs + 1}/{total_libs}"

                base_name = os.path.basename(a_path) if a_path else ""

                if _should_skip_library_for_version(
                    version_id, base_name, highest_versions
                ):
                    done_libs += 1
                    pct = (done_libs * 100.0) / max(1, total_libs)
                    _update_progress(
                        version_key,
                        "libraries",
                        pct,
                        f"Libraries {done_libs}/{total_libs}",
                        bytes_done=bytes_done,
                        bytes_total=total_size,
                    )
                    continue

                def lib_cb(done_bytes: int, total_bytes: Optional[int]) -> None:
                    _maybe_abort(version_key)
                    pct = (done_libs * 100.0) / max(1, total_libs)
                    _update_progress(
                        version_key,
                        "libraries",
                        pct,
                        msg,
                        bytes_done=bytes_done + min(done_bytes, a_size),
                        bytes_total=total_size,
                    )

                if a_url and a_path:
                    # Reuse cached library if SHA1 matches
                    if (
                        os.path.exists(cache_path)
                        and a_sha1
                        and _sha1_file(cache_path).lower() == a_sha1.lower()
                    ):
                        print(
                            f"[install] Using cached library {done_libs + 1}/{total_libs}: {a_path}"
                        )
                    else:
                        print(
                            f"[install] Library {done_libs + 1}/{total_libs}: {a_path} ({a_size} bytes)"
                        )
                        download_file(
                            a_url,
                            cache_path,
                            expected_sha1=a_sha1,
                            progress_cb=lib_cb,
                            version_key=version_key,
                        )

                    bytes_done += a_size
                    dest_lib = os.path.join(version_dir, base_name)
                    os.makedirs(os.path.dirname(dest_lib), exist_ok=True)
                    if os.path.abspath(cache_path) != os.path.abspath(dest_lib):
                        with open(cache_path, "rb") as src, open(
                            dest_lib, "wb"
                        ) as dst:
                            while True:
                                _maybe_abort(version_key)
                                chunk = src.read(DOWNLOAD_CHUNK_SIZE)
                                if not chunk:
                                    break
                                dst.write(chunk)
                    copied_lib_basenames.append(base_name)

            done_libs += 1
            pct = (done_libs * 100.0) / max(1, total_libs)
            _update_progress(
                version_key,
                "libraries",
                pct,
                f"Libraries {done_libs}/{total_libs}",
                bytes_done=bytes_done,
                bytes_total=total_size,
            )

        _update_progress(
            version_key,
            "libraries",
            100,
            "Libraries downloaded",
            bytes_done=bytes_done,
            bytes_total=total_size,
        )

    _maybe_abort(version_key)

    # ---- Natives ----
    total_native_entries = 0
    for lib in libs:
        downloads = lib.get("downloads") or {}
        classifiers = downloads.get("classifiers") or {}
        total_native_entries += len(classifiers)

    done_native_entries = 0

    if total_native_entries == 0:
        _update_progress(
            version_key,
            "natives",
            100,
            "No natives to download",
            bytes_done=bytes_done,
            bytes_total=total_size,
        )
    else:
        print(
            f"[install] Downloading {total_native_entries} native entries for {version_key}"
        )
        for lib in libs:
            downloads = lib.get("downloads") or {}
            classifiers = downloads.get("classifiers") or {}
            for key, nat in classifiers.items():
                _maybe_abort(version_key)

                n_url = nat.get("url")
                n_sha1 = nat.get("sha1")
                n_path = nat.get("path") or ""
                n_size = int(nat.get("size") or 0)
                cache_path = os.path.join(CACHE_LIBRARIES_DIR, n_path)
                msg = (
                    f"Downloading natives {done_native_entries + 1}/{total_native_entries}"
                )

                def nat_cb(done_bytes: int, total_bytes: Optional[int]) -> None:
                    _maybe_abort(version_key)
                    pct = (done_native_entries * 100.0) / max(
                        1, total_native_entries
                    )
                    _update_progress(
                        version_key,
                        "natives",
                        pct,
                        msg,
                        bytes_done=bytes_done + min(done_bytes, n_size),
                        bytes_total=total_size,
                    )

                if n_url and n_path:
                    # Reuse cached native if SHA1 matches
                    if (
                        os.path.exists(cache_path)
                        and n_sha1
                        and _sha1_file(cache_path).lower() == n_sha1.lower()
                    ):
                        print(
                            f"[install] Using cached native {done_native_entries + 1}/{total_native_entries}: {n_path}"
                        )
                    else:
                        print(
                            f"[install] Native {done_native_entries + 1}/{total_native_entries}: {n_path} ({n_size} bytes)"
                        )
                        download_file(
                            n_url,
                            cache_path,
                            expected_sha1=n_sha1,
                            progress_cb=nat_cb,
                            version_key=version_key,
                        )

                    bytes_done += n_size
                    os_name = _extract_os_from_classifier_key(key) or "unknown"
                    target_dir = os.path.join(version_dir, "native", os_name)
                    os.makedirs(target_dir, exist_ok=True)
                    try:
                        with zipfile.ZipFile(cache_path, "r") as zf:
                            for member in zf.infolist():
                                _maybe_abort(version_key)
                                zf.extract(member, target_dir)
                    except Exception as e:
                        raise RuntimeError(
                            f"failed to extract natives from {n_path}: {e}"
                        )

                done_native_entries += 1
                pct = (done_native_entries * 100.0) / max(1, total_native_entries)
                _update_progress(
                    version_key,
                    "natives",
                    pct,
                    f"Natives {done_native_entries}/{total_native_entries}",
                    bytes_done=bytes_done,
                    bytes_total=total_size,
                )

        _update_progress(
            version_key,
            "natives",
            100,
            "Natives downloaded",
            bytes_done=bytes_done,
            bytes_total=total_size,
        )

    _maybe_abort(version_key)

    # ---- Assets ----
    assets_info = vjson.get("assetIndex") or {}
    assets_url = assets_info.get("url")
    asset_index_name = assets_info.get("id") or None
    assets_sha1 = assets_info.get("sha1")

    modern = _is_modern_assets(version_id)

    if assets_url and asset_index_name:
        _update_progress(
            version_key,
            "assets",
            0,
            "Downloading asset index...",
            bytes_done=bytes_done,
            bytes_total=total_size,
        )
        index_path = os.path.join(ASSETS_INDEXES_DIR, f"{asset_index_name}.json")
        os.makedirs(os.path.dirname(index_path), exist_ok=True)

        def idx_cb(done: int, total: Optional[int]) -> None:
            _maybe_abort(version_key)
            _update_progress(
                version_key,
                "assets",
                0,
                "Downloading asset index...",
                bytes_done=bytes_done,
                bytes_total=total_size,
            )

        print(f"[install] Downloading asset index for {version_key}: {asset_index_name}")
        download_file(
            assets_url,
            index_path,
            expected_sha1=assets_sha1,
            progress_cb=idx_cb,
            version_key=version_key,
        )

        try:
            with open(index_path, "r", encoding="utf-8") as f:
                idx_json = json.load(f)
        except Exception as e:
            raise RuntimeError(f"failed to read asset index: {e}")

        objects = idx_json.get("objects") or {}
        keys = list(objects.keys())

        if full_assets and modern:
            asset_total = sum(int(obj.get("size") or 0) for obj in objects.values())
            total_size = bytes_done + asset_total

        if modern and not full_assets:
            _update_progress(
                version_key,
                "assets",
                100,
                "Assets will be downloaded by the game at runtime",
                bytes_done=bytes_done,
                bytes_total=total_size,
            )
        else:
            total_assets = len(keys)
            done_assets = 0

            if total_assets == 0:
                _update_progress(
                    version_key,
                    "assets",
                    100,
                    "No assets to download",
                    bytes_done=bytes_done,
                    bytes_total=total_size,
                )
            else:
                print(
                    f"[install] Downloading {total_assets} assets for {version_key}"
                )
                asset_threads = _choose_asset_threads()
                lock = threading.Lock()

                def worker(asset_keys: List[str]) -> None:
                    nonlocal bytes_done, done_assets
                    for k in asset_keys:
                        if _cancel_flags.get(version_key):
                            return
                        _check_pause(version_key)

                        obj = objects[k]
                        h = obj.get("hash")
                        size = int(obj.get("size") or 0)
                        if not h:
                            continue

                        subdir = os.path.join(h[0:2])
                        obj_path = os.path.join(ASSETS_OBJECTS_DIR, subdir, h)
                        if os.path.exists(obj_path):
                            with lock:
                                done_assets += 1
                                bytes_done += size
                                pct = done_assets * 100.0 / max(1, total_assets)
                                _update_progress(
                                    version_key,
                                    "assets",
                                    pct,
                                    f"Assets {done_assets}/{total_assets}",
                                    bytes_done=bytes_done,
                                    bytes_total=total_size,
                                )
                            continue

                        obj_url = (
                            f"https://resources.download.minecraft.net/{h[0:2]}/{h}"
                        )

                        def asset_cb(done_bytes: int, total_bytes: Optional[int]) -> None:
                            _maybe_abort(version_key)
                            # Per-asset progress is noisy; we only update on completion below.

                        print(
                            f"[install] Asset {done_assets + 1}/{total_assets}: {h} ({size} bytes)"
                        )
                        download_file(
                            obj_url,
                            obj_path,
                            expected_sha1=h,
                            progress_cb=asset_cb,
                            version_key=version_key,
                        )
                        if _cancel_flags.get(version_key):
                            return
                        with lock:
                            done_assets += 1
                            bytes_done += size
                            pct = done_assets * 100.0 / max(1, total_assets)
                            _update_progress(
                                version_key,
                                "assets",
                                pct,
                                f"Assets {done_assets}/{total_assets}",
                                bytes_done=bytes_done,
                                bytes_total=total_size,
                            )

                if keys:
                    chunks: List[List[str]] = [[] for _ in range(asset_threads)]
                    for i, k in enumerate(keys):
                        chunks[i % asset_threads].append(k)

                    threads: List[threading.Thread] = []
                    for chunk in chunks:
                        if not chunk:
                            continue
                        t = threading.Thread(
                            target=worker, args=(chunk,), daemon=True
                        )
                        threads.append(t)
                        t.start()
                    for t in threads:
                        t.join()

                _update_progress(
                    version_key,
                    "assets",
                    100,
                    "Assets downloaded",
                    bytes_done=bytes_done,
                    bytes_total=total_size,
                )
    else:
        _update_progress(
            version_key,
            "assets",
            100,
            "No assets required",
            bytes_done=bytes_done,
            bytes_total=total_size,
        )

    _maybe_abort(version_key)

    # ---- Finalize / metadata ----
    vtype = entry.get("type", "")
    img_url = _wiki_image_url(version_id, vtype)
    if img_url:
        try:
            _update_progress(
                version_key,
                "finalize",
                0,
                "Downloading display image...",
                bytes_done=bytes_done,
                bytes_total=total_size,
            )
            display_path = os.path.join(version_dir, "display.png")

            def img_cb(done_bytes: int, total_bytes: Optional[int]) -> None:
                _maybe_abort(version_key)

            print(f"[install] Downloading display image for {version_key}")
            download_file(
                img_url,
                display_path,
                expected_sha1=None,
                progress_cb=img_cb,
                version_key=version_key,
            )
        except Exception: pass

    _update_progress(
        version_key,
        "finalize",
        50,
        "Writing metadata...",
        bytes_done=bytes_done,
        bytes_total=total_size,
    )

    main_class = vjson.get("mainClass") or "net.minecraft.client.Minecraft"
    extra_args = _extract_extra_args(vjson)
    version_type = entry.get("type", "") or vjson.get("type", "")

    seen_libs = set()
    unique_libs: List[str] = []
    for name in copied_lib_basenames:
        if name not in seen_libs:
            seen_libs.add(name)
            unique_libs.append(name)

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

    _update_progress(
        version_key,
        "finalize",
        100,
        "Installation complete",
        bytes_done=bytes_done,
        bytes_total=total_size,
    )

    try:
        write_progress(
            version_key,
            {
                "status": "installed",
                "stage": "finalize",
                "stage_percent": 100,
                "overall_percent": 100,
                "message": "Installation complete",
                "bytes_done": int(bytes_done),
                "bytes_total": int(total_size),
            },
        )
    except Exception:
        pass

    try:
        notification.notify(
            title=f"[{version_id}] Installation complete!",
            message=f"Minecraft {version_id} has installed successfully!",
            app_icon=os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "ui",
                "favicon.ico",
            ),
        )
    except Exception:
        pass

    print(f"[install] Installation complete for {version_key}")


# ---------------- Public API ----------------


def _version_key(version_id: str, storage_category: str) -> str:
    return f"{storage_category}/{version_id}"


def install_version(
    version_id: str,
    storage_category: str = "Release",
    full_assets: bool = True,
    background: bool = True,
) -> None:
    version_key = _version_key(version_id, storage_category)

    if background:
        t = _workers.get(version_key)
        if t and t.is_alive():
            print(f"[install] Worker already running for {version_key}")
            return

        def runner() -> None:
            vk = _version_key(version_id, storage_category)
            storage_fs = _normalize_storage_category(storage_category)
            version_dir = os.path.join(DOWNLOAD_DIR, storage_fs, version_id)

            cancelled = False

            try:
                _install_version(version_id, storage_category, full_assets)
            except RuntimeError as e:
                if str(e) == "cancelled":
                    cancelled = True
                    print(f"[install] Installation cancelled for {vk}")
                    write_progress(
                        vk,
                        {
                            "status": "cancelled",
                            "stage": "finalize",
                            "stage_percent": 0,
                            "overall_percent": 0,
                            "message": "Installation cancelled",
                            "bytes_done": 0,
                            "bytes_total": 0,
                        },
                    )
                else:
                    print(f"[install] Error during install for {vk}: {e}")
                    write_progress(
                        vk,
                        {
                            "status": "error",
                            "stage": "finalize",
                            "stage_percent": 0,
                            "overall_percent": 0,
                            "message": str(e),
                            "bytes_done": 0,
                            "bytes_total": 0,
                        },
                    )
            finally:
                if cancelled:
                    try:
                        if os.path.isdir(version_dir):
                            print(
                                f"[install] Removing incomplete folder: {version_dir}"
                            )
                            shutil.rmtree(version_dir)
                    except Exception as cleanup_err:
                        print(f"[install] Cleanup failed: {cleanup_err}")

                _workers.pop(vk, None)
                _cancel_flags.pop(vk, None)
                _pause_flags.pop(vk, None)

        worker = threading.Thread(target=runner, daemon=True)
        _workers[version_key] = worker
        worker.start()
    else:
        _install_version(version_id, storage_category, full_assets)


def cancel_install(version_id: str, storage_category: str = "Release") -> None:
    version_key = _version_key(version_id, storage_category)
    print(f"[install] Cancel requested for {version_key}")
    _cancel_flags[version_key] = True
    _pause_flags.pop(version_key, None)


def pause_install(version_id: str, storage_category: str = "Release") -> None:
    version_key = _version_key(version_id, storage_category)
    print(f"[install] Pause requested for {version_key}")
    _pause_flags[version_key] = True


def resume_install(version_id: str, storage_category: str = "Release") -> None:
    version_key = _version_key(version_id, storage_category)
    print(f"[install] Resume requested for {version_key}")
    _pause_flags[version_key] = False


def is_installing(version_id: str, storage_category: str = "Release") -> bool:
    version_key = _version_key(version_id, storage_category)
    t = _workers.get(version_key)
    return bool(t and t.is_alive())


def get_install_status(
    version_id: str, storage_category: str = "Release"
) -> Optional[Dict[str, Any]]:
    version_key = _version_key(version_id, storage_category)
    prog = read_progress(version_key)
    if not prog:
        return None
    if _pause_flags.get(version_key):
        prog["status"] = "paused"
    return prog
