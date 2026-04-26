from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes

from core.shortcut_manager import APP_USER_MODEL_ID


__all__ = [
    "show_windows_notification",
    "set_launcher_hwnd",
]


# --- Win32 constants -------------------------------------------------------

WM_DESTROY = 0x0002
WM_SETICON = 0x0080
WM_APP = 0x8000
WM_USER = 0x0400
WM_LBUTTONUP = 0x0202

NIM_ADD = 0
NIM_DELETE = 2
NIM_SETVERSION = 4

NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIF_INFO = 0x10
NIF_SHOWTIP = 0x80

NIIF_INFO = 0x01
NIIF_USER = 0x04
NIIF_LARGE_ICON = 0x20

NOTIFYICON_VERSION_4 = 4

NIN_SELECT = WM_USER + 0
NIN_KEYSELECT = WM_USER + 1
NIN_BALLOONHIDE = WM_USER + 3
NIN_BALLOONTIMEOUT = WM_USER + 4
NIN_BALLOONUSERCLICK = WM_USER + 5

WS_OVERLAPPED = 0x00000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

IMAGE_ICON = 1
ICON_SMALL = 0
ICON_BIG = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040
IDI_APPLICATION = 32512

SW_RESTORE = 9
SW_SHOW = 5

WM_TRAYICON = WM_APP + 1


# --- ctypes setup ----------------------------------------------------------

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
user32.SendMessageW.restype = LRESULT
user32.SendMessageW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.DestroyWindow.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadImageW.argtypes = [
    wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.LoadIconW.restype = wintypes.HICON
user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
user32.DestroyIcon.restype = wintypes.BOOL
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.PeekMessageW.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
    wintypes.UINT,
]
user32.TranslateMessage.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.PostQuitMessage.restype = None
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostMessageW.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.ShowWindow.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetAncestor.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.AttachThreadInput.argtypes = [
    wintypes.DWORD, wintypes.DWORD, wintypes.BOOL,
]

ENUMWINDOWSPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
)
user32.EnumWindows.restype = wintypes.BOOL
user32.EnumWindows.argtypes = [ENUMWINDOWSPROC, wintypes.LPARAM]

shell32.Shell_NotifyIconW.restype = wintypes.BOOL
shell32.Shell_NotifyIconW.argtypes = [
    wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)
]

kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetCurrentProcessId.restype = wintypes.DWORD
kernel32.GetCurrentProcessId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetConsoleWindow.restype = wintypes.HWND
kernel32.GetConsoleWindow.argtypes = []

user32.SetWindowPos.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT,
]

# --- Per-window PKEY_AppUserModel_ID override --------------------------------

class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_uint32)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("wReserved1", ctypes.c_ushort),
        ("wReserved2", ctypes.c_ushort),
        ("wReserved3", ctypes.c_ushort),
        ("pwszVal", ctypes.c_void_p),
        ("padding", ctypes.c_uint64),
    ]


_PKEY_AppUserModel_ID = _PROPERTYKEY(
    _GUID(
        0x9F4C2855, 0x9F79, 0x4B39,
        (ctypes.c_ubyte * 8)(0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3),
    ),
    5,
)

_PKEY_AppUserModel_RelaunchCommand = _PROPERTYKEY(
    _GUID(
        0x9F4C2855, 0x9F79, 0x4B39,
        (ctypes.c_ubyte * 8)(0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3),
    ),
    2,
)

_PKEY_AppUserModel_RelaunchIconResource = _PROPERTYKEY(
    _GUID(
        0x9F4C2855, 0x9F79, 0x4B39,
        (ctypes.c_ubyte * 8)(0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3),
    ),
    3,
)

_PKEY_AppUserModel_RelaunchDisplayNameResource = _PROPERTYKEY(
    _GUID(
        0x9F4C2855, 0x9F79, 0x4B39,
        (ctypes.c_ubyte * 8)(0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3),
    ),
    4,
)

_IID_IPropertyStore = _GUID(
    0x886D8EEB, 0x8CF2, 0x4446,
    (ctypes.c_ubyte * 8)(0x8D, 0x02, 0xCD, 0xBA, 0x1D, 0xBD, 0xCF, 0x99),
)

_NOTIFICATION_WINDOW_APP_ID = APP_USER_MODEL_ID
_VT_LPWSTR = 31


def _notification_relaunch_command() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    rundll32 = os.path.join(system_root, "System32", "rundll32.exe")
    if not os.path.isfile(rundll32):
        return ""
    return f'"{rundll32}"'


class _StringPropVariant:
    def __init__(self, value: str) -> None:
        self.buffer = ctypes.create_unicode_buffer(value)
        self.propvariant = _PROPVARIANT()
        self.propvariant.vt = _VT_LPWSTR
        self.propvariant.pwszVal = ctypes.cast(
            self.buffer, ctypes.c_void_p
        ).value


