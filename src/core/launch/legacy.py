from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

from core.logger import colorize_log
from core.settings import get_base_dir
from core.subprocess_utils import no_window_kwargs

from core.launch.args import _is_legacy_pre16_runtime, _parse_mc_version
from core.launch.mods import _iter_proxy_url_candidates


__all__ = [
    "_FML_HASH_FIXUPS",
    "_FML_LIBRARIES",
    "_download_legacy_forge_file",
    "_find_forge_core_jar",
    "_find_modloader_runtime_jar",
    "_has_modloader_runtime",
    "_is_legacy_forge_runtime",
    "_is_modloader_runtime_jar",
    "_legacy_forge_has_fml",
    "_legacy_forge_lib_copy_targets",
    "_legacy_forge_requires_modloader",
    "_normalize_legacy_language_code",
    "_prepare_legacy_applet_window_patch",
    "_patch_fml_library_hashes",
    "_prepare_legacy_direct_buffer_sound_patch",
    "_prepare_legacy_assets_directory",
    "_prepare_legacy_client_resources",
    "_prepare_legacy_forge_merged_client_jar",
    "_prepare_legacy_forge_runtime_files",
    "_prepare_legacy_modloader_runtime_directory",
    "_prepare_legacy_options_file",
    "_read_fml_version_properties",
    "_sha1_file",
    "_stage_legacy_fml_libraries",
]


def _sha1_file(path: str) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().lower()


def _is_legacy_forge_runtime(version_identifier: str) -> bool:
    major, minor = _parse_mc_version(version_identifier)
    return major == 1 and minor is not None and minor < 6


def _legacy_forge_has_fml(version_dir: str, loader_version: str = None) -> bool:
    from core.launch.loader import _get_loader_version

    actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
    if not actual_loader_version:
        return False

    forge_loader_dir = os.path.join(version_dir, "loaders", "forge", actual_loader_version)
    if not os.path.isdir(forge_loader_dir):
        return False

    try:
        for filename in os.listdir(forge_loader_dir):
            if not filename.endswith(".jar"):
                continue
            lower_name = filename.lower()
            if not (
                lower_name.startswith("forge-")
                or lower_name.startswith("fml-")
                or lower_name.startswith("minecraftforge-")
            ):
                continue
            jar_path = os.path.join(forge_loader_dir, filename)
            try:
                with zipfile.ZipFile(jar_path, "r") as jar:
                    if any(
                        name.startswith("cpw/mods/fml/")
                        or name.startswith("net/minecraftforge/fml/")
                        for name in jar.namelist()
                    ):
                        return True
            except Exception:
                continue
    except Exception:
        return False

    return False


def _legacy_forge_requires_modloader(version_dir: str, loader_version: str = None) -> bool:
    version_name = os.path.basename(version_dir.rstrip(os.sep))
    major, minor = _parse_mc_version(version_name)
    if not (major == 1 and minor is not None and minor < 6):
        return False
    return not _legacy_forge_has_fml(version_dir, loader_version)


def _is_modloader_runtime_jar(jar_path: str) -> bool:
    try:
        with zipfile.ZipFile(jar_path, "r") as jar:
            names = set(jar.namelist())
            return "BaseMod.class" in names and "ModLoader.class" in names
    except Exception:
        return False


def _find_modloader_runtime_jar(version_dir: str) -> str:
    candidates: list = []

    try:
        for filename in os.listdir(version_dir):
            if filename.endswith(".jar") and "modloader" in filename.lower():
                candidates.append(os.path.join(version_dir, filename))
    except Exception:
        pass

    modloader_root = os.path.join(version_dir, "loaders", "modloader")
    if os.path.isdir(modloader_root):
        for root, dirs, files in os.walk(modloader_root):
            for filename in files:
                if filename.endswith(".jar"):
                    candidates.append(os.path.join(root, filename))

    seen: set = set()
    for jar_path in candidates:
        if jar_path in seen:
            continue
        seen.add(jar_path)
        if _is_modloader_runtime_jar(jar_path):
            return jar_path

    return ""


def _has_modloader_runtime(version_dir: str) -> bool:
    client_jar = os.path.join(version_dir, "client.jar")
    if os.path.isfile(client_jar) and _is_modloader_runtime_jar(client_jar):
        return True
    return bool(_find_modloader_runtime_jar(version_dir))


def _prepare_legacy_modloader_runtime_directory(version_dir: str) -> str:
    runtime_jar = _find_modloader_runtime_jar(version_dir)
    if not runtime_jar or not os.path.isfile(runtime_jar):
        return ""

    extract_dir = os.path.join(os.path.dirname(runtime_jar), ".runtime_extracted")
    marker_path = os.path.join(extract_dir, ".source_stamp")

    try:
        source_stamp = (
            f"{os.path.abspath(runtime_jar)}|{os.path.getsize(runtime_jar)}|"
            f"{int(os.path.getmtime(runtime_jar))}"
        )
    except OSError:
        source_stamp = os.path.abspath(runtime_jar)

    try:
        if (
            os.path.isdir(extract_dir)
            and os.path.isfile(marker_path)
            and os.path.isfile(os.path.join(extract_dir, "ModLoader.class"))
            and os.path.isfile(os.path.join(extract_dir, "BaseMod.class"))
        ):
            with open(marker_path, "r", encoding="utf-8") as f:
                existing_stamp = f.read().strip()
            if existing_stamp == source_stamp:
                return os.path.relpath(extract_dir, version_dir).replace("\\", "/")
    except Exception:
        pass

    tmp_dir = extract_dir + ".tmp"
    for stale_dir in (tmp_dir,):
        if os.path.isdir(stale_dir):
            try:
                shutil.rmtree(stale_dir)
            except OSError:
                pass

    extracted_count = 0
    abs_extract_dir = os.path.abspath(extract_dir)
    abs_tmp_dir = os.path.abspath(tmp_dir)

    try:
        os.makedirs(tmp_dir, exist_ok=True)
        with zipfile.ZipFile(runtime_jar, "r") as src_zip:
            for entry in src_zip.infolist():
                name = entry.filename.replace("\\", "/")
                if entry.is_dir() or not name or name.upper().startswith("META-INF/"):
                    continue

                dest_path = os.path.abspath(os.path.join(tmp_dir, name))
                if os.path.commonpath([abs_tmp_dir, dest_path]) != abs_tmp_dir:
                    raise RuntimeError(f"Unsafe ModLoader runtime entry path: {name}")

                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with src_zip.open(entry, "r") as src_file, open(dest_path, "wb") as dst_file:
                    shutil.copyfileobj(src_file, dst_file)
                extracted_count += 1

        with open(os.path.join(tmp_dir, ".source_stamp"), "w", encoding="utf-8") as f:
            f.write(source_stamp)

        if os.path.isdir(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(os.path.dirname(abs_extract_dir), exist_ok=True)
        shutil.move(tmp_dir, extract_dir)
        print(colorize_log(
            f"[launcher] Prepared extracted legacy ModLoader runtime directory from "
            f"{os.path.basename(runtime_jar)} ({extracted_count} entries)"
        ))
        return os.path.relpath(extract_dir, version_dir).replace("\\", "/")
    except Exception as e:
        try:
            if os.path.isdir(tmp_dir):
                shutil.rmtree(tmp_dir)
        except OSError:
            pass
        print(colorize_log(
            f"[launcher] Warning: Could not prepare extracted ModLoader runtime directory: {e}"
        ))
        return ""


def _find_forge_core_jar(version_dir: str, loader_version: str = None) -> str:
    from core.launch.loader import _get_loader_version

    actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
    if not actual_loader_version:
        return ""

    forge_loader_dir = os.path.join(version_dir, "loaders", "forge", actual_loader_version)
    if not os.path.isdir(forge_loader_dir):
        return ""

    preferred: list = []
    fallback: list = []
    for filename in sorted(os.listdir(forge_loader_dir)):
        if not filename.endswith(".jar"):
            continue
        full_path = os.path.join(forge_loader_dir, filename)
        lower_name = filename.lower()
        if "universal" in lower_name and ("minecraftforge" in lower_name or lower_name.startswith("forge-")):
            preferred.append(full_path)
        elif "minecraftforge" in lower_name or lower_name.startswith("forge-"):
            fallback.append(full_path)

    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    return ""


def _read_fml_version_properties(version_dir: str, loader_version: str = None) -> dict:
    forge_jar = _find_forge_core_jar(version_dir, loader_version)
    if not forge_jar:
        return {}

    try:
        with zipfile.ZipFile(forge_jar, "r") as jar:
            try:
                raw = jar.read("fmlversion.properties").decode("utf-8", errors="replace")
            except KeyError:
                return {}
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: Could not read fmlversion.properties: {e}"))
        return {}

    props: dict = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key.strip()] = value.strip()
    return props


def _legacy_forge_lib_copy_targets(version_dir: str, loader_version: str = None) -> list:
    from core.launch.loader import _get_loader_version

    actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
    if not actual_loader_version:
        return []

    def _fallback_targets_from_filesystem() -> list:
        root = os.path.join(version_dir, "loaders", "forge", actual_loader_version)
        if not os.path.isdir(root):
            return []

        targets: list = []
        seen: set = set()
        wanted_prefixes = {
            "argo-": "argo",
            "argo-small-": "argo",
            "guava-": "guava",
            "asm-all-": "asm-all",
            "bcprov-jdk15on-": "bcprov-jdk15on",
            "scala-library-": "scala-library",
            "scala-library.jar": "scala-library",
        }

        for walk_root, _, files in os.walk(root):
            for filename in files:
                if not filename.endswith(".jar"):
                    continue

                lowered = filename.lower()
                matched_kind = None
                for prefix, kind in wanted_prefixes.items():
                    if lowered == prefix or lowered.startswith(prefix):
                        matched_kind = kind
                        break
                if not matched_kind:
                    continue

                src = os.path.join(walk_root, filename)
                if matched_kind == "scala-library":
                    dst = "scala-library.jar"
                else:
                    dst = filename

                key = (matched_kind, os.path.normcase(src))
                if key in seen:
                    continue
                seen.add(key)
                targets.append((src, dst))

        return targets

    profile_path = os.path.join(
        version_dir, "loaders", "forge", actual_loader_version, ".metadata", "install_profile.json"
    )
    if not os.path.exists(profile_path):
        return _fallback_targets_from_filesystem()

    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile_data = json.load(f)
    except Exception as e:
        print(colorize_log(
            f"[launcher] Warning: Could not parse legacy Forge install_profile.json: {e}"
        ))
        return _fallback_targets_from_filesystem()

    libraries = ((profile_data.get("versionInfo") or {}).get("libraries") or [])
    targets: list = []
    wanted = {
        ("net.sourceforge.argo", "argo"),
        ("com.google.guava", "guava"),
        ("org.ow2.asm", "asm-all"),
        ("org.bouncycastle", "bcprov-jdk15on"),
        ("org.scala-lang", "scala-library"),
    }

    for lib in libraries:
        lib_name = lib.get("name", "") if isinstance(lib, dict) else str(lib)
        parts = lib_name.split(":")
        if len(parts) < 3:
            continue

        group, artifact, version = parts[0], parts[1], parts[2]
        if (group, artifact) not in wanted:
            continue

        src_path = os.path.join(
            version_dir,
            "loaders",
            "forge",
            actual_loader_version,
            "libraries",
            group.replace(".", os.sep),
            artifact,
            version,
            f"{artifact}-{version}.jar",
        )
        if not os.path.exists(src_path):
            continue

        if group == "net.sourceforge.argo" and artifact == "argo":
            dst_name = (
                f"argo-small-{version.replace('-small', '')}.jar"
                if version.endswith("-small")
                else f"argo-{version}.jar"
            )
        elif group == "org.scala-lang" and artifact == "scala-library":
            dst_name = "scala-library.jar"
        else:
            dst_name = f"{artifact}-{version}.jar"

        targets.append((src_path, dst_name))

    if targets:
        return targets

    return _fallback_targets_from_filesystem()


