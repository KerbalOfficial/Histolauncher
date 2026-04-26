from __future__ import annotations

import json
import os
import shutil
import tempfile
import time

from core.launch.constants import COPIED_SUFFIX
from core.logger import colorize_log
from core.settings import _apply_url_proxy

__all__ = [
    "_build_histolauncher_copied_mod_filename",
    "_cleanup_copied_mods",
    "_cleanup_stale_histolauncher_copied_files",
    "_cleanup_stale_histolauncher_copied_mods",
    "_copy_mods_for_launch",
    "_copy_simple_addons_for_launch",
    "_is_histolauncher_copied_mod_filename",
    "_is_supported_mod_archive",
    "_is_truthy_setting",
    "_iter_proxy_url_candidates",
    "_prepare_modloader_overwrite_layer",
    "_stage_addons_for_launch",
]


def _is_supported_mod_archive(filename: str) -> bool:
    return str(filename or "").lower().endswith((".jar", ".zip"))


def _is_histolauncher_copied_mod_filename(filename: str) -> bool:
    base_name = str(filename or "")
    if not base_name:
        return False
    stem, _ext = os.path.splitext(base_name)
    return stem.endswith(COPIED_SUFFIX)


def _build_histolauncher_copied_mod_filename(filename: str) -> str:
    base_name = str(filename or "")
    if not base_name:
        return ""
    stem, ext = os.path.splitext(base_name)
    if stem.endswith(COPIED_SUFFIX):
        return base_name
    return f"{stem}{COPIED_SUFFIX}{ext}" if ext else f"{base_name}{COPIED_SUFFIX}"


def _cleanup_stale_histolauncher_copied_mods(target_mods_dir: str) -> int:
    if not os.path.isdir(target_mods_dir):
        return 0

    removed_count = 0
    for entry in os.listdir(target_mods_dir):
        if not _is_histolauncher_copied_mod_filename(entry):
            continue

        entry_path = os.path.join(target_mods_dir, entry)
        try:
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path)
            else:
                os.remove(entry_path)
            removed_count += 1
        except Exception as e:
            print(colorize_log(f"[mods] Warning: Failed to remove stale tracked mod {entry}: {e}"))

    return removed_count


