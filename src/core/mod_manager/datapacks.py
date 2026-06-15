from __future__ import annotations

import json
import os
import shutil
import time

from typing import Any, Dict, List, Optional, Tuple

from core.launch.constants import COPIED_SUFFIX
from core.launch.mods import _is_histolauncher_copied_mod_filename, _is_supported_mod_archive
from core.logger import safe_print
from core.mod_manager._constants import logger
from core.nbt_editor import (
    TAG_END,
    TAG_LIST,
    TAG_STRING,
    compound_child as _compound_child,
    ensure_compound_value as _ensure_compound_value,
    read_nbt_file as _read_level_dat,
    write_nbt_file as _write_level_dat,
)
from core.world_manager._helpers import _data_value_from_root
from core.mod_manager._validation import _is_within_dir, _validate_mod_slug
from core.mod_manager.storage import _resolve_mod_archive_path, get_addon_dir, get_addon_version_dir, get_installed_addons, save_addon_metadata
from core.world_manager.storage import _world_dir, resolve_storage_target


def _datapack_copied_suffix() -> str:
    return COPIED_SUFFIX.replace('§0', '')


def _build_datapack_deployed_filename(filename: str) -> str:
    base_name = str(filename or '')
    if not base_name:
        return ''
    stem, ext = os.path.splitext(base_name)
    suffix = _datapack_copied_suffix()
    if stem.endswith(suffix):
        return base_name
    if ext:
        return f'{stem}{suffix}{ext}'
    return f'{base_name}{suffix}'


def _is_datapack_deployed_filename(filename: str) -> bool:
    stem, _ext = os.path.splitext(str(filename or ''))
    return bool(stem) and stem.endswith(_datapack_copied_suffix())


def _is_launcher_managed_datapack_filename(filename: str) -> bool:
    return _is_datapack_deployed_filename(filename) or _is_histolauncher_copied_mod_filename(filename)


def _datapack_registry_id(deployed_filename: str) -> str:
    stem, _ext = os.path.splitext(str(deployed_filename or '').strip())
    if not stem:
        return ''
    return f'file/{stem}'


def _deployment_registry_id(deployment: Dict[str, Any]) -> str:
    registry_id = str(deployment.get('registry_id') or '').strip()
    if registry_id:
        return registry_id
    return _datapack_registry_id(str(deployment.get('deployed_filename') or '').strip())


def _string_list_items(tag: Any) -> List[str]:
    if not isinstance(tag, dict):
        return []
    try:
        if int(tag.get('type', TAG_END) or TAG_END) != TAG_LIST:
            return []
    except Exception:
        return []
    payload = tag.get('value') or {}
    if not isinstance(payload, dict):
        return []
    try:
        if int(payload.get('list_type', TAG_END) or TAG_END) != TAG_STRING:
            return []
    except Exception:
        return []
    items = []
    for item in payload.get('items') or []:
        text = str(item or '').strip()
        if not text:
            continue
        items.append(text)
    return items


def _set_string_list_tag(compound: Dict[str, Any], key: str, values: List[str]) -> None:
    compound[key] = {
        'type': TAG_LIST,
        'value': {
            'list_type': TAG_STRING,
            'items': [str(value) for value in values],
        },
    }


