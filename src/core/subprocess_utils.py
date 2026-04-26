from __future__ import annotations

import subprocess
import sys
from typing import Any, Dict


_CREATE_NO_WINDOW = 0x08000000


def no_window_kwargs() -> Dict[str, Any]:
    if sys.platform != "win32":
        return {}

    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", _CREATE_NO_WINDOW),
    }


__all__ = ["no_window_kwargs"]
