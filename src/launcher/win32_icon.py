from __future__ import annotations

import ctypes
import sys

from launcher._constants import ICO_PATH


__all__ = [
    "replace_pywebview_icon",
    "set_app_user_model_id",
    "extract_pywebview_hwnd",
]


def _to_int(x):
    if isinstance(x, int):
        return x
    if hasattr(x, "ToInt64"):
        return int(x.ToInt64())
    if hasattr(x, "ToInt32"):
        return int(x.ToInt32())
    if hasattr(x, "value"):
        return int(x.value)
    try:
        return int(x)
    except Exception:
        raise TypeError(f"Cannot convert {type(x)!r} to int")


def _extract_hwnd_raw(window):
    gui = window.gui
    if hasattr(gui, "BrowserView"):
        instances = getattr(gui.BrowserView, "instances", None)
        if instances and window.uid in instances:
            form = instances[window.uid]
            if hasattr(form, "get_Handle"):
                raw = form.get_Handle()
            else:
                raw = getattr(form, "Handle", None)
            if raw is None:
                raise RuntimeError("BrowserForm has no Handle")
            return _to_int(raw)
    if hasattr(gui, "hwnd"):
        return _to_int(gui.hwnd)
    if hasattr(gui, "window"):
        return _to_int(gui.window)
    if hasattr(gui, "browser_window"):
        return _to_int(gui.browser_window)
    raise RuntimeError("Could not determine HWND for this pywebview backend")


def extract_pywebview_hwnd(window) -> int:
    if not sys.platform.startswith("win"):
        return 0
    try:
        hwnd_val = _extract_hwnd_raw(window)
    except Exception:
        return 0
    if not hwnd_val:
        return 0
    try:
        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.GetAncestor.restype = ctypes.c_void_p
        root = user32.GetAncestor(ctypes.c_void_p(hwnd_val), 3)  # GA_ROOTOWNER
        if root:
            hwnd_val = int(root)
    except Exception:
        pass
    return int(hwnd_val)


def set_app_user_model_id(app_id: str = "histolauncher.launcher") -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


if sys.platform.startswith("win"):
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _user32.SendMessageW.argtypes = [
        ctypes.c_void_p,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    _user32.SendMessageW.restype = ctypes.c_void_p
    _user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    _user32.LoadImageW.restype = wintypes.HANDLE
    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _user32.GetSystemMetrics.restype = ctypes.c_int
    _user32.GetAncestor.argtypes = [ctypes.c_void_p, wintypes.UINT]
    _user32.GetAncestor.restype = ctypes.c_void_p
    if hasattr(_user32, "SetClassLongPtrW"):
        _SetClassLongPtr = _user32.SetClassLongPtrW
        _SetClassLongPtr.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        _SetClassLongPtr.restype = ctypes.c_void_p
    else:  # pragma: no cover
        _SetClassLongPtr = _user32.SetClassLongW
        _SetClassLongPtr.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            wintypes.LONG,
        ]
        _SetClassLongPtr.restype = wintypes.LONG
else:  # pragma: no cover
    _user32 = None  # type: ignore[assignment]
    _SetClassLongPtr = None  # type: ignore[assignment]


_WM_SETICON = 0x0080
_ICON_SMALL = 0
_ICON_BIG = 1
_IMAGE_ICON = 1
_LR_LOADFROMFILE = 0x00000010
_LR_DEFAULTCOLOR = 0x00000000
_SM_CXICON = 11
_SM_CYICON = 12
_SM_CXSMICON = 49
_SM_CYSMICON = 50
_GCLP_HICON = -14
_GCLP_HICONSM = -34
_GA_ROOTOWNER = 3


def _set_window_app_user_model_id(hwnd: int, app_id: str) -> None:
    if not sys.platform.startswith("win") or not hwnd:
        return

    # PKEY_AppUserModel_ID = (FMTID {9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}, PID 5)
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
            ("pwszVal", ctypes.c_wchar_p),
            ("padding", ctypes.c_uint64),
        ]

    pkey = _PROPERTYKEY(
        _GUID(
            0x9F4C2855,
            0x9F79,
            0x4B39,
            (ctypes.c_ubyte * 8)(0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3),
        ),
        5,
    )

    pv = _PROPVARIANT()
    pv.vt = 31  # VT_LPWSTR
    pv.pwszVal = app_id

    try:
        shell32 = ctypes.windll.shell32

        shell32.SHGetPropertyStoreForWindow.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_GUID),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long

        # IID_IPropertyStore = {886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}
        iid_ips = _GUID(
            0x886D8EEB,
            0x8CF2,
            0x4446,
            (ctypes.c_ubyte * 8)(0x8D, 0x02, 0xCD, 0xBA, 0x1D, 0xBD, 0xCF, 0x99),
        )

        store = ctypes.c_void_p()
        hr = shell32.SHGetPropertyStoreForWindow(
            ctypes.c_void_p(hwnd), ctypes.byref(iid_ips), ctypes.byref(store)
        )
        if hr != 0 or not store.value:
            return

        vtbl_ptr = ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0]
        vtbl = ctypes.cast(vtbl_ptr, ctypes.POINTER(ctypes.c_void_p))
        SetValue = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.POINTER(_PROPERTYKEY),
            ctypes.POINTER(_PROPVARIANT),
        )(vtbl[6])
        Commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[7])
        Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])

        try:
            hr = SetValue(store, ctypes.byref(pkey), ctypes.byref(pv))
            if hr == 0:
                Commit(store)
        finally:
            Release(store)
    except Exception:
        pass


def replace_pywebview_icon(window):
    if not sys.platform.startswith("win") or _user32 is None:
        return

    hwnd_val = 0
    try:
        hwnd_val = _extract_hwnd_raw(window)
    except Exception:
        pass
    if not hwnd_val:
        return

    try:
        root = _user32.GetAncestor(ctypes.c_void_p(hwnd_val), _GA_ROOTOWNER)
        if root:
            hwnd_val = int(root)
    except Exception:
        pass

    hwnd_c = ctypes.c_void_p(hwnd_val)

    _set_window_app_user_model_id(hwnd_val, "histolauncher.launcher")

    cx_big = _user32.GetSystemMetrics(_SM_CXICON) or 32
    cy_big = _user32.GetSystemMetrics(_SM_CYICON) or 32
    cx_sm = _user32.GetSystemMetrics(_SM_CXSMICON) or 16
    cy_sm = _user32.GetSystemMetrics(_SM_CYSMICON) or 16

    hicon_big = _user32.LoadImageW(
        None, ICO_PATH, _IMAGE_ICON, cx_big, cy_big,
        _LR_LOADFROMFILE | _LR_DEFAULTCOLOR,
    )
    hicon_sm = _user32.LoadImageW(
        None, ICO_PATH, _IMAGE_ICON, cx_sm, cy_sm,
        _LR_LOADFROMFILE | _LR_DEFAULTCOLOR,
    )
    if not hicon_big or not hicon_sm:
        return
    try:
        _user32.SendMessageW(hwnd_c, _WM_SETICON, _ICON_SMALL, hicon_sm)
        _user32.SendMessageW(hwnd_c, _WM_SETICON, _ICON_BIG, hicon_big)
        if _SetClassLongPtr is not None:
            _SetClassLongPtr(hwnd_c, _GCLP_HICON, hicon_big)
            _SetClassLongPtr(hwnd_c, _GCLP_HICONSM, hicon_sm)
    except Exception:
        pass