def _update_level_dat_datapacks(
    level_dat_path: str,
    *,
    enable_ids: Optional[List[str]] = None,
    remove_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    enable_set = {str(entry or '').strip() for entry in enable_ids or [] if str(entry or '').strip()}
    remove_set = {str(entry or '').strip() for entry in remove_ids or [] if str(entry or '').strip()}
    if not enable_set and not remove_set:
        return {'ok': True}
    if not os.path.isfile(level_dat_path):
        return {'ok': False, 'error': 'World is missing level.dat.'}
    root_tag, compression = _read_level_dat(level_dat_path)
    if not root_tag:
        return {'ok': False, 'error': 'Failed to read level.dat.'}
    data_value = _data_value_from_root(root_tag)
    datapacks_config = _ensure_compound_value(data_value, 'DataPacks')
    enabled = _string_list_items(_compound_child(datapacks_config, 'Enabled'))
    disabled = _string_list_items(_compound_child(datapacks_config, 'Disabled'))
    if not enabled:
        enabled = ['vanilla']
    if remove_set:
        enabled = [entry for entry in enabled if entry not in remove_set]
        disabled = [entry for entry in disabled if entry not in remove_set]
    for registry_id in enable_set:
        if registry_id in disabled:
            disabled = [entry for entry in disabled if entry != registry_id]
        if registry_id not in enabled:
            enabled.append(registry_id)
    _set_string_list_tag(datapacks_config, 'Enabled', enabled)
    _set_string_list_tag(datapacks_config, 'Disabled', disabled)
    if not _write_level_dat(level_dat_path, root_tag, compression or 'gzip'):
        return {
            'ok': False,
            'error': 'Failed to update level.dat. Close the world in Minecraft and try again.',
        }
    return {'ok': True, 'enabled': enabled}


def _load_datapack_meta(mod_slug: str) -> Dict[str, Any]:
    mod_dir = get_addon_dir('datapacks', mod_slug)
    meta_file = os.path.join(mod_dir, 'mod_meta.json')
    if not os.path.isfile(meta_file):
        return {}
    try:
        with open(meta_file, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _deployment_matches(
    deployment: Dict[str, Any],
    *,
    storage_target: str,
    world_id: str,
    custom_path: str = '',
) -> bool:
    return (
        str(deployment.get('storage_target') or '').strip() == str(storage_target or '').strip()
        and str(deployment.get('world_id') or '').strip() == str(world_id or '').strip()
        and str(deployment.get('custom_path') or '').strip() == str(custom_path or '').strip()
    )


def get_datapack_source_path(mod_slug: str, version_label: str = '') -> str:
    if not _validate_mod_slug(mod_slug):
        return ''
    meta = _load_datapack_meta(mod_slug)
    active_version = str(version_label or meta.get('active_version') or '').strip()
    if not active_version:
        return ''
    ver_dir = get_addon_version_dir('datapacks', mod_slug, active_version)
    preferred_file_name = ''
    version_meta_file = os.path.join(ver_dir, 'version_meta.json')
    if os.path.isfile(version_meta_file):
        try:
            with open(version_meta_file, 'r', encoding='utf-8') as handle:
                version_meta = json.load(handle)
            if isinstance(version_meta, dict):
                preferred_file_name = str(version_meta.get('file_name') or '').strip()
        except Exception:
            preferred_file_name = ''
    return _resolve_mod_archive_path(ver_dir, preferred_file_name=preferred_file_name)


def list_deployments(mod_slug: str) -> List[Dict[str, Any]]:
    if not _validate_mod_slug(mod_slug):
        return []
    meta = _load_datapack_meta(mod_slug)
    deployments = meta.get('world_deployments')
    if not isinstance(deployments, list):
        return []
    return [entry for entry in deployments if isinstance(entry, dict)]


def list_deployments_for_world(
    storage_target: str,
    world_id: str,
    *,
    custom_path: str = '',
) -> List[Dict[str, Any]]:
    results = []
    for addon in get_installed_addons('datapacks'):
        mod_slug = str(addon.get('mod_slug') or '').strip()
        if not mod_slug:
            continue
        for deployment in list_deployments(mod_slug):
            if not _deployment_matches(
                deployment,
                storage_target=storage_target,
                world_id=world_id,
                custom_path=custom_path,
            ):
                continue
            results.append({
                'mod_slug': mod_slug,
                'mod_name': addon.get('mod_name') or addon.get('name') or mod_slug,
                'version_label': deployment.get('version_label') or addon.get('active_version') or '',
                'deployed_filename': deployment.get('deployed_filename') or '',
                'applied_at': deployment.get('applied_at'),
                'storage_target': deployment.get('storage_target') or storage_target,
                'custom_path': deployment.get('custom_path') or custom_path,
                'world_id': deployment.get('world_id') or world_id,
            })
    return results


def list_world_datapacks(
    storage_target: str,
    world_id: str,
    *,
    custom_path: str = '',
) -> Dict[str, Any]:
    world_dir, resolved = _world_dir(storage_target, world_id, custom_path=custom_path)
    if not resolved.get('ok'):
        return {**resolved, 'datapacks': []}
    if not world_dir or not os.path.isdir(world_dir):
        return {**resolved, 'ok': False, 'error': 'World not found.', 'datapacks': []}
    datapacks_dir = os.path.join(world_dir, 'datapacks')
    tracked_by_filename = {}
    for entry in list_deployments_for_world(storage_target, world_id, custom_path=custom_path):
        deployed_filename = str(entry.get('deployed_filename') or '').strip()
        if not deployed_filename:
            continue
        tracked_by_filename[deployed_filename.lower()] = entry
    entries = []
    if os.path.isdir(datapacks_dir):
        for name in sorted(os.listdir(datapacks_dir), key=lambda value: value.lower()):
            entry_path = os.path.join(datapacks_dir, name)
            if os.path.isdir(entry_path):
                entries.append({
                    'name': name,
                    'kind': 'folder',
                    'tracked': False,
                    'mod_slug': '',
                })
                continue
            if not _is_supported_mod_archive(name):
                continue
            tracked_entry = tracked_by_filename.get(name.lower())
            entries.append({
                'name': name,
                'kind': 'archive',
                'tracked': bool(tracked_entry) or _is_launcher_managed_datapack_filename(name),
                'mod_slug': str((tracked_entry or {}).get('mod_slug') or '').strip(),
                'version_label': str((tracked_entry or {}).get('version_label') or '').strip(),
            })
    return {**resolved, 'ok': True, 'world_id': world_id, 'datapacks': entries}


def apply_datapack_to_world(
    mod_slug: str,
    storage_target: str,
    world_id: str,
    *,
    custom_path: str = '',
    version_label: str = '',
    force_update: bool = False,
) -> Dict[str, Any]:
    if not _validate_mod_slug(mod_slug):
        return {'ok': False, 'error': 'Invalid datapack slug.'}
    world_dir, resolved = _world_dir(storage_target, world_id, custom_path=custom_path)
    if not resolved.get('ok'):
        return resolved
    if not world_dir or not os.path.isdir(world_dir):
        return {'ok': False, 'error': 'World not found.'}
    if not os.path.isfile(os.path.join(world_dir, 'level.dat')):
        return {'ok': False, 'error': 'World is missing level.dat.'}
    meta = _load_datapack_meta(mod_slug)
    if not meta:
        return {'ok': False, 'error': 'Datapack not found in library.'}
    if meta.get('disabled', False):
        return {'ok': False, 'error': 'Datapack is disabled in the library.'}
    active_version = str(version_label or meta.get('active_version') or '').strip()
    if not active_version:
        return {'ok': False, 'error': 'Datapack has no active version.'}
    source_path = get_datapack_source_path(mod_slug, version_label=active_version)
    if not source_path or not os.path.isfile(source_path):
        return {'ok': False, 'error': 'Datapack archive not found.'}
    source_name = os.path.basename(source_path)
    deployed_filename = _build_datapack_deployed_filename(source_name)
    if not deployed_filename:
        return {'ok': False, 'error': 'Invalid datapack archive filename.'}
    registry_id = _datapack_registry_id(deployed_filename)
    if not registry_id:
        return {'ok': False, 'error': 'Invalid datapack registry id.'}
    deployments = list(meta.get('world_deployments') or [])
    existing = next(
        (
            entry
            for entry in deployments
            if isinstance(entry, dict)
            and _deployment_matches(entry, storage_target=storage_target, world_id=world_id, custom_path=custom_path)
        ),
        None,
    )
    if (
        existing
        and not force_update
        and str(existing.get('version_label') or '').strip() == active_version
        and str(existing.get('deployed_filename') or '').strip() == deployed_filename
    ):
        return {
            'ok': True,
            'message': 'Datapack is already scheduled for this world.',
            'deployed_filename': deployed_filename,
            'registry_id': registry_id,
            'already_applied': True,
        }
    deployment_record = {
        'storage_target': str(storage_target or 'default').strip() or 'default',
        'custom_path': str(custom_path or '').strip(),
        'world_id': world_id,
        'deployed_filename': deployed_filename,
        'registry_id': registry_id,
        'version_label': active_version,
        'applied_at': int(time.time()),
    }
    updated_deployments = [
        entry
        for entry in deployments
        if isinstance(entry, dict)
        and not _deployment_matches(entry, storage_target=storage_target, world_id=world_id, custom_path=custom_path)
    ]
    updated_deployments.append(deployment_record)
    meta['world_deployments'] = updated_deployments
    save_addon_metadata('datapacks', mod_slug, meta)
    return {
        'ok': True,
        'message': f"Datapack scheduled for world '{world_id}'. It will deploy on next launch.",
        'deployed_filename': deployed_filename,
        'registry_id': registry_id,
        'version_label': active_version,
        'world_id': world_id,
        'mod_slug': mod_slug,
    }


def apply_datapack_to_worlds(
    mod_slug: str,
    storage_target: str,
    world_ids: List[str],
    *,
    custom_path: str = '',
    version_label: str = '',
) -> Dict[str, Any]:
    if not isinstance(world_ids, list) or not world_ids:
        return {'ok': False, 'error': 'world_ids is required'}
    applied = []
    errors = []
    for world_id in world_ids:
        world_key = str(world_id or '').strip()
        if not world_key:
            continue
        result = apply_datapack_to_world(
            mod_slug,
            storage_target,
            world_key,
            custom_path=custom_path,
            version_label=version_label,
        )
        if result.get('ok'):
            applied.append({
                'world_id': world_key,
                'deployed_filename': result.get('deployed_filename') or '',
                'already_applied': bool(result.get('already_applied')),
            })
        else:
            errors.append({
                'world_id': world_key,
                'error': result.get('error') or 'Failed to apply datapack.',
            })
    if not applied and errors:
        return {'ok': False, 'error': errors[0].get('error') or 'Failed to apply datapack.', 'errors': errors}
    return {
        'ok': True,
        'applied': applied,
        'errors': errors,
        'mod_slug': mod_slug,
    }


def remove_datapack_from_world(
    mod_slug: str,
    storage_target: str,
    world_id: str,
    *,
    custom_path: str = '',
) -> Dict[str, Any]:
    if not _validate_mod_slug(mod_slug):
        return {'ok': False, 'error': 'Invalid datapack slug.'}
    world_dir, resolved = _world_dir(storage_target, world_id, custom_path=custom_path)
    if not resolved.get('ok'):
        return resolved
    if not world_dir or not os.path.isdir(world_dir):
        return {'ok': False, 'error': 'World not found.'}
    meta = _load_datapack_meta(mod_slug)
    if not meta:
        return {'ok': False, 'error': 'Datapack not found in library.'}
    deployments = list(meta.get('world_deployments') or [])
    existing = next(
        (
            entry
            for entry in deployments
            if isinstance(entry, dict)
            and _deployment_matches(entry, storage_target=storage_target, world_id=world_id, custom_path=custom_path)
        ),
        None,
    )
    if not existing:
        return {'ok': False, 'error': 'Datapack is not applied to this world.'}
    meta['world_deployments'] = [
        entry
        for entry in deployments
        if isinstance(entry, dict)
        and not _deployment_matches(entry, storage_target=storage_target, world_id=world_id, custom_path=custom_path)
    ]
    save_addon_metadata('datapacks', mod_slug, meta)
    return {
        'ok': True,
        'message': f"Removed datapack deployment from world '{world_id}'. Changes apply on next launch.",
        'world_id': world_id,
        'mod_slug': mod_slug,
    }


def sync_datapack_deployments_at_launch(game_dir: str) -> int:
    if not game_dir or not os.path.isdir(game_dir):
        return 0
    normalized_game_dir = os.path.normcase(os.path.normpath(game_dir))
    world_plans = {}
    metadata_updates = []
    for addon in get_installed_addons('datapacks'):
        mod_slug = str(addon.get('mod_slug') or '').strip()
        if not mod_slug:
            continue
        meta = _load_datapack_meta(mod_slug)
        if not meta or meta.get('disabled', False):
            continue
        active_version = str(meta.get('active_version') or '').strip()
        if not active_version:
            continue
        source_path = get_datapack_source_path(mod_slug, version_label=active_version)
        if not source_path or not os.path.isfile(source_path):
            continue
        deployed_filename = _build_datapack_deployed_filename(os.path.basename(source_path))
        registry_id = _datapack_registry_id(deployed_filename)
        if not deployed_filename or not registry_id:
            continue
        deployments = list_deployments(mod_slug)
        if not deployments:
            continue
        updated_deployments = list(deployments)
        metadata_changed = False
        for index, deployment in enumerate(updated_deployments):
            world_id = str(deployment.get('world_id') or '').strip()
            if not world_id:
                continue
            storage_target = str(deployment.get('storage_target') or 'default').strip() or 'default'
            custom_path = str(deployment.get('custom_path') or '').strip()
            storage_resolved = resolve_storage_target(storage_target, custom_path=custom_path)
            if not storage_resolved.get('ok'):
                continue
            resolved_game_dir = os.path.normcase(os.path.normpath(str(storage_resolved.get('game_dir') or '')))
            if not resolved_game_dir or resolved_game_dir != normalized_game_dir:
                continue
            world_dir, world_resolved = _world_dir(storage_target, world_id, custom_path=custom_path)
            if not world_resolved.get('ok') or not world_dir:
                continue
            if not os.path.isfile(os.path.join(world_dir, 'level.dat')):
                continue
            world_key = os.path.normcase(os.path.normpath(world_dir))
            plan = world_plans.setdefault(world_key, {
                'world_dir': world_dir,
                'copies': [],
                'expected_filenames': set(),
                'expected_registry_ids': set(),
            })
            plan['copies'].append({
                'source_path': source_path,
                'deployed_filename': deployed_filename,
                'registry_id': registry_id,
                'mod_slug': mod_slug,
            })
            plan['expected_filenames'].add(deployed_filename.lower())
            plan['expected_registry_ids'].add(registry_id)
            if (
                str(deployment.get('deployed_filename') or '').strip() != deployed_filename
                or str(deployment.get('registry_id') or '').strip() != registry_id
                or str(deployment.get('version_label') or '').strip() != active_version
            ):
                updated_deployments[index] = {
                    **deployment,
                    'deployed_filename': deployed_filename,
                    'registry_id': registry_id,
                    'version_label': active_version,
                }
                metadata_changed = True
        if not metadata_changed:
            continue
        metadata_updates.append((mod_slug, {**meta, 'world_deployments': updated_deployments}))
    synced_count = 0
    for plan in world_plans.values():
        world_dir = str(plan.get('world_dir') or '')
        datapacks_dir = os.path.join(world_dir, 'datapacks')
        os.makedirs(datapacks_dir, exist_ok=True)
        stale_registry_ids = []
        if os.path.isdir(datapacks_dir):
            for entry_name in os.listdir(datapacks_dir):
                if not _is_launcher_managed_datapack_filename(entry_name):
                    continue
                if entry_name.lower() in plan['expected_filenames']:
                    continue
                stale_registry_ids.append(_datapack_registry_id(entry_name))
                entry_path = os.path.join(datapacks_dir, entry_name)
                if not _is_within_dir(datapacks_dir, entry_path):
                    continue
                try:
                    os.remove(entry_path)
                    safe_print(f'[addons] Removed stale deployed datapack: {entry_name}')
                except Exception as exc:
                    safe_print(f'[addons] Warning: Failed to remove stale datapack {entry_name}: {exc}')
        for copy_job in plan['copies']:
            destination_path = os.path.join(datapacks_dir, copy_job['deployed_filename'])
            if not _is_within_dir(datapacks_dir, destination_path):
                continue
            try:
                shutil.copy2(copy_job['source_path'], destination_path)
                synced_count += 1
                safe_print(f'[addons] Deployed datapack to {os.path.basename(world_dir)}: {copy_job["deployed_filename"]}')
            except Exception as exc:
                safe_print(f'[addons] Warning: Failed to deploy datapack {copy_job.get("mod_slug")}: {exc}')
        level_dat_path = os.path.join(world_dir, 'level.dat')
        register_result = _update_level_dat_datapacks(
            level_dat_path,
            enable_ids=sorted(plan['expected_registry_ids']),
            remove_ids=stale_registry_ids,
        )
        if register_result.get('ok'):
            continue
        safe_print(f'[addons] Warning: Could not update level.dat for {os.path.basename(world_dir)}: {register_result.get("error") or "unknown error"}')
    for mod_slug, updated_meta in metadata_updates:
        save_addon_metadata('datapacks', mod_slug, updated_meta)
    if synced_count > 0:
        safe_print(f'[addons] Deployed {synced_count} datapack file(s) for this launch')
    return synced_count


def sync_deployments_for_active_version(mod_slug: str) -> Dict[str, Any]:
    deployments = list_deployments(mod_slug)
    if not deployments:
        return {'ok': True, 'synced': [], 'errors': []}
    synced = []
    errors = []
    for deployment in deployments:
        world_id = str(deployment.get('world_id') or '').strip()
        if not world_id:
            continue
        result = apply_datapack_to_world(
            mod_slug,
            str(deployment.get('storage_target') or 'default').strip() or 'default',
            world_id,
            custom_path=str(deployment.get('custom_path') or '').strip(),
            force_update=True,
        )
        if result.get('ok'):
            synced.append(world_id)
        else:
            errors.append({
                'world_id': world_id,
                'error': result.get('error') or 'Failed to sync datapack.',
            })
    return {'ok': not errors or bool(synced), 'synced': synced, 'errors': errors}


__all__ = [
    'apply_datapack_to_world',
    'apply_datapack_to_worlds',
    'get_datapack_source_path',
    'list_deployments',
    'list_deployments_for_world',
    'list_world_datapacks',
    'remove_datapack_from_world',
    'sync_datapack_deployments_at_launch',
    'sync_deployments_for_active_version',
]