def _download_legacy_forge_file(dest_path: str, file_name: str, expected_sha1: str) -> bool:
    candidate_urls = [
        f"https://web.archive.org/web/20200830040255if_/http://files.minecraftforge.net/fmllibs/{file_name}",
        f"https://files.minecraftforge.net/fmllibs/{file_name}",
        f"http://files.minecraftforge.net/fmllibs/{file_name}",
    ]

    expanded_urls: list = []
    for base_url in candidate_urls:
        for candidate_url in _iter_proxy_url_candidates(base_url):
            if candidate_url not in expanded_urls:
                expanded_urls.append(candidate_url)

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    for url in expanded_urls:
        tmp_path = None
        try:
            print(colorize_log(f"[launcher] Downloading legacy Forge support file: {url}"))
            fd, tmp_path = tempfile.mkstemp(prefix="legacy_forge_", suffix=".tmp")
            os.close(fd)

            request = urllib.request.Request(
                url, headers={"User-Agent": "Histolauncher/1.0"}
            )
            with urllib.request.urlopen(request, timeout=30) as response, open(tmp_path, "wb") as out:
                shutil.copyfileobj(response, out)

            actual_sha1 = _sha1_file(tmp_path)
            if expected_sha1 and actual_sha1.lower() != expected_sha1.lower():
                print(colorize_log(
                    f"[launcher] Warning: Legacy support file checksum mismatch for "
                    f"{file_name}: expected {expected_sha1}, got {actual_sha1}"
                ))
                continue

            shutil.move(tmp_path, dest_path)
            tmp_path = None
            print(colorize_log(
                f"[launcher] Cached legacy Forge support file: {os.path.basename(dest_path)}"
            ))
            return True
        except Exception as e:
            print(colorize_log(
                f"[launcher] Warning: Could not download {file_name} from {url}: {e}"
            ))
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    return False


def _prepare_legacy_forge_runtime_files(
    version_dir: str, game_dir: str, loader_version: str = None
) -> None:
    from core.launch.loader import _get_loader_version

    actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
    if not actual_loader_version or not game_dir:
        return

    lib_dir = os.path.join(game_dir, "lib")
    os.makedirs(lib_dir, exist_ok=True)

    for src_path, dst_name in _legacy_forge_lib_copy_targets(version_dir, actual_loader_version):
        dst_path = os.path.join(lib_dir, dst_name)
        try:
            if os.path.exists(dst_path):
                if _sha1_file(dst_path) == _sha1_file(src_path):
                    continue
            shutil.copy2(src_path, dst_path)
            print(colorize_log(f"[launcher] Seeded legacy FML library: {dst_name}"))
        except Exception as e:
            print(colorize_log(
                f"[launcher] Warning: Could not seed legacy FML library {dst_name}: {e}"
            ))

    fml_props = _read_fml_version_properties(version_dir, actual_loader_version)
    mc_version = fml_props.get("fmlbuild.mcversion", "").strip()
    deobf_hash = fml_props.get("fmlbuild.deobfuscation.hash", "").strip().lower()
    if not mc_version or not deobf_hash:
        return

    deobf_name = f"deobfuscation_data_{mc_version}.zip"
    deobf_dest = os.path.join(lib_dir, deobf_name)
    try:
        if os.path.exists(deobf_dest) and _sha1_file(deobf_dest) == deobf_hash:
            print(colorize_log(
                f"[launcher] Legacy deobfuscation data already present: {deobf_name}"
            ))
            return
    except Exception:
        pass

    cache_dir = os.path.join(version_dir, "loaders", "forge", actual_loader_version, ".legacy_fml")
    os.makedirs(cache_dir, exist_ok=True)
    cached_deobf = os.path.join(cache_dir, deobf_name)

    cached_valid = False
    if os.path.exists(cached_deobf):
        try:
            cached_valid = _sha1_file(cached_deobf) == deobf_hash
        except Exception:
            cached_valid = False

    if not cached_valid:
        cached_valid = _download_legacy_forge_file(cached_deobf, deobf_name, deobf_hash)

    if cached_valid:
        try:
            shutil.copy2(cached_deobf, deobf_dest)
            print(colorize_log(f"[launcher] Seeded legacy deobfuscation data: {deobf_name}"))
        except Exception as e:
            print(colorize_log(
                f"[launcher] Warning: Could not place legacy deobfuscation data: {e}"
            ))


def _is_windows_directory_junction(path: str) -> bool:
    isjunction = getattr(os.path, "isjunction", None)
    if os.name != "nt" or isjunction is None:
        return False
    try:
        return bool(isjunction(path))
    except Exception:
        return False


def _remove_legacy_resources_root(path: str) -> None:
    try:
        exists = os.path.exists(path) or os.path.lexists(path)
    except Exception:
        exists = os.path.exists(path)
    if not exists:
        return

    try:
        if os.path.islink(path):
            os.unlink(path)
            return
    except Exception:
        pass

    if os.name == "nt" and os.path.isdir(path):
        try:
            subprocess.run(
                ["cmd", "/c", "rmdir", path],
                capture_output=True,
                text=True,
                timeout=10,
                **no_window_kwargs(),
            )
            if not os.path.exists(path):
                return
        except Exception:
            pass
        if _is_windows_directory_junction(path):
            print(colorize_log(
                f"[launcher] Warning: Could not remove legacy resources junction: {path}"
            ))
            return

    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: Could not clear legacy resources root: {e}"))


def _create_legacy_resources_junction(link_path: str, source_dir: str) -> bool:
    if os.name != "nt":
        return False
    link_path = os.path.normpath(link_path)
    source_dir = os.path.normpath(source_dir)
    try:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", link_path, source_dir],
            capture_output=True,
            text=True,
            timeout=10,
            **no_window_kwargs(),
        )
        if result.returncode == 0 and os.path.isdir(link_path):
            print(colorize_log(
                f"[launcher] Linked legacy resources directory using Windows junction: {link_path} -> {source_dir}"
            ))
            return True
        detail = (result.stderr or result.stdout or "junction command failed").strip()
        print(colorize_log(f"[launcher] Warning: Could not junction legacy resources: {detail}"))
    except Exception as e:
        print(colorize_log(f"[launcher] Warning: Could not junction legacy resources: {e}"))
    return False


def _legacy_resource_file_filter(rel_path: str) -> bool:
    rel_norm = str(rel_path or "").replace("\\", "/").strip("/")
    if not rel_norm or rel_norm.startswith("../") or "/../" in rel_norm:
        return False
    audio_roots = {"music", "newmusic", "newsound", "sound", "sound3", "streaming"}
    audio_exts = {".mus", ".ogg", ".wav"}
    first_part = rel_norm.split("/", 1)[0].lower()
    ext = os.path.splitext(rel_norm)[1].lower()
    return first_part in audio_roots or ext in audio_exts


def _seed_legacy_game_resources(staged_assets_dir: str, game_dir: str) -> None:
    if not staged_assets_dir or not game_dir:
        return
    if not os.path.isdir(staged_assets_dir) or not os.path.isdir(game_dir):
        return

    target_dir = os.path.join(game_dir, "resources")
    try:
        if os.path.exists(target_dir):
            try:
                if os.path.normcase(os.path.realpath(target_dir)) == os.path.normcase(os.path.realpath(staged_assets_dir)):
                    return
            except Exception:
                pass
        else:
            try:
                os.symlink(staged_assets_dir, target_dir, target_is_directory=True)
                print(colorize_log(
                    f"[launcher] Linked legacy game resources to staged assets: {target_dir} -> {staged_assets_dir}"
                ))
                return
            except Exception:
                if _create_legacy_resources_junction(target_dir, staged_assets_dir):
                    return
    except Exception:
        pass

    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception:
        return

    linked_count = 0
    copied_count = 0
    reused_count = 0
    skipped_count = 0

    for current_dir, _dirs, files in os.walk(staged_assets_dir):
        for filename in files:
            src_path = os.path.join(current_dir, filename)
            rel_path = os.path.relpath(src_path, staged_assets_dir)
            rel_norm = rel_path.replace(os.sep, "/")
            if not _legacy_resource_file_filter(rel_norm):
                continue

            dest_path = os.path.join(target_dir, rel_path)
            try:
                src_size = os.path.getsize(src_path)
                if os.path.exists(dest_path) and os.path.getsize(dest_path) == src_size:
                    reused_count += 1
                    continue
            except OSError:
                skipped_count += 1
                continue

            try:
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                try:
                    os.link(src_path, dest_path)
                    linked_count += 1
                except OSError:
                    shutil.copy2(src_path, dest_path)
                    copied_count += 1
            except Exception:
                skipped_count += 1

    if linked_count or copied_count or reused_count or skipped_count:
        print(colorize_log(
            f"[launcher] Seeded legacy game resources in {target_dir} "
            f"(linked {linked_count}, copied {copied_count}, reused {reused_count}, skipped {skipped_count})"
        ))


def _prepare_legacy_assets_directory(
    version_identifier: str, version_dir: str, game_dir: str, meta: dict
) -> str:
    if not version_dir:
        return ""

    asset_index_name = (meta.get("asset_index") or "").strip()
    if not asset_index_name:
        return ""

    if not _is_legacy_pre16_runtime(version_identifier):
        return ""

    base_dir = get_base_dir()
    index_path = os.path.join(base_dir, "assets", "indexes", f"{asset_index_name}.json")
    if not os.path.exists(index_path):
        print(colorize_log(f"[launcher] Warning: Legacy asset index not found: {index_path}"))
        return ""

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            index_data = json.load(f)
    except Exception as e:
        print(colorize_log(
            f"[launcher] Warning: Could not read legacy asset index {asset_index_name}: {e}"
        ))
        return ""

    objects = index_data.get("objects") or {}
    if not isinstance(objects, dict) or not objects:
        print(colorize_log(
            f"[launcher] Warning: Legacy asset index {asset_index_name} has no objects"
        ))
        return ""

    staged_assets_dir = os.path.join(version_dir, "resources")
    os.makedirs(staged_assets_dir, exist_ok=True)

    legacy_resources_root = os.path.join(get_base_dir(), "assets", "legacy")
    os.makedirs(os.path.dirname(legacy_resources_root), exist_ok=True)

    def _set_legacy_resources_link(source_dir):
        _remove_legacy_resources_root(legacy_resources_root)
        try:
            os.symlink(source_dir, legacy_resources_root, target_is_directory=True)
            print(colorize_log(
                f"[launcher] Linked legacy resources root to {source_dir}"
            ))
            return True
        except Exception as e:
            if _create_legacy_resources_junction(legacy_resources_root, source_dir):
                return True
            print(colorize_log(f"[launcher] Warning: Could not link legacy resources: {e}"))
            return False

    _set_legacy_resources_link(staged_assets_dir)

    copied_count = 0
    linked_count = 0
    missing_count = 0
    objects_root = os.path.join(base_dir, "assets", "objects")

    for rel_path, obj in objects.items():
        if not isinstance(obj, dict):
            continue

        obj_hash = (obj.get("hash") or "").strip().lower()
        obj_size = int(obj.get("size") or 0)
        if len(obj_hash) < 2:
            continue

        src_path = os.path.join(objects_root, obj_hash[:2], obj_hash)
        if not os.path.exists(src_path):
            missing_count += 1
            continue

        dest_path = os.path.join(staged_assets_dir, rel_path.replace("/", os.sep))
        dest_dir = os.path.dirname(dest_path)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)

        try:
            if os.path.exists(dest_path) and os.path.getsize(dest_path) == obj_size:
                continue
        except OSError:
            pass

        try:
            if os.path.exists(dest_path):
                os.remove(dest_path)
        except OSError:
            pass

        try:
            os.link(src_path, dest_path)
            linked_count += 1
        except OSError:
            try:
                shutil.copy2(src_path, dest_path)
                copied_count += 1
            except Exception:
                missing_count += 1

    print(colorize_log(
        f"[launcher] Prepared legacy assets in {staged_assets_dir} "
        f"(linked {linked_count}, copied {copied_count}, missing {missing_count})"
    ))
    _seed_legacy_game_resources(staged_assets_dir, game_dir)

    return staged_assets_dir