def _is_truthy_setting(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _iter_proxy_url_candidates(url: str) -> list:
    raw_url = str(url or "").strip()
    if not raw_url:
        return []

    proxied_url = _apply_url_proxy(raw_url)
    candidates = []
    if proxied_url:
        candidates.append(proxied_url)
    if raw_url not in candidates:
        candidates.append(raw_url)
    return candidates


def _prepare_modloader_overwrite_layer(target_loader: str = "modloader") -> str:
    overlay_dir = ""
    loader_key = str(target_loader or "modloader").strip().lower()
    if not loader_key:
        return ""
    loader_label = loader_key.upper()

    try:
        from core import mod_manager

        mods_storage = mod_manager.get_mods_storage_dir()
        loader_dir = os.path.join(mods_storage, loader_key)
        modpacks_dir = ""
        try:
            modpacks_dir = mod_manager.get_modpacks_storage_dir()
        except Exception:
            modpacks_dir = ""

        has_standalone = os.path.isdir(loader_dir)
        has_modpacks = bool(modpacks_dir) and os.path.isdir(modpacks_dir)
        if not has_standalone and not has_modpacks:
            return ""

        overlay_dir = tempfile.mkdtemp(prefix=f"hl_{loader_key}_overwrite_", suffix=".jar")
        total_files = 0
        applied_mods = 0

        if has_standalone:
            for mod_slug in sorted(os.listdir(loader_dir)):
                mod_dir = os.path.join(loader_dir, mod_slug)
                if not os.path.isdir(mod_dir):
                    continue

                meta_file = os.path.join(mod_dir, "mod_meta.json")
                if not os.path.isfile(meta_file):
                    continue

                try:
                    with open(meta_file, "r", encoding="utf-8") as mf:
                        meta = json.load(mf)
                except Exception:
                    continue

                if meta.get("disabled", False):
                    continue

                active_version = str(meta.get("active_version") or "").strip()
                if not active_version:
                    continue

                version_dir = os.path.join(mod_dir, active_version)
                if not os.path.isdir(version_dir):
                    continue

                version_meta_path = os.path.join(version_dir, "version_meta.json")
                if not os.path.isfile(version_meta_path):
                    continue

                try:
                    with open(version_meta_path, "r", encoding="utf-8") as vf:
                        version_meta = json.load(vf)
                except Exception:
                    version_meta = {}

                if str(version_meta.get("mod_loader") or loader_key).strip().lower() != loader_key:
                    continue
                if not bool(version_meta.get("overwrite_classes", False)):
                    continue

                source_subfolder = str(version_meta.get("source_subfolder") or "")
                file_name = str(version_meta.get("file_name") or "")
                try:
                    extracted_count = mod_manager.extract_mod_archive_subfolder(
                        loader_key,
                        mod_slug,
                        active_version,
                        source_subfolder,
                        overlay_dir,
                        preferred_file_name=file_name,
                    )
                except Exception as e:
                    print(colorize_log(
                        f"[mods] Warning: Could not apply {loader_label} overwrite layer for {mod_slug}: {e}"
                    ))
                    continue

                if extracted_count > 0:
                    total_files += extracted_count
                    applied_mods += 1
                    source_display = source_subfolder or "/ (default)"
                    print(colorize_log(
                        f"[mods] Applied {loader_label} overwrite layer: {mod_slug} "
                        f"({source_display}, {extracted_count} files)"
                    ))
                else:
                    print(colorize_log(
                        f"[mods] Warning: overwrite_classes enabled for {mod_slug}, "
                        "but no files were extracted"
                    ))

        if has_modpacks:
            for pack_slug in sorted(os.listdir(modpacks_dir)):
                pack_dir = os.path.join(modpacks_dir, pack_slug)
                if not os.path.isdir(pack_dir):
                    continue
                pack_data_file = os.path.join(pack_dir, "data.json")
                if not os.path.isfile(pack_data_file):
                    continue
                try:
                    with open(pack_data_file, "r", encoding="utf-8") as pdf:
                        pack_data = json.load(pdf)
                except Exception:
                    continue

                if pack_data.get("disabled", False):
                    continue
                pack_loader = str(pack_data.get("mod_loader") or "").strip().lower()
                if pack_loader != loader_key:
                    continue

                pack_mods = pack_data.get("mods")
                if not isinstance(pack_mods, list):
                    continue

                for pm in pack_mods:
                    if not isinstance(pm, dict):
                        continue
                    if pm.get("disabled", False):
                        continue

                    pm_slug = str(pm.get("mod_slug") or "").strip()
                    pm_ver = str(pm.get("version_label") or "").strip()
                    if not pm_slug or not pm_ver:
                        continue

                    pm_ver_dir = os.path.join(pack_dir, "mods", pm_slug, pm_ver)
                    if not os.path.isdir(pm_ver_dir):
                        continue

                    packed_meta_path = os.path.join(pm_ver_dir, "version_meta.json")
                    packed_meta = {}
                    if os.path.isfile(packed_meta_path):
                        try:
                            with open(packed_meta_path, "r", encoding="utf-8") as vf:
                                packed_meta = json.load(vf) or {}
                        except Exception:
                            packed_meta = {}

                    overwrite_flag = bool(
                        pm.get("overwrite_classes", packed_meta.get("overwrite_classes", False))
                    )
                    if not overwrite_flag:
                        continue

                    source_subfolder = str(
                        pm.get("source_subfolder", packed_meta.get("source_subfolder", "")) or ""
                    )
                    preferred_name = str(packed_meta.get("file_name") or "").strip()

                    archive_path = ""
                    if preferred_name:
                        candidate = os.path.join(pm_ver_dir, preferred_name)
                        if os.path.isfile(candidate):
                            archive_path = candidate
                    if not archive_path:
                        for fn in sorted(os.listdir(pm_ver_dir)):
                            if _is_supported_mod_archive(fn):
                                archive_path = os.path.join(pm_ver_dir, fn)
                                break

                    if not archive_path:
                        print(colorize_log(
                            f"[mods] Warning: overwrite_classes enabled for "
                            f"modpack {pack_slug}/{pm_slug}, but no jar file found"
                        ))
                        continue

                    try:
                        extracted_count = mod_manager.extract_archive_path_subfolder(
                            archive_path, source_subfolder, overlay_dir
                        )
                    except Exception as e:
                        print(colorize_log(
                            f"[mods] Warning: Could not apply {loader_label} overwrite "
                            f"layer for modpack {pack_slug}/{pm_slug}: {e}"
                        ))
                        continue

                    if extracted_count > 0:
                        total_files += extracted_count
                        applied_mods += 1
                        source_display = source_subfolder or "/ (default)"
                        print(colorize_log(
                            f"[mods] Applied {loader_label} overwrite layer (modpack "
                            f"{pack_slug}): {pm_slug} ({source_display}, "
                            f"{extracted_count} files)"
                        ))
                    else:
                        print(colorize_log(
                            f"[mods] Warning: overwrite_classes enabled for modpack "
                            f"{pack_slug}/{pm_slug}, but no files were extracted"
                        ))

        if total_files <= 0:
            shutil.rmtree(overlay_dir, ignore_errors=True)
            return ""

        print(colorize_log(
            f"[mods] Prepared {loader_label} overwrite classpath layer "
            f"({applied_mods} mod(s), {total_files} file(s))"
        ))
        return overlay_dir
    except Exception as e:
        print(colorize_log(f"[mods] Warning: Failed to prepare {loader_label} overwrite layer: {e}"))
        if overlay_dir and os.path.isdir(overlay_dir):
            shutil.rmtree(overlay_dir, ignore_errors=True)
        return ""


def _cleanup_stale_histolauncher_copied_files(target_dir: str, label: str = "addon") -> int:
    if not os.path.isdir(target_dir):
        return 0

    removed_count = 0
    for entry in os.listdir(target_dir):
        if not _is_histolauncher_copied_mod_filename(entry):
            continue

        entry_path = os.path.join(target_dir, entry)
        try:
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path)
            else:
                os.remove(entry_path)
            removed_count += 1
        except Exception as e:
            print(colorize_log(f"[addons] Warning: Failed to remove stale tracked {label} {entry}: {e}"))

    return removed_count