def _set_property_string(
    set_value, store: ctypes.c_void_p, key: _PROPERTYKEY, value: str
) -> bool:
    if not value:
        return False
    prop = _StringPropVariant(value)
    hr = set_value(
        store,
        ctypes.byref(key),
        ctypes.byref(prop.propvariant),
    )
    return not _hresult_failed(hr)


def _set_notification_window_app_user_model_id(
    hwnd: int, icon_path: str = ""
) -> None:
    if not hwnd:
        return
    try:
        shell32.SHGetPropertyStoreForWindow.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_GUID),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long

        store = ctypes.c_void_p()
        hr = shell32.SHGetPropertyStoreForWindow(
            ctypes.c_void_p(int(hwnd)),
            ctypes.byref(_IID_IPropertyStore),
            ctypes.byref(store),
        )
        if hr != 0 or not store.value:
            return

        icon_value = ""
        if icon_path and os.path.isfile(icon_path):
            icon_value = f"{icon_path},0"

        relaunch_command = _notification_relaunch_command()
        try:
            vtbl_ptr = ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0]
            vtbl = ctypes.cast(vtbl_ptr, ctypes.POINTER(ctypes.c_void_p))
            SetValue = ctypes.WINFUNCTYPE(
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.POINTER(_PROPERTYKEY),
                ctypes.POINTER(_PROPVARIANT),
            )(vtbl[6])
            Commit = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p
            )(vtbl[7])
            Release = ctypes.WINFUNCTYPE(
                ctypes.c_ulong, ctypes.c_void_p
            )(vtbl[2])

            try:
                _set_property_string(
                    SetValue,
                    store,
                    _PKEY_AppUserModel_ID,
                    _NOTIFICATION_WINDOW_APP_ID,
                )
                if relaunch_command:
                    _set_property_string(
                        SetValue,
                        store,
                        _PKEY_AppUserModel_RelaunchCommand,
                        relaunch_command,
                    )
                    _set_property_string(
                        SetValue,
                        store,
                        _PKEY_AppUserModel_RelaunchDisplayNameResource,
                        "Histolauncher",
                    )
                if icon_value:
                    _set_property_string(
                        SetValue,
                        store,
                        _PKEY_AppUserModel_RelaunchIconResource,
                        icon_value,
                    )
                Commit(store)
            finally:
                Release(store)
        except Exception:
            pass
    except Exception:
        pass


def _hresult_failed(hr: int) -> bool:
    return ctypes.c_long(hr).value < 0

_HWND_BOTTOM = 1
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010


def _push_console_to_back() -> None:
    try:
        console = kernel32.GetConsoleWindow()
    except Exception:
        return
    if not console:
        return
    try:
        user32.SetWindowPos(
            console,
            wintypes.HWND(_HWND_BOTTOM),
            0, 0, 0, 0,
            _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOACTIVATE,
        )
    except Exception:
        pass


# --- Window discovery ------------------------------------------------------

_registered_hwnd_lock = threading.Lock()
_registered_hwnd: int = 0


def set_launcher_hwnd(hwnd: int) -> None:
    global _registered_hwnd
    with _registered_hwnd_lock:
        try:
            _registered_hwnd = int(hwnd) if hwnd else 0
        except Exception:
            _registered_hwnd = 0


def _get_registered_hwnd() -> int:
    with _registered_hwnd_lock:
        hwnd = _registered_hwnd
    if hwnd and user32.IsWindow(wintypes.HWND(hwnd)):
        return hwnd
    return 0


def _find_launcher_hwnd(title_substr: str = "Histolauncher") -> int:
    own_pid = kernel32.GetCurrentProcessId()
    needle = title_substr.lower()
    found: list[int] = []

    @ENUMWINDOWSPROC
    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != own_pid:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value or ""
        if needle in title.lower():
            found.append(int(hwnd))
            return False
        return True

    try:
        user32.EnumWindows(_cb, 0)
    except Exception:
        pass
    return found[0] if found else 0


