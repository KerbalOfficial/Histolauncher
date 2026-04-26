from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, TypedDict
from urllib.parse import urlsplit

from core.http_client import HttpClient, HttpClientError
from core.subprocess_utils import no_window_kwargs

__all__ = [
    "JAVA_INSTALLABLE_FEATURE_VERSIONS",
    "JavaInstallEnvironment",
    "download_java_installer",
    "get_java_install_environment",
    "get_java_install_options",
    "install_downloaded_java_package",
    "open_java_installer_file",
    "resolve_java_installer_asset",
    "suggest_java_feature_version",
]


ADOPTIUM_API_BASE: Final[str] = "https://api.adoptium.net/v3"
JAVA_INSTALLABLE_FEATURE_VERSIONS: Final[tuple[int, ...]] = (8, 11, 16, 17, 21, 25)


class JavaInstallEnvironment(TypedDict):
    os: str
    architecture: str
    platform: str
    machine: str
    supported: bool
    error: str


@dataclass(frozen=True)
class JavaInstallerAsset:
    requested_feature_version: int
    feature_version: int
    image_type: str
    os: str
    architecture: str
    url: str
    file_name: str
    size: int
    kind: str
    release_name: str


def _normalize_os(system: str | None = None) -> str:
    value = (system or platform.system() or "").strip().lower()
    if value.startswith("win"):
        return "windows"
    if value in {"darwin", "mac", "macos", "osx"}:
        return "mac"
    if value.startswith("linux"):
        return "linux"
    return ""


def _normalize_arch(machine: str | None = None) -> str:
    value = (machine or platform.machine() or "").strip().lower()
    aliases = {
        "amd64": "x64",
        "x86_64": "x64",
        "x64": "x64",
        "i386": "x32",
        "i686": "x32",
        "x86": "x32",
        "arm64": "aarch64",
        "aarch64": "aarch64",
        "armv7l": "arm",
        "armv8l": "arm",
        "ppc64le": "ppc64le",
        "s390x": "s390x",
    }
    return aliases.get(value, "")


def get_java_install_environment() -> JavaInstallEnvironment:
    system = platform.system() or ""
    machine = platform.machine() or ""
    os_name = _normalize_os(system)
    arch = _normalize_arch(machine)

    if not os_name:
        return {
            "os": "",
            "architecture": arch,
            "platform": system,
            "machine": machine,
            "supported": False,
            "error": f"Unsupported operating system: {system or 'unknown'}",
        }
    if not arch:
        return {
            "os": os_name,
            "architecture": "",
            "platform": system,
            "machine": machine,
            "supported": False,
            "error": f"Unsupported CPU architecture: {machine or 'unknown'}",
        }

    return {
        "os": os_name,
        "architecture": arch,
        "platform": system,
        "machine": machine,
        "supported": True,
        "error": "",
    }


def suggest_java_feature_version(required_major: int) -> int:
    try:
        required = int(required_major or 0)
    except (TypeError, ValueError):
        required = 0

    if required <= 0:
        return 21
    for version in JAVA_INSTALLABLE_FEATURE_VERSIONS:
        if version >= required:
            return version
    return required


def get_java_install_options() -> list[dict[str, Any]]:
    descriptions = {
        8: "Minecraft oldest - 1.16.5",
        11: "Compatibility for mods/tools",
        16: "Minecraft 1.17 - 1.17.1",
        17: "Minecraft 1.18 - 1.20.4",
        21: "Minecraft 1.20.5 - 1.21.11",
        25: "Minecraft 26.1 - latest",
    }
    recommended = {8, 25}
    return [
        {
            "version": version,
            "label": f"Java {version}",
            "description": descriptions.get(version, "Temurin Java runtime"),
            "recommended": version in recommended,
        }
        for version in JAVA_INSTALLABLE_FEATURE_VERSIONS
    ]


def _metadata_url(feature_version: int, image_type: str, env: JavaInstallEnvironment) -> str:
    return (
        f"{ADOPTIUM_API_BASE}/assets/latest/{feature_version}/hotspot"
        f"?architecture={env['architecture']}&image_type={image_type}"
        f"&os={env['os']}&vendor=eclipse"
    )


def _safe_file_name(raw_name: str, fallback: str) -> str:
    name = os.path.basename(urlsplit(raw_name or "").path) or raw_name or fallback
    clean = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" ._")
    if not clean:
        return fallback
    return clean[:180]


def _download_entries(asset: dict[str, Any]) -> list[dict[str, Any]]:
    binary = asset.get("binary") if isinstance(asset, dict) else None
    if not isinstance(binary, dict):
        return []

    entries: list[dict[str, Any]] = []
    for kind in ("installer", "package"):
        item = binary.get(kind)
        if not isinstance(item, dict):
            continue
        link = str(item.get("link") or "").strip()
        if not link:
            continue
        entries.append(
            {
                "kind": kind,
                "url": link,
                "name": str(item.get("name") or os.path.basename(urlsplit(link).path)),
                "size": int(item.get("size") or 0),
            }
        )
    return entries