def _copy_simple_addons_for_launch(game_dir, addon_type):
    if not game_dir:
        return []

    target_dirs = {
        "resourcepacks": ("resourcepacks", "texturepacks"),
        "shaderpacks": ("shaderpacks",),
    }
    addon_key = str(addon_type or "").strip().lower()
    target_dir_names = target_dirs.get(addon_key)
    if not target_dir_names:
        return []

    try:
        from core import mod_manager

        storage_dir = mod_manager.get_addon_storage_dir(addon_key)
        if not os.path.isdir(storage_dir):
            return []

        copied_files = []

        prepared_targets = []
        existing_files_by_target = {}

        for target_dir_name in target_dir_names:
            target_dir = os.path.join(game_dir, target_dir_name)
            os.makedirs(target_dir, exist_ok=True)
            prepared_targets.append((target_dir_name, target_dir))

            stale_removed_count = _cleanup_stale_histolauncher_copied_files(target_dir, label=addon_key)
            if stale_removed_count > 0:
                print(colorize_log(
                    f"[addons] Removed {stale_removed_count} stale tracked {addon_key} file(s) before copy ({target_dir_name})"
                ))

            existing_files = set()
            if os.path.isdir(target_dir):
                existing_files = {
                    f.lower() for f in os.listdir(target_dir)
                    if _is_supported_mod_archive(f)
                }
            existing_files_by_target[target_dir_name] = existing_files

        for addon_slug in os.listdir(storage_dir):
            addon_dir = os.path.join(storage_dir, addon_slug)
            if not os.path.isdir(addon_dir):
                continue

            meta_file = os.path.join(addon_dir, "mod_meta.json")
            if not os.path.isfile(meta_file):
                continue

            try:
                with open(meta_file, "r", encoding="utf-8") as mf:
                    meta = json.load(mf)
            except Exception:
                continue

            if meta.get("disabled", False):
                continue

            active_version = str(meta.get("active_version") or "").strip()
            if not active_version:
                continue

            version_dir = os.path.join(addon_dir, active_version)
            if not os.path.isdir(version_dir):
                continue

            for filename in os.listdir(version_dir):
                if not _is_supported_mod_archive(filename):
                    continue

                filename_lower = filename.lower()
                tracked_filename = _build_histolauncher_copied_mod_filename(filename)
                src = os.path.join(version_dir, filename)

                for target_dir_name, target_dir in prepared_targets:
                    existing_files = existing_files_by_target.setdefault(target_dir_name, set())
                    if filename_lower in existing_files:
                        print(colorize_log(f"[addons] Skipping {filename} ({target_dir_name} already exists)"))
                        continue

                    dst = os.path.join(target_dir, tracked_filename)

                    try:
                        shutil.copy2(src, dst)
                        copied_files.append(dst)
                        existing_files.add(filename_lower)
                        print(colorize_log(f"[addons] Copied {addon_key} -> {target_dir_name}: {tracked_filename}"))
                    except Exception as e:
                        print(colorize_log(
                            f"[addons] Warning: Failed to copy {addon_key} file {filename} -> {target_dir_name}: {e}"
                        ))

        try:
            modpacks_dir = mod_manager.get_modpacks_storage_dir()
            if os.path.isdir(modpacks_dir):
                for pack_slug in sorted(os.listdir(modpacks_dir)):
                    pack_dir = os.path.join(modpacks_dir, pack_slug)
                    if not os.path.isdir(pack_dir):
                        continue
                    data_file = os.path.join(pack_dir, "data.json")
                    if not os.path.isfile(data_file):
                        continue
                    try:
                        with open(data_file, "r", encoding="utf-8") as df:
                            pack_data = json.load(df)
                    except Exception:
                        continue
                    if pack_data.get("disabled", False):
                        continue

                    pack_addons = pack_data.get(addon_key)
                    if not isinstance(pack_addons, list):
                        continue

                    for pack_addon in pack_addons:
                        if not isinstance(pack_addon, dict) or pack_addon.get("disabled", False):
                            continue
                        addon_slug = str(
                            pack_addon.get("mod_slug")
                            or pack_addon.get("addon_slug")
                            or ""
                        ).strip()
                        version_label = str(pack_addon.get("version_label") or "").strip()
                        if not addon_slug or not version_label:
                            continue

                        version_dir = os.path.join(pack_dir, addon_key, addon_slug, version_label)
                        if not os.path.isdir(version_dir):
                            continue

                        for filename in os.listdir(version_dir):
                            if not _is_supported_mod_archive(filename):
                                continue

                            filename_lower = filename.lower()
                            tracked_filename = _build_histolauncher_copied_mod_filename(filename)
                            src = os.path.join(version_dir, filename)

                            for target_dir_name, target_dir in prepared_targets:
                                existing_files = existing_files_by_target.setdefault(target_dir_name, set())
                                if filename_lower in existing_files:
                                    continue

                                dst = os.path.join(target_dir, tracked_filename)
                                try:
                                    shutil.copy2(src, dst)
                                    copied_files.append(dst)
                                    existing_files.add(filename_lower)
                                    print(colorize_log(
                                        f"[addons] Copied {addon_key} from modpack {pack_slug} -> "
                                        f"{target_dir_name}: {tracked_filename}"
                                    ))
                                except Exception as e:
                                    print(colorize_log(
                                        f"[addons] Warning: Failed to copy modpack {addon_key} file "
                                        f"{filename} -> {target_dir_name}: {e}"
                                    ))
        except Exception as e:
            print(colorize_log(f"[addons] Error copying modpack {addon_key}: {e}"))

        if copied_files:
            print(colorize_log(f"[addons] Total {addon_key} files copied: {len(copied_files)}"))

        return copied_files
    except Exception as e:
        print(colorize_log(f"[addons] Error copying {addon_key}: {e}"))
        return []


