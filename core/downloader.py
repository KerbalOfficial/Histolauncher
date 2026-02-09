# core/downloader.py
import os
import json
import hashlib
import threading
import urllib.request
import urllib.error
import zipfile
from typing import Optional, Dict, Any, Callable, List, Tuple

from core.settings import load_global_settings, get_base_dir
from core import manifest as core_manifest

from core.libraries.plyer import notification

BASE_DIR = get_base_dir()

DOWNLOAD_DIR = os.path.join(BASE_DIR, "clients")
PROGRESS_DIR = os.path.join(BASE_DIR, "cache", "progress")
CACHE_LIBRARIES_DIR = os.path.join(BASE_DIR, "cache", "libraries")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
ASSETS_INDEXES_DIR = os.path.join(ASSETS_DIR, "indexes")
ASSETS_OBJECTS_DIR = os.path.join(ASSETS_DIR, "objects")

_workers: Dict[str, threading.Thread] = {}
_cancel_flags: Dict[str, bool] = {}


def ensure_dirs():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    os.makedirs(CACHE_LIBRARIES_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(ASSETS_INDEXES_DIR, exist_ok=True)
    os.makedirs(ASSETS_OBJECTS_DIR, exist_ok=True)


def progress_path(version_key: str) -> str:
    ensure_dirs()
    safe = version_key.replace("/", "_")
    return os.path.join(PROGRESS_DIR, f"{safe}.json")


def write_progress(version_key: str, data: Dict[str, Any]) -> None:
    p = progress_path(version_key)
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def read_progress(version_key: str) -> Optional[Dict[str, Any]]:
    p = progress_path(version_key)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def delete_progress(version_key: str) -> None:
    try:
        p = progress_path(version_key)
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass


def list_progress_files() -> List[Tuple[str, Dict[str, Any]]]:
    ensure_dirs()
    out = []
    for name in os.listdir(PROGRESS_DIR):
        if not name.endswith(".json"):
            continue
        path = os.path.join(PROGRESS_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = name[:-5].replace("_", "/")
            out.append((key, data))
        except Exception:
            continue
    return out


def _get_url_proxy_prefix() -> str:
    try:
        s = load_global_settings() or {}
    except Exception:
        s = {}
    prefix = (s.get("url_proxy") or "").strip()
    return prefix


def _apply_url_proxy(url: str) -> str:
    prefix = _get_url_proxy_prefix()
    if not prefix:
        return url
    return prefix + url


def _sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(
    url: str,
    dest_path: str,
    expected_sha1: Optional[str] = None,
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
    retries: int = 3
) -> None:
    url = _apply_url_proxy(url)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    print(f"[download] Starting: {url} -> {dest_path}")
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher"})
            with urllib.request.urlopen(req) as resp:
                total = getattr(resp, "length", None)
                tmp_path = dest_path + ".part"
                with open(tmp_path, "wb") as f:
                    downloaded = 0
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb:
                            progress_cb(downloaded, total)
                        if total:
                            print(f"[download] {dest_path}: {downloaded}/{total} bytes")
                        else:
                            print(f"[download] {dest_path}: {downloaded} bytes")
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
    raise last_err or RuntimeError(f"Failed to download {url}")


def _wiki_image_url(version_id: str, version_type: str) -> Optional[str]:
    t = (version_type or "").lower()
    if t == "release":
        prefix = "Java_Edition_"
        clean_id = version_id
    elif t == "old_beta":
        prefix = "Beta_"
        clean_id = version_id[1:] if version_id.startswith("b") else version_id
    elif t == "old_alpha":
        prefix = "Alpha_v"
        clean_id = version_id[1:] if version_id.startswith("a") else version_id
    else:
        return None
    return f"https://minecraft.wiki/images/thumb/{prefix}{clean_id}.png/260px-.png"


STAGE_WEIGHTS = {
    "version_json": 5,
    "client": 20,
    "libraries": 25,
    "natives": 15,
    "assets": 25,
    "finalize": 10,
}


def _compute_overall(stage: str, stage_percent: float) -> float:
    total = 0.0
    for k, w in STAGE_WEIGHTS.items():
        if k == stage:
            total += w * (stage_percent / 100.0)
            break
        else:
            total += w
    return min(100.0, max(0.0, total))


def _update_progress(
    version_key: str,
    stage: str,
    stage_percent: float,
    message: str,
    bytes_done: int = 0,
    bytes_total: int = 0
) -> None:
    overall = _compute_overall(stage, stage_percent)
    write_progress(version_key, {
        "status": "downloading",
        "stage": stage,
        "stage_percent": int(stage_percent),
        "overall_percent": int(overall),
        "message": message,
        "bytes_done": int(bytes_done),
        "bytes_total": int(bytes_total),
    })
    print(f"[progress] {version_key} | {stage} {stage_percent:.1f}% (overall {overall:.1f}%) - {message}")


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
        return 16
    if threads >= 6:
        return 8
    return 4


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


def _should_skip_library_for_version(version_id: str, lib_basename: str) -> bool:
    """
    Avoid installing older LWJGL 3.2.1 when 3.2.2+ is required (1.13+).
    Very simple heuristic: if the jar name contains '3.2.1' and the
    Minecraft version is >= 1.13, skip it.
    """
    if not lib_basename:
        return False
    if _is_at_least(version_id, 1, 13):
        if "3.2.1" in lib_basename:
            print(f"[install] Skipping outdated LWJGL library for {version_id}: {lib_basename}")
            return True
    return False


def _compute_total_size(vjson: Dict[str, Any], version_id: str, full_assets: bool) -> int:
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
            index_path = os.path.join(ASSETS_INDEXES_DIR, f"{assets_info.get('id','')}.json")
            if os.path.exists(index_path):
                with open(index_path, "r", encoding="utf-8") as f:
                    idx_json = json.load(f)
            else:
                idx_json = {}
        except Exception:
            idx_json = {}
        objects = (idx_json.get("objects") or {})
        for obj in objects.values():
            total += int(obj.get("size") or 0)

    return total


def _normalize_storage_category(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return "Release"
    return n[0].upper() + n[1:].lower()


def _install_version(version_id: str, storage_category: str, full_assets: bool) -> None:
    ensure_dirs()

    version_key = f"{storage_category}/{version_id}"
    _cancel_flags.pop(version_key, None)

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

    _update_progress(version_key, "version_json", 100, "Version metadata loaded",
                     bytes_done=bytes_done, bytes_total=total_size)

    storage_fs = _normalize_storage_category(storage_category)
    version_dir = os.path.join(DOWNLOAD_DIR, storage_fs, version_id)
    os.makedirs(version_dir, exist_ok=True)

    if _cancel_flags.get(version_key):
        raise RuntimeError("cancelled")

    client_info = (vjson.get("downloads") or {}).get("client")
    if not client_info:
        raise RuntimeError("version json missing client download info")

    client_url = client_info.get("url")
    client_sha1 = client_info.get("sha1")
    client_size = int(client_info.get("size") or 0)
    if not client_url:
        raise RuntimeError("client download url missing")

    client_path = os.path.join(version_dir, "client.jar")
    _update_progress(version_key, "client", 0, "Downloading client.jar...",
                     bytes_done=bytes_done, bytes_total=total_size)
    print(f"[install] Downloading client.jar for {version_key} ({client_size} bytes)")

    def client_cb(done, total):
        if _cancel_flags.get(version_key):
            raise RuntimeError("cancelled")
        pct = 0
        if total and total > 0:
            pct = done * 100.0 / total
        _update_progress(version_key, "client", pct, "Downloading client.jar...",
                         bytes_done=bytes_done + min(done, client_size),
                         bytes_total=total_size)

    download_file(client_url, client_path, expected_sha1=client_sha1, progress_cb=client_cb)
    bytes_done += client_size
    _update_progress(version_key, "client", 100, "client.jar downloaded",
                     bytes_done=bytes_done, bytes_total=total_size)

    if _cancel_flags.get(version_key):
        raise RuntimeError("cancelled")

    libs = vjson.get("libraries") or []
    total_libs = len(libs)
    done_libs = 0
    copied_lib_basenames: List[str] = []

    if total_libs == 0:
        _update_progress(version_key, "libraries", 100, "No libraries to download",
                         bytes_done=bytes_done, bytes_total=total_size)
    else:
        print(f"[install] Downloading {total_libs} libraries for {version_key}")
        for lib in libs:
            if _cancel_flags.get(version_key):
                raise RuntimeError("cancelled")

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

                if _should_skip_library_for_version(version_id, base_name):
                    done_libs += 1
                    pct = (done_libs * 100.0) / max(1, total_libs)
                    _update_progress(version_key, "libraries", pct,
                                     f"Libraries {done_libs}/{total_libs}",
                                     bytes_done=bytes_done, bytes_total=total_size)
                    continue

                def lib_cb(done_bytes, total_bytes):
                    if _cancel_flags.get(version_key):
                        raise RuntimeError("cancelled")
                    pct = (done_libs * 100.0) / max(1, total_libs)
                    _update_progress(version_key, "libraries", pct, msg,
                                     bytes_done=bytes_done + min(done_bytes, a_size),
                                     bytes_total=total_size)

                if a_url and a_path:
                    print(f"[install] Library {done_libs + 1}/{total_libs}: {a_path} ({a_size} bytes)")
                    download_file(a_url, cache_path, expected_sha1=a_sha1, progress_cb=lib_cb)
                    bytes_done += a_size
                    dest_lib = os.path.join(version_dir, base_name)
                    os.makedirs(os.path.dirname(dest_lib), exist_ok=True)
                    if os.path.abspath(cache_path) != os.path.abspath(dest_lib):
                        with open(cache_path, "rb") as src, open(dest_lib, "wb") as dst:
                            while True:
                                chunk = src.read(8192)
                                if not chunk:
                                    break
                                dst.write(chunk)
                    copied_lib_basenames.append(base_name)

            done_libs += 1
            pct = (done_libs * 100.0) / max(1, total_libs)
            _update_progress(version_key, "libraries", pct,
                             f"Libraries {done_libs}/{total_libs}",
                             bytes_done=bytes_done, bytes_total=total_size)

        _update_progress(version_key, "libraries", 100, "Libraries downloaded",
                         bytes_done=bytes_done, bytes_total=total_size)

    if _cancel_flags.get(version_key):
        raise RuntimeError("cancelled")

    total_native_entries = 0
    for lib in libs:
        downloads = lib.get("downloads") or {}
        classifiers = downloads.get("classifiers") or {}
        total_native_entries += len(classifiers)

    done_native_entries = 0

    if total_native_entries == 0:
        _update_progress(version_key, "natives", 100, "No natives to download",
                         bytes_done=bytes_done, bytes_total=total_size)
    else:
        print(f"[install] Downloading {total_native_entries} native entries for {version_key}")
        for lib in libs:
            downloads = lib.get("downloads") or {}
            classifiers = downloads.get("classifiers") or {}
            for key, nat in classifiers.items():
                if _cancel_flags.get(version_key):
                    raise RuntimeError("cancelled")

                n_url = nat.get("url")
                n_sha1 = nat.get("sha1")
                n_path = nat.get("path") or ""
                n_size = int(nat.get("size") or 0)
                cache_path = os.path.join(CACHE_LIBRARIES_DIR, n_path)
                msg = f"Downloading natives {done_native_entries + 1}/{total_native_entries}"

                def nat_cb(done_bytes, total_bytes):
                    if _cancel_flags.get(version_key):
                        raise RuntimeError("cancelled")
                    pct = (done_native_entries * 100.0) / max(1, total_native_entries)
                    _update_progress(version_key, "natives", pct, msg,
                                     bytes_done=bytes_done + min(done_bytes, n_size),
                                     bytes_total=total_size)

                if n_url and n_path:
                    print(f"[install] Native {done_native_entries + 1}/{total_native_entries}: {n_path} ({n_size} bytes)")
                    download_file(n_url, cache_path, expected_sha1=n_sha1, progress_cb=nat_cb)
                    bytes_done += n_size
                    os_name = _extract_os_from_classifier_key(key) or "unknown"
                    target_dir = os.path.join(version_dir, "native", os_name)
                    os.makedirs(target_dir, exist_ok=True)
                    try:
                        with zipfile.ZipFile(cache_path, "r") as zf:
                            zf.extractall(target_dir)
                    except Exception as e:
                        raise RuntimeError(f"failed to extract natives from {n_path}: {e}")

                done_native_entries += 1
                pct = (done_native_entries * 100.0) / max(1, total_native_entries)
                _update_progress(version_key, "natives", pct,
                                 f"Natives {done_native_entries}/{total_native_entries}",
                                 bytes_done=bytes_done, bytes_total=total_size)

        _update_progress(version_key, "natives", 100, "Natives downloaded",
                         bytes_done=bytes_done, bytes_total=total_size)

    if _cancel_flags.get(version_key):
        raise RuntimeError("cancelled")

    assets_info = vjson.get("assetIndex") or {}
    assets_url = assets_info.get("url")
    asset_index_name = assets_info.get("id") or None
    assets_sha1 = assets_info.get("sha1")

    modern = _is_modern_assets(version_id)

    if assets_url and asset_index_name:
        _update_progress(version_key, "assets", 0, "Downloading asset index...",
                         bytes_done=bytes_done, bytes_total=total_size)
        index_path = os.path.join(ASSETS_INDEXES_DIR, f"{asset_index_name}.json")
        os.makedirs(os.path.dirname(index_path), exist_ok=True)

        def idx_cb(done, total):
            if _cancel_flags.get(version_key):
                raise RuntimeError("cancelled")
            _update_progress(version_key, "assets", 0, "Downloading asset index...",
                             bytes_done=bytes_done, bytes_total=total_size)

        print(f"[install] Downloading asset index for {version_key}: {asset_index_name}")
        download_file(assets_url, index_path, expected_sha1=assets_sha1, progress_cb=idx_cb)

        try:
            with open(index_path, "r", encoding="utf-8") as f:
                idx_json = json.load(f)
        except Exception as e:
            raise RuntimeError(f"failed to read asset index: {e}")

        objects = (idx_json.get("objects") or {})
        keys = list(objects.keys())

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
                _update_progress(version_key, "assets", 100, "No assets to download",
                                 bytes_done=bytes_done, bytes_total=total_size)
            else:
                print(f"[install] Downloading {total_assets} assets for {version_key}")
                asset_threads = _choose_asset_threads()
                lock = threading.Lock()

                def worker(asset_keys: List[str]):
                    nonlocal bytes_done, done_assets
                    for k in asset_keys:
                        if _cancel_flags.get(version_key):
                            return
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
                                _update_progress(version_key, "assets", pct,
                                                 f"Assets {done_assets}/{total_assets}",
                                                 bytes_done=bytes_done, bytes_total=total_size)
                            continue

                        obj_url = f"https://resources.download.minecraft.net/{h[0:2]}/{h}"

                        def asset_cb(done_bytes, total_bytes):
                            if _cancel_flags.get(version_key):
                                raise RuntimeError("cancelled")

                        print(f"[install] Asset {done_assets + 1}/{total_assets}: {h} ({size} bytes)")
                        download_file(obj_url, obj_path, expected_sha1=h, progress_cb=asset_cb)
                        with lock:
                            done_assets += 1
                            bytes_done += size
                            pct = done_assets * 100.0 / max(1, total_assets)
                            _update_progress(version_key, "assets", pct,
                                             f"Assets {done_assets}/{total_assets}",
                                             bytes_done=bytes_done, bytes_total=total_size)

                if keys:
                    chunks: List[List[str]] = [[] for _ in range(asset_threads)]
                    for i, k in enumerate(keys):
                        chunks[i % asset_threads].append(k)

                    threads: List[threading.Thread] = []
                    for chunk in chunks:
                        if not chunk:
                            continue
                        t = threading.Thread(target=worker, args=(chunk,), daemon=True)
                        threads.append(t)
                        t.start()
                    for t in threads:
                        t.join()

                _update_progress(version_key, "assets", 100, "Assets downloaded",
                                 bytes_done=bytes_done, bytes_total=total_size)
    else:
        _update_progress(version_key, "assets", 100, "No assets required",
                         bytes_done=bytes_done, bytes_total=total_size)

    if _cancel_flags.get(version_key):
        raise RuntimeError("cancelled")

    vtype = entry.get("type", "")
    img_url = _wiki_image_url(version_id, vtype)
    if img_url:
        try:
            _update_progress(version_key, "finalize", 0, "Downloading display image...",
                             bytes_done=bytes_done, bytes_total=total_size)
            display_path = os.path.join(version_dir, "display.png")

            def img_cb(done_bytes, total_bytes):
                if _cancel_flags.get(version_key):
                    raise RuntimeError("cancelled")

            print(f"[install] Downloading display image for {version_key}")
            download_file(img_url, display_path, expected_sha1=None, progress_cb=img_cb)
        except Exception:
            pass

    _update_progress(version_key, "finalize", 50, "Writing metadata...",
                     bytes_done=bytes_done, bytes_total=total_size)

    main_class = vjson.get("mainClass") or "net.minecraft.client.Minecraft"
    extra_args = _extract_extra_args(vjson)
    version_type = entry.get("type", "") or vjson.get("type", "")

    # Deduplicate libraries while preserving order
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
    lines.append('launch_disabled=false,""')

    with open(data_ini_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    _update_progress(version_key, "finalize", 100, "Installation complete",
                     bytes_done=bytes_done, bytes_total=total_size)
    print(f"[install] Installation complete for {version_key}")


def start_download(version_id: str, storage_category: str, full_assets: bool = False) -> str:
    ensure_dirs()
    storage_category = (storage_category or "release").lower()
    version_key = f"{storage_category}/{version_id}"

    if version_key in _workers:
        print(f"[install] Download already in progress for {version_key}")
        return version_key

    def _worker():
        try:
            write_progress(version_key, {"status": "starting"})
            _install_version(version_id, storage_category, full_assets)
            write_progress(version_key, {
                "status": "installed",
                "stage": "finalize",
                "stage_percent": 100,
                "overall_percent": 100,
                "message": "Installed successfully",
            })
            notification.notify(
                title=f"[{version_id}] Installation complete!",
                message=f"Minecraft {version_id} has installed successfully!",
                app_icon=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"ui","favicon.ico")
            )
        except Exception as e:
            if str(e) == "cancelled":
                write_progress(version_key, {
                    "status": "cancelled",
                    "message": "Download cancelled",
                })
                print(f"[install] Download cancelled for {version_key}")
            else:
                write_progress(version_key, {
                    "status": "failed",
                    "message": str(e),
                })
                print(f"[install] Download failed for {version_key}: {e}")
        finally:
            _workers.pop(version_key, None)
            _cancel_flags.pop(version_key, None)

    t = threading.Thread(target=_worker, daemon=True)
    _workers[version_key] = t
    t.start()
    return version_key


def get_status(version_key: str) -> Optional[Dict[str, Any]]:
    return read_progress(version_key)


def cancel_download(version_key: str) -> None:
    print(f"[install] Cancel requested for {version_key}")
    _cancel_flags[version_key] = True


def list_installing_versions() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for key, data in list_progress_files():
        status = data.get("status")
        if status in ("starting", "downloading"):
            out[key] = data
    return out