def _extension_rank(os_name: str, kind: str, name: str) -> tuple[int, int]:
    lower = name.lower()
    preferred = {
        "windows": (".msi", ".exe", ".zip"),
        "mac": (".pkg", ".dmg", ".tar.gz", ".zip"),
        "linux": (".tar.gz", ".tgz", ".zip"),
    }.get(os_name, (".zip", ".tar.gz"))

    for idx, suffix in enumerate(preferred):
        if lower.endswith(suffix):
            return (0, idx)
    return (0 if kind == "installer" else 1, len(preferred))


def _select_asset_download(
    assets: Any,
    *,
    requested_feature_version: int,
    feature_version: int,
    image_type: str,
    env: JavaInstallEnvironment,
) -> JavaInstallerAsset | None:
    if not isinstance(assets, list):
        return None

    candidates: list[tuple[tuple[int, int], dict[str, Any], dict[str, Any]]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        for entry in _download_entries(asset):
            rank = _extension_rank(env["os"], str(entry.get("kind") or ""), str(entry.get("name") or ""))
            candidates.append((rank, asset, entry))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    _rank, asset, entry = candidates[0]
    url = str(entry.get("url") or "").strip()
    fallback_name = f"temurin-java-{feature_version}-{env['os']}-{env['architecture']}.bin"
    file_name = _safe_file_name(str(entry.get("name") or url), fallback_name)
    return JavaInstallerAsset(
        requested_feature_version=requested_feature_version,
        feature_version=feature_version,
        image_type=image_type,
        os=env["os"],
        architecture=env["architecture"],
        url=url,
        file_name=file_name,
        size=int(entry.get("size") or 0),
        kind=str(entry.get("kind") or "package"),
        release_name=str(asset.get("release_name") or ""),
    )


def _feature_version_candidates(requested_version: int) -> list[int]:
    suggested = suggest_java_feature_version(requested_version)
    out: list[int] = []
    for version in (requested_version, suggested):
        try:
            value = int(version)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in out:
            out.append(value)
    return out


def resolve_java_installer_asset(feature_version: int) -> JavaInstallerAsset:
    try:
        requested = int(feature_version)
    except (TypeError, ValueError) as exc:
        raise ValueError("Java version must be a number") from exc
    if requested <= 0 or requested > 99:
        raise ValueError("Java version is outside the supported range")

    env = get_java_install_environment()
    if not env["supported"]:
        raise RuntimeError(env["error"] or "This system is not supported")

    client = HttpClient(allow_insecure_fallback=True)
    errors: list[str] = []
    for candidate_version in _feature_version_candidates(requested):
        for image_type in ("jre", "jdk"):
            url = _metadata_url(candidate_version, image_type, env)
            try:
                assets = client.get_json(url)
            except HttpClientError as exc:
                errors.append(f"Java {candidate_version} {image_type}: {exc}")
                continue
            asset = _select_asset_download(
                assets,
                requested_feature_version=requested,
                feature_version=candidate_version,
                image_type=image_type,
                env=env,
            )
            if asset is not None:
                return asset

    detail = "; ".join(errors[-2:]) if errors else "No matching download was returned."
    raise RuntimeError(
        f"No Temurin Java download was found for Java {requested} "
        f"on {env['os']} {env['architecture']}. {detail}"
    )


def _download_directory() -> Path:
    return Path(tempfile.gettempdir()) / "Histolauncher" / "Java"


def _managed_java_directory() -> Path:
    from core.settings import get_base_dir

    return Path(get_base_dir()) / "java"


def _strip_archive_suffix(name: str) -> str:
    lower = name.lower()
    for suffix in (".tar.gz", ".tar.xz", ".tgz", ".zip", ".tar"):
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return os.path.splitext(name)[0]


def _archive_install_dir_name(download_info: dict[str, Any]) -> str:
    raw = _strip_archive_suffix(str(download_info.get("file_name") or ""))
    fallback = (
        f"temurin-java-{download_info.get('feature_version') or 'runtime'}-"
        f"{download_info.get('image_type') or 'jre'}-"
        f"{download_info.get('os') or 'linux'}-"
        f"{download_info.get('architecture') or platform.machine() or 'unknown'}"
    )
    return _safe_file_name(raw, fallback)


def _is_java_archive(path: str) -> bool:
    lower = str(path or "").lower()
    return lower.endswith((".tar.gz", ".tar.xz", ".tgz", ".zip", ".tar"))


def _assert_inside_directory(base_dir: Path, target: Path) -> None:
    base_resolved = base_dir.resolve()
    target_resolved = target.resolve()
    try:
        target_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise RuntimeError(f"Archive contains an unsafe path: {target}") from exc


def _safe_extract_tar(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        for member in members:
            target = destination / member.name
            _assert_inside_directory(destination, target)
            if member.issym() or member.islnk():
                link_name = member.linkname or ""
                if os.path.isabs(link_name):
                    raise RuntimeError(f"Archive contains an unsafe link: {member.name}")
                link_target = (
                    target.parent / link_name
                    if member.issym()
                    else destination / link_name
                )
                _assert_inside_directory(destination, link_target)
        archive.extractall(destination)


def _safe_extract_zip(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            target = destination / info.filename
            _assert_inside_directory(destination, target)
            archive.extract(info, destination)
            mode = (info.external_attr >> 16) & 0o777
            if mode and not info.is_dir():
                try:
                    os.chmod(target, mode)
                except OSError:
                    pass


def _extract_java_archive(archive_path: Path, destination: Path) -> None:
    lower = archive_path.name.lower()
    if lower.endswith(".zip"):
        _safe_extract_zip(archive_path, destination)
        return
    _safe_extract_tar(archive_path, destination)


def _move_extracted_payload(extract_dir: Path, install_dir: Path) -> None:
    children = [child for child in extract_dir.iterdir()]
    if install_dir.exists():
        shutil.rmtree(install_dir)
    install_dir.parent.mkdir(parents=True, exist_ok=True)

    if len(children) == 1 and children[0].is_dir():
        shutil.move(str(children[0]), str(install_dir))
        return

    install_dir.mkdir(parents=True, exist_ok=True)
    for child in children:
        shutil.move(str(child), str(install_dir / child.name))


def _find_java_executable(install_dir: Path, os_name: str) -> Path | None:
    exe_name = "java.exe" if str(os_name or "").lower().startswith("win") else "java"
    preferred = install_dir / "bin" / exe_name
    if preferred.is_file():
        return preferred
    for candidate in install_dir.rglob(exe_name):
        if candidate.is_file() and candidate.parent.name == "bin":
            return candidate
    return None


def install_downloaded_java_package(download_info: dict[str, Any]) -> dict[str, Any]:
    archive_path = Path(str(download_info.get("path") or "")).expanduser()
    if not archive_path.is_file():
        raise RuntimeError("Downloaded Java package was not found.")
    if not _is_java_archive(str(archive_path)):
        raise RuntimeError("Downloaded Java file is not a supported archive package.")

    managed_root = _managed_java_directory()
    managed_root.mkdir(parents=True, exist_ok=True)
    install_dir = managed_root / _archive_install_dir_name(download_info)
    temp_extract_dir = Path(tempfile.mkdtemp(prefix="extract-", dir=str(managed_root)))
    try:
        _extract_java_archive(archive_path, temp_extract_dir)
        _move_extracted_payload(temp_extract_dir, install_dir)
    except Exception:
        try:
            if install_dir.exists():
                shutil.rmtree(install_dir)
        finally:
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
        raise
    else:
        shutil.rmtree(temp_extract_dir, ignore_errors=True)

    package_os = str(download_info.get("os") or platform.system()).lower()
    java_path = _find_java_executable(install_dir, package_os)
    if java_path is None:
        shutil.rmtree(install_dir, ignore_errors=True)
        raise RuntimeError("Installed Java package did not contain a bin/java executable.")
    if not package_os.startswith("win"):
        try:
            java_path.chmod(java_path.stat().st_mode | 0o755)
        except OSError:
            pass

    return {
        "installed": True,
        "install_dir": str(install_dir),
        "runtime_path": str(java_path),
    }


def download_java_installer(feature_version: int) -> dict[str, Any]:
    asset = resolve_java_installer_asset(feature_version)
    dest_dir = _download_directory()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / asset.file_name

    reused = False
    if dest_path.is_file() and dest_path.stat().st_size > 0:
        if asset.size <= 0 or dest_path.stat().st_size == asset.size:
            reused = True

    if not reused:
        HttpClient(allow_insecure_fallback=True).stream_to(asset.url, dest_path)

    data = asdict(asset)
    data.update(
        {
            "path": str(dest_path),
            "reused": reused,
        }
    )
    return data


def open_java_installer_file(path: str) -> tuple[bool, str]:
    target = str(path or "").strip()
    if not target or not os.path.isfile(target):
        return False, "Downloaded Java installer file was not found."

    system = platform.system().lower()
    try:
        if system.startswith("win"):
            startfile = getattr(os, "startfile", None)
            if not callable(startfile):
                return False, "Windows file launcher is not available."
            startfile(target)
            return True, ""
        if system == "darwin":
            subprocess.Popen(
                ["open", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **no_window_kwargs(),
            )
            return True, ""

        opener = shutil.which("xdg-open") or shutil.which("gio")
        if not opener:
            return False, "No file opener was found. Open the downloaded Java file manually."
        command = [opener, "open", target] if os.path.basename(opener) == "gio" else [opener, target]
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **no_window_kwargs(),
        )
        return True, ""
    except Exception as exc:
        return False, str(exc)