def _stage_addons_for_launch(game_dir, mod_loader):
    copied_files = []

    copied_files.extend(_copy_simple_addons_for_launch(game_dir, "resourcepacks"))
    if mod_loader:
        copied_files.extend(_copy_mods_for_launch(game_dir, mod_loader))
        copied_files.extend(_copy_simple_addons_for_launch(game_dir, "shaderpacks"))

    return copied_files


def _copy_mods_for_launch(game_dir, mod_loader):
    if not game_dir or not mod_loader:
        return []

    try:
        from core import mod_manager

        mods_storage = mod_manager.get_mods_storage_dir()

        target_mods_dir = os.path.join(game_dir, "mods")
        os.makedirs(target_mods_dir, exist_ok=True)

        copied_files = []

        stale_removed_count = _cleanup_stale_histolauncher_copied_mods(target_mods_dir)
        if stale_removed_count > 0:
            print(colorize_log(f"[mods] Removed {stale_removed_count} stale tracked mod(s) before copy"))

        if not os.path.isdir(mods_storage):
            return []

        existing_files = set()
        if os.path.isdir(target_mods_dir):
            existing_files = {
                f.lower() for f in os.listdir(target_mods_dir)
                if _is_supported_mod_archive(f)
            }

        for loader_name in os.listdir(mods_storage):
            loader_dir = os.path.join(mods_storage, loader_name)
            if not os.path.isdir(loader_dir):
                continue

            for mod_slug in os.listdir(loader_dir):
                mod_dir = os.path.join(loader_dir, mod_slug)
                if not os.path.isdir(mod_dir):
                    continue

                meta_file = os.path.join(mod_dir, "mod_meta.json")
                if not os.path.isfile(meta_file):
                    continue

                try:
                    with open(meta_file, "r", encoding="utf-8") as mf:
                        meta = json.load(mf)
                except Exception:
                    continue

                if meta.get("disabled", False):
                    print(colorize_log(f"[mods] Skipping disabled mod: {mod_slug}"))
                    continue

                active_version = meta.get("active_version")
                if not active_version:
                    continue

                version_dir = os.path.join(mod_dir, active_version)
                if not os.path.isdir(version_dir):
                    continue

                ver_meta_file = os.path.join(version_dir, "version_meta.json")
                overwrite_classes_enabled = False
                if os.path.isfile(ver_meta_file):
                    try:
                        with open(ver_meta_file, "r", encoding="utf-8") as vf:
                            ver_meta = json.load(vf)
                        if ver_meta.get("mod_loader", "").lower() != mod_loader.lower():
                            print(colorize_log(
                                f"[mods] Skipping {mod_slug} v{active_version} "
                                f"(loader mismatch: {ver_meta.get('mod_loader')} != {mod_loader})"
                            ))
                            continue
                        overwrite_classes_enabled = bool(ver_meta.get("overwrite_classes", False))
                    except Exception:
                        pass

                if overwrite_classes_enabled:
                    print(colorize_log(
                        f"[mods] Skipping {mod_slug} v{active_version} in mods/ staging (overwrite_classes enabled)"
                    ))
                    continue

                for filename in os.listdir(version_dir):
                    if not _is_supported_mod_archive(filename):
                        continue

                    if filename.lower() in existing_files:
                        print(colorize_log(f"[mods] Skipping {filename} (already exists)"))
                        continue

                    tracked_filename = _build_histolauncher_copied_mod_filename(filename)

                    src = os.path.join(version_dir, filename)
                    dst = os.path.join(target_mods_dir, tracked_filename)

                    try:
                        shutil.copy2(src, dst)
                        copied_files.append(dst)
                        existing_files.add(filename.lower())
                        print(colorize_log(f"[mods] Copied: {tracked_filename}"))
                    except Exception as e:
                        print(colorize_log(f"[mods] Warning: Failed to copy {filename}: {e}"))

        if copied_files:
            print(colorize_log(f"[mods] Total mods copied: {len(copied_files)}"))

        try:
            modpacks_dir = mod_manager.get_modpacks_storage_dir()
            if os.path.isdir(modpacks_dir):
                for pack_slug in os.listdir(modpacks_dir):
                    pack_dir = os.path.join(modpacks_dir, pack_slug)
                    if not os.path.isdir(pack_dir):
                        continue
                    data_file = os.path.join(pack_dir, "data.json")
                    if not os.path.isfile(data_file):
                        continue
                    try:
                        with open(data_file, "r", encoding="utf-8") as df:
                            pack_data = json.load(df)
                    except Exception:
                        continue
                    if pack_data.get("disabled", False):
                        print(colorize_log(f"[mods] Skipping disabled modpack: {pack_slug}"))
                        continue
                    pack_loader = (pack_data.get("mod_loader") or "").lower()
                    if pack_loader != mod_loader.lower():
                        print(colorize_log(
                            f"[mods] Skipping modpack {pack_slug} (loader mismatch: {pack_loader} != {mod_loader})"
                        ))
                        continue

                    pack_mod_entries = pack_data.get("mods") if isinstance(pack_data.get("mods"), list) else []

                    for pm in pack_mod_entries:
                        if not isinstance(pm, dict):
                            continue
                        if pm.get("disabled", False):
                            continue

                        pm_slug = str(pm.get("mod_slug") or "").strip()
                        ver_name = str(pm.get("version_label") or "").strip()
                        if not pm_slug:
                            continue

                        # Skip mods marked for overwrite-classpath staging — the
                        # _prepare_modloader_overwrite_layer pass handles them.
                        pm_overwrite = bool(pm.get("overwrite_classes", False))
                        if not pm_overwrite and ver_name:
                            packed_meta_check = os.path.join(
                                pack_dir, "mods", pm_slug, ver_name, "version_meta.json"
                            )
                            if os.path.isfile(packed_meta_check):
                                try:
                                    with open(packed_meta_check, "r", encoding="utf-8") as pmf:
                                        pm_overwrite = bool(
                                            (json.load(pmf) or {}).get("overwrite_classes", False)
                                        )
                                except Exception:
                                    pm_overwrite = False
                        if pm_overwrite:
                            print(colorize_log(
                                f"[mods] Skipping modpack mod {pack_slug}/{pm_slug} "
                                "in mods/ staging (overwrite_classes enabled)"
                            ))
                            continue

                        ver_candidates = []
                        if ver_name:
                            ver_candidates.append(os.path.join(pack_dir, "mods", pm_slug, ver_name))
                            ver_candidates.append(os.path.join(pack_dir, "mods", pack_loader, pm_slug, ver_name))

                        if not ver_candidates:
                            base_new = os.path.join(pack_dir, "mods", pm_slug)
                            if os.path.isdir(base_new):
                                ver_candidates.extend(
                                    [
                                        os.path.join(base_new, d)
                                        for d in os.listdir(base_new)
                                        if os.path.isdir(os.path.join(base_new, d))
                                    ]
                                )
                            base_old = os.path.join(pack_dir, "mods", pack_loader, pm_slug)
                            if os.path.isdir(base_old):
                                ver_candidates.extend(
                                    [
                                        os.path.join(base_old, d)
                                        for d in os.listdir(base_old)
                                        if os.path.isdir(os.path.join(base_old, d))
                                    ]
                                )

                        for ver_dir in ver_candidates:
                            if not os.path.isdir(ver_dir):
                                continue
                            for filename in os.listdir(ver_dir):
                                if not _is_supported_mod_archive(filename):
                                    continue
                                if filename.lower() in existing_files:
                                    continue
                                tracked_filename = _build_histolauncher_copied_mod_filename(filename)
                                src = os.path.join(ver_dir, filename)
                                dst = os.path.join(target_mods_dir, tracked_filename)
                                try:
                                    shutil.copy2(src, dst)
                                    copied_files.append(dst)
                                    existing_files.add(filename.lower())
                                    print(colorize_log(f"[mods] Copied (modpack {pack_slug}): {tracked_filename}"))
                                except Exception as e:
                                    print(colorize_log(
                                        f"[mods] Warning: Failed to copy modpack file {filename}: {e}"
                                    ))

                    if not pack_mod_entries:
                        pack_mods_dir = os.path.join(pack_dir, "mods", pack_loader)
                        if os.path.isdir(pack_mods_dir):
                            for pm_slug in os.listdir(pack_mods_dir):
                                pm_dir = os.path.join(pack_mods_dir, pm_slug)
                                if not os.path.isdir(pm_dir):
                                    continue
                                for ver_name in os.listdir(pm_dir):
                                    ver_dir = os.path.join(pm_dir, ver_name)
                                    if not os.path.isdir(ver_dir):
                                        continue
                                    for filename in os.listdir(ver_dir):
                                        if not _is_supported_mod_archive(filename):
                                            continue
                                        if filename.lower() in existing_files:
                                            continue
                                        tracked_filename = _build_histolauncher_copied_mod_filename(filename)
                                        src = os.path.join(ver_dir, filename)
                                        dst = os.path.join(target_mods_dir, tracked_filename)
                                        try:
                                            shutil.copy2(src, dst)
                                            copied_files.append(dst)
                                            existing_files.add(filename.lower())
                                            print(colorize_log(
                                                f"[mods] Copied (legacy modpack {pack_slug}): {tracked_filename}"
                                            ))
                                        except Exception as e:
                                            print(colorize_log(
                                                f"[mods] Warning: Failed to copy legacy modpack file {filename}: {e}"
                                            ))
        except Exception as e:
            print(colorize_log(f"[mods] Error copying modpack mods: {e}"))

        if copied_files:
            print(colorize_log(f"[mods] Total files copied (mods + modpacks): {len(copied_files)}"))

        return copied_files
    except Exception as e:
        print(colorize_log(f"[mods] Error copying mods: {e}"))
        return []


