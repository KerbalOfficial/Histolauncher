from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.downloader.errors import DownloadFailed
from core.downloader.http import CLIENT, DownloadTask
from core.downloader.library_store import link_into_version, store_path_for
from core.logger import colorize_log
from core.settings import get_versions_profile_dir


DEFAULT_MAVEN: str = "https://libraries.minecraft.net/"


@dataclass(frozen=True)
class ImportResult:
    profile_id: str
    profile_path: str  # destination path inside the real version dir
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

    # Fallback: scan for the newest <name>/<name>.json that doesn't look like
    # the vanilla MC entry we placed ourselves.
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

    # Prefer entries other than vanilla MC dirs (those usually have a client
    # jar next to the json). The newest candidate wins on tie.
    candidates.sort(key=lambda t: t[0], reverse=True)
    for mtime, name, path in candidates:
        client_jar = os.path.join(os.path.dirname(path), f"{name}.jar")
        if not os.path.isfile(client_jar):
            return name, path

    # Otherwise the newest. (Will be the loader profile in the rare case it
    # ships its own jar.)
    return candidates[0][1], candidates[0][2]


def _maven_to_artifact_path(name: str) -> Optional[str]:
    parts = (name or "").split(":")
    if len(parts) < 3:
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
    file_name = f"{artifact}-{version}"
    if classifier:
        file_name += f"-{classifier}"
    file_name += f".{extension}"
    return f"{group}/{artifact}/{version}/{file_name}"


def _resolve_artifact(
    lib: Dict[str, Any],
) -> Optional[Tuple[str, str, Optional[str], Optional[int]]]:
    name = str(lib.get("name") or "").strip()

    # Modern shape: downloads.artifact carries url+sha1+size+path.
    downloads = lib.get("downloads") or {}
    artifact = downloads.get("artifact") if isinstance(downloads, dict) else None
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

    # Fabric/Quilt shape: just name + base URL.
    if not name:
        return None
    path = _maven_to_artifact_path(name)
    if not path:
        return None
    base = str(lib.get("url") or DEFAULT_MAVEN).rstrip("/")
    # Encode each path segment to handle '+' in versions etc.
    encoded_path = "/".join(
        urllib.parse.quote(seg, safe="+") for seg in path.split("/")
    )
    return (path, f"{base}/{encoded_path}", None, None)


def import_profile(
    *,
    fake_mc_dir: str,
    real_version_dir: str,
    expected_profile_id: Optional[str] = None,
    cancel_check: Optional[Callable[[], None]] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    max_workers: int = 8,
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

    # Resolve each library to an artifact path + URL, dedup by store path.
    plan: Dict[str, Tuple[str, Optional[str], Optional[int]]] = {}
    skipped: List[str] = []
    for lib in libraries:
        if not isinstance(lib, dict):
            continue
        resolved = _resolve_artifact(lib)
        if resolved is None:
            skipped.append(str(lib.get("name") or lib))
            continue
        artifact_path, url, sha1, size = resolved
        plan.setdefault(artifact_path, (url, sha1, size))

    if skipped:
        print(colorize_log(
            f"[profile-import] skipped {len(skipped)} unresolved libraries"
        ))

    # Download every needed artifact into the canonical store.
    tasks: List[DownloadTask] = []
    store_paths: Dict[str, str] = {}
    for artifact_path, (url, sha1, size) in plan.items():
        store_dest = store_path_for(artifact_path)
        store_paths[artifact_path] = store_dest
        if os.path.isfile(store_dest) and sha1 is None:
            continue  # cached, no expectation to re-verify
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

    # Hardlink each into the real version dir under libraries/<artifact_path>.
    libs_dir = os.path.join(real_version_dir, "libraries")
    linked = 0
    for artifact_path, store_dest in store_paths.items():
        if not os.path.isfile(store_dest):
            # Some libraries (e.g. Forge installer-only entries) may have no
            # downloadable artifact. Skip silently — they shouldn't be on the
            # client classpath.
            continue
        version_dest = os.path.join(libs_dir, artifact_path.replace("/", os.sep))
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
