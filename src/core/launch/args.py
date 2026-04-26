from __future__ import annotations

import os
import re
import zipfile
from uuid import NAMESPACE_DNS, uuid3

from core.launch.paths import _load_data_ini  # noqa: F401  (re-export potential)
from core.logger import colorize_log
from core.settings import get_base_dir

__all__ = [
    "_expand_placeholders",
    "_extract_tweak_class_from_arg_list",
    "_extract_tweak_class_from_arg_string",
    "_is_legacy_http_proxy_needed",
    "_is_legacy_pre16_runtime",
    "_jar_has_class",
    "_classpath_has_class",
    "_parse_mc_version",
    "_resolve_runtime_main_class",
    "username_to_uuid",
]


def _jar_has_class(jar_path: str, class_name: str) -> bool:
    if not jar_path or not os.path.isfile(jar_path) or not class_name:
        return False
    class_path = class_name.replace('.', '/') + '.class'
    try:
        with zipfile.ZipFile(jar_path, 'r') as zf:
            return class_path in zf.namelist()
    except Exception:
        return False


def _classpath_has_class(version_dir: str, classpath_entries: list, class_name: str) -> bool:
    for entry in classpath_entries or []:
        rel = str(entry or "").strip()
        if not rel:
            continue
        abs_path = os.path.normpath(os.path.join(version_dir, rel))

        if os.path.isfile(abs_path) and abs_path.lower().endswith('.jar'):
            if _jar_has_class(abs_path, class_name):
                return True
            continue

        if os.path.isdir(abs_path):
            class_rel = class_name.replace('.', os.sep) + '.class'
            if os.path.isfile(os.path.join(abs_path, class_rel)):
                return True

    return False


def _parse_mc_version(version_identifier):
    if "/" in version_identifier:
        _, base = version_identifier.split("/", 1)
    else:
        base = version_identifier
    b = base.lower()
    m = re.search(r"\d+w\d+[a-z]", b)
    if m:
        return 99, 0
    base = base.split("-", 1)[0]
    parts = base.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return major, minor
    except Exception:
        return None, None


def _is_legacy_pre16_runtime(version_identifier: str) -> bool:
    raw = (version_identifier or "").replace("\\", "/")
    base = raw.split("/", 1)[1] if "/" in raw else raw
    b = base.strip().lower()

    if re.match(r'^(?:b1|a1|c0|inf-|in-|rd-)', b):
        return True

    major, minor = _parse_mc_version(version_identifier)
    if major is None:
        return False
    if major > 1:
        return False
    return minor is not None and minor < 6


def _is_legacy_http_proxy_needed(version_identifier):
    return _is_legacy_pre16_runtime(version_identifier)


def _resolve_runtime_main_class(
    version_identifier: str,
    version_dir: str,
    classpath_entries: list,
    configured_main: str,
) -> str:
    main_class = (configured_main or "").strip() or "net.minecraft.client.Minecraft"
    client_jar = os.path.join(version_dir, "client.jar")

    if _jar_has_class(client_jar, main_class) or _classpath_has_class(version_dir, classpath_entries, main_class):
        return main_class

    if main_class.startswith("net.minecraft.launchwrapper"):
        print(colorize_log(
            f"[launcher] main_class '{main_class}' not found on classpath; "
            f"keeping configured class (missing LaunchWrapper dependency)"
        ))
        return main_class

    legacy_hint = _is_legacy_pre16_runtime(version_identifier)
    candidates: list[str] = []

    if legacy_hint:
        candidates.extend([
            "net.minecraft.client.MinecraftApplet",
            "com.mojang.minecraft.MinecraftApplet",
            "net.minecraft.client.Minecraft",
            "com.mojang.minecraft.Minecraft",
        ])
    else:
        candidates.extend([
            "net.minecraft.client.main.Main",
            "net.minecraft.client.Minecraft",
            "net.minecraft.client.MinecraftApplet",
            "com.mojang.minecraft.Minecraft",
            "com.mojang.minecraft.MinecraftApplet",
        ])

    for candidate in candidates:
        if _jar_has_class(client_jar, candidate):
            print(colorize_log(
                f"[launcher] main_class '{main_class}' not found in client.jar; using '{candidate}'"
            ))
            return candidate

    return main_class


def username_to_uuid(username: str) -> str:
    offline_uuid = uuid3(NAMESPACE_DNS, "OfflinePlayer:" + username)
    return str(offline_uuid).replace("-", "")


