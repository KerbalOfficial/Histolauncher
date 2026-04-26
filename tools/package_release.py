from __future__ import annotations

import argparse
import os
import stat
import tarfile
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = REPO_ROOT / "src"
DEFAULT_DIST_DIR = REPO_ROOT / "dist"


EXCLUDE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

EXCLUDE_SUFFIXES = {
    ".pyc",
    ".pyo",
}

EXECUTABLE_NAMES = {
    "launcher.sh",
    "launcher.pyw",
    "shortcut.sh",
    "shortcut.pyw",
}

REQUIRED_ENTRYPOINTS = (
    "launcher.pyw",
    "launcher.sh",
    "shortcut.pyw",
    "shortcut.sh",
)


def _read_version(source_dir: Path) -> str:
    version_file = source_dir / "version.dat"
    try:
        version = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        version = "dev"
    return version or "dev"


def _iter_release_files(source_dir: Path):
    for root, dirnames, filenames in os.walk(source_dir):
        dirnames[:] = [name for name in dirnames if name not in EXCLUDE_DIRS]
        root_path = Path(root)
        for filename in filenames:
            path = root_path / filename
            if path.suffix in EXCLUDE_SUFFIXES:
                continue
            yield path


def _archive_name(path: Path, source_dir: Path) -> str:
    return path.relative_to(source_dir).as_posix()


def _file_mode(path: Path) -> int:
    if path.name in EXECUTABLE_NAMES or path.suffix == ".sh":
        return 0o755
    return 0o644


def _write_zip(source_dir: Path, output_path: Path) -> None:
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in _iter_release_files(source_dir):
            info = zipfile.ZipInfo(_archive_name(path, source_dir))
            mode = _file_mode(path)
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.date_time = _zip_timestamp(path)
            with path.open("rb") as handle:
                archive.writestr(info, handle.read())


def _zip_timestamp(path: Path) -> tuple[int, int, int, int, int, int]:
    timestamp = path.stat().st_mtime
    try:
        import time

        return time.localtime(timestamp)[:6]
    except Exception:
        return (1980, 1, 1, 0, 0, 0)


def _write_tar(source_dir: Path, output_path: Path) -> None:
    with tarfile.open(output_path, "w:gz") as archive:
        for path in _iter_release_files(source_dir):
            arcname = _archive_name(path, source_dir)
            info = archive.gettarinfo(str(path), arcname=arcname)
            info.mode = _file_mode(path)
            with path.open("rb") as handle:
                archive.addfile(info, handle)


def package_release(source_dir: Path, dist_dir: Path, version: str | None = None) -> list[Path]:
    source_dir = source_dir.resolve()
    dist_dir = dist_dir.resolve()
    version = (version or _read_version(source_dir)).strip() or "dev"
    package_root = f"Histolauncher-{version}"

    missing_entrypoints = [
        filename for filename in REQUIRED_ENTRYPOINTS
        if not (source_dir / filename).is_file()
    ]
    if missing_entrypoints:
        missing = ", ".join(missing_entrypoints)
        raise FileNotFoundError(f"Missing required release entrypoint(s) in {source_dir}: {missing}")

    dist_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dist_dir / f"{package_root}.zip"
    tar_path = dist_dir / f"{package_root}.tar.gz"

    _write_zip(source_dir, zip_path)
    _write_tar(source_dir, tar_path)

    return [zip_path, tar_path]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build Histolauncher release archives while preserving Linux "
            "execute permissions for launcher.sh."
        )
    )
    parser.add_argument("--source", default=str(DEFAULT_SOURCE_DIR), help="Source folder to package")
    parser.add_argument("--dist", default=str(DEFAULT_DIST_DIR), help="Output folder")
    parser.add_argument("--version", default=None, help="Release version override")
    args = parser.parse_args()

    outputs = package_release(
        source_dir=Path(args.source),
        dist_dir=Path(args.dist),
        version=args.version,
    )
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())