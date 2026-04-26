from __future__ import annotations

import os
import shutil
from typing import Dict, List, Optional

from core.downloader._legacy.transport import _download_with_retry

from core.downloader._legacy.loaders.forge._const import (
    MODLAUNCHER_FALLBACK_VERSIONS,
)
from core.downloader._legacy.loaders.forge._context import ForgeContext
from core.downloader._legacy.loaders.forge._jar_inspect import (
    find_runtime_jars,
    gather_manifest_libraries,
    jar_has_class,
    loader_dir_has_class,
)


def copy_root_jars(ctx: ForgeContext) -> None:
    print("[forge] Checking for root-level JARs...")
    for filename in os.listdir(ctx.extraction_dir):
        if not filename.endswith(".jar"):
            continue
        if filename.lower() == "forge-installer.jar":
            print(
                "[forge] Skipping forge-installer.jar (not needed for game "
                "launch)"
            )
            continue
        src_jar = os.path.join(ctx.extraction_dir, filename)
        dst_jar = os.path.join(ctx.loader_dest_dir, filename)
        if not os.path.exists(dst_jar):
            try:
                shutil.copy2(src_jar, dst_jar)
                ctx.jars_copied += 1
                print(f"[forge] Copied root JAR: {filename}")
            except Exception as e:
                print(f"[forge] Failed to copy {filename}: {e}")


def _has_forge_core_jar(loader_dest_dir: str) -> bool:
    return any(
        n.endswith(".jar")
        and (n.startswith("forge-") or n.startswith("minecraftforge-"))
        for n in os.listdir(loader_dest_dir)
    )


def recover_nested_legacy_jars(ctx: ForgeContext) -> None:
    if _has_forge_core_jar(ctx.loader_dest_dir):
        return
    recovered = 0
    for root, _, files in os.walk(ctx.extraction_dir):
        for filename in files:
            if not filename.endswith(".jar"):
                continue
            lower_name = filename.lower()
            if lower_name == "forge-installer.jar":
                continue
            is_legacy_core = (
                lower_name.startswith("forge-")
                or lower_name.startswith("minecraftforge-")
                or "universal" in lower_name
            )
            if not is_legacy_core:
                continue
            src_jar = os.path.join(root, filename)
            dst_jar = os.path.join(ctx.loader_dest_dir, filename)
            if os.path.exists(dst_jar):
                continue
            try:
                shutil.copy2(src_jar, dst_jar)
                ctx.jars_copied += 1
                recovered += 1
                print(
                    "[forge] Recovered legacy core JAR from nested path: "
                    f"{filename}"
                )
            except Exception as e:
                print(
                    f"[forge] Failed recovering nested JAR {filename}: {e}"
                )
    if recovered > 0:
        print(
            f"[forge] Recovered {recovered} nested legacy Forge core JAR(s)"
        )


def stage_legacy_universal_archive(ctx: ForgeContext) -> None:
    if _has_forge_core_jar(ctx.loader_dest_dir):
        return
    if not ctx.is_legacy_universal_archive:
        return
    staged_name = ctx.downloaded_artifact_name
    if staged_name.lower().endswith(".zip"):
        staged_name = staged_name[:-4] + ".jar"
    staged_path = os.path.join(ctx.loader_dest_dir, staged_name)
    try:
        shutil.copy2(ctx.downloaded_artifact_path, staged_path)
        ctx.jars_copied += 1
        print(
            "[forge] Staged legacy universal archive as runtime JAR: "
            f"{staged_name}"
        )
    except Exception as e:
        print(f"[forge] Failed to stage legacy universal archive as JAR: {e}")


def recover_legacy_fml(ctx: ForgeContext) -> None:
    if ctx.modlauncher_era:
        return
    if loader_dir_has_class(
        ctx.loader_dest_dir, "cpw/mods/fml/common/launcher/FMLTweaker.class"
    ):
        return

    props_path = os.path.join(ctx.loader_dest_dir, "fmlversion.properties")
    if not os.path.exists(props_path):
        props_path = os.path.join(ctx.extraction_dir, "fmlversion.properties")

    props: Dict[str, str] = {}
    if os.path.exists(props_path):
        try:
            with open(
                props_path, "r", encoding="utf-8", errors="replace"
            ) as pf:
                for line in pf:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    props[k.strip()] = v.strip()
        except Exception as e:
            print(
                f"[forge] Warning: Could not parse fmlversion.properties: {e}"
            )

    fml_mc = props.get("fmlbuild.mcversion", ctx.mc_version).strip()
    fml_major = props.get("fmlbuild.major.number", "").strip()
    fml_minor = props.get("fmlbuild.minor.number", "").strip()
    fml_revision = props.get("fmlbuild.revision.number", "").strip()
    fml_build = props.get("fmlbuild.build.number", "").strip()

    if all([fml_mc, fml_major, fml_minor, fml_revision, fml_build]):
        fml_numeric = f"{fml_major}.{fml_minor}.{fml_revision}.{fml_build}"
        fml_coord = f"{fml_mc}-{fml_numeric}"
        fml_zip_url = (
            f"https://maven.minecraftforge.net/net/minecraftforge/fml/"
            f"{fml_coord}/fml-{fml_coord}-universal.zip"
        )
        fml_dest_name = f"fml-{fml_coord}-universal.jar"
        fml_dest_path = os.path.join(ctx.loader_dest_dir, fml_dest_name)

        if not os.path.exists(fml_dest_path):
            fml_tmp_path = os.path.join(
                ctx.temp_dir, f"fml-{fml_coord}-universal.zip"
            )
            try:
                print(
                    f"[forge] Downloading legacy FML artifact: {fml_zip_url}"
                )
                _download_with_retry(fml_zip_url, fml_tmp_path)
                shutil.copy2(fml_tmp_path, fml_dest_path)
                ctx.jars_copied += 1
                print(
                    f"[forge] Staged legacy FML artifact as JAR: "
                    f"{fml_dest_name}"
                )
            except Exception as e:
                print(
                    "[forge] Warning: Could not download legacy FML "
                    f"artifact: {e}"
                )

    if loader_dir_has_class(
        ctx.loader_dest_dir, "cpw/mods/fml/common/launcher/FMLTweaker.class"
    ):
        print("[forge] Legacy FMLTweaker class is available")
    else:
        print(
            "[forge] Warning: FMLTweaker class still missing after legacy "
            "FML recovery"
        )