def _expand_placeholders(args_str, version_identifier, game_dir, version_dir,
                         global_settings, meta, assets_root_override=None):
    from server.yggdrasil import _get_username_and_uuid  # lazy

    username, auth_uuid_raw = _get_username_and_uuid()
    base_dir = get_base_dir()
    assets_root = assets_root_override or os.path.join(base_dir, "assets")
    asset_index_name = meta.get("asset_index") or ""
    version_type = meta.get("version_type") or ""
    auth_uuid = (
        f"{auth_uuid_raw[0:8]}-{auth_uuid_raw[8:12]}-{auth_uuid_raw[12:16]}-"
        f"{auth_uuid_raw[16:20]}-{auth_uuid_raw[20:]}"
    )
    auth_access_token = "0"
    user_type = "legacy"
    user_properties = "{}"
    game_dir = game_dir or ""

    mc_version = version_identifier.split("/")[-1] if "/" in version_identifier else version_identifier

    replacements = {
        "${auth_player_name}": username,
        "${auth_uuid}": auth_uuid,
        "${auth_access_token}": auth_access_token,
        "${user_type}": user_type,
        "${user_properties}": user_properties,
        "${version_name}": mc_version,
        "${game_directory}": game_dir,
        "${gameDir}": game_dir,
        "${assets_root}": assets_root,
        "${game_assets}": assets_root,
        "${assets_index_name}": asset_index_name,
        "${version_type}": version_type,
        "${resolution_width}": "854",
        "${resolution_height}": "480",
        "${auth_session}": "0",
        "${auth_player_type}": "legacy",
    }

    if not asset_index_name:
        print(colorize_log(f"[launcher] DEBUG: asset_index not in metadata for {version_identifier}"))
    print(colorize_log(
        f"[launcher] DEBUG: Expanding placeholders - assets_root={assets_root}, asset_index={asset_index_name}"
    ))

    args_before_expand = args_str.split()
    filtered_before_expand: list[str] = []
    skip_next = False

    for i, arg in enumerate(args_before_expand):
        if skip_next:
            skip_next = False
            continue
        if arg in ("--clientId", "--xuid") or arg.startswith("--quickPlay"):
            if "=" not in arg and i + 1 < len(args_before_expand) and not args_before_expand[i + 1].startswith("--"):
                skip_next = True
            continue
        filtered_before_expand.append(arg)

    args_str_filtered = " ".join(filtered_before_expand)

    out = args_str_filtered
    for k, v in replacements.items():
        if k in out:
            out = out.replace(k, v)
    args = out.split()

    unresolved = [arg for arg in args if "${" in arg and "}" in arg]
    if unresolved:
        print(colorize_log(f"[launcher] DEBUG: Unresolved placeholders found: {unresolved}"))

    filtered: list[str] = []
    skip_next = False
    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if "${" in arg and "}" in arg:
            print(colorize_log(f"[launcher] DEBUG: Filtering out unresolved placeholder: {arg}"))
            continue
        if arg.startswith("--gameDir"):
            if "=" not in arg:
                skip_next = True
            continue
        if arg.startswith("--demo") or arg.startswith("--width") or arg.startswith("--height"):
            continue
        filtered.append(arg)

    final: list[str] = []
    i = 0
    while i < len(filtered) and not filtered[i].startswith("--"):
        final.append(filtered[i])
        i += 1

    while i < len(filtered):
        arg = filtered[i]

        if arg.startswith("--"):
            needs_arg = arg in {
                '--username', '--version', '--gameDir', '--gameDirectory',
                '--assetsDir', '--assetIndex', '--uuid', '--accessToken',
                '--userType', '--versionType', '--userProperties', '--tweakClass'
            } or arg.split('=', 1)[0] in {
                '--username', '--version', '--gameDir', '--gameDirectory',
                '--assetsDir', '--assetIndex', '--uuid', '--accessToken',
                '--userType', '--versionType', '--userProperties', '--tweakClass'
            }

            has_value_inline = "=" in arg

            final.append(arg)
            i += 1

            if needs_arg and not has_value_inline and i < len(filtered) and not filtered[i].startswith("--"):
                final.append(filtered[i])
                i += 1
        else:
            if final and final[-1].startswith("--") and "=" not in final[-1]:
                final.append(arg)
            i += 1

    return " ".join(final)


def _extract_tweak_class_from_arg_string(arg_str: str) -> str:
    if not isinstance(arg_str, str) or not arg_str.strip():
        return ""
    match = re.search(r"(?:^|\s)--tweakClass\s+([^\s]+)", arg_str)
    if match:
        return match.group(1).strip()
    match = re.search(r"(?:^|\s)--tweakClass=([^\s]+)", arg_str)
    if match:
        return match.group(1).strip()
    return ""


def _extract_tweak_class_from_arg_list(arg_list: list) -> str:
    if not isinstance(arg_list, list):
        return ""
    for idx, arg in enumerate(arg_list):
        if isinstance(arg, str):
            if arg == "--tweakClass" and idx + 1 < len(arg_list) and isinstance(arg_list[idx + 1], str):
                return arg_list[idx + 1].strip()
            if arg.startswith("--tweakClass="):
                return arg.split("=", 1)[1].strip()
    return ""
