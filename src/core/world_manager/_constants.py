from __future__ import annotations

import os

from core.settings import get_default_minecraft_dir


CURSEFORGE_WORLD_CLASS_ID = 17
MAX_WORLD_ID_LENGTH = 255
MAX_WORLD_TITLE_LENGTH = 128
EMBEDDED_WORLD_PLAYER_ID = "__embedded__"
OVERWORLD_CLOCK_ID = "minecraft:overworld"
MINECRAFT_USERCACHE_PATH = os.path.join(get_default_minecraft_dir(), "usercache.json")
DIFFICULTY_NAME_TO_ID = {
    "peaceful": 0,
    "easy": 1,
    "normal": 2,
    "hard": 3,
}
DIFFICULTY_ID_TO_NAME = {value: key for key, value in DIFFICULTY_NAME_TO_ID.items()}


__all__ = [
    "CURSEFORGE_WORLD_CLASS_ID",
    "MAX_WORLD_ID_LENGTH",
    "MAX_WORLD_TITLE_LENGTH",
    "EMBEDDED_WORLD_PLAYER_ID",
    "OVERWORLD_CLOCK_ID",
    "MINECRAFT_USERCACHE_PATH",
    "DIFFICULTY_NAME_TO_ID",
    "DIFFICULTY_ID_TO_NAME",
]