def _prepare_legacy_client_resources(version_dir: str, staged_assets_dir: str) -> None:
    if not staged_assets_dir:
        return

    client_jar = os.path.join(version_dir, "client.jar")
    if not os.path.exists(client_jar):
        return

    extracted_count = 0
    skipped_count = 0

    try:
        with zipfile.ZipFile(client_jar, "r") as jar:
            for entry in jar.infolist():
                name = entry.filename
                if entry.is_dir():
                    continue
                if name.startswith("META-INF/") or name.endswith(".class"):
                    continue

                dest_path = os.path.join(staged_assets_dir, name.replace("/", os.sep))
                dest_dir = os.path.dirname(dest_path)
                if dest_dir:
                    os.makedirs(dest_dir, exist_ok=True)

                try:
                    if os.path.exists(dest_path) and os.path.getsize(dest_path) == entry.file_size:
                        skipped_count += 1
                        continue
                except OSError:
                    pass

                with jar.open(entry, "r") as src, open(dest_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted_count += 1
    except Exception as e:
        print(colorize_log(
            f"[launcher] Warning: Could not prepare legacy client resources: {e}"
        ))
        return

    print(colorize_log(
        f"[launcher] Prepared legacy client.jar resources in {staged_assets_dir} "
        f"(extracted {extracted_count}, reused {skipped_count})"
    ))


def _class_utf8_replace_exact(class_data: bytes, old_value: bytes, new_value: bytes) -> bytes:
    if len(old_value) != len(new_value):
        return class_data
    if not class_data.startswith(b"\xca\xfe\xba\xbe"):
        return class_data

    data = bytearray(class_data)
    pos = 8
    try:
        cp_count = int.from_bytes(data[pos:pos + 2], "big")
        pos += 2
        index = 1
        while index < cp_count:
            tag = data[pos]
            pos += 1
            if tag == 1:
                length = int.from_bytes(data[pos:pos + 2], "big")
                pos += 2
                if data[pos:pos + length] == old_value:
                    data[pos:pos + length] = new_value
                pos += length
            elif tag in (3, 4, 9, 10, 11, 12, 18):
                pos += 4
            elif tag in (5, 6):
                pos += 8
                index += 1
            elif tag in (7, 8, 16):
                pos += 2
            elif tag == 15:
                pos += 3
            else:
                return class_data
            index += 1
    except Exception:
        return class_data
    return bytes(data)


def _class_patch_bytebuffer_wrap_calls(class_data: bytes) -> tuple[bytes, bool]:
    if not class_data.startswith(b"\xca\xfe\xba\xbe"):
        return class_data, False

    data = bytearray(class_data)
    pos = 8
    try:
        cp_count = int.from_bytes(data[pos:pos + 2], "big")
        pos += 2
        cp_entries = [None] * cp_count
        index = 1
        while index < cp_count:
            tag = data[pos]
            pos += 1
            if tag == 1:
                length = int.from_bytes(data[pos:pos + 2], "big")
                pos += 2
                cp_entries[index] = (tag, data[pos:pos + length].decode("utf-8", errors="replace"))
                pos += length
            elif tag in (7, 8, 16):
                cp_entries[index] = (tag, int.from_bytes(data[pos:pos + 2], "big"))
                pos += 2
            elif tag in (9, 10, 11, 12, 18):
                cp_entries[index] = (
                    tag,
                    int.from_bytes(data[pos:pos + 2], "big"),
                    int.from_bytes(data[pos + 2:pos + 4], "big"),
                )
                pos += 4
            elif tag in (3, 4):
                pos += 4
            elif tag in (5, 6):
                pos += 8
                index += 1
            elif tag == 15:
                pos += 3
            else:
                return class_data, False
            index += 1
    except Exception:
        return class_data, False

    cp_end = pos

    def utf8(cp_index: int) -> str:
        entry = cp_entries[cp_index] if 0 < cp_index < len(cp_entries) else None
        return entry[1] if entry and entry[0] == 1 else ""

    def class_name(cp_index: int) -> str:
        entry = cp_entries[cp_index] if 0 < cp_index < len(cp_entries) else None
        return utf8(entry[1]) if entry and entry[0] == 7 else ""

    def name_type(cp_index: int) -> tuple[str, str]:
        entry = cp_entries[cp_index] if 0 < cp_index < len(cp_entries) else None
        if not entry or entry[0] != 12:
            return "", ""
        return utf8(entry[1]), utf8(entry[2])

    wrap_descriptors = {
        "([B)Ljava/nio/ByteBuffer;",
        "([BII)Ljava/nio/ByteBuffer;",
    }
    wrap_refs: dict[int, str] = {}
    for cp_index, entry in enumerate(cp_entries):
        if not entry or entry[0] != 10:
            continue
        owner = class_name(entry[1])
        method_name, descriptor = name_type(entry[2])
        if owner == "java/nio/ByteBuffer" and method_name == "wrap" and descriptor in wrap_descriptors:
            wrap_refs[cp_index] = descriptor

    if not wrap_refs:
        return class_data, False

    extra_cp = bytearray()
    appended_entries: list[tuple[int, tuple]] = []
    next_cp_index = cp_count

    def find_utf8(value: str) -> int:
        for cp_index, entry in enumerate(cp_entries):
            if entry and entry[0] == 1 and entry[1] == value:
                return cp_index
        for cp_index, entry in appended_entries:
            if entry[0] == 1 and entry[1] == value:
                return cp_index
        return 0

    def find_class(value: str) -> int:
        for cp_index, entry in enumerate(cp_entries):
            if entry and entry[0] == 7 and utf8(entry[1]) == value:
                return cp_index
        for cp_index, entry in appended_entries:
            if entry[0] == 7:
                name_entry = next((item for idx, item in appended_entries if idx == entry[1]), None)
                if name_entry and name_entry[0] == 1 and name_entry[1] == value:
                    return cp_index
        return 0

    def append_utf8(value: str) -> int:
        nonlocal next_cp_index
        existing = find_utf8(value)
        if existing:
            return existing
        cp_index = next_cp_index
        next_cp_index += 1
        encoded = value.encode("utf-8")
        extra_cp.extend(b"\x01" + len(encoded).to_bytes(2, "big") + encoded)
        appended_entries.append((cp_index, (1, value)))
        return cp_index

    def append_class(value: str) -> int:
        nonlocal next_cp_index
        existing = find_class(value)
        if existing:
            return existing
        name_index = append_utf8(value)
        cp_index = next_cp_index
        next_cp_index += 1
        extra_cp.extend(b"\x07" + name_index.to_bytes(2, "big"))
        appended_entries.append((cp_index, (7, name_index)))
        return cp_index

    def append_name_type(name: str, descriptor: str) -> int:
        nonlocal next_cp_index
        for cp_index, entry in enumerate(cp_entries):
            if entry and entry[0] == 12 and utf8(entry[1]) == name and utf8(entry[2]) == descriptor:
                return cp_index
        for cp_index, entry in appended_entries:
            if entry[0] != 12:
                continue
            name_entry = next((item for idx, item in appended_entries if idx == entry[1]), None)
            desc_entry = next((item for idx, item in appended_entries if idx == entry[2]), None)
            if name_entry and desc_entry and name_entry[1] == name and desc_entry[1] == descriptor:
                return cp_index
        name_index = append_utf8(name)
        desc_index = append_utf8(descriptor)
        cp_index = next_cp_index
        next_cp_index += 1
        extra_cp.extend(b"\x0c" + name_index.to_bytes(2, "big") + desc_index.to_bytes(2, "big"))
        appended_entries.append((cp_index, (12, name_index, desc_index)))
        return cp_index

    def append_method_ref(owner: str, name: str, descriptor: str) -> int:
        nonlocal next_cp_index
        owner_index = append_class(owner)
        name_type_index = append_name_type(name, descriptor)
        cp_index = next_cp_index
        next_cp_index += 1
        extra_cp.extend(b"\x0a" + owner_index.to_bytes(2, "big") + name_type_index.to_bytes(2, "big"))
        appended_entries.append((cp_index, (10, owner_index, name_type_index)))
        return cp_index

    method_ref_replacements = {
        old_index: append_method_ref("histolauncher/DBufX", "wrap", descriptor)
        for old_index, descriptor in wrap_refs.items()
    }

    fixed_operand_sizes = {
        0x10: 1, 0x11: 2, 0x12: 1, 0x13: 2, 0x14: 2,
        0x15: 1, 0x16: 1, 0x17: 1, 0x18: 1, 0x19: 1,
        0x36: 1, 0x37: 1, 0x38: 1, 0x39: 1, 0x3A: 1,
        0x84: 2, 0x99: 2, 0x9A: 2, 0x9B: 2, 0x9C: 2,
        0x9D: 2, 0x9E: 2, 0x9F: 2, 0xA0: 2, 0xA1: 2,
        0xA2: 2, 0xA3: 2, 0xA4: 2, 0xA5: 2, 0xA6: 2,
        0xA7: 2, 0xA8: 2, 0xA9: 1, 0xB2: 2, 0xB3: 2,
        0xB4: 2, 0xB5: 2, 0xB6: 2, 0xB7: 2, 0xB8: 2,
        0xB9: 4, 0xBA: 4, 0xBB: 2, 0xBC: 1, 0xBD: 2,
        0xC0: 2, 0xC1: 2, 0xC5: 3, 0xC6: 2, 0xC7: 2,
        0xC8: 4, 0xC9: 4,
    }

    def patch_code(code_start: int, code_end: int) -> int:
        count = 0
        cursor = code_start
        while cursor < code_end:
            opcode_pos = cursor
            opcode = data[cursor]
            cursor += 1
            if opcode == 0xB8:
                method_index = int.from_bytes(data[cursor:cursor + 2], "big")
                replacement = method_ref_replacements.get(method_index)
                if replacement:
                    data[cursor:cursor + 2] = replacement.to_bytes(2, "big")
                    count += 1
                cursor += 2
            elif opcode == 0xAA:
                while (cursor - code_start) % 4:
                    cursor += 1
                low = int.from_bytes(data[cursor + 4:cursor + 8], "big", signed=True)
                high = int.from_bytes(data[cursor + 8:cursor + 12], "big", signed=True)
                cursor += 12 + max(0, high - low + 1) * 4
            elif opcode == 0xAB:
                while (cursor - code_start) % 4:
                    cursor += 1
                pairs = int.from_bytes(data[cursor + 4:cursor + 8], "big", signed=True)
                cursor += 8 + max(0, pairs) * 8
            elif opcode == 0xC4:
                wide_opcode = data[cursor]
                cursor += 1
                cursor += 4 if wide_opcode == 0x84 else 2
            else:
                cursor += fixed_operand_sizes.get(opcode, 0)
            if cursor <= opcode_pos:
                return count
        return count

    try:
        pos = cp_end + 6
        interfaces_count = int.from_bytes(data[pos:pos + 2], "big")
        pos += 2 + interfaces_count * 2

        def skip_members(member_pos: int) -> int:
            member_count = int.from_bytes(data[member_pos:member_pos + 2], "big")
            member_pos += 2
            for _ in range(member_count):
                member_pos += 6
                attr_count = int.from_bytes(data[member_pos:member_pos + 2], "big")
                member_pos += 2
                for _ in range(attr_count):
                    attr_len = int.from_bytes(data[member_pos + 2:member_pos + 6], "big")
                    member_pos += 6 + attr_len
            return member_pos

        pos = skip_members(pos)
        methods_count = int.from_bytes(data[pos:pos + 2], "big")
        pos += 2
        patched_calls = 0
        for _ in range(methods_count):
            pos += 6
            attr_count = int.from_bytes(data[pos:pos + 2], "big")
            pos += 2
            for _ in range(attr_count):
                attr_name_index = int.from_bytes(data[pos:pos + 2], "big")
                attr_len = int.from_bytes(data[pos + 2:pos + 6], "big")
                attr_body = pos + 6
                if utf8(attr_name_index) == "Code" and attr_len >= 8:
                    code_len = int.from_bytes(data[attr_body + 4:attr_body + 8], "big")
                    code_start = attr_body + 8
                    patched_calls += patch_code(code_start, code_start + code_len)
                pos = attr_body + attr_len
    except Exception:
        return class_data, False

    if not patched_calls:
        return class_data, False

    output = bytearray()
    output.extend(data[:8])
    output.extend(next_cp_index.to_bytes(2, "big"))
    output.extend(data[10:cp_end])
    output.extend(extra_cp)
    output.extend(data[cp_end:])
    return bytes(output), True


def _class_patch_indev_missing_music_guard(class_data: bytes) -> tuple[bytes, bool]:
    if not class_data.startswith(b"\xca\xfe\xba\xbe"):
        return class_data, False

    data = bytearray(class_data)
    pos = 8
    try:
        cp_count = int.from_bytes(data[pos:pos + 2], "big")
        pos += 2
        cp_entries = [None] * cp_count
        index = 1
        while index < cp_count:
            tag = data[pos]
            pos += 1
            if tag == 1:
                length = int.from_bytes(data[pos:pos + 2], "big")
                pos += 2
                cp_entries[index] = (tag, data[pos:pos + length].decode("utf-8", errors="replace"))
                pos += length
            elif tag in (7, 8, 16):
                cp_entries[index] = (tag, int.from_bytes(data[pos:pos + 2], "big"))
                pos += 2
            elif tag in (9, 10, 11, 12, 18):
                cp_entries[index] = (
                    tag,
                    int.from_bytes(data[pos:pos + 2], "big"),
                    int.from_bytes(data[pos + 2:pos + 4], "big"),
                )
                pos += 4
            elif tag in (3, 4):
                cp_entries[index] = (tag, bytes(data[pos:pos + 4]))
                pos += 4
            elif tag in (5, 6):
                cp_entries[index] = (tag, bytes(data[pos:pos + 8]))
                pos += 8
                index += 1
            elif tag == 15:
                pos += 3
            else:
                return class_data, False
            index += 1
    except Exception:
        return class_data, False

    cp_end = pos

    def utf8(cp_index: int) -> str:
        entry = cp_entries[cp_index] if 0 < cp_index < len(cp_entries) else None
        return entry[1] if entry and entry[0] == 1 else ""

    def class_name(cp_index: int) -> str:
        entry = cp_entries[cp_index] if 0 < cp_index < len(cp_entries) else None
        return utf8(entry[1]) if entry and entry[0] == 7 else ""

    def name_type(cp_index: int) -> tuple[str, str]:
        entry = cp_entries[cp_index] if 0 < cp_index < len(cp_entries) else None
        if not entry or entry[0] != 12:
            return "", ""
        return utf8(entry[1]), utf8(entry[2])

    def find_ref(tag: int, owner: str, name: str, descriptor: str) -> int:
        for cp_index, entry in enumerate(cp_entries):
            if not entry or entry[0] != tag or class_name(entry[1]) != owner:
                continue
            ref_name, ref_desc = name_type(entry[2])
            if ref_name == name and ref_desc == descriptor:
                return cp_index
        return 0

    def find_string(value: str) -> int:
        for cp_index, entry in enumerate(cp_entries):
            if entry and entry[0] == 8 and utf8(entry[1]) == value:
                return cp_index
        return 0

    def find_float(raw: bytes) -> int:
        for cp_index, entry in enumerate(cp_entries):
            if entry and entry[0] == 4 and entry[1] == raw:
                return cp_index
        return 0

    def u2(value: int) -> bytes:
        return int(value).to_bytes(2, "big")

    refs = {
        "sound_system": find_ref(9, "net/minecraft/client/e/c", "a", "Lpaulscode/sound/SoundSystem;"),
        "music_pool": find_ref(9, "net/minecraft/client/e/c", "c", "Lnet/minecraft/client/e/b;"),
        "settings": find_ref(9, "net/minecraft/client/e/c", "e", "Lnet/minecraft/client/r;"),
        "music_enabled": find_ref(9, "net/minecraft/client/r", "a", "Z"),
        "pool_get": find_ref(10, "net/minecraft/client/e/b", "a", "(Ljava/lang/String;)Lnet/minecraft/client/e/a;"),
        "entry_name": find_ref(9, "net/minecraft/client/e/a", "a", "Ljava/lang/String;"),
        "entry_url": find_ref(9, "net/minecraft/client/e/a", "b", "Ljava/net/URL;"),
        "new_streaming": find_ref(
            10,
            "paulscode/sound/SoundSystem",
            "newStreamingSource",
            "(ZLjava/lang/String;Ljava/net/URL;Ljava/lang/String;ZFFFIF)V",
        ),
        "play": find_ref(10, "paulscode/sound/SoundSystem", "play", "(Ljava/lang/String;)V"),
        "playing": find_ref(10, "paulscode/sound/SoundSystem", "playing", "(Ljava/lang/String;)Z"),
        "bg_music": find_string("BgMusic"),
        "calm": find_string("calm"),
        "distance": find_float(b"\x42\x00\x00\x00"),
    }
    if not all(refs.values()):
        return class_data, False

    replacement_code = b"".join([
        b"\x2a\xb4" + u2(refs["settings"]),
        b"\xc6\x00\x58",
        b"\x2a\xb4" + u2(refs["settings"]),
        b"\xb4" + u2(refs["music_enabled"]),
        b"\x9a\x00\x04",
        b"\xb1",
        b"\x2a\xb4" + u2(refs["sound_system"]),
        b"\xc7\x00\x04",
        b"\xb1",
        b"\x2a\xb4" + u2(refs["sound_system"]),
        b"\x12" + bytes([refs["bg_music"]]),
        b"\xb6" + u2(refs["playing"]),
        b"\x99\x00\x04",
        b"\xb1",
        b"\x2a\xb4" + u2(refs["music_pool"]),
        b"\x12" + bytes([refs["calm"]]),
        b"\xb6" + u2(refs["pool_get"]),
        b"\x3a\x04",
        b"\x19\x04",
        b"\xc7\x00\x04",
        b"\xb1",
        b"\x2a\xb4" + u2(refs["sound_system"]),
        b"\x04",
        b"\x12" + bytes([refs["bg_music"]]),
        b"\x19\x04",
        b"\xb4" + u2(refs["entry_url"]),
        b"\x19\x04",
        b"\xb4" + u2(refs["entry_name"]),
        b"\x03",
        b"\x23\x24\x25",
        b"\x05",
        b"\x12" + bytes([refs["distance"]]),
        b"\xb6" + u2(refs["new_streaming"]),
        b"\x2a\xb4" + u2(refs["sound_system"]),
        b"\x12" + bytes([refs["bg_music"]]),
        b"\xb6" + u2(refs["play"]),
        b"\xb1",
    ])

    try:
        pos = cp_end + 6
        interfaces_count = int.from_bytes(data[pos:pos + 2], "big")
        pos += 2 + interfaces_count * 2

        fields_count = int.from_bytes(data[pos:pos + 2], "big")
        pos += 2
        for _ in range(fields_count):
            pos += 6
            attr_count = int.from_bytes(data[pos:pos + 2], "big")
            pos += 2
            for _ in range(attr_count):
                attr_len = int.from_bytes(data[pos + 2:pos + 6], "big")
                pos += 6 + attr_len

        methods_count_pos = pos
        methods_count = int.from_bytes(data[pos:pos + 2], "big")
        pos += 2
        for _ in range(methods_count):
            method_name = utf8(int.from_bytes(data[pos + 2:pos + 4], "big"))
            method_desc = utf8(int.from_bytes(data[pos + 4:pos + 6], "big"))
            pos += 6
            attr_count = int.from_bytes(data[pos:pos + 2], "big")
            pos += 2
            for _ in range(attr_count):
                attr_pos = pos
                attr_name = utf8(int.from_bytes(data[pos:pos + 2], "big"))
                attr_len = int.from_bytes(data[pos + 2:pos + 6], "big")
                attr_body = pos + 6
                if method_name == "a" and method_desc == "(FFF)V" and attr_name == "Code":
                    max_stack = max(11, int.from_bytes(data[attr_body:attr_body + 2], "big"))
                    max_locals = max(5, int.from_bytes(data[attr_body + 2:attr_body + 4], "big"))
                    old_code_len = int.from_bytes(data[attr_body + 4:attr_body + 8], "big")
                    old_code = bytes(data[attr_body + 8:attr_body + 8 + old_code_len])
                    if b"\x12" + bytes([refs["calm"]]) not in old_code:
                        return class_data, False
                    trailing_code_attr = bytes(data[attr_body + 8 + old_code_len:attr_body + attr_len])
                    new_body = (
                        max_stack.to_bytes(2, "big")
                        + max_locals.to_bytes(2, "big")
                        + len(replacement_code).to_bytes(4, "big")
                        + replacement_code
                        + trailing_code_attr
                    )
                    output = bytearray()
                    output.extend(data[:attr_pos + 2])
                    output.extend(len(new_body).to_bytes(4, "big"))
                    output.extend(new_body)
                    output.extend(data[attr_body + attr_len:])
                    return bytes(output), True
                pos = attr_body + attr_len
        _ = methods_count_pos
    except Exception:
        return class_data, False

    return class_data, False


def _class_patch_alpha_applet_window_bridge(class_data: bytes) -> tuple[bytes, bool]:
    if not class_data.startswith(b"\xca\xfe\xba\xbe"):
        return class_data, False

    data = bytearray(class_data)
    pos = 8
    try:
        cp_count = int.from_bytes(data[pos:pos + 2], "big")
        pos += 2
        cp_entries = [None] * cp_count
        index = 1
        while index < cp_count:
            tag = data[pos]
            pos += 1
            if tag == 1:
                length = int.from_bytes(data[pos:pos + 2], "big")
                pos += 2
                cp_entries[index] = (tag, data[pos:pos + length].decode("utf-8", errors="replace"))
                pos += length
            elif tag in (7, 8, 16):
                cp_entries[index] = (tag, int.from_bytes(data[pos:pos + 2], "big"))
                pos += 2
            elif tag in (9, 10, 11, 12, 18):
                cp_entries[index] = (
                    tag,
                    int.from_bytes(data[pos:pos + 2], "big"),
                    int.from_bytes(data[pos + 2:pos + 4], "big"),
                )
                pos += 4
            elif tag in (3, 4):
                pos += 4
            elif tag in (5, 6):
                pos += 8
                index += 1
            elif tag == 15:
                pos += 3
            else:
                return class_data, False
            index += 1
    except Exception:
        return class_data, False

    cp_end = pos

    def utf8(cp_index: int) -> str:
        entry = cp_entries[cp_index] if 0 < cp_index < len(cp_entries) else None
        return entry[1] if entry and entry[0] == 1 else ""

    def class_name(cp_index: int) -> str:
        entry = cp_entries[cp_index] if 0 < cp_index < len(cp_entries) else None
        return utf8(entry[1]) if entry and entry[0] == 7 else ""

    def name_type(cp_index: int) -> tuple[str, str]:
        entry = cp_entries[cp_index] if 0 < cp_index < len(cp_entries) else None
        if not entry or entry[0] != 12:
            return "", ""
        return utf8(entry[1]), utf8(entry[2])

    def find_ref(tag: int, owner: str, name: str, descriptor: str) -> int:
        for cp_index, entry in enumerate(cp_entries):
            if not entry or entry[0] != tag or class_name(entry[1]) != owner:
                continue
            ref_name, ref_desc = name_type(entry[2])
            if ref_name == name and ref_desc == descriptor:
                return cp_index
        return 0

    def find_class(value: str) -> int:
        for cp_index, entry in enumerate(cp_entries):
            if entry and entry[0] == 7 and utf8(entry[1]) == value:
                return cp_index
        return 0

    pack_ref = find_ref(10, "java/awt/Frame", "pack", "()V")
    center_ref = find_ref(10, "java/awt/Frame", "setLocationRelativeTo", "(Ljava/awt/Component;)V")
    visible_ref = find_ref(10, "java/awt/Frame", "setVisible", "(Z)V")
    validate_ref = find_ref(10, "java/awt/Frame", "validate", "()V")
    frame_class = find_class("java/awt/Frame")
    if not all((pack_ref, center_ref, visible_ref, validate_ref, frame_class)):
        return class_data, False

    extra_cp = bytearray()
    next_cp_index = cp_count

    def append_utf8(value: str) -> int:
        nonlocal next_cp_index
        for cp_index, entry in enumerate(cp_entries):
            if entry and entry[0] == 1 and entry[1] == value:
                return cp_index
        cp_index = next_cp_index
        next_cp_index += 1
        encoded = value.encode("utf-8")
        extra_cp.extend(b"\x01" + len(encoded).to_bytes(2, "big") + encoded)
        return cp_index

    method_name = append_utf8("setExtendedState")
    method_desc = append_utf8("(I)V")
    name_type_index = next_cp_index
    next_cp_index += 1
    extra_cp.extend(b"\x0c" + method_name.to_bytes(2, "big") + method_desc.to_bytes(2, "big"))
    set_extended_ref = next_cp_index
    next_cp_index += 1
    extra_cp.extend(b"\x0a" + frame_class.to_bytes(2, "big") + name_type_index.to_bytes(2, "big"))

    bridge_name = append_utf8("histolauncher/AppletResizeBridge")
    bridge_class = next_cp_index
    next_cp_index += 1
    extra_cp.extend(b"\x07" + bridge_name.to_bytes(2, "big"))
    install_name = append_utf8("install")
    install_desc = append_utf8("(Ljava/awt/Frame;)V")
    install_name_type = next_cp_index
    next_cp_index += 1
    extra_cp.extend(b"\x0c" + install_name.to_bytes(2, "big") + install_desc.to_bytes(2, "big"))
    install_ref = next_cp_index
    next_cp_index += 1
    extra_cp.extend(b"\x0a" + bridge_class.to_bytes(2, "big") + install_name_type.to_bytes(2, "big"))

    def u2(value: int) -> bytes:
        return int(value).to_bytes(2, "big")

    old_sequence = b"".join([
        b"\x19\x05\xb6" + u2(pack_ref),
        b"\x19\x05\x01\xb6" + u2(center_ref),
        b"\x19\x05\x04\xb6" + u2(visible_ref),
    ])
    new_sequence = b"".join([
        b"\x19\x05\x10\x06\xb6" + u2(set_extended_ref),
        b"\x19\x05\x04\xb6" + u2(visible_ref),
        b"\x00\x00\x00\x00",
    ])
    if len(old_sequence) != len(new_sequence):
        return class_data, False
    patch_at = data.find(old_sequence, cp_end)
    if patch_at < 0:
        return class_data, False
    data[patch_at:patch_at + len(old_sequence)] = new_sequence

    validate_sequence = b"\x19\x05\xb6" + u2(validate_ref)
    install_sequence = b"\x19\x05\xb8" + u2(install_ref)
    install_at = data.find(validate_sequence, patch_at + len(new_sequence))
    if install_at < 0:
        return class_data, False
    data[install_at:install_at + len(validate_sequence)] = install_sequence

    output = bytearray()
    output.extend(data[:8])
    output.extend(next_cp_index.to_bytes(2, "big"))
    output.extend(data[10:cp_end])
    output.extend(extra_cp)
    output.extend(data[cp_end:])
    return bytes(output), True


def _class_patch_classic_applet_display_sync(class_data: bytes) -> tuple[bytes, bool]:
    if not class_data.startswith(b"\xca\xfe\xba\xbe"):
        return class_data, False

    data = bytearray(class_data)
    pos = 8
    try:
        cp_count = int.from_bytes(data[pos:pos + 2], "big")
        pos += 2
        cp_entries = [None] * cp_count
        index = 1
        while index < cp_count:
            tag = data[pos]
            pos += 1
            if tag == 1:
                length = int.from_bytes(data[pos:pos + 2], "big")
                pos += 2
                cp_entries[index] = (tag, data[pos:pos + length].decode("utf-8", errors="replace"))
                pos += length
            elif tag in (7, 8, 16):
                cp_entries[index] = (tag, int.from_bytes(data[pos:pos + 2], "big"))
                pos += 2
            elif tag in (9, 10, 11, 12, 18):
                cp_entries[index] = (
                    tag,
                    int.from_bytes(data[pos:pos + 2], "big"),
                    int.from_bytes(data[pos + 2:pos + 4], "big"),
                )
                pos += 4
            elif tag in (3, 4):
                pos += 4
            elif tag in (5, 6):
                pos += 8
                index += 1
            elif tag == 15:
                pos += 3
            else:
                return class_data, False
            index += 1
    except Exception:
        return class_data, False

    cp_end = pos

    def utf8(cp_index: int) -> str:
        entry = cp_entries[cp_index] if 0 < cp_index < len(cp_entries) else None
        return entry[1] if entry and entry[0] == 1 else ""

    def class_name(cp_index: int) -> str:
        entry = cp_entries[cp_index] if 0 < cp_index < len(cp_entries) else None
        return utf8(entry[1]) if entry and entry[0] == 7 else ""

    def name_type(cp_index: int) -> tuple[str, str]:
        entry = cp_entries[cp_index] if 0 < cp_index < len(cp_entries) else None
        if not entry or entry[0] != 12:
            return "", ""
        return utf8(entry[1]), utf8(entry[2])

    def find_ref(tag: int, owner: str, name: str, descriptor: str) -> int:
        for cp_index, entry in enumerate(cp_entries):
            if not entry or entry[0] != tag or class_name(entry[1]) != owner:
                continue
            ref_name, ref_desc = name_type(entry[2])
            if ref_name == name and ref_desc == descriptor:
                return cp_index
        return 0

    def find_string(value: str) -> int:
        for cp_index, entry in enumerate(cp_entries):
            if entry and entry[0] == 8 and utf8(entry[1]) == value:
                return cp_index
        return 0

    pre_render_string = find_string("Pre render")
    gl_check_ref = find_ref(10, "com/mojang/minecraft/l", "a", "(Ljava/lang/String;)V")
    if not pre_render_string or not gl_check_ref:
        return class_data, False

    extra_cp = bytearray()
    next_cp_index = cp_count

    def append_utf8(value: str) -> int:
        nonlocal next_cp_index
        for cp_index, entry in enumerate(cp_entries):
            if entry and entry[0] == 1 and entry[1] == value:
                return cp_index
        cp_index = next_cp_index
        next_cp_index += 1
        encoded = value.encode("utf-8")
        extra_cp.extend(b"\x01" + len(encoded).to_bytes(2, "big") + encoded)
        return cp_index

    sync_class_name = append_utf8("histolauncher/AppletDisplaySync")
    sync_class = next_cp_index
    next_cp_index += 1
    extra_cp.extend(b"\x07" + sync_class_name.to_bytes(2, "big"))
    sync_name = append_utf8("sync")
    sync_desc = append_utf8("(Lcom/mojang/minecraft/l;)V")
    sync_name_type = next_cp_index
    next_cp_index += 1
    extra_cp.extend(b"\x0c" + sync_name.to_bytes(2, "big") + sync_desc.to_bytes(2, "big"))
    sync_ref = next_cp_index
    next_cp_index += 1
    extra_cp.extend(b"\x0a" + sync_class.to_bytes(2, "big") + sync_name_type.to_bytes(2, "big"))

    old_ldc = b""
    if pre_render_string <= 0xFF:
        old_ldc = b"\x12" + bytes([pre_render_string]) + b"\xb8" + gl_check_ref.to_bytes(2, "big")
        new_call = b"\x2a\xb8" + sync_ref.to_bytes(2, "big") + b"\x00"
    else:
        old_ldc = b"\x13" + pre_render_string.to_bytes(2, "big") + b"\xb8" + gl_check_ref.to_bytes(2, "big")
        new_call = b"\x2a\xb8" + sync_ref.to_bytes(2, "big") + b"\x00\x00"
    if len(old_ldc) != len(new_call):
        return class_data, False

    patch_at = data.find(old_ldc, cp_end)
    if patch_at < 0:
        return class_data, False
    data[patch_at:patch_at + len(old_ldc)] = new_call

    output = bytearray()
    output.extend(data[:8])
    output.extend(next_cp_index.to_bytes(2, "big"))
    output.extend(data[10:cp_end])
    output.extend(extra_cp)
    output.extend(data[cp_end:])
    return bytes(output), True


class _SimpleClassBuilder:
    def __init__(self) -> None:
        self.cp: list[tuple[str, object]] = [None]
        self.indexes: dict[tuple, int] = {}

    def utf8(self, value: str) -> int:
        key = ("Utf8", value)
        if key not in self.indexes:
            self.indexes[key] = len(self.cp)
            self.cp.append(("Utf8", value))
        return self.indexes[key]

    def class_ref(self, name: str) -> int:
        key = ("Class", name)
        if key not in self.indexes:
            name_index = self.utf8(name)
            self.indexes[key] = len(self.cp)
            self.cp.append(("Class", name_index))
        return self.indexes[key]

    def name_type(self, name: str, desc: str) -> int:
        key = ("NameType", name, desc)
        if key not in self.indexes:
            name_index = self.utf8(name)
            desc_index = self.utf8(desc)
            self.indexes[key] = len(self.cp)
            self.cp.append(("NameType", name_index, desc_index))
        return self.indexes[key]

    def method_ref(self, owner: str, name: str, desc: str) -> int:
        key = ("MethodRef", owner, name, desc)
        if key not in self.indexes:
            owner_index = self.class_ref(owner)
            name_type_index = self.name_type(name, desc)
            self.indexes[key] = len(self.cp)
            self.cp.append(("MethodRef", owner_index, name_type_index))
        return self.indexes[key]

    def field_ref(self, owner: str, name: str, desc: str) -> int:
        key = ("FieldRef", owner, name, desc)
        if key not in self.indexes:
            owner_index = self.class_ref(owner)
            name_type_index = self.name_type(name, desc)
            self.indexes[key] = len(self.cp)
            self.cp.append(("FieldRef", owner_index, name_type_index))
        return self.indexes[key]

    @staticmethod
    def u1(value: int) -> bytes:
        return bytes([value & 0xFF])

    @staticmethod
    def u2(value: int) -> bytes:
        return int(value).to_bytes(2, "big")

    @staticmethod
    def u4(value: int) -> bytes:
        return int(value).to_bytes(4, "big")

    def class_file(
        self,
        *,
        this_class: str,
        super_class: str,
        methods: list[tuple[int, str, str, bytes, int, int]],
        fields: list[tuple[int, str, str]] = None,
        access: int = 0x0021,
        major: int = 49,
    ) -> bytes:
        fields = list(fields or [])
        this_index = self.class_ref(this_class)
        super_index = self.class_ref(super_class)
        code_index = self.utf8("Code")
        for _access, name, desc in fields:
            self.utf8(name)
            self.utf8(desc)
        for _access, name, desc, _code, _max_stack, _max_locals in methods:
            self.utf8(name)
            self.utf8(desc)

        output = bytearray()
        output.extend(b"\xca\xfe\xba\xbe")
        output.extend(self.u2(0))
        output.extend(self.u2(major))
        output.extend(self.u2(len(self.cp)))
        for entry in self.cp[1:]:
            tag = entry[0]
            if tag == "Utf8":
                encoded = entry[1].encode("utf-8")
                output.extend(self.u1(1) + self.u2(len(encoded)) + encoded)
            elif tag == "Class":
                output.extend(self.u1(7) + self.u2(entry[1]))
            elif tag == "NameType":
                output.extend(self.u1(12) + self.u2(entry[1]) + self.u2(entry[2]))
            elif tag == "MethodRef":
                output.extend(self.u1(10) + self.u2(entry[1]) + self.u2(entry[2]))
            elif tag == "FieldRef":
                output.extend(self.u1(9) + self.u2(entry[1]) + self.u2(entry[2]))

        output.extend(self.u2(access))
        output.extend(self.u2(this_index))
        output.extend(self.u2(super_index))
        output.extend(self.u2(0))
        output.extend(self.u2(len(fields)))
        for field_access, name, desc in fields:
            output.extend(self.u2(field_access))
            output.extend(self.u2(self.utf8(name)))
            output.extend(self.u2(self.utf8(desc)))
            output.extend(self.u2(0))

        output.extend(self.u2(len(methods)))
        for method_access, name, desc, code, max_stack, max_locals in methods:
            body = (
                self.u2(max_stack)
                + self.u2(max_locals)
                + self.u4(len(code))
                + code
                + self.u2(0)
                + self.u2(0)
            )
            output.extend(self.u2(method_access))
            output.extend(self.u2(self.utf8(name)))
            output.extend(self.u2(self.utf8(desc)))
            output.extend(self.u2(1))
            output.extend(self.u2(code_index))
            output.extend(self.u4(len(body)))
            output.extend(body)
        output.extend(self.u2(0))
        return bytes(output)


class _BytecodeBuilder:
    def __init__(self) -> None:
        self.buf = bytearray()
        self.labels: dict[str, int] = {}
        self.patches: list[tuple[int, str]] = []

    def emit(self, *values: int | bytes) -> None:
        for value in values:
            if isinstance(value, bytes):
                self.buf.extend(value)
            else:
                self.buf.append(value & 0xFF)

    def label(self, name: str) -> None:
        self.labels[name] = len(self.buf)

    def branch(self, opcode: int, label: str) -> None:
        pos = len(self.buf)
        self.emit(opcode, 0, 0)
        self.patches.append((pos, label))

    def finish(self) -> bytes:
        for pos, label in self.patches:
            offset = self.labels[label] - pos
            self.buf[pos + 1:pos + 3] = (offset & 0xFFFF).to_bytes(2, "big")
        return bytes(self.buf)


def _legacy_applet_resize_bridge_classes() -> dict[str, bytes]:
    def u2(value: int) -> bytes:
        return int(value).to_bytes(2, "big")

    bridge = _SimpleClassBuilder()
    object_init = bridge.method_ref("java/lang/Object", "<init>", "()V")
    listener_init = bridge.method_ref(
        "histolauncher/AppletResizeBridge$Listener", "<init>", "(Ljava/awt/Frame;)V"
    )
    add_component_listener = bridge.method_ref(
        "java/awt/Component", "addComponentListener", "(Ljava/awt/event/ComponentListener;)V"
    )
    set_focusable_window_state = bridge.method_ref("java/awt/Window", "setFocusableWindowState", "(Z)V")
    sync_ref = bridge.method_ref("histolauncher/AppletResizeBridge", "sync", "(Ljava/awt/Frame;)V")
    get_size = bridge.method_ref("java/awt/Component", "getSize", "()Ljava/awt/Dimension;")
    get_insets = bridge.method_ref("java/awt/Container", "getInsets", "()Ljava/awt/Insets;")
    math_max = bridge.method_ref("java/lang/Math", "max", "(II)I")
    get_components = bridge.method_ref("java/awt/Container", "getComponents", "()[Ljava/awt/Component;")
    sync_component = bridge.method_ref(
        "histolauncher/AppletResizeBridge", "syncComponent", "(Ljava/awt/Component;II)V"
    )
    do_layout = bridge.method_ref("java/awt/Container", "doLayout", "()V")
    validate = bridge.method_ref("java/awt/Container", "validate", "()V")
    repaint = bridge.method_ref("java/awt/Component", "repaint", "()V")
    set_size = bridge.method_ref("java/awt/Component", "setSize", "(II)V")
    dimension_init = bridge.method_ref("java/awt/Dimension", "<init>", "(II)V")
    set_preferred_size = bridge.method_ref(
        "java/awt/Component", "setPreferredSize", "(Ljava/awt/Dimension;)V"
    )
    dimension_width = bridge.field_ref("java/awt/Dimension", "width", "I")
    dimension_height = bridge.field_ref("java/awt/Dimension", "height", "I")
    insets_left = bridge.field_ref("java/awt/Insets", "left", "I")
    insets_right = bridge.field_ref("java/awt/Insets", "right", "I")
    insets_top = bridge.field_ref("java/awt/Insets", "top", "I")
    insets_bottom = bridge.field_ref("java/awt/Insets", "bottom", "I")
    listener_class = bridge.class_ref("histolauncher/AppletResizeBridge$Listener")
    container_class = bridge.class_ref("java/awt/Container")
    dimension_class = bridge.class_ref("java/awt/Dimension")

    init_code = b"\x2a\xb7" + u2(object_init) + b"\xb1"

    install = _BytecodeBuilder()
    install.emit(0x2A)
    install.branch(0xC7, "frame_ok")
    install.emit(0xB1)
    install.label("frame_ok")
    install.emit(0x2A, 0x04, 0xB6, u2(set_focusable_window_state))
    install.emit(0x2A, 0xBB, u2(listener_class), 0x59, 0x2A, 0xB7, u2(listener_init))
    install.emit(0xB6, u2(add_component_listener))
    install.emit(0x2A, 0xB8, u2(sync_ref))
    install.emit(0xB1)

    sync = _BytecodeBuilder()
    sync.emit(0x2A)
    sync.branch(0xC7, "frame_ok")
    sync.emit(0xB1)
    sync.label("frame_ok")
    sync.emit(0x2A, 0xB6, u2(get_size), 0x4C)
    sync.emit(0x2A, 0xB6, u2(get_insets), 0x4D)
    sync.emit(0x04, 0x2B, 0xB4, u2(dimension_width), 0x2C, 0xB4, u2(insets_left), 0x64)
    sync.emit(0x2C, 0xB4, u2(insets_right), 0x64, 0xB8, u2(math_max), 0x3E)
    sync.emit(0x04, 0x2B, 0xB4, u2(dimension_height), 0x2C, 0xB4, u2(insets_top), 0x64)
    sync.emit(0x2C, 0xB4, u2(insets_bottom), 0x64, 0xB8, u2(math_max), 0x36, 0x04)
    sync.emit(0x2A, 0xB6, u2(get_components), 0x3A, 0x05)
    sync.emit(0x03, 0x36, 0x06)
    sync.label("loop")
    sync.emit(0x15, 0x06, 0x19, 0x05, 0xBE)
    sync.branch(0xA2, "after_loop")
    sync.emit(0x19, 0x05, 0x15, 0x06, 0x32, 0x1D, 0x15, 0x04, 0xB8, u2(sync_component))
    sync.emit(0x84, 0x06, 0x01)
    sync.branch(0xA7, "loop")
    sync.label("after_loop")
    sync.emit(0x2A, 0xB6, u2(do_layout), 0x2A, 0xB6, u2(validate), 0x2A, 0xB6, u2(repaint))
    sync.emit(0xB1)

    sync_child = _BytecodeBuilder()
    sync_child.emit(0x2A)
    sync_child.branch(0xC7, "component_ok")
    sync_child.emit(0xB1)
    sync_child.label("component_ok")
    sync_child.emit(0x2A, 0x1B, 0x1C, 0xB6, u2(set_size))
    sync_child.emit(0x2A, 0xBB, u2(dimension_class), 0x59, 0x1B, 0x1C, 0xB7, u2(dimension_init))
    sync_child.emit(0xB6, u2(set_preferred_size))
    sync_child.emit(0x2A, 0xC1, u2(container_class))
    sync_child.branch(0x99, "after_container")
    sync_child.emit(0x2A, 0xC0, u2(container_class), 0x4E)
    sync_child.emit(0x2D, 0xB6, u2(get_components), 0x3A, 0x04)
    sync_child.emit(0x03, 0x36, 0x05)
    sync_child.label("loop")
    sync_child.emit(0x15, 0x05, 0x19, 0x04, 0xBE)
    sync_child.branch(0xA2, "after_loop")
    sync_child.emit(0x19, 0x04, 0x15, 0x05, 0x32, 0x1B, 0x1C, 0xB8, u2(sync_component))
    sync_child.emit(0x84, 0x05, 0x01)
    sync_child.branch(0xA7, "loop")
    sync_child.label("after_loop")
    sync_child.emit(0x2D, 0xB6, u2(do_layout), 0x2D, 0xB6, u2(validate))
    sync_child.label("after_container")
    sync_child.emit(0x2A, 0xB6, u2(repaint), 0xB1)

    bridge_class_bytes = bridge.class_file(
        this_class="histolauncher/AppletResizeBridge",
        super_class="java/lang/Object",
        methods=[
            (0x0001, "<init>", "()V", init_code, 1, 1),
            (0x0009, "install", "(Ljava/awt/Frame;)V", install.finish(), 4, 1),
            (0x0009, "sync", "(Ljava/awt/Frame;)V", sync.finish(), 5, 7),
            (0x000A, "syncComponent", "(Ljava/awt/Component;II)V", sync_child.finish(), 5, 6),
        ],
    )

    listener = _SimpleClassBuilder()
    adapter_init = listener.method_ref("java/awt/event/ComponentAdapter", "<init>", "()V")
    frame_field = listener.field_ref(
        "histolauncher/AppletResizeBridge$Listener", "frame", "Ljava/awt/Frame;"
    )
    listener_sync = listener.method_ref("histolauncher/AppletResizeBridge", "sync", "(Ljava/awt/Frame;)V")
    listener_init_code = b"\x2a\xb7" + u2(adapter_init) + b"\x2a\x2b\xb5" + u2(frame_field) + b"\xb1"
    listener_sync_code = b"\x2a\xb4" + u2(frame_field) + b"\xb8" + u2(listener_sync) + b"\xb1"
    listener_class_bytes = listener.class_file(
        this_class="histolauncher/AppletResizeBridge$Listener",
        super_class="java/awt/event/ComponentAdapter",
        fields=[(0x0012, "frame", "Ljava/awt/Frame;")],
        methods=[
            (0x0001, "<init>", "(Ljava/awt/Frame;)V", listener_init_code, 2, 2),
            (0x0001, "componentResized", "(Ljava/awt/event/ComponentEvent;)V", listener_sync_code, 1, 2),
            (0x0001, "componentShown", "(Ljava/awt/event/ComponentEvent;)V", listener_sync_code, 1, 2),
        ],
    )

    return {
        "histolauncher/AppletResizeBridge.class": bridge_class_bytes,
        "histolauncher/AppletResizeBridge$Listener.class": listener_class_bytes,
    }


def _legacy_applet_display_sync_classes() -> dict[str, bytes]:
    def u2(value: int) -> bytes:
        return int(value).to_bytes(2, "big")

    builder = _SimpleClassBuilder()
    object_init = builder.method_ref("java/lang/Object", "<init>", "()V")
    canvas_field = builder.field_ref("com/mojang/minecraft/l", "j", "Ljava/awt/Canvas;")
    game_width = builder.field_ref("com/mojang/minecraft/l", "b", "I")
    game_height = builder.field_ref("com/mojang/minecraft/l", "c", "I")
    game_hud = builder.field_ref("com/mojang/minecraft/l", "w", "Lcom/mojang/minecraft/e/m;")
    game_screen = builder.field_ref("com/mojang/minecraft/l", "o", "Lcom/mojang/minecraft/e/o;")
    get_width = builder.method_ref("java/awt/Component", "getWidth", "()I")
    get_height = builder.method_ref("java/awt/Component", "getHeight", "()I")
    hud_init = builder.method_ref("com/mojang/minecraft/e/m", "<init>", "(Lcom/mojang/minecraft/l;II)V")
    screen_init = builder.method_ref("com/mojang/minecraft/e/o", "a", "(Lcom/mojang/minecraft/l;II)V")
    hud_class = builder.class_ref("com/mojang/minecraft/e/m")

    init_code = b"\x2a\xb7" + u2(object_init) + b"\xb1"

    sync = _BytecodeBuilder()
    sync.emit(0x2A)
    sync.branch(0xC7, "game_ok")
    sync.emit(0xB1)
    sync.label("game_ok")
    sync.emit(0x2A, 0xB4, u2(canvas_field), 0x4C)
    sync.emit(0x2B)
    sync.branch(0xC7, "canvas_ok")
    sync.emit(0xB1)
    sync.label("canvas_ok")
    sync.emit(0x2B, 0xB6, u2(get_width), 0x3D)
    sync.emit(0x2B, 0xB6, u2(get_height), 0x3E)
    sync.emit(0x1C)
    sync.branch(0x9D, "width_ok")
    sync.emit(0xB1)
    sync.label("width_ok")
    sync.emit(0x1D)
    sync.branch(0x9D, "height_ok")
    sync.emit(0xB1)
    sync.label("height_ok")
    sync.emit(0x2A, 0xB4, u2(game_width), 0x1C)
    sync.branch(0xA0, "changed")
    sync.emit(0x2A, 0xB4, u2(game_height), 0x1D)
    sync.branch(0xA0, "changed")
    sync.emit(0xB1)
    sync.label("changed")
    sync.emit(0x2A, 0x1C, 0xB5, u2(game_width))
    sync.emit(0x2A, 0x1D, 0xB5, u2(game_height))
    sync.emit(0x2A, 0xBB, u2(hud_class), 0x59, 0x2A, 0x1C, 0x1D, 0xB7, u2(hud_init))
    sync.emit(0xB5, u2(game_hud))
    sync.emit(0x2A, 0xB4, u2(game_screen), 0x3A, 0x04)
    sync.emit(0x19, 0x04)
    sync.branch(0xC7, "screen_ok")
    sync.emit(0xB1)
    sync.label("screen_ok")
    sync.emit(0x19, 0x04, 0x2A, 0x1C, 0x11, u2(240), 0x68, 0x1D, 0x6C, 0x11, u2(240))
    sync.emit(0xB6, u2(screen_init), 0xB1)

    class_bytes = builder.class_file(
        this_class="histolauncher/AppletDisplaySync",
        super_class="java/lang/Object",
        methods=[
            (0x0001, "<init>", "()V", init_code, 1, 1),
            (0x0009, "sync", "(Lcom/mojang/minecraft/l;)V", sync.finish(), 6, 5),
        ],
    )

    return {"histolauncher/AppletDisplaySync.class": class_bytes}


def _prepare_legacy_applet_window_patch(version_dir: str) -> str:
    wrapper_jar = os.path.join(version_dir, "launchwrapper-1.6.jar")
    if not os.path.isfile(wrapper_jar):
        return ""

    injector_name = "net/minecraft/launchwrapper/injector/AlphaVanillaTweakInjector.class"
    game_name = "com/mojang/minecraft/l.class"
    try:
        with zipfile.ZipFile(wrapper_jar, "r") as src_zip:
            if injector_name not in src_zip.namelist():
                return ""
            injector_payload = src_zip.read(injector_name)
    except Exception:
        return ""

    patched, changed = _class_patch_alpha_applet_window_bridge(injector_payload)
    if not changed:
        return ""

    game_patched = b""
    game_changed = False
    client_jar = os.path.join(version_dir, "client.jar")
    if os.path.isfile(client_jar):
        try:
            with zipfile.ZipFile(client_jar, "r") as src_zip:
                if game_name in src_zip.namelist():
                    game_patched, game_changed = _class_patch_classic_applet_display_sync(src_zip.read(game_name))
        except Exception:
            game_patched = b""
            game_changed = False

    patch_dir = os.path.join(version_dir, ".histolauncher")
    patch_name = "legacy-applet-window-patch-v7.jar"
    patch_path = os.path.join(patch_dir, patch_name)
    try:
        source_mtime = max(os.path.getmtime(wrapper_jar), os.path.getmtime(client_jar) if os.path.exists(client_jar) else 0)
        patch_mtime = os.path.getmtime(patch_path) if os.path.exists(patch_path) else 0
        if patch_mtime >= source_mtime:
            return os.path.relpath(patch_path, version_dir).replace("\\", "/")
    except OSError:
        pass

    os.makedirs(patch_dir, exist_ok=True)
    tmp_path = patch_path + ".tmp"
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as dst_zip:
            dst_zip.writestr(injector_name, patched)
            for helper_name, helper_payload in _legacy_applet_resize_bridge_classes().items():
                dst_zip.writestr(helper_name, helper_payload)
            if game_changed:
                dst_zip.writestr(game_name, game_patched)
                for helper_name, helper_payload in _legacy_applet_display_sync_classes().items():
                    dst_zip.writestr(helper_name, helper_payload)
        os.replace(tmp_path, patch_path)
        print(colorize_log(
            "[launcher] Prepared legacy applet window patch for maximized startup and resize sync"
        ))
        return os.path.relpath(patch_path, version_dir).replace("\\", "/")
    except Exception as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        print(colorize_log(
            f"[launcher] Warning: Could not prepare legacy applet window patch: {e}"
        ))
        return ""


def _java_class_file(
    *, this_class: str, super_class: str, methods: list[tuple[int, str, str, bytes, int, int]]
) -> bytes:
    cp: list[tuple[str, object]] = [None]
    indexes: dict[tuple, int] = {}

    def add_utf8(value: str) -> int:
        key = ("Utf8", value)
        if key not in indexes:
            indexes[key] = len(cp)
            cp.append(("Utf8", value))
        return indexes[key]

    def add_class(name: str) -> int:
        key = ("Class", name)
        if key not in indexes:
            name_index = add_utf8(name)
            indexes[key] = len(cp)
            cp.append(("Class", name_index))
        return indexes[key]

    def add_name_type(name: str, desc: str) -> int:
        key = ("NameType", name, desc)
        if key not in indexes:
            name_index = add_utf8(name)
            desc_index = add_utf8(desc)
            indexes[key] = len(cp)
            cp.append(("NameType", name_index, desc_index))
        return indexes[key]

    def add_method_ref(owner: str, name: str, desc: str) -> int:
        key = ("MethodRef", owner, name, desc)
        if key not in indexes:
            owner_index = add_class(owner)
            name_type_index = add_name_type(name, desc)
            indexes[key] = len(cp)
            cp.append(("MethodRef", owner_index, name_type_index))
        return indexes[key]

    this_index = add_class(this_class)
    super_index = add_class(super_class)
    code_index = add_utf8("Code")
    object_init = add_method_ref("java/lang/Object", "<init>", "()V")
    allocate_direct = add_method_ref(
        "java/nio/ByteBuffer", "allocateDirect", "(I)Ljava/nio/ByteBuffer;"
    )
    put_bytes = add_method_ref(
        "java/nio/ByteBuffer", "put", "([B)Ljava/nio/ByteBuffer;"
    )
    put_bytes_range = add_method_ref(
        "java/nio/ByteBuffer", "put", "([BII)Ljava/nio/ByteBuffer;"
    )
    flip = add_method_ref("java/nio/ByteBuffer", "flip", "()Ljava/nio/Buffer;")

    def u1(value: int) -> bytes:
        return bytes([value & 0xFF])

    def u2(value: int) -> bytes:
        return int(value).to_bytes(2, "big")

    def u4(value: int) -> bytes:
        return int(value).to_bytes(4, "big")

    def method_code(max_stack: int, max_locals: int, code: bytes) -> bytes:
        body = u2(max_stack) + u2(max_locals) + u4(len(code)) + code + u2(0) + u2(0)
        return u2(code_index) + u4(len(body)) + body

    init_code = b"\x2a\xb7" + u2(object_init) + b"\xb1"
    wrap_code = (
        b"\x2a\xbe\xb8" + u2(allocate_direct)
        + b"\x4c\x2b\x2a\xb6" + u2(put_bytes)
        + b"\x57\x2b\xb6" + u2(flip)
        + b"\x57\x2b\xb0"
    )
    wrap_range_code = (
        b"\x1c\xb8" + u2(allocate_direct)
        + b"\x4e\x2d\x2a\x1b\x1c\xb6" + u2(put_bytes_range)
        + b"\x57\x2d\xb6" + u2(flip)
        + b"\x57\x2d\xb0"
    )

    methods.extend([
        (0x0001, "<init>", "()V", init_code, 1, 1),
        (0x0009, "wrap", "([B)Ljava/nio/ByteBuffer;", wrap_code, 2, 2),
        (0x0009, "wrap", "([BII)Ljava/nio/ByteBuffer;", wrap_range_code, 4, 4),
    ])

    for _access, name, desc, _code, _max_stack, _max_locals in methods:
        add_utf8(name)
        add_utf8(desc)

    output = bytearray()
    output.extend(b"\xca\xfe\xba\xbe")
    output.extend(u2(0))
    output.extend(u2(49))
    output.extend(u2(len(cp)))
    for entry in cp[1:]:
        tag = entry[0]
        if tag == "Utf8":
            encoded = entry[1].encode("utf-8")
            output.extend(u1(1) + u2(len(encoded)) + encoded)
        elif tag == "Class":
            output.extend(u1(7) + u2(entry[1]))
        elif tag == "NameType":
            output.extend(u1(12) + u2(entry[1]) + u2(entry[2]))
        elif tag == "MethodRef":
            output.extend(u1(10) + u2(entry[1]) + u2(entry[2]))

    output.extend(u2(0x0021))
    output.extend(u2(this_index))
    output.extend(u2(super_index))
    output.extend(u2(0))
    output.extend(u2(0))
    output.extend(u2(len(methods)))
    for access, name, desc, code, max_stack, max_locals in methods:
        output.extend(u2(access))
        output.extend(u2(add_utf8(name)))
        output.extend(u2(add_utf8(desc)))
        output.extend(u2(1))
        output.extend(method_code(max_stack, max_locals, code))
    output.extend(u2(0))
    return bytes(output)


def _legacy_direct_buffer_helper_class() -> bytes:
    return _java_class_file(
        this_class="histolauncher/DBufX",
        super_class="java/lang/Object",
        methods=[],
    )


def _prepare_legacy_direct_buffer_sound_patch(version_dir: str) -> str:
    client_jar = os.path.join(version_dir, "client.jar")
    if not os.path.isfile(client_jar):
        return ""

    openal_patch_classes = [
        "paulscode/sound/libraries/LibraryLWJGLOpenAL.class",
        "paulscode/sound/libraries/ChannelLWJGLOpenAL.class",
    ]
    sound_manager_class = "net/minecraft/client/e/c.class"
    try:
        with zipfile.ZipFile(client_jar, "r") as src_zip:
            names = set(src_zip.namelist())
            class_payloads = {
                name: src_zip.read(name)
                for name in openal_patch_classes + [sound_manager_class]
                if name in names
            }
    except Exception:
        return ""

    if not class_payloads:
        return ""

    patched_payloads: dict[str, bytes] = {}
    for name in openal_patch_classes:
        payload = class_payloads.get(name)
        if not payload:
            continue
        patched, changed = _class_patch_bytebuffer_wrap_calls(payload)
        if changed:
            patched_payloads[name] = patched

    sound_manager_payload = class_payloads.get(sound_manager_class)
    if sound_manager_payload:
        patched, changed = _class_patch_indev_missing_music_guard(sound_manager_payload)
        if changed:
            patched_payloads[sound_manager_class] = patched

    if not patched_payloads:
        return ""

    patch_dir = os.path.join(version_dir, ".histolauncher")
    patch_name = "legacy-sound-compat-patch-v4.jar"
    patch_path = os.path.join(patch_dir, patch_name)
    try:
        patch_mtime = os.path.getmtime(patch_path) if os.path.exists(patch_path) else 0
        if patch_mtime >= os.path.getmtime(client_jar):
            return os.path.relpath(patch_path, version_dir).replace("\\", "/")
    except OSError:
        pass

    os.makedirs(patch_dir, exist_ok=True)
    tmp_path = patch_path + ".tmp"
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as dst_zip:
            dst_zip.writestr("histolauncher/DBufX.class", _legacy_direct_buffer_helper_class())
            for name, patched in patched_payloads.items():
                dst_zip.writestr(name, patched)
        os.replace(tmp_path, patch_path)
        print(colorize_log(
            "[launcher] Prepared legacy direct-buffer sound patch for old OpenAL runtime"
        ))
        return os.path.relpath(patch_path, version_dir).replace("\\", "/")
    except Exception as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        print(colorize_log(
            f"[launcher] Warning: Could not prepare legacy direct-buffer sound patch: {e}"
        ))
        return ""


def _normalize_legacy_language_code(lang_code: str) -> str:
    value = (lang_code or "").strip()
    if not value:
        return "en_US"

    value = value.replace("-", "_")
    parts = value.split("_")
    if len(parts) >= 2 and parts[0] and parts[1]:
        return f"{parts[0].lower()}_{parts[1].upper()}"
    return value


def _legacy_default_audio_options(version_identifier: str) -> tuple[str, str]:
    raw = (version_identifier or "").replace("\\", "/")
    base = raw.split("/", 1)[1] if "/" in raw else raw
    lowered = base.strip().lower()
    if lowered.startswith(("a", "c", "inf-", "in-", "rd-")):
        return "music:true", "sound:true"
    return "music:1.0", "sound:1.0"


def _prepare_legacy_options_file(version_identifier: str, game_dir: str) -> None:
    if not _is_legacy_pre16_runtime(version_identifier):
        return

    if not game_dir:
        return

    default_music_line, default_sound_line = _legacy_default_audio_options(version_identifier)
    options_path = os.path.join(game_dir, "options.txt")
    if not os.path.exists(options_path):
        try:
            os.makedirs(game_dir, exist_ok=True)
            with open(options_path, "w", encoding="utf-8") as f:
                f.write(f"{default_music_line}\n{default_sound_line}\nlang:en_US\n")
            print(colorize_log(
                "[launcher] Created legacy options.txt with audio defaults and lang:en_US"
            ))
        except Exception as e:
            print(colorize_log(f"[launcher] Warning: Could not create legacy options.txt: {e}"))
        return

    try:
        with open(options_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(colorize_log(
            f"[launcher] Warning: Could not read options.txt for legacy normalization: {e}"
        ))
        return

    changed = False
    found_lang = False
    found_music = False
    found_sound = False
    normalized_lines: list = []

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line.strip():
            changed = True
            continue
        if ":" not in line:
            changed = True
            print(colorize_log(
                f"[launcher] Removed malformed legacy option line: {line}"
            ))
            continue

        key, value = line.split(":", 1)
        if key == "lastServer" and value == "":
            normalized_lines.append("lastServer: \n")
            changed = True
            print(colorize_log("[launcher] Normalized empty legacy lastServer option"))
        elif line.startswith("music:"):
            found_music = True
            normalized_lines.append(raw_line if raw_line.endswith("\n") else (raw_line + "\n"))
        elif line.startswith("sound:"):
            found_sound = True
            normalized_lines.append(raw_line if raw_line.endswith("\n") else (raw_line + "\n"))
        elif line.startswith("lang:"):
            found_lang = True
            current = line.split(":", 1)[1]
            normalized = _normalize_legacy_language_code(current)
            if normalized != current:
                changed = True
                print(colorize_log(
                    f"[launcher] Normalized legacy lang option: {current} -> {normalized}"
                ))
            normalized_lines.append(f"lang:{normalized}\n")
        else:
            normalized_lines.append(raw_line if raw_line.endswith("\n") else (raw_line + "\n"))

    if not found_music:
        normalized_lines.insert(0, f"{default_music_line}\n")
        changed = True
        print(colorize_log(f"[launcher] Added missing legacy music option: {default_music_line}"))

    if not found_sound:
        insert_at = 1 if not found_music else 0
        normalized_lines.insert(insert_at, f"{default_sound_line}\n")
        changed = True
        print(colorize_log(f"[launcher] Added missing legacy sound option: {default_sound_line}"))

    if not found_lang:
        normalized_lines.append("lang:en_US\n")
        changed = True
        print(colorize_log("[launcher] Added missing legacy lang option: en_US"))

    if not changed:
        return

    try:
        with open(options_path, "w", encoding="utf-8") as f:
            f.writelines(normalized_lines)
    except Exception as e:
        print(colorize_log(
            f"[launcher] Warning: Could not write normalized options.txt: {e}"
        ))


def _prepare_legacy_forge_merged_client_jar(
    version_dir: str, loader_version: str = None
) -> str:
    from core.launch.loader import _get_loader_version

    actual_loader_version = loader_version or _get_loader_version(version_dir, "forge")
    if not actual_loader_version:
        return ""

    forge_jar = _find_forge_core_jar(version_dir, actual_loader_version)
    client_jar = os.path.join(version_dir, "client.jar")
    if not forge_jar or not os.path.exists(client_jar):
        return ""

    fml_jar = None
    modloader_jar = ""
    forge_loader_path = os.path.join(version_dir, "loaders", "forge", actual_loader_version)
    if os.path.isdir(forge_loader_path):
        for fname in os.listdir(forge_loader_path):
            if fname.startswith("fml-") and fname.endswith(".jar"):
                fml_jar = os.path.join(forge_loader_path, fname)
                break

    if _legacy_forge_requires_modloader(version_dir, actual_loader_version):
        modloader_jar = _find_modloader_runtime_jar(version_dir)
        if modloader_jar:
            print(colorize_log(
                f"[launcher] Found ModLoader runtime for legacy Forge: "
                f"{os.path.basename(modloader_jar)}"
            ))

    merge_dir = os.path.join(
        version_dir, "loaders", "forge", actual_loader_version, ".legacy_merged"
    )
    os.makedirs(merge_dir, exist_ok=True)

    merged_name = f"forge-{actual_loader_version}-client-merged.jar"
    merged_path = os.path.join(merge_dir, merged_name)

    source_jars = [j for j in [fml_jar, modloader_jar, forge_jar, client_jar] if j and os.path.exists(j)]
    try:
        merged_mtime = os.path.getmtime(merged_path) if os.path.exists(merged_path) else 0
        source_mtime = max(os.path.getmtime(j) for j in source_jars)
        if merged_mtime >= source_mtime:
            return os.path.relpath(merged_path, version_dir).replace("\\", "/")
    except OSError:
        pass

    tmp_path = merged_path + ".tmp"
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    seen_entries: set = set()
    forge_count = 0
    client_count = 0

    def _copy_jar_entries(src_jar: str, *, skip_existing: bool) -> int:
        copied = 0
        with zipfile.ZipFile(src_jar, "r") as src_zip, zipfile.ZipFile(
            tmp_path, "a", compression=zipfile.ZIP_DEFLATED
        ) as dst_zip:
            for entry in src_zip.infolist():
                name = entry.filename
                if entry.is_dir():
                    continue
                if name.upper().startswith("META-INF/"):
                    continue
                if skip_existing and name in seen_entries:
                    continue

                with src_zip.open(entry, "r") as src_file:
                    dst_zip.writestr(name, src_file.read())
                seen_entries.add(name)
                copied += 1
        return copied

    fml_count = 0
    modloader_count = 0
    try:
        forge_count = _copy_jar_entries(forge_jar, skip_existing=False)
        if fml_jar and os.path.exists(fml_jar):
            fml_count = _copy_jar_entries(fml_jar, skip_existing=True)
        if modloader_jar and os.path.exists(modloader_jar):
            modloader_count = _copy_jar_entries(modloader_jar, skip_existing=True)
        client_count = _copy_jar_entries(client_jar, skip_existing=True)
        os.replace(tmp_path, merged_path)
        print(colorize_log(
            f"[launcher] Prepared legacy merged Forge jar: {merged_name} "
            f"(fml entries {fml_count}, modloader entries {modloader_count}, "
            f"forge entries {forge_count}, client fallback entries {client_count})"
        ))

        _patch_fml_library_hashes(merged_path)

    except Exception as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        print(colorize_log(
            f"[launcher] Warning: Could not prepare legacy merged Forge jar: {e}"
        ))
        return ""

    return os.path.relpath(merged_path, version_dir).replace("\\", "/")


_FML_HASH_FIXUPS = {
    b"98308890597acb64047f7e896638e0d98753ae82": b"2518725354c7a6a491a323249b9e86846b00df09",
}


def _patch_fml_library_hashes(merged_jar_path: str) -> None:
    target_entry = "cpw/mods/fml/relauncher/CoreFMLLibraries.class"
    try:
        with zipfile.ZipFile(merged_jar_path, "r") as zin:
            if target_entry not in zin.namelist():
                return
            data = zin.read(target_entry)

        patched = False
        for old_hash, new_hash in _FML_HASH_FIXUPS.items():
            if old_hash in data:
                data = data.replace(old_hash, new_hash, 1)
                patched = True

        if not patched:
            return

        tmp_path = merged_jar_path + ".patch_tmp"
        with zipfile.ZipFile(merged_jar_path, "r") as zin, \
             zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == target_entry:
                    zout.writestr(item, data)
                else:
                    zout.writestr(item, zin.read(item.filename))
        os.replace(tmp_path, merged_jar_path)
        print(colorize_log(
            "[launcher] Patched CoreFMLLibraries.class in merged jar "
            "(updated dead fmllibs checksums to Maven Central equivalents)"
        ))
    except Exception as e:
        print(colorize_log(
            f"[launcher] Warning: Could not patch FML library hashes: {e}"
        ))


_FML_LIBRARIES = [
    {
        "name": "argo-2.25.jar",
        "url": "https://repo1.maven.org/maven2/net/sourceforge/argo/argo/2.25/argo-2.25.jar",
        "sha1": "bb672829fde76cb163004752b86b0484bd0a7f4b",
    },
    {
        "name": "guava-12.0.1.jar",
        "url": "https://repo1.maven.org/maven2/com/google/guava/guava/12.0.1/guava-12.0.1.jar",
        "sha1": "b8e78b9af7bf45900e14c6f958486b6ca682195f",
    },
    {
        "name": "asm-all-4.0.jar",
        "url": "https://repo1.maven.org/maven2/org/ow2/asm/asm-all/4.0/asm-all-4.0.jar",
        "sha1": "2518725354c7a6a491a323249b9e86846b00df09",
    },
    {
        "name": "bcprov-jdk15on-147.jar",
        "url": "https://repo1.maven.org/maven2/org/bouncycastle/bcprov-jdk15on/1.47/bcprov-jdk15on-1.47.jar",
        "sha1": "b6f5d9926b0afbde9f4dbe3db88c5247be7794bb",
    },
]


def _stage_legacy_fml_libraries(game_dir: str) -> None:
    lib_dir = os.path.join(game_dir, "lib")
    os.makedirs(lib_dir, exist_ok=True)

    for lib in _FML_LIBRARIES:
        dest = os.path.join(lib_dir, lib["name"])
        if os.path.isfile(dest):
            try:
                with open(dest, "rb") as f:
                    actual = hashlib.sha1(f.read()).hexdigest()
                if actual == lib["sha1"]:
                    continue
            except OSError:
                pass

        try:
            print(colorize_log(f"[launcher] Downloading FML library: {lib['name']}"))
            data = None
            last_error = None
            for candidate_url in _iter_proxy_url_candidates(lib["url"]):
                try:
                    req = urllib.request.Request(
                        candidate_url, headers={"User-Agent": "Histolauncher/1.0"}
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        data = resp.read()
                    break
                except Exception as e:
                    last_error = e

            if data is None:
                raise RuntimeError(last_error or "download failed")

            actual = hashlib.sha1(data).hexdigest()
            if actual != lib["sha1"]:
                print(colorize_log(
                    f"[launcher] Warning: SHA1 mismatch for {lib['name']} "
                    f"(got {actual}, expected {lib['sha1']})"
                ))
                continue
            with open(dest, "wb") as f:
                f.write(data)
            print(colorize_log(f"[launcher] Staged FML library: {lib['name']}"))
        except Exception as e:
            print(colorize_log(
                f"[launcher] Warning: Could not download {lib['name']}: {e}"
            ))
