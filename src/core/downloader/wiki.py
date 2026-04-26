from __future__ import annotations

import re
from typing import Optional

from core.settings import load_global_settings


def _wiki_image_url(version_id: str, version_type: str) -> Optional[str]:
    settings = load_global_settings()
    low_data = settings.get("low_data_mode") == "1"
    pixel_res = round(260 / (2 if low_data else 1))
    version_id_str = str(version_id or "")

    prefix = "Java_Edition_"
    clean_id = version_id_str
    lid = version_id_str.lower()

    if lid.startswith("combat"):
        match = re.search(r"(\d)(?!.*\d)", version_id_str)
        version_num = int(match.group(1)) if match else 0
        if version_num <= 6:
            prefix = "Release_"
        clean_id = f"Combat_Test_{version_id_str[6:]}"
        if version_num == 1:
            prefix = "Release_1.14.3_"
            clean_id = "Combat_Test"
    elif lid.startswith("13w12~"):
        clean_id = version_id_str[:6]
    elif lid.startswith("1.5-pre"):
        clean_id = version_id_str.replace("-pre", "")
    elif lid == "1.0":
        clean_id = "1.0.0"
    elif lid.startswith("inf-"):
        prefix = "Infdev_"
        clean_id = version_id_str[4:12] + "_menu"
    elif lid.startswith("in-"):
        prefix = "Indev_"
        clean_id = version_id_str[3:11] + "_menu"
    elif lid.startswith("a1"):
        prefix = "Alpha_v"
        clean_id = (version_id_str[1:] if version_id_str.startswith("a") else version_id_str) + "_menu"
    elif lid.startswith("b1"):
        prefix = "Beta_"
        clean_id = (version_id_str[1:] if version_id_str.startswith("b") else version_id_str) + "_menu"
    elif lid.startswith("c0"):
        prefix = "Classic_"
        clean_id = version_id_str[1:]

    clean_id = (
        clean_id
        .replace("-", "_")
        .replace("pre_", "Pre-Release_")
        .replace("pre", "Pre-Release_")
        .replace("rc_", "Release_Candidate_")
        .replace("rc", "Release_Candidate_")
        .replace("snapshot", "Snapshot")
        .replace("_unobf", "")
        .replace("_whitelinefix", "")
        .replace("_whitetexturefix", "")
        .replace("_tominecon", "")
    )

    return f"https://minecraft.wiki/images/thumb/{prefix}{clean_id}.png/{pixel_res}px-.png"


__all__ = ["_wiki_image_url"]
