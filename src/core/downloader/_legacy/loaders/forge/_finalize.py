from __future__ import annotations

import os
import zipfile

from core.downloader._legacy.loaders.forge._const import (
    FALLBACK_LOG4J_XML,
    LOG4J_INCOMPATIBLE_MARKERS,
)
from core.downloader._legacy.loaders.forge._context import ForgeContext


def extract_service_providers(ctx: ForgeContext) -> None:
    print("[forge] Extracting service providers from Forge JARs...")
    services_dest = os.path.join(ctx.loader_dest_dir, "META-INF", "services")
    os.makedirs(services_dest, exist_ok=True)

    services_copied = 0
    try:
        jar_files = [
            f for f in os.listdir(ctx.loader_dest_dir) if f.endswith(".jar")
        ]
        print(
            f"[forge] Found {len(jar_files)} JARs to scan for service providers"
        )
        for jar_filename in sorted(jar_files):
            jar_path = os.path.join(ctx.loader_dest_dir, jar_filename)
            try:
                with zipfile.ZipFile(jar_path, "r") as jar:
                    for name in jar.namelist():
                        if name.startswith("META-INF/services/"):
                            service_name = os.path.basename(name)
                            if service_name:
                                service_file = os.path.join(
                                    services_dest, service_name
                                )
                                if not os.path.exists(service_file):
                                    content = jar.read(name)
                                    with open(service_file, "wb") as f:
                                        f.write(content)
                                    services_copied += 1
                                    print(
                                        "[forge] Extracted service from "
                                        f"{jar_filename}: {service_name}"
                                    )
            except Exception:
                pass

        if services_copied > 0:
            print(
                f"[forge] Total: {services_copied} service provider files "
                "extracted"
            )
        else:
            print(
                "[forge] Note: No service providers found in JARs (they may "
                "still be discoverable)"
            )
    except Exception as e:
        print(f"[forge] Warning: Error extracting service providers: {e}")


def extract_bootstrap_configs(ctx: ForgeContext) -> None:
    print("[forge] Extracting bootstrap configuration files...")
    bootstrap_extracted = False
    try:
        if not ctx.is_installer_archive:
            raise RuntimeError(
                "bootstrap extraction skipped for non-installer Forge artifact"
            )

        with zipfile.ZipFile(ctx.downloaded_artifact_path, "r") as jar:
            all_entries = jar.namelist()
            for entry in all_entries:
                if (
                    entry.lower().endswith("bootstrap-shim.list")
                    or entry.lower().endswith(".shim")
                    or (
                        entry.lower().startswith("bootstrap")
                        and entry.lower().endswith(".list")
                    )
                ):
                    try:
                        content = jar.read(entry)
                        basename = os.path.basename(entry)
                        dst_path = os.path.join(ctx.loader_dest_dir, basename)
                        with open(dst_path, "wb") as f:
                            f.write(content)
                        print(
                            "[forge] Extracted critical bootstrap file: "
                            f"{basename}"
                        )
                        bootstrap_extracted = True
                    except Exception as e:
                        print(
                            f"[forge] Warning: Could not extract {entry}: {e}"
                        )

                elif entry.startswith("META-INF/") and (
                    "launcher" in entry.lower()
                    or "modlauncher" in entry.lower()
                    or "bootstrap" in entry.lower()
                    or "fml" in entry.lower()
                ):
                    if not entry.endswith("/"):
                        try:
                            content = jar.read(entry)
                            sub_path = os.path.join(
                                ctx.loader_dest_dir,
                                entry.replace("/", os.sep),
                            )
                            os.makedirs(
                                os.path.dirname(sub_path), exist_ok=True
                            )
                            with open(sub_path, "wb") as f:
                                f.write(content)
                            print(
                                "[forge] Extracted bootstrap config: "
                                f"{os.path.basename(entry)}"
                            )
                        except Exception:
                            pass

        if bootstrap_extracted:
            print("[forge] Bootstrap files extracted successfully")
        else:
            print("[forge] Note: No explicit bootstrap-shim.list found")
            print(
                "[forge] This is normal for Forge 36.x - using extracted "
                "JARs for bootstrap"
            )
    except Exception as e:
        print(f"[forge] Warning: Could not extract bootstrap files: {e}")


def patch_or_create_log4j_config(ctx: ForgeContext) -> None:
    log4j_config_path = os.path.join(ctx.loader_dest_dir, "log4j2.xml")
    if not os.path.exists(log4j_config_path):
        print(
            "[forge] log4j2.xml not found at top level, searching Forge JARs..."
        )
        forge_jars = [
            f for f in os.listdir(ctx.loader_dest_dir) if f.endswith(".jar")
        ]
        for jar_file in sorted(forge_jars):
            jar_path = os.path.join(ctx.loader_dest_dir, jar_file)
            try:
                with zipfile.ZipFile(jar_path, "r") as jar:
                    for config_name in [
                        "log4j2.xml", "log4j.properties", "log4j.xml",
                    ]:
                        for potential_path in [
                            config_name,
                            f"assets/{config_name}",
                            f"META-INF/{config_name}",
                            f"com/mojang/launcher/{config_name}",
                        ]:
                            try:
                                content = jar.read(potential_path)
                                dst_path = os.path.join(
                                    ctx.loader_dest_dir, config_name
                                )
                                with open(dst_path, "wb") as f:
                                    f.write(content)
                                print(
                                    f"[forge] Extracted {config_name} from "
                                    f"{jar_file}"
                                )
                                if os.path.exists(log4j_config_path):
                                    break
                            except KeyError:
                                continue
                        if os.path.exists(log4j_config_path):
                            break
            except Exception:
                continue
            if os.path.exists(log4j_config_path):
                break

    if os.path.exists(log4j_config_path):
        try:
            with open(log4j_config_path, "r") as f:
                log4j_content = f.read()
            has_incompatible = any(
                m in log4j_content for m in LOG4J_INCOMPATIBLE_MARKERS
            )
            if has_incompatible:
                print("[forge] Detected incompatible log4j2.xml components")
                print("[forge] Replacing with compatible fallback...")
                with open(log4j_config_path, "w") as f:
                    f.write(FALLBACK_LOG4J_XML)
                print("[forge] Replaced with compatible log4j2.xml")
        except Exception as e:
            print(f"[forge] Could not check log4j2.xml: {e}")

    if not os.path.exists(log4j_config_path):
        print("[forge] WARNING: log4j2.xml not found in any Forge JAR")
        print("[forge] Creating compatible log4j2.xml configuration...")
        try:
            with open(log4j_config_path, "w") as f:
                f.write(FALLBACK_LOG4J_XML)
            print(
                "[forge] Created compatible log4j2.xml (using standard "
                "appenders)"
            )
            ctx.files_copied += 1
        except Exception as e:
            print(f"[forge] Failed to create log4j2.xml: {e}")


__all__ = [
    "extract_bootstrap_configs",
    "extract_service_providers",
    "patch_or_create_log4j_config",
]
