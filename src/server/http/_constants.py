from __future__ import annotations

import os


__all__ = ["BASE_DIR", "UI_DIR"]


BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
UI_DIR = os.path.join(BASE_DIR, "ui")
