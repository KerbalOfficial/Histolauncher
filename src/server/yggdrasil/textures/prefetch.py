from __future__ import annotations

import os
import time
import urllib.parse
import urllib.request

from core.settings import _apply_url_proxy

from server.yggdrasil.identity import (
    _get_username_and_uuid,
    _histolauncher_account_enabled,
    _normalize_uuid_hex,
    _uuid_hex_to_dashed,
)
from server.yggdrasil.state import TEXTURES_API_HOSTNAME
from server.yggdrasil.textures.local import (
    _persist_cached_skin_model,
    _remove_local_skin_model_metadata,
    _remove_local_texture_files,
)
from server.yggdrasil.textures.metadata import _resolve_remote_texture_metadata
from server.yggdrasil.textures.resolver import (
    _resolve_skin_model,
    invalidate_texture_cache,
)
from server.yggdrasil.textures.urls import _collect_texture_identifiers


__all__ = ["cache_textures", "refresh_textures"]


def cache_textures(
    uuid_hex: str = "",
    username: str = "",
    probe_remote: bool = True,
    timeout_seconds: float = 3.0,
) -> dict:
    out: dict[str, list] = {"skin": [], "cape": []}
    if not probe_remote or not _histolauncher_account_enabled():
        return out

    try:
        uname, cur_u_hex = _get_username_and_uuid()
        u_hex = _normalize_uuid_hex(uuid_hex) or _normalize_uuid_hex(cur_u_hex)
        profile_name = (username or uname or "").strip()

        identifiers = _collect_texture_identifiers(u_hex or "", profile_name)

        base_dir = os.path.expanduser("~/.histolauncher")
        skins_dir = os.path.join(base_dir, "skins")
        os.makedirs(skins_dir, exist_ok=True)

        def _write_image(kind: str, data: bytes) -> list[str]:
            saved: list[str] = []
            try:
                if u_hex:
                    dashed = _uuid_hex_to_dashed(u_hex)
                    targets = [dashed, u_hex]
                else:
                    targets = []

                if profile_name:
                    targets.append(profile_name)

                seen: set[str] = set()
                final: list[str] = []
                for t in targets:
                    if not t or t in seen:
                        continue
                    seen.add(t)
                    final.append(t)

                for t in final:
                    suffix = "skin" if kind == "skin" else "cape"
                    fname = os.path.join(skins_dir, f"{t}+{suffix}.png")
                    try:
                        with open(fname, "wb") as wf:
                            wf.write(data)
                        saved.append(fname)
                    except Exception:
                        continue
            except Exception:
                pass
            return saved

        meta = _resolve_remote_texture_metadata(u_hex or "", profile_name)

        for ttype in ("skin", "cape"):
            urls: list[str] = []
            if meta is not None:
                remote_url = (meta or {}).get(ttype)
                if remote_url:
                    urls.append(remote_url)
                else:
                    removed = _remove_local_texture_files(u_hex or "", profile_name, ttype)
                    out[ttype].extend(removed)
                    if ttype == "skin":
                        out[ttype].extend(_remove_local_skin_model_metadata(u_hex or ""))
                    continue
            else:
                for ident in identifiers:
                    if not ident:
                        continue
                    candidate = (
                        f"https://{TEXTURES_API_HOSTNAME}/{ttype}/"
                        f"{urllib.parse.quote(str(ident), safe='')}"
                    )
                    if candidate not in urls:
                        urls.append(candidate)

            for remote_url in urls:
                try:
                    probe_url = _apply_url_proxy(remote_url)
                    req = urllib.request.Request(
                        probe_url, headers={"User-Agent": "Histolauncher/1.0"}
                    )
                    with urllib.request.urlopen(
                        req, timeout=float(timeout_seconds)
                    ) as resp:
                        ctype = str(resp.headers.get("Content-Type") or "").lower()
                        if "image" not in ctype:
                            continue
                        data = resp.read()
                    saved = _write_image(ttype, data)
                    out[ttype].extend(saved)
                    if ttype == "skin":
                        try:
                            _persist_cached_skin_model(
                                u_hex or "",
                                _resolve_skin_model(u_hex or "", profile_name) or "classic",
                                profile_name,
                            )
                        except Exception:
                            pass
                    break
                except Exception:
                    continue
    except Exception:
        pass

    return out


def refresh_textures(
    uuid_hex: str = "", username: str = "", timeout_seconds: float = 3.0
) -> dict:
    uname, cur_u_hex = _get_username_and_uuid()
    u_hex = _normalize_uuid_hex(uuid_hex) or _normalize_uuid_hex(cur_u_hex)
    profile_name = (username or uname or "").strip()

    invalidate_texture_cache(u_hex, profile_name)
    result = cache_textures(
        u_hex,
        profile_name,
        probe_remote=True,
        timeout_seconds=timeout_seconds,
    )
    result["texture_revision"] = int(time.time() * 1000)
    return result
