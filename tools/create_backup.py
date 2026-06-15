from __future__ import annotations

import argparse
import os
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = REPO_ROOT / "src"
DEFAULT_BACKUP_DIR = REPO_ROOT / "backup"


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


def _read_version(source_dir: Path) -> str:
    version_file = source_dir / "version.dat"
    try:
        version = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        version = "dev"
    return version or "dev"


def _iter_backup_files(source_dir: Path):
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


def _write_zip(source_dir: Path, output_path: Path, note: str) -> None:
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in _iter_backup_files(source_dir):
            info = zipfile.ZipInfo(_archive_name(path, source_dir))
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.date_time = _zip_timestamp(path)
            with path.open("rb") as handle:
                archive.writestr(info, handle.read())
        archive.writestr("note.txt", note)


def _zip_timestamp(path: Path) -> tuple[int, int, int, int, int, int]:
    timestamp = path.stat().st_mtime
    try:
        import time
        return time.localtime(timestamp)[:6]
    except Exception:
        return (1980, 1, 1, 0, 0, 0)


def create_backup(source_dir: Path, backup_dir: Path, note: str, version: str | None = None) -> Path:
    source_dir = source_dir.resolve()
    backup_dir = backup_dir.resolve()
    version = (version or _read_version(source_dir)).strip() or "dev"

    now = datetime.now()
    timestamp = now.strftime("%m%d%Y-%H%M%S")
    created_at = f"{now.month}/{now.day}/{now.year} {now.strftime('%H:%M')}"
    note_content = f"{note}\n\n------------------------------------------------\nCreated at: {created_at}"

    backup_dir.mkdir(parents=True, exist_ok=True)
    zip_path = backup_dir / f"Histolauncher-{version}-{timestamp}.zip"

    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".zip")
    tmp_path = Path(tmp_name)
    try:
        os.close(tmp_fd)
        _write_zip(source_dir, tmp_path, note_content)
        shutil.move(str(tmp_path), str(zip_path))
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a zip backup snapshot of the Histolauncher src folder."
    )
    parser.add_argument("--source", default=str(DEFAULT_SOURCE_DIR), help="Source folder to back up")
    parser.add_argument("--backup", default=str(DEFAULT_BACKUP_DIR), help="Output folder")
    parser.add_argument("--version", default=None, help="Version label override")
    parser.add_argument("--note", required=True, help="Describe what changed and why this backup was created")
    args = parser.parse_args()

    output = create_backup(
        source_dir=Path(args.source),
        backup_dir=Path(args.backup),
        note=args.note,
        version=args.version,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())