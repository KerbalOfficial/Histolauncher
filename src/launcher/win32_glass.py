from __future__ import annotations

import ctypes
import sys

__all__ = ["apply_acrylic_blur"]

_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
_WCA_ACCENT_POLICY = 19


class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_int),
    ]


class _WCAD(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]


class _MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    ]


_GA_ROOT = 2


def _get_tk_hwnd(widget) -> int:
    try:
        child = widget.winfo_id()
        user32 = ctypes.windll.user32
        root_hwnd = user32.GetAncestor(ctypes.c_void_p(child), _GA_ROOT)
        return int(root_hwnd) if root_hwnd else int(child)
    except Exception:
        return 0


def apply_acrylic_blur(widget, tint_abgr: int = 0x88000000) -> bool:
    if not sys.platform.startswith("win"):
        return False

    try:
        hwnd = _get_tk_hwnd(widget)
        if not hwnd:
            return False

        hwnd_vp = ctypes.c_void_p(hwnd)

        try:
            margins = _MARGINS(-1, -1, -1, -1)
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
                hwnd_vp, ctypes.byref(margins)
            )
        except Exception:
            pass

        accent = _ACCENT_POLICY()
        accent.AccentState = _ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.AccentFlags = 2  # draw luminosity layer
        accent.GradientColor = tint_abgr & 0xFFFFFFFF

        wcad = _WCAD()
        wcad.Attribute = _WCA_ACCENT_POLICY
        wcad.Data = ctypes.cast(ctypes.addressof(accent), ctypes.c_void_p)
        wcad.SizeOfData = ctypes.sizeof(accent)

        user32 = ctypes.windll.user32
        user32.SetWindowCompositionAttribute.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_WCAD),
        ]
        user32.SetWindowCompositionAttribute.restype = ctypes.c_bool
        return bool(user32.SetWindowCompositionAttribute(hwnd_vp, ctypes.byref(wcad)))
    except Exception:
        return False
