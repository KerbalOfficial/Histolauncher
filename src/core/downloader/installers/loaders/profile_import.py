from __future__ import annotations

import json
import os
import platform
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.constants import DOWNLOAD_PARALLEL_WORKERS
from core.downloader.errors import DownloadFailed
from core.downloader.http import CLIENT, DownloadTask
from core.downloader.library_store import link_into_version, store_path_for
from core.logger import colorize_log
from core.settings import get_versions_profile_dir


DEFAULT_MAVEN: str = "https://libraries.minecraft.net/"


@dataclass(frozen=True)
class ImportResult:
    profile_id: str
    profile_path: str
    library_count: int
    main_class: Optional[str]


def find_profile_json(
    *,
    fake_mc_dir: str,
    expected_profile_id: Optional[str] = None,
) -> Tuple[str, str]:
    versions_root = os.path.join(fake_mc_dir, "versions")
    if not os.path.isdir(versions_root):
        raise DownloadFailed(
            f"Installer did not create versions directory at {versions_root}",
            url=None,
        )

    if expected_profile_id:
        candidate = os.path.join(
            versions_root, expected_profile_id, f"{expected_profile_id}.json"
        )
        if os.path.isfile(candidate):
            return expected_profile_id, candidate

    candidates: List[Tuple[float, str, str]] = []
    for entry in os.listdir(versions_root):
        sub = os.path.join(versions_root, entry)
        json_path = os.path.join(sub, f"{entry}.json")
        if os.path.isdir(sub) and os.path.isfile(json_path):
            candidates.append((os.path.getmtime(json_path), entry, json_path))

    if not candidates:
        raise DownloadFailed(
            f"Installer produced no profile JSON in {versions_root}", url=None
        )

    candidates.sort(key=lambda t: t[0], reverse=True)
    for mtime, name, path in candidates:
        client_jar = os.path.join(os.path.dirname(path), f"{name}.jar")
        if not os.path.isfile(client_jar):
            return name, path

    return candidates[0][1], candidates[0][2]


def _maven_to_artifact_path(name: str) -> Optional[str]:
    parts = (name or "").split(":")
    if len(parts) < 3:
        return None
    for raw in parts:
        if not raw or any(ch in raw for ch in ("/", "\\", "\x00")):
            return None
        for segment in raw.split("."):
            if segment in ("", ".", ".."):
                return None
    group = parts[0].replace(".", "/")
    artifact = parts[1]
    version = parts[2]
    classifier = ""
    extension = "jar"
    if "@" in version:
        version, extension = version.split("@", 1)
    if len(parts) >= 4:
        cls = parts[3]
        if "@" in cls:
            classifier, extension = cls.split("@", 1)
        else:
            classifier = cls
    if extension and any(ch in extension for ch in ("/", "\\", "\x00", "..")):
        return None
    if classifier and any(ch in classifier for ch in ("/", "\\", "\x00", "..")):
        return None
    file_name = f"{artifact}-{version}"
    if classifier:
        file_name += f"-{classifier}"
    file_name += f".{extension}"
    return f"{group}/{artifact}/{version}/{file_name}"


def _resolve_artifact(
    lib: Dict[str, Any],
) -> Optional[Tuple[str, str, Optional[str], Optional[int]]]:
    name = str(lib.get("name") or "").strip()

    downloads = lib.get("downloads") or {}
    if not isinstance(downloads, dict):
        downloads = {}
    artifact = downloads.get("artifact")
    if isinstance(artifact, dict) and artifact.get("url"):
        path = artifact.get("path") or _maven_to_artifact_path(name)
        if not path:
            return None
        return (
            path,
            str(artifact.get("url")),
            artifact.get("sha1") or None,
            artifact.get("size") if isinstance(artifact.get("size"), int) else None,
        )

    # Classifiers-only library (e.g. natives) — no main artifact jar exists.
    if isinstance(downloads.get("classifiers"), dict):
        return None

    if not name:
        return None
    path = _maven_to_artifact_path(name)
    if not path:
        return None
    base = str(lib.get("url") or DEFAULT_MAVEN).rstrip("/")
    encoded_path = "/".join(
        urllib.parse.quote(seg, safe="+") for seg in path.split("/")
    )
    return (path, f"{base}/{encoded_path}", None, None)


def _platform_native_key(lib: Dict[str, Any]) -> Optional[str]:
    natives = lib.get("natives")
    if not isinstance(natives, dict):
        return None
    system = platform.system().lower()
    if "windows" in system:
        return natives.get("windows")
    if "linux" in system:
        return natives.get("linux")
    if "darwin" in system or "mac" in system:
        return natives.get("osx") or natives.get("mac")
    return None


