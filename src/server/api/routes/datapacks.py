from __future__ import annotations

from typing import Any, List

from core.logger import safe_print
from core.settings import normalize_custom_storage_directory
from server.api._validation import _validate_mod_slug

__all__ = ['api_datapacks_apply', 'api_datapacks_deployments', 'api_datapacks_remove']


def _normalize_world_ids(value: Any) -> List[str]:
    if isinstance(value, str):
        raw_values = [value]
    elif isinstance(value, list):
        raw_values = value
    else:
        raw_values = []
    world_ids = []
    seen = set()
    for entry in raw_values:
        world_id = str(entry or '').strip()
        if not world_id or world_id in seen:
            continue
        seen.add(world_id)
        world_ids.append(world_id)
    return world_ids


def api_datapacks_deployments(data):
    try:
        from core import mod_manager
        payload = data if isinstance(data, dict) else {}
        mod_slug = str(payload.get('mod_slug') or '').strip().lower()
        world_id = str(payload.get('world_id') or '').strip()
        storage_target = str(payload.get('storage_target') or 'default').strip() or 'default'
        custom_path = normalize_custom_storage_directory(payload.get('custom_path') or '')
        if mod_slug:
            if not _validate_mod_slug(mod_slug):
                return {'ok': False, 'error': 'Invalid mod_slug format'}
            deployments = mod_manager.list_deployments(mod_slug)
            mod_name = mod_slug
            for addon in mod_manager.get_installed_addons('datapacks'):
                if str(addon.get('mod_slug') or '').strip().lower() == mod_slug:
                    mod_name = addon.get('mod_name') or addon.get('name') or mod_slug
                    break
            return {
                'ok': True,
                'mod_slug': mod_slug,
                'mod_name': mod_name,
                'deployments': deployments,
            }
        if world_id:
            deployments = mod_manager.list_deployments_for_world(
                storage_target,
                world_id,
                custom_path=custom_path,
            )
            world_datapacks = mod_manager.list_world_datapacks(
                storage_target,
                world_id,
                custom_path=custom_path,
            )
            if not world_datapacks.get('ok'):
                return world_datapacks
            return {
                'ok': True,
                'world_id': world_id,
                'storage_target': storage_target,
                'deployments': deployments,
                'datapacks': world_datapacks.get('datapacks') or [],
            }
        return {'ok': False, 'error': 'mod_slug or world_id is required'}
    except Exception as exc:
        safe_print(f'[api] Failed to list datapack deployments: {exc}')
        return {'ok': False, 'error': str(exc)}


def api_datapacks_apply(data):
    try:
        from core import mod_manager
        payload = data if isinstance(data, dict) else {}
        mod_slug = str(payload.get('mod_slug') or '').strip().lower()
        storage_target = str(payload.get('storage_target') or 'default').strip() or 'default'
        custom_path = normalize_custom_storage_directory(payload.get('custom_path') or '')
        version_label = str(payload.get('version_label') or '').strip()
        world_ids = _normalize_world_ids(payload.get('world_ids') or payload.get('world_id'))
        if not mod_slug:
            return {'ok': False, 'error': 'mod_slug is required'}
        if not _validate_mod_slug(mod_slug):
            return {'ok': False, 'error': 'Invalid mod_slug format'}
        if not world_ids:
            return {'ok': False, 'error': 'world_ids is required'}
        return mod_manager.apply_datapack_to_worlds(
            mod_slug,
            storage_target,
            world_ids,
            custom_path=custom_path,
            version_label=version_label,
        )
    except Exception as exc:
        safe_print(f'[api] Failed to apply datapack: {exc}')
        return {'ok': False, 'error': str(exc)}


def api_datapacks_remove(data):
    try:
        from core import mod_manager
        payload = data if isinstance(data, dict) else {}
        mod_slug = str(payload.get('mod_slug') or '').strip().lower()
        world_id = str(payload.get('world_id') or '').strip()
        storage_target = str(payload.get('storage_target') or 'default').strip() or 'default'
        custom_path = normalize_custom_storage_directory(payload.get('custom_path') or '')
        if not mod_slug:
            return {'ok': False, 'error': 'mod_slug is required'}
        if not world_id:
            return {'ok': False, 'error': 'world_id is required'}
        if not _validate_mod_slug(mod_slug):
            return {'ok': False, 'error': 'Invalid mod_slug format'}
        return mod_manager.remove_datapack_from_world(
            mod_slug,
            storage_target,
            world_id,
            custom_path=custom_path,
        )
    except Exception as exc:
        safe_print(f'[api] Failed to remove datapack from world: {exc}')
        return {'ok': False, 'error': str(exc)}
