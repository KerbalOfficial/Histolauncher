from __future__ import annotations

import tempfile
import traceback
from typing import Any, Dict

from core.downloader._legacy._state import STATE

from core.downloader._legacy.loaders.forge._context import ForgeContext
from core.downloader._legacy.loaders.forge._download import (
    copy_extracted_configs,
    download_forge_artifact,
    extract_forge_artifact,
    extract_pre_staged_libraries,
    parse_install_profile_and_save_metadata,
)
from core.downloader._legacy.loaders.forge._finalize import (
    extract_bootstrap_configs,
    extract_service_providers,
    patch_or_create_log4j_config,
)
from core.downloader._legacy.loaders.forge._legacy_installer import (
    run_legacy_installer_if_needed,
)
from core.downloader._legacy.loaders.forge._metadata import (
    write_forge_metadata_and_finalize,
)
from core.downloader._legacy.loaders.forge._metadata_libs import (
    download_metadata_libraries,
)
from core.downloader._legacy.loaders.forge._modern_installer import (
    is_new_format_installer,
    prepare_fake_minecraft_dir,
    run_modern_installer,
    seed_processor_artifacts_for_offline,
)
from core.downloader._legacy.loaders.forge._recovery import (
    copy_root_jars,
    download_manifest_libraries,
    download_modlauncher_fallback,
    recover_legacy_fml,
    recover_nested_legacy_jars,
    stage_legacy_universal_archive,
    verify_runtime_jars_present,
)


def _install_forge_loader(
    mc_version: str, loader_version: str, loaders_dir: str, version_key: str
) -> Dict[str, Any]:
    STATE.cancel_flags.pop(version_key, None)

    ctx = ForgeContext(
        mc_version=mc_version,
        loader_version=loader_version,
        loaders_dir=loaders_dir,
        version_key=version_key,
    )
    ctx.init_paths()

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            ctx.temp_dir = temp_dir

            err = download_forge_artifact(ctx)
            if err is not None:
                return {"ok": False, "error": err}

            err = extract_forge_artifact(ctx)
            if err is not None:
                return {"ok": False, "error": err}

            parse_install_profile_and_save_metadata(ctx)
            copy_extracted_configs(ctx)
            extract_pre_staged_libraries(ctx)

            err = download_metadata_libraries(ctx)
            if err is not None:
                return {"ok": False, "error": err}

            if is_new_format_installer(ctx):
                print(
                    "[forge] Detected new-format installer (1.13+), running "
                    "installer to apply binary patches..."
                )
                prepare_fake_minecraft_dir(ctx)
                seed_processor_artifacts_for_offline(ctx)
                run_modern_installer(ctx)
            else:
                run_legacy_installer_if_needed(ctx)

            copy_root_jars(ctx)
            recover_nested_legacy_jars(ctx)
            stage_legacy_universal_archive(ctx)
            recover_legacy_fml(ctx)
            download_modlauncher_fallback(ctx)
            download_manifest_libraries(ctx)

            err = verify_runtime_jars_present(ctx)
            if err is not None:
                return {"ok": False, "error": err}

            extract_service_providers(ctx)
            extract_bootstrap_configs(ctx)
            patch_or_create_log4j_config(ctx)

            return write_forge_metadata_and_finalize(ctx)

    except Exception as e:
        print(f"[forge] Error: {e}")
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


__all__ = ["_install_forge_loader"]