def _focus_window(hwnd: int) -> None:
    if not hwnd or not user32.IsWindow(hwnd):
        return
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        else:
            user32.ShowWindow(hwnd, SW_SHOW)

        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        cur_tid = kernel32.GetCurrentThreadId()
        attached = False
        if target_tid and target_tid != cur_tid:
            attached = bool(user32.AttachThreadInput(cur_tid, target_tid, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(cur_tid, target_tid, False)
    except Exception:
        pass


# --- Notification implementation ------------------------------------------

_class_lock = threading.Lock()
_class_atom = 0
_class_name = "HistolauncherToastWnd"
_uid_counter = 0
_uid_lock = threading.Lock()


def _next_uid() -> int:
    global _uid_counter
    with _uid_lock:
        _uid_counter = (_uid_counter + 1) & 0x7FFFFFFF
        return _uid_counter or 1


def _ensure_class_registered() -> int:
    global _class_atom
    with _class_lock:
        if _class_atom:
            return _class_atom
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = 0
        wc.lpfnWndProc = _wnd_proc  # keep ref via module-level binding
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.hIcon = 0
        wc.hCursor = 0
        wc.hbrBackground = 0
        wc.lpszMenuName = None
        wc.lpszClassName = _class_name
        wc.hIconSm = 0
        atom = user32.RegisterClassExW(ctypes.byref(wc))
        if atom:
            _class_atom = atom
        return _class_atom


def _on_balloon_click() -> None:
    _push_console_to_back()

    hwnd = _get_registered_hwnd()
    if not hwnd:
        hwnd = _find_launcher_hwnd()
    if hwnd:
        _focus_window(hwnd)
        def _reassert():
            time.sleep(0.15)
            try:
                _push_console_to_back()
                _focus_window(hwnd)
            except Exception:
                pass
        threading.Thread(target=_reassert, daemon=True).start()


def _wnd_proc_impl(hwnd, msg, wparam, lparam):
    if msg == WM_TRAYICON:
        event = lparam & 0xFFFF
        if event in (NIN_BALLOONUSERCLICK, NIN_SELECT, NIN_KEYSELECT,
                     WM_LBUTTONUP):
            try:
                _on_balloon_click()
            except Exception:
                pass
            user32.PostMessageW(hwnd, WM_DESTROY, 0, 0)
            return 0
        if event in (NIN_BALLOONTIMEOUT, NIN_BALLOONHIDE):
            user32.PostMessageW(hwnd, WM_DESTROY, 0, 0)
            return 0
        return 0
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_wnd_proc = WNDPROC(_wnd_proc_impl)


def _load_icon(icon_path: str) -> int:
    if icon_path and os.path.isfile(icon_path):
        h = user32.LoadImageW(
            None, icon_path, IMAGE_ICON, 0, 0,
            LR_LOADFROMFILE | LR_DEFAULTSIZE,
        )
        if h:
            return int(h)
    return int(user32.LoadIconW(None, ctypes.cast(IDI_APPLICATION,
                                                  wintypes.LPCWSTR)) or 0)


def _set_window_icon(hwnd: int, hicon: int) -> None:
    if not hwnd or not hicon:
        return
    try:
        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
    except Exception:
        pass


def _show_balloon_thread(
    *, title: str, message: str, app_name: str, icon_path: str,
    timeout_ms: int,
) -> None:
    atom = _ensure_class_registered()
    if not atom:
        return
    hinst = kernel32.GetModuleHandleW(None)

    hwnd = user32.CreateWindowExW(
        WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        _class_name,
        app_name or "Histolauncher",
        WS_OVERLAPPED,
        0, 0, 0, 0,
        None,
        None,
        hinst,
        None,
    )
    if not hwnd:
        return

    _set_notification_window_app_user_model_id(int(hwnd), icon_path)

    hicon = _load_icon(icon_path)
    _set_window_icon(int(hwnd), hicon)
    custom_icon = bool(icon_path) and hicon != 0
    uid = _next_uid()

    nid = NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    nid.hWnd = hwnd
    nid.uID = uid
    nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_INFO | NIF_SHOWTIP
    nid.uCallbackMessage = WM_TRAYICON
    nid.hIcon = hicon
    nid.szTip = (app_name or "Histolauncher")[:127]
    nid.szInfo = (message or "")[:255]
    nid.szInfoTitle = (title or app_name or "Histolauncher")[:63]
    nid.dwInfoFlags = (NIIF_USER | NIIF_LARGE_ICON) if custom_icon else NIIF_INFO
    nid.uVersion = NOTIFYICON_VERSION_4
    nid.hBalloonIcon = hicon if custom_icon else 0

    try:
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            return
        shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))

        deadline = time.monotonic() + max(0.5, timeout_ms / 1000.0)
        msg = MSG()
        PM_REMOVE = 0x0001
        WM_QUIT = 0x0012
        while time.monotonic() < deadline:
            while user32.PeekMessageW(
                ctypes.byref(msg), None, 0, 0, PM_REMOVE
            ):
                if msg.message == WM_QUIT:
                    deadline = 0
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if deadline == 0:
                break
            time.sleep(0.05)
    finally:
        try:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        except Exception:
            pass
        try:
            if hicon and custom_icon:
                user32.DestroyIcon(hicon)
        except Exception:
            pass
        try:
            user32.DestroyWindow(hwnd)
        except Exception:
            pass


def show_windows_notification(
    *,
    title: str,
    message: str,
    app_name: str = "Histolauncher",
    icon_path: str = "",
    timeout_ms: int = 12000,
) -> None:
    t = threading.Thread(
        target=_show_balloon_thread,
        kwargs={
            "title": title,
            "message": message,
            "app_name": app_name,
            "icon_path": icon_path,
            "timeout_ms": timeout_ms,
        },
        name="histolauncher-toast",
        daemon=True,
    )
    t.start()