def _cleanup_copied_mods(copied_files):
    if not copied_files:
        return

    try:
        MAX_ATTEMPTS = 10
        RETRY_DELAY = 2  # seconds

        remaining = [
            p for p in copied_files
            if os.path.isfile(p) or os.path.isdir(p)
        ]
        removed_count = 0

        for attempt in range(1, MAX_ATTEMPTS + 1):
            if not remaining:
                break

            still_locked = []
            for file_path in remaining:
                try:
                    if os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                    else:
                        os.remove(file_path)
                    removed_count += 1
                except Exception as e:
                    still_locked.append(file_path)
                    if attempt == 1:
                        print(colorize_log(
                            f"[addons] File locked, will retry: {os.path.basename(file_path)} ({e})"
                        ))

            remaining = still_locked

            if remaining and attempt < MAX_ATTEMPTS:
                print(colorize_log(
                    f"[addons] {len(remaining)} addon file(s) still locked, "
                    f"retrying in {RETRY_DELAY}s (attempt {attempt}/{MAX_ATTEMPTS})..."
                ))
                time.sleep(RETRY_DELAY)

        if removed_count > 0:
            print(colorize_log(f"[addons] Cleaned up {removed_count} copied addon file(s)"))

        if remaining:
            print(colorize_log(
                f"[addons] Warning: {len(remaining)} addon file(s) could not be removed after {MAX_ATTEMPTS} attempts:"
            ))
            for p in remaining:
                print(colorize_log(f"[addons]   - {p}"))
    except Exception as e:
        print(colorize_log(f"[addons] Error during cleanup: {e}"))
