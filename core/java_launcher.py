# core/java_launcher.py
import os
import subprocess
import platform
from uuid import uuid3, NAMESPACE_DNS
from core.settings import load_global_settings, get_base_dir


def _native_subfolder_for_platform():
    system = platform.system().lower()
    if "windows" in system:
        return os.path.join("native", "windows")
    if "linux" in system:
        return os.path.join("native", "linux")
    if "darwin" in system or "mac" in system:
        return os.path.join("native", "mac")
    return os.path.join("native", "windows")


def _join_classpath(base_dir, entries):
    sep = os.pathsep
    abs_entries = [os.path.join(base_dir, e) for e in entries]
    return sep.join(abs_entries)


def _load_data_ini(version_dir):
    data_ini = os.path.join(version_dir, "data.ini")
    if not os.path.exists(data_ini):
        return {}
    meta = {}
    with open(data_ini, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                meta[k.strip()] = v.strip()
    return meta


def _parse_mc_version(version_identifier):
    if "/" in version_identifier:
        _, base = version_identifier.split("/", 1)
    else:
        base = version_identifier
    base = base.split("-", 1)[0]
    parts = base.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return major, minor
    except Exception:
        return None, None


def _is_authlib_injector_needed(version_identifier):
    major, minor = _parse_mc_version(version_identifier)
    if major is None:
        return False
    if major > 1:
        return True
    if major == 1 and minor >= 13:
        return True
    return False


def username_to_uuid(username: str) -> str:
    offline_uuid = uuid3(NAMESPACE_DNS, "OfflinePlayer:" + username)
    return str(offline_uuid).replace("-", "")


def _expand_placeholders(args_str, version_identifier, game_dir, version_dir, global_settings, meta):
    username = (global_settings.get("username") or "Player").strip() or "Player"
    base_dir = get_base_dir()
    assets_root = os.path.join(base_dir, "assets")
    asset_index_name = meta.get("asset_index") or ""
    version_type = meta.get("version_type") or ""
    auth_uuid = "00000000-0000-0000-0000-000000000000"
    auth_access_token = "0"
    user_type = "legacy"
    user_properties = "{}"
    game_dir = game_dir or ""
    replacements = {
        "${auth_player_name}": username,
        "${auth_uuid}": auth_uuid,
        "${auth_access_token}": auth_access_token,
        "${user_type}": user_type,
        "${user_properties}": user_properties,
        "${version_name}": version_identifier,
        "${game_directory}": game_dir,
        "${gameDir}": game_dir,
        "${assets_root}": assets_root,
        "${assets_index_name}": asset_index_name,
        "${version_type}": version_type,
        "${resolution_width}": "854",
        "${resolution_height}": "480",
    }
    out = args_str
    for k, v in replacements.items():
        out = out.replace(k, v)
    args = out.split()
    filtered = [arg for arg in args if not arg.startswith("--demo") and not arg.startswith("--gameDir") and not arg.startswith("--quickPlay")]
    return " ".join(filtered)


def launch_version(version_identifier, username_override=None):
    base_dir = get_base_dir()
    clients_dir = os.path.join(base_dir, "clients")
    if "/" in version_identifier:
        parts = version_identifier.replace("\\", "/").split("/", 1)
        category, folder = parts[0], parts[1]
        version_dir = os.path.join(clients_dir, category.lower(), folder)
    else:
        version_dir = None
        for cat in os.listdir(clients_dir):
            p = os.path.join(clients_dir, cat, version_identifier)
            if os.path.isdir(p):
                version_dir = p
                break
        if not version_dir:
            print("ERROR: Version directory not found for", version_identifier)
            return False
    meta = _load_data_ini(version_dir)
    main_class = meta.get("main_class") or "net.minecraft.client.Minecraft"
    classpath_entries = [p.strip() for p in (meta.get("classpath") or "client.jar").split(",") if p.strip()]
    classpath = _join_classpath(version_dir, classpath_entries)
    global_settings = load_global_settings()
    username = username_override or global_settings.get("username", "Player")
    min_ram = global_settings.get("min_ram", "64M")
    max_ram = global_settings.get("max_ram", "2048M")
    storage_mode = global_settings.get("storage_directory", "global").lower()
    if storage_mode == "version":
        game_dir = os.path.join(version_dir, "data")
    else:
        system = platform.system().lower()
        if "windows" in system:
            user_profile = os.environ.get("APPDATA")
            game_dir = os.path.join(user_profile, ".minecraft")
        else:
            game_dir = os.path.expanduser(os.path.join("~", ".minecraft"))
    cmd = ["java", f"-Xms{min_ram}", f"-Xmx{max_ram}"]
    if _is_authlib_injector_needed(version_identifier):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        authlib_path = os.path.join(project_root, "assets", "authlib-injector.jar")
        if os.path.exists(authlib_path):
            port_str = os.environ.get("HISTOLAUNCHER_PORT")
            if port_str:
                try:
                    ygg_port = int(port_str)
                except ValueError:
                    ygg_port = 0
            else:
                ygg_port = 0
            if ygg_port > 0:
                ygg_url = f"http://127.0.0.1:{ygg_port}/authserver"
                cmd.append(f"-javaagent:{authlib_path}={ygg_url}")
    native_folder = meta.get("native_subfolder") or _native_subfolder_for_platform()
    native_path = os.path.join(version_dir, native_folder)
    if os.path.isdir(native_path):
        cmd.append(f"-Djava.library.path={native_path}")
    cmd.extend(["-cp", classpath])
    cmd.append(main_class)
    if game_dir is not None:
        cmd.extend(["--gameDir", game_dir])
    extra = meta.get("extra_jvm_args")
    if extra:
        expanded = _expand_placeholders(extra, version_identifier, game_dir, version_dir, global_settings, meta)
        cmd.extend(expanded.split())
    else:
        cmd.append(username)
    print("Launching version:", version_identifier)
    print("Version dir:", version_dir)
    print("Command:", " ".join(cmd))
    try:
        subprocess.Popen(cmd, cwd=version_dir)
        return True
    except Exception as e:
        print("ERROR launching:", e)
        return False
