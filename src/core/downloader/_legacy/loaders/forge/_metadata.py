from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict

from core.downloader._legacy.progress import _update_progress

from core.downloader._legacy.loaders.forge._context import ForgeContext


def _detect_modlauncher_in_loader(ctx: ForgeContext) -> bool:
    for root, _, files in os.walk(ctx.loader_dest_dir):
        for f in files:
            if f.endswith(".jar") and "modlauncher" in f.lower():
                return True
    return False


def _stage_modlauncher_client_resources(
    ctx: ForgeContext, metadata: Dict[str, Any]
) -> None:
    main_client_jar = os.path.join(ctx.version_dir, "client.jar")
    if not os.path.exists(main_client_jar):
        return

    mc_version_folder = os.path.basename(ctx.version_dir.rstrip(os.sep))
    minecraft_client_dir = os.path.join(
        ctx.loader_dest_dir, "libraries", "net", "minecraft", "client",
        mc_version_folder,
    )
    os.makedirs(minecraft_client_dir, exist_ok=True)
    expected_jar = os.path.join(
        minecraft_client_dir, f"client-{mc_version_folder}-extra.jar"
    )
    if not os.path.exists(expected_jar):
        try:
            shutil.copy2(main_client_jar, expected_jar)
            print(
                "[forge] Created minecraft client resource for ModLauncher: "
                f"{os.path.relpath(expected_jar, ctx.loader_dest_dir)}"
            )
            ctx.files_copied += 1
        except Exception as e:
            print(
                "[forge] Note: Could not create client resource structure: "
                f"{e}"
            )
            print(
                "[forge] (This may be needed for ModLauncher - will attempt "
                "at runtime if needed)"
            )

    try:
        raw_mcp = str(metadata.get("mcp_version") or "").strip()
        if not raw_mcp:
            return
        mcp_only = raw_mcp
        prefix = f"{mc_version_folder}-"
        if mcp_only.startswith(prefix):
            mcp_only = mcp_only[len(prefix):]
        if not mcp_only:
            return
        version_token = f"{mc_version_folder}-{mcp_only}"
        srg_dir = os.path.join(
            ctx.loader_dest_dir, "libraries", "net", "minecraft",
            "client", version_token,
        )
        os.makedirs(srg_dir, exist_ok=True)
        source_jar = (
            expected_jar if os.path.exists(expected_jar) else main_client_jar
        )
        mcp_extra_jar = os.path.join(
            srg_dir, f"client-{version_token}-extra.jar"
        )
        if not os.path.exists(mcp_extra_jar):
            shutil.copy2(source_jar, mcp_extra_jar)
            print(
                "[forge] Staged missing ModLauncher MCP client resource: "
                f"{os.path.relpath(mcp_extra_jar, ctx.loader_dest_dir)}"
            )
        srg_jar = os.path.join(srg_dir, f"client-{version_token}-srg.jar")
        if not os.path.exists(srg_jar):
            shutil.copy2(source_jar, srg_jar)
            print(
                "[forge] Staged missing ModLauncher SRG client resource: "
                f"{os.path.relpath(srg_jar, ctx.loader_dest_dir)}"
            )
    except Exception as e:
        print(
            "[forge] Warning: Could not stage ModLauncher MCP resources: "
            f"{e}"
        )


def write_forge_metadata_and_finalize(ctx: ForgeContext) -> Dict[str, Any]:
    metadata_file = os.path.join(ctx.loader_dest_dir, "forge_metadata.json")
    metadata: Dict[str, Any] = {
        "forge_version": ctx.loader_version,
        "mc_version": ctx.mc_version,
        "installed_jars": ctx.jars_copied,
        "installed_configs": ctx.files_copied,
    }
    try:
        if ctx.profile_data:
            metadata["profile_spec"] = ctx.profile_data.get("spec", 0)
            raw_version = ctx.profile_data.get("version", "")
            if isinstance(raw_version, dict):
                metadata["profile_version"] = raw_version.get("id", "unknown")
            else:
                metadata["profile_version"] = raw_version or "unknown"
            profile_data_section = ctx.profile_data.get("data", {})
            mcp_ver = ""

            raw_mcp = (
                (profile_data_section.get("MCP_VERSION") or {}).get(
                    "client", ""
                )
            )
            if raw_mcp:
                mcp_ver = raw_mcp.strip("'")

            if not mcp_ver:
                raw_srg = (
                    (profile_data_section.get("MC_SRG") or {}).get(
                        "client", ""
                    )
                )
                if raw_srg:
                    inner = raw_srg.strip("[]")
                    srg_parts = inner.split(":")
                    if len(srg_parts) >= 3:
                        mcp_ver = srg_parts[2]

            if not mcp_ver:
                raw_mappings = (
                    (profile_data_section.get("MAPPINGS") or {}).get(
                        "client", ""
                    )
                )
                if raw_mappings:
                    inner = raw_mappings.strip("[]").split("@")[0]
                    map_parts = inner.split(":")
                    if len(map_parts) >= 3:
                        mcp_ver = map_parts[2]

            if mcp_ver:
                metadata["mcp_version"] = mcp_ver
                print(f"[forge] Stored MCP Config version: {mcp_ver}")
            else:
                print(
                    "[forge] Warning: MCP_VERSION not found in "
                    "install_profile.json data section"
                )

        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)
        print("[forge] Created metadata file")
    except Exception as e:
        print(f"[forge] Warning: Could not create metadata file: {e}")

    is_modlauncher = False
    if ctx.loader_version:
        is_modlauncher = _detect_modlauncher_in_loader(ctx)

    if is_modlauncher and ctx.modlauncher_era:
        print(
            "[forge] Detected ModLauncher-based Forge, preparing client "
            "resources..."
        )
        _stage_modlauncher_client_resources(ctx, metadata)

    if ctx.installer_completed_cleanly:
        print(f"[forge] Forge {ctx.loader_version} installed successfully")
    else:
        print(
            f"[forge] Forge {ctx.loader_version} installed with installer "
            "warnings"
        )
    print(f"[forge]   - {ctx.jars_copied} JARs")
    print(f"[forge]   - {ctx.files_copied} configuration/service files")
    print(f"[forge]   - Location: {ctx.loader_dest_dir}")

    final_status_msg = (
        f"Forge installed ({ctx.jars_copied} JARs + configs)"
    )
    if not ctx.installer_completed_cleanly:
        final_status_msg = (
            f"Forge installed with warnings "
            f"({ctx.jars_copied} JARs + configs)"
        )
    _update_progress(
        ctx.version_key, "extracting_loader", 100, final_status_msg
    )

    result: Dict[str, Any] = {
        "ok": True, "loader_version": ctx.loader_version,
    }
    if not ctx.installer_completed_cleanly:
        result["warning"] = "installer-did-not-exit-cleanly"
    return result


__all__ = ["write_forge_metadata_and_finalize"]
