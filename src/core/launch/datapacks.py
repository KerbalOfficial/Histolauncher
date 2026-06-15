from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time

from core.launch.mods import _is_supported_mod_archive
from core.logger import safe_print
from core.mod_manager.datapacks import (
    _build_datapack_deployed_filename,
    get_datapack_source_path,
    sync_datapack_deployments_at_launch,
)

__all__ = [
    'stage_datapack_deployments_for_launch',
    'start_world_creation_datapack_watcher',
]

_MCWORLD_PREFIX = 'mcworld-'
_POLL_INTERVAL_S = 0.75


def _temp_dirs_to_watch() -> list[str]:
    dirs = []
    seen = set()
    for candidate in (
        tempfile.gettempdir(),
        os.environ.get('TEMP', ''),
        os.environ.get('TMP', ''),
        os.environ.get('TMPDIR', ''),
    ):
        normalized = os.path.normcase(os.path.normpath(str(candidate or '').strip()))
        if not normalized or not os.path.isdir(normalized):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        dirs.append(normalized)
    return dirs


def _iter_enabled_datapack_sources():
    try:
        from core import mod_manager
        storage_dir = mod_manager.get_addon_storage_dir('datapacks')
    except Exception:
        return
    if not os.path.isdir(storage_dir):
        return
    for mod_slug in sorted(os.listdir(storage_dir)):
        addon_dir = os.path.join(storage_dir, mod_slug)
        if not os.path.isdir(addon_dir):
            continue
        meta_file = os.path.join(addon_dir, 'mod_meta.json')
        if not os.path.isfile(meta_file):
            continue
        try:
            with open(meta_file, 'r', encoding='utf-8') as handle:
                meta = json.load(handle)
        except Exception:
            continue
        if meta.get('disabled', False):
            continue
        source_path = get_datapack_source_path(mod_slug)
        if source_path and os.path.isfile(source_path):
            yield source_path
    try:
        modpacks_dir = mod_manager.get_modpacks_storage_dir()
    except Exception:
        return
    if not modpacks_dir or not os.path.isdir(modpacks_dir):
        return
    for pack_slug in sorted(os.listdir(modpacks_dir)):
        pack_dir = os.path.join(modpacks_dir, pack_slug)
        if not os.path.isdir(pack_dir):
            continue
        data_file = os.path.join(pack_dir, 'data.json')
        if not os.path.isfile(data_file):
            continue
        try:
            with open(data_file, 'r', encoding='utf-8') as handle:
                pack_data = json.load(handle)
        except Exception:
            continue
        if pack_data.get('disabled', False):
            continue
        pack_addons = pack_data.get('datapacks')
        if not isinstance(pack_addons, list):
            continue
        for pack_addon in pack_addons:
            if not isinstance(pack_addon, dict) or pack_addon.get('disabled', False):
                continue
            addon_slug = str(pack_addon.get('mod_slug') or pack_addon.get('addon_slug') or '').strip()
            version_label = str(pack_addon.get('version_label') or '').strip()
            if not addon_slug or not version_label:
                continue
            version_dir = os.path.join(pack_dir, 'datapacks', addon_slug, version_label)
            if not os.path.isdir(version_dir):
                continue
            preferred_file_name = ''
            version_meta_file = os.path.join(version_dir, 'version_meta.json')
            if os.path.isfile(version_meta_file):
                try:
                    with open(version_meta_file, 'r', encoding='utf-8') as handle:
                        version_meta = json.load(handle)
                    if isinstance(version_meta, dict):
                        preferred_file_name = str(version_meta.get('file_name') or '').strip()
                except Exception:
                    preferred_file_name = ''
            archive_path = ''
            if preferred_file_name:
                candidate = os.path.join(version_dir, preferred_file_name)
                if os.path.isfile(candidate):
                    archive_path = candidate
            if not archive_path:
                for filename in sorted(os.listdir(version_dir)):
                    if not _is_supported_mod_archive(filename):
                        continue
                    archive_path = os.path.join(version_dir, filename)
                    break
            if archive_path and os.path.isfile(archive_path):
                yield archive_path


def _has_enabled_datapacks() -> bool:
    for _source_path in _iter_enabled_datapack_sources():
        return True
    return False


def _copy_enabled_datapacks_to_dir(datapacks_dir: str, copied_names: set[str]) -> int:
    copied_count = 0
    for source_path in _iter_enabled_datapack_sources():
        source_name = os.path.basename(source_path)
        tracked_filename = _build_datapack_deployed_filename(source_name)
        if not tracked_filename:
            continue
        tracked_key = tracked_filename.lower()
        if tracked_key in copied_names:
            continue
        destination_path = os.path.join(datapacks_dir, tracked_filename)
        try:
            shutil.copy2(source_path, destination_path)
            copied_names.add(tracked_key)
            copied_count += 1
            safe_print(f'[addons] Staged for world creation: {tracked_filename}')
        except Exception as exc:
            safe_print(f'[addons] Warning: Failed to stage {source_name} for world creation: {exc}')
    return copied_count


def _world_creation_datapack_watcher_thread(process) -> None:
    temp_dirs = _temp_dirs_to_watch()
    if not temp_dirs:
        return
    seen_mcworld_dirs = set()
    copied_names_by_dir = {}
    while process.poll() is None:
        for temp_root in temp_dirs:
            try:
                entries = os.listdir(temp_root)
            except Exception:
                continue
            for entry in entries:
                if not entry.startswith(_MCWORLD_PREFIX):
                    continue
                mcworld_dir = os.path.join(temp_root, entry)
                if not os.path.isdir(mcworld_dir):
                    continue
                normalized_dir = os.path.normcase(os.path.normpath(mcworld_dir))
                if normalized_dir not in seen_mcworld_dirs:
                    seen_mcworld_dirs.add(normalized_dir)
                    safe_print(f'[addons] Detected world-creation temp folder: {mcworld_dir}')
                copied_names = copied_names_by_dir.setdefault(normalized_dir, set())
                _copy_enabled_datapacks_to_dir(mcworld_dir, copied_names)
        time.sleep(_POLL_INTERVAL_S)


def stage_datapack_deployments_for_launch(game_dir: str) -> int:
    return sync_datapack_deployments_at_launch(game_dir)


def start_world_creation_datapack_watcher(process) -> None:
    if process is None:
        return
    if not _has_enabled_datapacks():
        return
    thread = threading.Thread(target=_world_creation_datapack_watcher_thread, args=(process,), daemon=True, name='hl-datapack-world-creation-watcher')
    thread.start()
    safe_print('[addons] Watching temp folders for world-creation datapack staging')