def download_modlauncher_fallback(ctx: ForgeContext) -> None:
    if not ctx.modlauncher_era:
        return
    existing_runtime_jars = find_runtime_jars([ctx.loader_dest_dir])
    if existing_runtime_jars:
        return

    print(
        "[forge] No JARs found from installer extraction; attempting "
        "modlauncher download..."
    )
    for ml_version in MODLAUNCHER_FALLBACK_VERSIONS:
        ml_jar_name = f"modlauncher-{ml_version}.jar"
        ml_jar_path = os.path.join(ctx.loader_dest_dir, ml_jar_name)
        ml_urls = [
            f"https://maven.minecraftforge.net/cpw/mods/modlauncher/"
            f"{ml_version}/{ml_jar_name}",
            f"https://repo1.maven.org/maven2/cpw/mods/modlauncher/"
            f"{ml_version}/{ml_jar_name}",
        ]
        for ml_url in ml_urls:
            try:
                print(f"[forge] Trying modlauncher {ml_version}...")
                _download_with_retry(ml_url, ml_jar_path)
                if os.path.exists(ml_jar_path):
                    if jar_has_class(
                        ml_jar_path, "cpw/mods/modlauncher/Launcher.class"
                    ):
                        ctx.jars_copied += 1
                        print(
                            "[forge] Successfully downloaded modlauncher "
                            f"{ml_version}"
                        )
                        return
                    else:
                        os.remove(ml_jar_path)
            except Exception:
                continue


def download_manifest_libraries(ctx: ForgeContext) -> None:
    manifest_libs: List[str] = []
    for jarfile in os.listdir(ctx.loader_dest_dir):
        if jarfile.endswith(".jar"):
            manifest_libs.extend(
                gather_manifest_libraries(
                    os.path.join(ctx.loader_dest_dir, jarfile)
                )
            )

    if not manifest_libs:
        return

    print(
        f"[forge] Found {len(manifest_libs)} libraries in JAR manifests"
    )
    for rel in manifest_libs:
        dest_name = os.path.basename(rel)
        dest_path = os.path.join(ctx.loader_dest_dir, dest_name)
        if os.path.exists(dest_path):
            continue
        url = f"https://maven.minecraftforge.net/{rel}"
        try:
            print(f"[forge] Downloading manifest library: {rel}")
            _download_with_retry(url, dest_path)
            ctx.jars_copied += 1
            if ctx.jars_copied <= 20:
                print(f"[forge] Downloaded: {dest_name}")
        except Exception as e:
            print(
                f"[forge] Failed to download manifest library {rel}: {e}"
            )


def verify_runtime_jars_present(ctx: ForgeContext) -> Optional[str]:
    existing_runtime_jars = find_runtime_jars([ctx.loader_dest_dir])
    if existing_runtime_jars:
        return None

    if ctx.modlauncher_era:
        return "Could not find any Forge runtime JARs"

    has_legacy_core_jar = any(
        name.endswith(".jar") and (
            name.lower().startswith("forge-")
            or name.lower().startswith("minecraftforge-")
            or "universal" in name.lower()
        )
        for name in os.listdir(ctx.loader_dest_dir)
    )
    if has_legacy_core_jar:
        print(
            "[forge] Legacy Forge core JAR detected without embedded "
            "LaunchWrapper; continuing (vanilla classpath provides "
            "LaunchWrapper)"
        )
        return None

    return "Could not find LaunchWrapper runtime JARs for legacy Forge"


__all__ = [
    "copy_root_jars",
    "download_manifest_libraries",
    "download_modlauncher_fallback",
    "recover_legacy_fml",
    "recover_nested_legacy_jars",
    "stage_legacy_universal_archive",
    "verify_runtime_jars_present",
]
