from __future__ import annotations

import os
import zipfile
from typing import Iterable, List


# Class entries that mark a runtime "launcher" JAR (modlauncher / launchwrapper).
RUNTIME_MARKER_CLASSES = (
    "cpw/mods/modlauncher/Launcher.class",
    "net/minecraft/launchwrapper/Launch.class",
)


def jar_has_class(jar_path: str, class_path: str) -> bool:
    try:
        with zipfile.ZipFile(jar_path, "r") as z:
            return class_path in z.namelist()
    except Exception:
        return False


def find_runtime_jars(search_roots: Iterable[str]) -> List[str]:
    found: List[str] = []
    for root in search_roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, _, files in os.walk(root):
            for f in files:
                if not f.endswith(".jar"):
                    continue
                p = os.path.join(dirpath, f)
                try:
                    if any(jar_has_class(p, cls) for cls in RUNTIME_MARKER_CLASSES):
                        found.append(p)
                except Exception:
                    continue
    return found


def loader_dir_has_class(loader_dest_dir: str, class_path: str) -> bool:
    try:
        for name in os.listdir(loader_dest_dir):
            if not name.endswith(".jar"):
                continue
            if jar_has_class(os.path.join(loader_dest_dir, name), class_path):
                return True
    except Exception:
        pass
    return False


def gather_manifest_libraries(jar_path: str) -> List[str]:
    libs: List[str] = []
    try:
        with zipfile.ZipFile(jar_path, "r") as jf:
            mf = jf.read("META-INF/MANIFEST.MF").decode("utf-8", errors="ignore")
        for line in mf.splitlines():
            if line.startswith("libraries/"):
                libs.append(line.strip())
    except Exception:
        pass
    return libs


__all__ = [
    "find_runtime_jars",
    "gather_manifest_libraries",
    "jar_has_class",
    "loader_dir_has_class",
]