def _resolve_native_classifier(
    lib: Dict[str, Any],
) -> Optional[Tuple[str, str, Optional[str], Optional[int]]]:
    """Return (artifact_path, url, sha1, size) for the platform-native classifier."""
    native_key = _platform_native_key(lib)
    if not native_key:
        return None
    downloads = lib.get("downloads") or {}
    classifiers = downloads.get("classifiers") if isinstance(downloads, dict) else None
    if not isinstance(classifiers, dict):
        return None
    entry = classifiers.get(native_key)
    if not isinstance(entry, dict) or not entry.get("url"):
        return None
    path = entry.get("path")
    if not path:
        name = str(lib.get("name") or "").strip()
        path = _maven_to_artifact_path(f"{name}:{native_key}") if name else None
    if not path:
        return None
    return (
        path,
        str(entry["url"]),
        entry.get("sha1") or None,
        entry.get("size") if isinstance(entry.get("size"), int) else None,
    )


def import_profile(
    *,
    fake_mc_dir: str,
    real_version_dir: str,
    expected_profile_id: Optional[str] = None,
    cancel_check: Optional[Callable[[], None]] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    max_workers: int = DOWNLOAD_PARALLEL_WORKERS,
) -> ImportResult:
    profile_id, profile_src = find_profile_json(
        fake_mc_dir=fake_mc_dir, expected_profile_id=expected_profile_id
    )

    os.makedirs(real_version_dir, exist_ok=True)
    profile_dst = os.path.join(real_version_dir, f"{profile_id}.json")

    with open(profile_src, "r", encoding="utf-8") as fp:
        profile = json.load(fp)

    with open(profile_dst, "w", encoding="utf-8") as fp:
        json.dump(profile, fp, indent=2)

    libraries = profile.get("libraries") or []
    main_class = str(profile.get("mainClass") or "").strip() or None

    plan: Dict[str, Tuple[str, Optional[str], Optional[int]]] = {}
    skipped: List[str] = []
    for lib in libraries:
        if not isinstance(lib, dict):
            continue
        resolved = _resolve_artifact(lib)
        if resolved is None:
            skipped.append(str(lib.get("name") or lib))
        else:
            artifact_path, url, sha1, size = resolved
            plan.setdefault(artifact_path, (url, sha1, size))
        # Also collect the platform-appropriate native classifier jar.
        native = _resolve_native_classifier(lib)
        if native is not None:
            native_path, native_url, native_sha1, native_size = native
            plan.setdefault(native_path, (native_url, native_sha1, native_size))

    if skipped:
        print(colorize_log(
            f"[profile-import] skipped {len(skipped)} libraries with no main artifact (natives-only or unresolved)"
        ))

    tasks: List[DownloadTask] = []
    store_paths: Dict[str, str] = {}
    for artifact_path, (url, sha1, size) in plan.items():
        store_dest = store_path_for(artifact_path)
        store_paths[artifact_path] = store_dest
        if os.path.isfile(store_dest) and sha1 is None:
            continue
        tasks.append(DownloadTask(
            url=url,
            dest_path=store_dest,
            expected_sha1=sha1,
            expected_size=size,
        ))

    if tasks:
        print(colorize_log(
            f"[profile-import] downloading {len(tasks)} libraries via store"
        ))
        CLIENT.download_many(
            tasks, max_workers=max_workers, cancel_check=cancel_check
        )

    libs_dir = os.path.join(real_version_dir, "libraries")
    libs_dir_real = os.path.realpath(libs_dir)
    linked = 0
    for artifact_path, store_dest in store_paths.items():
        if not os.path.isfile(store_dest):
            continue
        version_dest = os.path.join(libs_dir, artifact_path.replace("/", os.sep))
        version_dest_real = os.path.realpath(version_dest)
        try:
            if os.path.commonpath([libs_dir_real, version_dest_real]) != libs_dir_real:
                print(colorize_log(
                    f"[profile-import] refusing to link library outside libraries/: {artifact_path}"
                ))
                continue
        except ValueError:
            print(colorize_log(
                f"[profile-import] rejecting cross-volume library path: {artifact_path}"
            ))
            continue
        link_into_version(store_file=store_dest, version_dest=version_dest)
        linked += 1
        if progress_cb is not None:
            try:
                progress_cb(linked, len(store_paths))
            except Exception:
                pass

    return ImportResult(
        profile_id=profile_id,
        profile_path=profile_dst,
        library_count=linked,
        main_class=main_class,
    )


__all__ = [
    "DEFAULT_MAVEN",
    "ImportResult",
    "find_profile_json",
    "import_profile",
]
