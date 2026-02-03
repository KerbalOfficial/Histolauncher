# core/java_launcher.py
import os
import subprocess
import platform
from core.settings import load_global_settings

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
    abs_entries.append(base_dir)
    return sep.join(abs_entries)

def launch_version(version_identifier, username_override=None):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    clients_dir = os.path.join(base_dir, "clients")

    if "/" in version_identifier or "\\" in version_identifier:
        parts = version_identifier.replace("\\", "/").split("/", 1)
        category, folder = parts[0], parts[1]
        version_dir = os.path.join(clients_dir, category, folder)
    else:
        candidate = os.path.join(clients_dir, version_identifier)
        if os.path.isdir(candidate):
            version_dir = candidate
        else:
            found = None
            for cat in os.listdir(clients_dir):
                p = os.path.join(clients_dir, cat, version_identifier)
                if os.path.isdir(p):
                    found = p
                    break
            if not found:
                print("ERROR: Version directory not found for", version_identifier)
                return False
            version_dir = found

    if not os.path.isdir(version_dir):
        print("ERROR: Version directory does not exist:", version_dir)
        return False

    data_ini = os.path.join(version_dir, "data.ini")
    if not os.path.exists(data_ini):
        print("ERROR: data.ini missing in", version_dir)
        return False

    meta = {}
    with open(data_ini, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                meta[k.strip()] = v.strip()

    main_class = meta.get("main_class")
    classpath_raw = meta.get("classpath", "")
    if not main_class or not classpath_raw:
        print("ERROR: data.ini must contain main_class and classpath")
        return False

    classpath_entries = [p.strip() for p in classpath_raw.split(",") if p.strip()]
    classpath = _join_classpath(version_dir, classpath_entries)

    global_settings = load_global_settings()
    min_ram = (global_settings.get("min_ram") or "").strip()
    max_ram = (global_settings.get("max_ram") or "").strip()
    username = username_override or global_settings.get("username", "Player")

    if not min_ram:
        min_ram = "256M"
    if not max_ram:
        max_ram = "1024M"

    native_candidate = meta.get("native_subfolder") or _native_subfolder_for_platform()
    native_path = os.path.join(version_dir, native_candidate) if native_candidate else None
    if native_path and not os.path.isdir(native_path):
        fallback = os.path.join(version_dir, "native")
        if os.path.isdir(fallback):
            native_path = fallback
        else:
            native_path = None

    cmd = [
        "java",
        f"-Xms{min_ram}",
        f"-Xmx{max_ram}",
        "-cp", classpath,
        main_class,
        username,
    ]

    if native_path:
        cmd = [
            "java",
            f"-Xms{min_ram}",
            f"-Xmx{max_ram}",
            f"-Djava.library.path={native_path}",
            "-cp", classpath,
            main_class,
            username,
        ]

    extra = meta.get("extra_jvm_args")
    if extra:
        extra_parts = extra.split()
        cmd = ["java"] + extra_parts + cmd[1:]

    print("Launching version:", version_identifier)
    print("Version dir:", version_dir)
    print("Command:", " ".join(cmd))

    try:
        subprocess.Popen(cmd, cwd=version_dir)
        return True
    except FileNotFoundError:
        print("ERROR: 'java' not found. Make sure Java is installed and on PATH.")
        return False
    except Exception as e:
        print("ERROR launching:", e)
        return False
