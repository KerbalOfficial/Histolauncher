from __future__ import annotations

import base64
import os
import shlex
import shutil
import subprocess
import sys
import threading

from core.downloader._legacy._constants import BASE_DIR
from server.api.version_check import read_local_version


__all__ = [
    "APP_USER_MODEL_ID",
    "SHORTCUT_NAME",
    "delete_linux_desktop_shortcut",
    "delete_platform_shortcut",
    "delete_start_menu_shortcut",
    "get_shortcut_icon_path",
    "install_linux_desktop_shortcut",
    "install_platform_shortcut",
    "install_start_menu_shortcut",
    "linux_shortcut_target_for_project",
    "linux_desktop_shortcut_path",
    "python_launcher_script_path",
    "python_shortcut_target_for_script",
    "platform_shortcut_exists",
]


APP_USER_MODEL_ID = "Histolauncher"
SHORTCUT_NAME = "Histolauncher"
SHORTCUT_DESCRIPTION = "Lightweight, community-driven Minecraft launcher"
LINUX_DESKTOP_FILE_NAME = "histolauncher.desktop"

_shortcut_lock = threading.Lock()


def _system_powershell() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return os.path.join(
        system_root,
        "System32",
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe",
    )


def _run_hidden(command: list[str], env: dict[str, str] | None = None) -> int:
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": env,
    }
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    except Exception:
        pass
    try:
        return subprocess.run(command, check=False, **kwargs).returncode
    except Exception:
        return 1


def _run_powershell_script(script: str, env: dict[str, str]) -> bool:
    powershell = _system_powershell()
    if not os.path.isfile(powershell):
        return False
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return _run_hidden([
        powershell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encoded,
    ], env=env) == 0


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def python_launcher_script_path(project_root: str) -> str:
    for filename in ("launcher.pyw", "launcher.py"):
        path = os.path.join(project_root, filename)
        if os.path.isfile(path):
            return path
    return os.path.join(project_root, "launcher.pyw")


def _windows_python_executable_variant(interpreter: str, *, windowed: bool) -> str:
    if not interpreter:
        return ""

    directory = os.path.dirname(interpreter)
    name = os.path.basename(interpreter)
    lower_name = name.lower()
    if not lower_name.endswith(".exe"):
        return interpreter

    candidates: list[str] = []
    if lower_name.startswith("pythonw"):
        suffix = name[len("pythonw"):]
        if windowed:
            candidates.append(interpreter)
        else:
            candidates.extend([
                os.path.join(directory, "python" + suffix),
                os.path.join(directory, "python.exe"),
                os.path.join(directory, "python3.exe"),
            ])
    elif lower_name.startswith("python"):
        suffix = name[len("python"):]
        if windowed:
            candidates.extend([
                os.path.join(directory, "pythonw" + suffix),
                os.path.join(directory, "pythonw.exe"),
                os.path.join(directory, "pythonw3.exe"),
            ])
        else:
            candidates.append(interpreter)
    else:
        return interpreter

    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.normcase(os.path.abspath(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isfile(candidate):
            return candidate
    return interpreter


def python_shortcut_target_for_script(
    script_path: str,
    interpreter: str | None = None,
) -> str:
    current_interpreter = interpreter or sys.executable or ""
    if not sys.platform.startswith("win"):
        return current_interpreter

    extension = os.path.splitext(script_path)[1].lower()
    if extension == ".pyw":
        return _windows_python_executable_variant(
            current_interpreter,
            windowed=True,
        )
    if extension == ".py":
        return _windows_python_executable_variant(
            current_interpreter,
            windowed=False,
        )
    return current_interpreter


def linux_shortcut_target_for_project(
    project_root: str,
    *,
    interpreter: str | None = None,
    shell_path: str | None = None,
) -> tuple[str, str]:
    launcher_shell_script = os.path.join(project_root, "launcher.sh")
    if os.path.isfile(launcher_shell_script):
        shell = shell_path or shutil.which("sh") or "/bin/sh"
        return shell, f'"{launcher_shell_script}"'

    launcher_script = python_launcher_script_path(project_root)
    return interpreter or sys.executable or "python3", f'"{launcher_script}"'


def _linux_desktop_data_dir() -> str:
    return os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )


def linux_desktop_shortcut_path() -> str:
    return os.path.join(
        _linux_desktop_data_dir(),
        "applications",
        LINUX_DESKTOP_FILE_NAME,
    )


def start_menu_shortcut_path() -> str:
    if os.name != "nt":
        return ""
    programs = os.path.join(
        os.environ.get("APPDATA") or "",
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
    )
    if not programs or not os.path.isdir(programs):
        try:
            import ctypes
            from ctypes import wintypes

            CSIDL_PROGRAMS = 0x0002
            SHGFP_TYPE_CURRENT = 0
            buffer = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            result = ctypes.windll.shell32.SHGetFolderPathW(
                None,
                CSIDL_PROGRAMS,
                None,
                SHGFP_TYPE_CURRENT,
                buffer,
            )
            if result == 0 and buffer.value:
                programs = buffer.value
        except Exception:
            pass
    return os.path.join(programs, SHORTCUT_NAME + ".lnk") if programs else ""


def platform_shortcut_exists() -> bool:
    if sys.platform.startswith("linux"):
        return os.path.isfile(linux_desktop_shortcut_path())
    if os.name == "nt":
        path = start_menu_shortcut_path()
        return bool(path and os.path.isfile(path))
    return False


def _desktop_field(value: str) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()


def _desktop_exec_quote(value: str) -> str:
    escaped = str(value or "").replace("\\", "\\\\")
    escaped = escaped.replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    return f'"{escaped}"'


def _desktop_exec_command(target_path: str, arguments: str) -> str:
    parts = [_desktop_exec_quote(target_path)]
    try:
        argument_parts = shlex.split(str(arguments or ""))
    except ValueError:
        argument_parts = [str(arguments or "").strip()]
    parts.extend(_desktop_exec_quote(part) for part in argument_parts if part)
    return " ".join(parts)


def _refresh_linux_desktop_database(applications_dir: str) -> None:
    update = shutil.which("update-desktop-database")
    if not update:
        return
    try:
        subprocess.run(
            [update, applications_dir],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass


def install_linux_desktop_shortcut(
    *,
    target_path: str,
    arguments: str,
    icon_path: str,
    working_dir: str = "",
) -> bool:
    with _shortcut_lock:
        if not _is_linux():
            return False
        if not target_path or not (os.path.isfile(target_path) or shutil.which(target_path)):
            return False
        if not icon_path or not os.path.isfile(icon_path):
            return False

        shortcut_path = linux_desktop_shortcut_path()
        applications_dir = os.path.dirname(shortcut_path)
        exec_command = _desktop_exec_command(target_path, arguments)

        launcher_version = read_local_version(base_dir=BASE_DIR)

        fields = [
            "[Desktop Entry]",
            "Type=Application",
            f"Version={launcher_version}",
            f"Name={SHORTCUT_NAME}",
            f"Comment={SHORTCUT_DESCRIPTION}",
            f"Exec={exec_command}",
        ]
        if working_dir:
            fields.append(f"Path={_desktop_field(working_dir)}")
        fields.extend([
            f"Icon={_desktop_field(icon_path)}",
            "Terminal=false",
            "Categories=Game;",
            f"StartupWMClass={SHORTCUT_NAME}",
            "StartupNotify=true",
            "NoDisplay=false",
            "",
        ])
        contents = "\n".join(fields)

        try:
            os.makedirs(applications_dir, exist_ok=True)
            existing = ""
            if os.path.isfile(shortcut_path):
                try:
                    with open(shortcut_path, "r", encoding="utf-8") as handle:
                        existing = handle.read()
                except Exception:
                    existing = ""
            if existing != contents:
                with open(shortcut_path, "w", encoding="utf-8") as handle:
                    handle.write(contents)
                try:
                    os.chmod(shortcut_path, 0o644)
                except Exception:
                    pass
            _refresh_linux_desktop_database(applications_dir)
            return True
        except Exception:
            return False


def delete_linux_desktop_shortcut() -> bool:
    with _shortcut_lock:
        if not _is_linux():
            return False

        shortcut_path = linux_desktop_shortcut_path()
        applications_dir = os.path.dirname(shortcut_path)
        try:
            if os.path.exists(shortcut_path):
                os.remove(shortcut_path)
            _refresh_linux_desktop_database(applications_dir)
            return True
        except Exception:
            return False


def install_start_menu_shortcut(
    *,
    target_path: str,
    arguments: str,
    icon_path: str,
    working_dir: str = "",
) -> bool:
    with _shortcut_lock:
        if os.name != "nt":
            return False
        if not target_path or not os.path.isfile(target_path):
            return False
        if not icon_path or not os.path.isfile(icon_path):
            return False

        script = r'''
$ErrorActionPreference = 'Stop'
$targetPath = $env:HISTOLAUNCHER_SHORTCUT_TARGET
$arguments = $env:HISTOLAUNCHER_SHORTCUT_ARGUMENTS
$iconPath = $env:HISTOLAUNCHER_SHORTCUT_ICON
$appId = $env:HISTOLAUNCHER_SHORTCUT_AUMID
$shortcutName = $env:HISTOLAUNCHER_SHORTCUT_NAME
$shortcutDescription = $env:HISTOLAUNCHER_SHORTCUT_DESCRIPTION
$workingDir = $env:HISTOLAUNCHER_SHORTCUT_WORKDIR

$programs = [Environment]::GetFolderPath('Programs')
if (-not $programs) { exit 1 }
$shortcutPath = Join-Path $programs ($shortcutName + '.lnk')

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $shortcutPath) | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.Arguments = $arguments
$shortcut.IconLocation = "$iconPath,0"
$shortcut.Description = $shortcutDescription
if ($workingDir) { $shortcut.WorkingDirectory = $workingDir }
$shortcut.Save()

$code = @'
using System;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct PROPERTYKEY
{
    public Guid fmtid;
    public uint pid;
}

[StructLayout(LayoutKind.Explicit)]
public struct PROPVARIANT
{
    [FieldOffset(0)] public ushort vt;
    [FieldOffset(8)] public IntPtr pwszVal;
}

[ComImport]
[Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPropertyStore
{
    int GetCount(out uint cProps);
    int GetAt(uint iProp, out PROPERTYKEY pkey);
    int GetValue(ref PROPERTYKEY key, out PROPVARIANT pv);
    int SetValue(ref PROPERTYKEY key, ref PROPVARIANT pv);
    int Commit();
}

public static class StartMenuShortcutWriter
{
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
    private static extern int SHGetPropertyStoreFromParsingName(
        string pszPath, IntPtr pbc, uint flags, ref Guid riid, out IPropertyStore ppv);

    private const uint GPS_READWRITE = 0x00000002;
    private const ushort VT_LPWSTR = 31;

    public static void SetString(string path, uint pid, string value)
    {
        Guid iid = new Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99");
        IPropertyStore store;
        int hr = SHGetPropertyStoreFromParsingName(path, IntPtr.Zero, GPS_READWRITE, ref iid, out store);
        if (hr != 0) Marshal.ThrowExceptionForHR(hr);

        PROPERTYKEY key = new PROPERTYKEY {
            fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"),
            pid = pid
        };
        PROPVARIANT propValue = new PROPVARIANT {
            vt = VT_LPWSTR,
            pwszVal = Marshal.StringToCoTaskMemUni(value)
        };
        try
        {
            hr = store.SetValue(ref key, ref propValue);
            if (hr != 0) Marshal.ThrowExceptionForHR(hr);
            hr = store.Commit();
            if (hr != 0) Marshal.ThrowExceptionForHR(hr);
        }
        finally
        {
            Marshal.FreeCoTaskMem(propValue.pwszVal);
            Marshal.ReleaseComObject(store);
        }
    }
}
'@

Add-Type -TypeDefinition $code -Language CSharp
[StartMenuShortcutWriter]::SetString($shortcutPath, 5, $appId)
$relaunchCommand = "`"$targetPath`""
if ($arguments) { $relaunchCommand = "$relaunchCommand $arguments" }
[StartMenuShortcutWriter]::SetString($shortcutPath, 2, $relaunchCommand)
[StartMenuShortcutWriter]::SetString($shortcutPath, 3, "$iconPath,0")
[StartMenuShortcutWriter]::SetString($shortcutPath, 4, 'Histolauncher')
'''

        env = os.environ.copy()
        env.update({
            "HISTOLAUNCHER_SHORTCUT_TARGET": target_path,
            "HISTOLAUNCHER_SHORTCUT_ARGUMENTS": arguments,
            "HISTOLAUNCHER_SHORTCUT_ICON": icon_path,
            "HISTOLAUNCHER_SHORTCUT_AUMID": APP_USER_MODEL_ID,
            "HISTOLAUNCHER_SHORTCUT_NAME": SHORTCUT_NAME,
            "HISTOLAUNCHER_SHORTCUT_DESCRIPTION": SHORTCUT_DESCRIPTION,
            "HISTOLAUNCHER_SHORTCUT_WORKDIR": working_dir,
        })
        return _run_powershell_script(script, env)


def delete_start_menu_shortcut() -> bool:
    with _shortcut_lock:
        if os.name != "nt":
            return False

        script = r'''
$ErrorActionPreference = 'Stop'
$shortcutName = $env:HISTOLAUNCHER_SHORTCUT_NAME
$programs = [Environment]::GetFolderPath('Programs')
if (-not $programs) { exit 1 }
$shortcutPath = Join-Path $programs ($shortcutName + '.lnk')
if (Test-Path -LiteralPath $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath -Force
}
'''
        env = os.environ.copy()
        env.update({
            "HISTOLAUNCHER_SHORTCUT_NAME": SHORTCUT_NAME,
        })
        return _run_powershell_script(script, env)


def get_shortcut_icon_path(project_root: str) -> str:
    image_dir = os.path.join(project_root, "ui", "assets", "images")
    if sys.platform.startswith("linux"):
        for filename in ("histolauncher_256x256.png", "histolauncher_256x256.ico"):
            path = os.path.join(image_dir, filename)
            if os.path.isfile(path):
                return path
    return os.path.join(image_dir, "histolauncher_256x256.ico")


def install_platform_shortcut(project_root: str) -> bool:
    icon_path = get_shortcut_icon_path(project_root)

    if sys.platform.startswith("linux"):
        target_path, arguments = linux_shortcut_target_for_project(project_root)
        return install_linux_desktop_shortcut(
            target_path=target_path,
            arguments=arguments,
            icon_path=icon_path,
            working_dir=project_root,
        )

    if os.name == "nt":
        launcher_script = python_launcher_script_path(project_root)
        target_path = python_shortcut_target_for_script(launcher_script)
        return install_start_menu_shortcut(
            target_path=target_path,
            arguments=f'"{launcher_script}"',
            icon_path=icon_path,
            working_dir=project_root,
        )

    return False


def delete_platform_shortcut() -> bool:
    if sys.platform.startswith("linux"):
        return delete_linux_desktop_shortcut()
    if os.name == "nt":
        return delete_start_menu_shortcut()
    return False