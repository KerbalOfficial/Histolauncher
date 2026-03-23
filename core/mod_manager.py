# core/mod_manager.py

import os
import json
import shutil
import time
import zipfile
import re
import io
import urllib.request
import urllib.parse
import urllib.error
import logging

from typing         import List, Dict, Any, Optional

from core.settings  import get_mods_profile_dir, _apply_url_proxy

logger = logging.getLogger(__name__)

CURSEFORGE_API_BASE = "https://mods.histolauncher.workers.dev/curseforge"
MODRINTH_API_BASE = "https://mods.histolauncher.workers.dev/modrinth"

CURSEFORGE_MINECRAFT_GAME_ID = 432

CURSEFORGE_MODLOADER_TYPE_FORGE = 1
CURSEFORGE_MODLOADER_TYPE_FABRIC = 4

REQUEST_TIMEOUT = 30.0

_MODRINTH_CACHE: Dict[str, Any] = {}
_MODRINTH_SEARCH_TTL = 120
_MODRINTH_DETAIL_TTL = 300

_MAX_SAFE_COMPONENT_LENGTH = 128


def _is_within_dir(base_dir: str, target_path: str) -> bool:
    base_real = os.path.realpath(base_dir)
    target_real = os.path.realpath(target_path)
    return target_real == base_real or target_real.startswith(base_real + os.sep)


def _validate_mod_slug(mod_slug: str) -> bool:
    if not isinstance(mod_slug, str):
        return False
    s = mod_slug.strip().lower()
    if not s or len(s) > _MAX_SAFE_COMPONENT_LENGTH:
        return False
    if "/" in s or "\\" in s or ".." in s:
        return False
    return bool(re.match(r"^[a-z0-9][a-z0-9._-]*$", s))


def _validate_modpack_slug(slug: str) -> bool:
    if not isinstance(slug, str):
        return False
    s = slug.strip().lower()
    if not s or len(s) > _MAX_SAFE_COMPONENT_LENGTH:
        return False
    if "/" in s or "\\" in s or ".." in s:
        return False
    return bool(re.match(r"^[a-z0-9][a-z0-9-]*$", s))


def normalize_version_label(version_label: str) -> str:
    raw = str(version_label or "").strip()
    raw = raw.replace("/", "_").replace("\\", "_").replace("|", "_").replace("..", "_")
    safe_label = re.sub(r"[^a-zA-Z0-9._ +()-]+", "_", raw).strip(" .")
    if not safe_label:
        safe_label = "unknown"
    return safe_label[:_MAX_SAFE_COMPONENT_LENGTH]


def _validate_jar_filename(file_name: str) -> bool:
    if not isinstance(file_name, str):
        return False
    f = file_name.strip()
    if not f or len(f) > 255:
        return False
    if os.path.basename(f) != f:
        return False
    if "/" in f or "\\" in f or ".." in f:
        return False
    if any(c in f for c in '<>:"|?*'):
        return False
    return f.lower().endswith(".jar")


def _normalize_download_url(download_url: str) -> str:
    raw = str(download_url or "").strip()
    if not raw:
        return ""
    try:
        parts = urllib.parse.urlsplit(raw)
        if not parts.scheme or not parts.netloc:
            return raw
        encoded_path = urllib.parse.quote(
            urllib.parse.unquote(parts.path),
            safe="/@%+~!$&'()*,;=:-._"
        )
        encoded_query = urllib.parse.quote(
            urllib.parse.unquote(parts.query),
            safe="=&%+/:,.-_~!$'()[]*"
        )
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, encoded_path, encoded_query, parts.fragment))
    except Exception:
        return raw


def _modrinth_cache_get(key: str) -> Optional[Any]:
    entry = _MODRINTH_CACHE.get(key)
    if entry and time.monotonic() < entry["expires"]:
        return entry["data"]
    if entry:
        del _MODRINTH_CACHE[key]
    return None


def _modrinth_cache_set(key: str, data: Any, ttl: float) -> None:
    _MODRINTH_CACHE[key] = {"data": data, "expires": time.monotonic() + ttl}


def get_mods_storage_dir() -> str:
    profile_root = get_mods_profile_dir()
    mods_dir = os.path.join(profile_root, "mods")
    os.makedirs(mods_dir, exist_ok=True)
    return mods_dir


def get_mod_dir(mod_loader: str, mod_slug: str) -> str:
    if not _validate_mod_slug(mod_slug):
        raise ValueError(f"Invalid mod slug: {mod_slug}")
    mods_storage = get_mods_storage_dir()
    mod_dir = os.path.join(mods_storage, mod_loader.lower(), mod_slug)
    os.makedirs(mod_dir, exist_ok=True)
    return mod_dir


def get_mod_version_dir(mod_loader: str, mod_slug: str, version_label: str) -> str:
    mod_dir = get_mod_dir(mod_loader, mod_slug)
    safe_label = normalize_version_label(version_label)
    ver_dir = os.path.join(mod_dir, safe_label)
    os.makedirs(ver_dir, exist_ok=True)
    return ver_dir


def get_installed_mods() -> List[Dict[str, Any]]:
    mods_storage = get_mods_storage_dir()
    installed = []

    if not os.path.isdir(mods_storage):
        return installed

    for loader_name in os.listdir(mods_storage):
        loader_path = os.path.join(mods_storage, loader_name)
        if not os.path.isdir(loader_path):
            continue

        for mod_slug in os.listdir(loader_path):
            mod_path = os.path.join(loader_path, mod_slug)
            if not os.path.isdir(mod_path):
                continue

            display_path = os.path.join(mod_path, "display.png")
            local_icon_url = ""
            if os.path.isfile(display_path):
                local_icon_url = f"/mods-cache/{loader_name}/{mod_slug}/display.png"

            meta_file = os.path.join(mod_path, "mod_meta.json")
            if not os.path.isfile(meta_file):
                continue

            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read mod meta for {loader_name}/{mod_slug}: {e}")
                continue

            versions = []
            for entry in os.listdir(mod_path):
                ver_path = os.path.join(mod_path, entry)
                if not os.path.isdir(ver_path):
                    continue
                ver_meta_file = os.path.join(ver_path, "version_meta.json")
                if not os.path.isfile(ver_meta_file):
                    continue
                try:
                    with open(ver_meta_file, "r", encoding="utf-8") as f:
                        ver_meta = json.load(f)
                    jar_files = [fn for fn in os.listdir(ver_path) if fn.endswith(".jar")]
                    versions.append({
                        "version_label": entry,
                        "version": ver_meta.get("version", entry),
                        "mod_loader": ver_meta.get("mod_loader", loader_name),
                        "file_name": ver_meta.get("file_name", ""),
                        "jar_count": len(jar_files),
                    })
                except Exception as e:
                    logger.warning(f"Failed to read version meta {loader_name}/{mod_slug}/{entry}: {e}")

            installed.append({
                "mod_slug": mod_slug,
                "mod_name": meta.get("name", mod_slug),
                "mod_id": meta.get("mod_id"),
                "mod_loader": meta.get("mod_loader", loader_name),
                "description": meta.get("description", ""),
                "icon_url": local_icon_url or meta.get("icon_url", ""),
                "provider": meta.get("provider", "unknown"),
                "active_version": meta.get("active_version", ""),
                "disabled": meta.get("disabled", False),
                "is_imported": meta.get("is_imported", False),
                "versions": versions,
            })

    return installed


def save_mod_metadata(mod_loader: str, mod_slug: str, metadata: Dict[str, Any]):
    mod_dir = get_mod_dir(mod_loader, mod_slug)
    meta_file = os.path.join(mod_dir, "mod_meta.json")

    try:
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save mod metadata for {mod_loader}/{mod_slug}: {e}")


def save_version_metadata(mod_loader: str, mod_slug: str, version_label: str, metadata: Dict[str, Any]):
    ver_dir = get_mod_version_dir(mod_loader, mod_slug, version_label)
    meta_file = os.path.join(ver_dir, "version_meta.json")

    try:
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save version metadata for {mod_slug}/{version_label}: {e}")


def set_active_version(mod_loader: str, mod_slug: str, version_label: str) -> bool:
    mod_dir = get_mod_dir(mod_loader, mod_slug)
    meta_file = os.path.join(mod_dir, "mod_meta.json")
    if not os.path.isfile(meta_file):
        return False
    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["active_version"] = version_label
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        logger.info(f"Set active version for {mod_slug} to {version_label}")
        return True
    except Exception as e:
        logger.error(f"Failed to set active version for {mod_slug}: {e}")
        return False


def toggle_mod_disabled(mod_loader: str, mod_slug: str, disabled: bool) -> bool:
    mod_dir = get_mod_dir(mod_loader, mod_slug)
    meta_file = os.path.join(mod_dir, "mod_meta.json")
    if not os.path.isfile(meta_file):
        return False
    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["disabled"] = disabled
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        logger.info(f"{'Disabled' if disabled else 'Enabled'} mod {mod_slug}")
        return True
    except Exception as e:
        logger.error(f"Failed to toggle mod {mod_slug}: {e}")
        return False


def download_mod_icon(icon_url: str, mod_loader: str, mod_slug: str) -> bool:
    if not icon_url:
        return False
    mod_dir = get_mod_dir(mod_loader, mod_slug)
    display_path = os.path.join(mod_dir, "display.png")
    if os.path.isfile(display_path):
        return True
    try:
        url = _apply_url_proxy(icon_url)
        req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher/1.0"})
        with urllib.request.urlopen(req, timeout=10.0) as response:
            with open(display_path, "wb") as f:
                shutil.copyfileobj(response, f)
        return True
    except Exception as e:
        logger.warning(f"Failed to download mod icon for {mod_slug}: {e}")
        return False


def get_mod_detail_modrinth(mod_id: str) -> Optional[Dict[str, Any]]:
    cache_key = f"detail:{mod_id}"
    cached = _modrinth_cache_get(cache_key)
    if cached is not None:
        return cached

    response = _modrinth_request(f"/project/{mod_id}")
    if not response:
        return None
    result = {
        "title": response.get("title", ""),
        "description": response.get("description", ""),
        "body": response.get("body", ""),
        "icon_url": response.get("icon_url", ""),
        "gallery": response.get("gallery", []),
        "downloads": response.get("downloads", 0),
        "categories": response.get("categories", []),
        "source_url": response.get("source_url", ""),
        "issues_url": response.get("issues_url", ""),
        "wiki_url": response.get("wiki_url", ""),
    }
    _modrinth_cache_set(cache_key, result, _MODRINTH_DETAIL_TTL)
    return result


def get_mod_detail_curseforge(mod_id: str) -> Optional[Dict[str, Any]]:
    response = _curseforge_request(f"/mods/{mod_id}")
    if not response or "data" not in response:
        return None
    mod = response["data"]
    
    screenshots = []
    for ss in (mod.get("screenshots") or []):
        if isinstance(ss, dict) and ss.get("url"):
            screenshots.append({"url": ss["url"], "title": ss.get("title", "")})
    
    desc_resp = _curseforge_request(f"/mods/{mod_id}/description")
    body_html = ""
    if desc_resp and "data" in desc_resp:
        body_html = desc_resp["data"]
    
    return {
        "title": mod.get("name", ""),
        "description": mod.get("summary", ""),
        "body": body_html,
        "icon_url": (mod.get("logo") or {}).get("url", ""),
        "gallery": screenshots,
        "downloads": mod.get("downloadCount", 0),
        "categories": [c.get("name", "") for c in (mod.get("categories") or []) if isinstance(c, dict)],
        "source_url": (mod.get("links") or {}).get("sourceUrl", ""),
        "issues_url": (mod.get("links") or {}).get("issuesUrl", ""),
        "wiki_url": (mod.get("links") or {}).get("wikiUrl", ""),
    }


def delete_mod(mod_loader: str, mod_slug: str, version_label: str = None) -> bool:
    if not _validate_mod_slug(mod_slug):
        return False

    mod_dir = get_mod_dir(mod_loader, mod_slug)

    try:
        if version_label:
            safe_version_label = normalize_version_label(version_label)
            ver_dir = os.path.join(mod_dir, safe_version_label)
            if not _is_within_dir(mod_dir, ver_dir):
                return False
            if os.path.isdir(ver_dir):
                shutil.rmtree(ver_dir)
                logger.info(f"Deleted version {safe_version_label} of mod {mod_slug}")

                meta_file = os.path.join(mod_dir, "mod_meta.json")
                if os.path.isfile(meta_file):
                    with open(meta_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    if meta.get("active_version") == safe_version_label:
                        remaining = [d for d in os.listdir(mod_dir)
                                     if os.path.isdir(os.path.join(mod_dir, d))
                                     and os.path.isfile(os.path.join(mod_dir, d, "version_meta.json"))]
                        meta["active_version"] = remaining[0] if remaining else ""
                        with open(meta_file, "w", encoding="utf-8") as f:
                            json.dump(meta, f, indent=2)

                remaining = [d for d in os.listdir(mod_dir)
                             if os.path.isdir(os.path.join(mod_dir, d))
                             and os.path.isfile(os.path.join(mod_dir, d, "version_meta.json"))]
                if not remaining:
                    shutil.rmtree(mod_dir)
                    logger.info(f"No versions left - deleted entire mod {mod_slug}")
                return True
            return False
        else:
            if os.path.isdir(mod_dir):
                shutil.rmtree(mod_dir)
                logger.info(f"Deleted mod {mod_slug}")
                return True
    except Exception as e:
        logger.error(f"Failed to delete mod {mod_slug}: {e}")

    return False


# ==================== Modpack Management ====================

_MODPACK_NAME_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def get_modpacks_storage_dir() -> str:
    profile_root = get_mods_profile_dir()
    d = os.path.join(profile_root, "modpacks")
    os.makedirs(d, exist_ok=True)
    return d


def _modpack_slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or "modpack"


def _is_modpack_mod_enabled(mod_entry: Dict[str, Any]) -> bool:
    return not bool(mod_entry.get("disabled", False))


def _get_modpack_mod_icon_path(pack_dir: str, mod_loader: str, mod_slug: str) -> str:
    icon_new = os.path.join(pack_dir, "mods", mod_slug, "display.png")
    if os.path.isfile(icon_new):
        return icon_new

    icon_legacy = os.path.join(pack_dir, "mod_icons", mod_slug, "display.png")
    if os.path.isfile(icon_legacy):
        return icon_legacy

    icon_legacy_loader = os.path.join(pack_dir, "mods", mod_loader, mod_slug, "display.png")
    if os.path.isfile(icon_legacy_loader):
        return icon_legacy_loader

    return ""


def get_installed_modpacks() -> List[Dict[str, Any]]:
    base = get_modpacks_storage_dir()
    result = []
    if not os.path.isdir(base):
        return result
    for slug in os.listdir(base):
        pack_dir = os.path.join(base, slug)
        if not os.path.isdir(pack_dir):
            continue
        data_file = os.path.join(pack_dir, "data.json")
        if not os.path.isfile(data_file):
            continue
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            icon_url = ""
            if os.path.isfile(os.path.join(pack_dir, "display.png")):
                icon_url = f"/modpacks-cache/{slug}/display.png"
            data["slug"] = slug
            data["icon_url"] = icon_url
            mod_loader = (data.get("mod_loader") or "").lower()
            for mod_entry in data.get("mods", []):
                ms = mod_entry.get("mod_slug", "")
                mod_entry["disabled"] = bool(mod_entry.get("disabled", False))
                icon_path = _get_modpack_mod_icon_path(pack_dir, mod_loader, ms) if ms else ""
                if icon_path:
                    rel = os.path.relpath(icon_path, pack_dir).replace("\\", "/")
                    mod_entry["icon_url"] = f"/modpacks-cache/{slug}/{rel}"
                else:
                    mod_entry["icon_url"] = ""
            result.append(data)
        except Exception as e:
            logger.warning(f"Failed to read modpack {slug}: {e}")
    return result


def export_modpack(name: str, version: str, description: str,
                   mod_loader: str, mods: List[Dict[str, Any]],
                   image_data: bytes = None) -> bytes:
    buf = io.BytesIO()
    mods_storage = get_mods_storage_dir()
    mod_entries = []

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        written_paths = set()

        def _write_if_exists(src_path: str, arc_path: str) -> bool:
            if not os.path.isfile(src_path):
                return False
            normalized_arc = str(arc_path or "").replace("\\", "/").lstrip("/")
            if not normalized_arc or normalized_arc in written_paths:
                return False
            zf.write(src_path, normalized_arc)
            written_paths.add(normalized_arc)
            return True

        if image_data:
            zf.writestr("display.png", image_data)
            written_paths.add("display.png")

        for m in mods:
            slug = m.get("mod_slug", "")
            ver_label = m.get("version_label", "")
            if not slug or not ver_label:
                continue

            mod_dir = os.path.join(mods_storage, mod_loader.lower(), slug)
            ver_dir = os.path.join(mod_dir, ver_label)
            if not os.path.isdir(ver_dir):
                continue

            disabled_in_pack = bool(m.get("disabled", False))

            for fn in sorted(os.listdir(ver_dir)):
                src = os.path.join(ver_dir, fn)
                if not os.path.isfile(src):
                    continue
                arc_path = f"mods/{slug}/{ver_label}/{fn}"
                _write_if_exists(src, arc_path)

            meta_src = os.path.join(mod_dir, "mod_meta.json")
            _write_if_exists(meta_src, f"mods/{slug}/mod_meta.json")

            mod_icon_src = os.path.join(mod_dir, "display.png")
            _write_if_exists(mod_icon_src, f"mods/{slug}/display.png")

            meta_file = os.path.join(mod_dir, "mod_meta.json")
            mod_name = slug
            if os.path.isfile(meta_file):
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        mm = json.load(f)
                    mod_name = mm.get("name", slug)
                except Exception:
                    pass

            mod_entries.append({
                "mod_slug": slug,
                "mod_name": mod_name,
                "version_label": ver_label,
                "disabled": disabled_in_pack,
            })

        data_json = {
            "name": name,
            "version": version,
            "description": description,
            "mod_loader": mod_loader.lower(),
            "mod_count": len(mod_entries),
            "mods": mod_entries,
        }
        zf.writestr("data.json", json.dumps(data_json, indent=2))

    return buf.getvalue()


def import_modpack(hlmp_bytes: bytes) -> Dict[str, Any]:
    import io

    try:
        zf = zipfile.ZipFile(io.BytesIO(hlmp_bytes), "r")
    except Exception:
        return {"ok": False, "error": "Invalid .hlmp file (not a valid zip)"}

    if "data.json" not in zf.namelist():
        return {"ok": False, "error": "Invalid modpack: missing data.json"}

    try:
        data = json.loads(zf.read("data.json"))
    except Exception:
        return {"ok": False, "error": "Invalid modpack: corrupt data.json"}

    pack_name = (data.get("name") or "").strip()
    if not pack_name or len(pack_name) > 64 or _MODPACK_NAME_FORBIDDEN.search(pack_name):
        return {"ok": False, "error": "Invalid modpack name"}

    mod_loader = (data.get("mod_loader") or "").lower()
    if mod_loader not in ("fabric", "forge"):
        return {"ok": False, "error": "Invalid mod_loader in modpack"}

    normalized_mods = []
    for pm in data.get("mods", []):
        if not isinstance(pm, dict):
            continue
        mod_slug = str(pm.get("mod_slug") or "").strip().lower()
        if not mod_slug:
            continue
        normalized_mods.append({
            "mod_slug": mod_slug,
            "mod_name": pm.get("mod_name", mod_slug),
            "version_label": str(pm.get("version_label") or "").strip(),
            "disabled": bool(pm.get("disabled", False)),
        })

    data["mods"] = normalized_mods
    pack_mods = normalized_mods
    slug = _modpack_slug(pack_name)

    existing_packs = get_installed_modpacks()
    incoming_slugs = {m.get("mod_slug") for m in pack_mods if m.get("mod_slug")}

    for ep in existing_packs:
        if ep.get("slug") == slug:
            continue
        ep_slugs = {m.get("mod_slug") for m in ep.get("mods", []) if m.get("mod_slug")}
        overlap = incoming_slugs & ep_slugs
        if overlap:
            names = ", ".join(sorted(overlap)[:5])
            return {
                "ok": False,
                "error": f"Conflict with modpack \"{ep.get('name', ep.get('slug'))}\": overlapping mods ({names})",
            }

    base = get_modpacks_storage_dir()
    pack_dir = os.path.join(base, slug)
    pack_dir_real = os.path.realpath(pack_dir)
    if os.path.isdir(pack_dir):
        shutil.rmtree(pack_dir)
    os.makedirs(pack_dir, exist_ok=True)

    for zi in zf.infolist():
        if zi.is_dir():
            continue
        if zi.filename.startswith("mods/") or zi.filename.startswith("mod_icons/"):
            normalized = zi.filename.replace("\\", "/")
            parts = normalized.split("/")
            if any(part in ("", ".", "..") for part in parts):
                shutil.rmtree(pack_dir, ignore_errors=True)
                zf.close()
                return {"ok": False, "error": f"Invalid path in modpack archive: {zi.filename}"}

            target = os.path.join(pack_dir, normalized.replace("/", os.sep))
            target_real = os.path.realpath(target)
            if not _is_within_dir(pack_dir_real, target_real):
                shutil.rmtree(pack_dir, ignore_errors=True)
                zf.close()
                return {"ok": False, "error": f"Unsafe archive entry: {zi.filename}"}

            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(zi) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)

    if "display.png" in zf.namelist():
        display_target = os.path.join(pack_dir, "display.png")
        with zf.open("display.png") as src, open(display_target, "wb") as dst:
            shutil.copyfileobj(src, dst)

    legacy_loader_root = os.path.join(pack_dir, "mods", mod_loader)
    if os.path.isdir(legacy_loader_root):
        for slug_name in os.listdir(legacy_loader_root):
            legacy_slug_dir = os.path.join(legacy_loader_root, slug_name)
            if not os.path.isdir(legacy_slug_dir):
                continue

            canonical_slug_dir = os.path.join(pack_dir, "mods", slug_name)
            os.makedirs(canonical_slug_dir, exist_ok=True)

            for entry in os.listdir(legacy_slug_dir):
                src = os.path.join(legacy_slug_dir, entry)
                dst = os.path.join(canonical_slug_dir, entry)
                if os.path.exists(dst):
                    continue
                shutil.move(src, dst)

            try:
                if not os.listdir(legacy_slug_dir):
                    os.rmdir(legacy_slug_dir)
            except Exception:
                pass

        try:
            if not os.listdir(legacy_loader_root):
                os.rmdir(legacy_loader_root)
        except Exception:
            pass

    legacy_icons_root = os.path.join(pack_dir, "mod_icons")
    if os.path.isdir(legacy_icons_root):
        for slug_name in os.listdir(legacy_icons_root):
            icon_src = os.path.join(legacy_icons_root, slug_name, "display.png")
            if not os.path.isfile(icon_src):
                continue
            icon_dst = os.path.join(pack_dir, "mods", slug_name, "display.png")
            os.makedirs(os.path.dirname(icon_dst), exist_ok=True)
            if not os.path.isfile(icon_dst):
                shutil.copy2(icon_src, icon_dst)

    data["disabled"] = False
    data["slug"] = slug
    data["mods"] = pack_mods
    with open(os.path.join(pack_dir, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    mods_storage = get_mods_storage_dir()
    disabled_standalone = []
    for pm in pack_mods:
        if not _is_modpack_mod_enabled(pm):
            continue
        ms = pm.get("mod_slug", "")
        if not ms:
            continue
        mod_dir = os.path.join(mods_storage, mod_loader, ms)
        meta_file = os.path.join(mod_dir, "mod_meta.json")
        if os.path.isfile(meta_file):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    mm = json.load(f)
                if not mm.get("disabled"):
                    mm["disabled"] = True
                    mm["blocked_by_modpack"] = slug
                    with open(meta_file, "w", encoding="utf-8") as f:
                        json.dump(mm, f, indent=2)
                    disabled_standalone.append(ms)
            except Exception:
                pass

    zf.close()
    return {
        "ok": True,
        "name": pack_name,
        "slug": slug,
        "disabled_standalone": disabled_standalone,
    }


def toggle_mod_in_modpack(pack_slug: str, mod_slug: str, disabled: bool) -> bool:
    if not _validate_modpack_slug(pack_slug) or not _validate_mod_slug(mod_slug):
        return False
    base = get_modpacks_storage_dir()
    data_file = os.path.join(base, pack_slug, "data.json")
    if not os.path.isfile(data_file):
        return False
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        found = False
        for m in data.get("mods", []):
            if m.get("mod_slug") == mod_slug:
                m["disabled"] = disabled
                found = True
        if not found:
            return False
        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Toggled mod {mod_slug} in modpack {pack_slug}: disabled={disabled}")
        return True
    except Exception as e:
        logger.error(f"Failed to toggle mod in modpack {pack_slug}/{mod_slug}: {e}")
        return False


def toggle_modpack(slug: str, disabled: bool) -> bool:
    if not _validate_modpack_slug(slug):
        return False
    base = get_modpacks_storage_dir()
    data_file = os.path.join(base, slug, "data.json")
    if not os.path.isfile(data_file):
        return False
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["disabled"] = disabled
        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        if disabled:
            _unblock_standalone_mods(slug)

        if not disabled:
            mods_storage = get_mods_storage_dir()
            mod_loader = data.get("mod_loader", "")
            for pm in data.get("mods", []):
                if not _is_modpack_mod_enabled(pm):
                    continue
                ms = pm.get("mod_slug", "")
                if not ms:
                    continue
                mod_dir = os.path.join(mods_storage, mod_loader, ms)
                meta_file = os.path.join(mod_dir, "mod_meta.json")
                if os.path.isfile(meta_file):
                    try:
                        with open(meta_file, "r", encoding="utf-8") as f:
                            mm = json.load(f)
                        mm["disabled"] = True
                        mm["blocked_by_modpack"] = slug
                        with open(meta_file, "w", encoding="utf-8") as f:
                            json.dump(mm, f, indent=2)
                    except Exception:
                        pass

        return True
    except Exception as e:
        logger.error(f"Failed to toggle modpack {slug}: {e}")
        return False


def delete_modpack(slug: str) -> bool:
    if not _validate_modpack_slug(slug):
        return False
    base = get_modpacks_storage_dir()
    pack_dir = os.path.join(base, slug)
    if not os.path.isdir(pack_dir):
        return False
    try:
        _unblock_standalone_mods(slug)
        shutil.rmtree(pack_dir)
        logger.info(f"Deleted modpack {slug}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete modpack {slug}: {e}")
        return False


def _unblock_standalone_mods(modpack_slug: str):
    mods_storage = get_mods_storage_dir()
    if not os.path.isdir(mods_storage):
        return
    for loader_name in os.listdir(mods_storage):
        loader_path = os.path.join(mods_storage, loader_name)
        if not os.path.isdir(loader_path):
            continue
        for mod_slug in os.listdir(loader_path):
            mod_path = os.path.join(loader_path, mod_slug)
            meta_file = os.path.join(mod_path, "mod_meta.json")
            if not os.path.isfile(meta_file):
                continue
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    mm = json.load(f)
                if mm.get("blocked_by_modpack") == modpack_slug:
                    mm["disabled"] = False
                    mm.pop("blocked_by_modpack", None)
                    with open(meta_file, "w", encoding="utf-8") as f:
                        json.dump(mm, f, indent=2)
            except Exception:
                pass


# ==================== CurseForge API ====================

def _curseforge_request(endpoint: str, params: Dict[str, Any] = None, api_key: str = None) -> Optional[Dict[str, Any]]:
    url = f"{CURSEFORGE_API_BASE}{endpoint}"
    
    if params:
        url += "?" + urllib.parse.urlencode(params)
    
    headers = {
        "Accept": "application/json",
        "User-Agent": "Histolauncher/1.0"
    }
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        logger.error(f"CurseForge API HTTP error: {e.code} {e.reason} body={body[:240]}")
        return {
            "error": f"CurseForge HTTP {e.code}",
            "requires_api_key": e.code in (401, 403),
        }
    except urllib.error.URLError as e:
        logger.error(f"CurseForge API URL error: {e}")
        return {
            "error": "CurseForge connection failed",
            "requires_api_key": False,
        }
    except Exception as e:
        logger.error(f"CurseForge API request failed: {e}")
        return {
            "error": "CurseForge request failed",
            "requires_api_key": False,
        }


def search_mods_curseforge(
    search_query: str = "",
    game_version: str = None,
    mod_loader_type: str = None,
    page_size: int = 20,
    index: int = 0,
    api_key: str = None 
) -> Dict[str, Any]:
    safe_page_size = max(1, min(int(page_size or 20), 50))
    safe_index = max(0, int(index or 0))
    offset = safe_index * safe_page_size

    params = {
        "gameId": CURSEFORGE_MINECRAFT_GAME_ID,
        "classId": 6,
        "pageSize": safe_page_size,
        "index": offset,
        "sortField": 2,
        "sortOrder": "desc",
    }
    
    if search_query:
        params["searchFilter"] = search_query
        params["sortField"] = 1
    
    if game_version:
        params["gameVersion"] = game_version
    
    if mod_loader_type:
        if mod_loader_type.lower() == "forge":
            params["modLoaderType"] = CURSEFORGE_MODLOADER_TYPE_FORGE
        elif mod_loader_type.lower() == "fabric":
            params["modLoaderType"] = CURSEFORGE_MODLOADER_TYPE_FABRIC
    
    response = _curseforge_request("/mods/search", params, api_key)
    
    if not response or "data" not in response:
        return {
            "mods": [],
            "total": 0,
            "has_more": False,
            "error": (response or {}).get("error"),
            "requires_api_key": bool((response or {}).get("requires_api_key")),
        }
    
    mods = []
    for mod in response.get("data", []):
        categories = []
        for cat in (mod.get("categories") or []):
            if isinstance(cat, dict):
                name = (cat.get("name") or "").strip()
                if name:
                    categories.append(name)

        mods.append({
            "mod_id": str(mod.get("id")),
            "mod_slug": mod.get("slug", ""),
            "name": mod.get("name", ""),
            "summary": mod.get("summary", ""),
            "icon_url": mod.get("logo", {}).get("url", ""),
            "download_count": mod.get("downloadCount", 0),
            "date_modified": mod.get("dateModified", ""),
            "categories": categories,
            "provider": "curseforge",
        })
    
    pagination = response.get("pagination", {})
    total = pagination.get("totalCount", 0)
    
    return {
        "mods": mods,
        "total": total,
        "has_more": offset + len(mods) < total,
        "error": None,
        "requires_api_key": False,
    }


def get_mod_files_curseforge(mod_id: str, game_version: str = None, mod_loader_type: str = None, api_key: str = None) -> List[Dict[str, Any]]:
    PAGE_SIZE = 50
    params = {"pageSize": PAGE_SIZE, "index": 0}

    if game_version:
        params["gameVersion"] = game_version

    if mod_loader_type:
        if mod_loader_type.lower() == "forge":
            params["modLoaderType"] = CURSEFORGE_MODLOADER_TYPE_FORGE
        elif mod_loader_type.lower() == "fabric":
            params["modLoaderType"] = CURSEFORGE_MODLOADER_TYPE_FABRIC

    all_file_data = []
    while True:
        response = _curseforge_request(f"/mods/{mod_id}/files", params, api_key)
        if not response or "data" not in response:
            break
        page = response.get("data", [])
        all_file_data.extend(page)
        pagination = response.get("pagination", {})
        total_count = pagination.get("totalCount", len(all_file_data))
        if len(all_file_data) >= total_count or len(page) < PAGE_SIZE:
            break
        params["index"] += PAGE_SIZE

    files = []
    for file_data in all_file_data:
        game_versions = file_data.get("gameVersions", [])
        loaders = []
        clean_versions = []
        for gv in game_versions:
            gv_lower = gv.lower()
            if gv_lower in ("fabric", "forge", "neoforge", "quilt"):
                loaders.append(gv_lower)
            else:
                clean_versions.append(gv)

        cf_release_type = file_data.get("releaseType", 1)
        if cf_release_type == 1:
            version_type = "release"
        elif cf_release_type == 2:
            version_type = "beta"
        else:
            version_type = "alpha"

        files.append({
            "file_id": str(file_data.get("id")),
            "file_name": file_data.get("fileName", ""),
            "display_name": file_data.get("displayName", ""),
            "version_number": file_data.get("displayName", file_data.get("fileName", "")),
            "version_type": version_type,
            "file_date": file_data.get("fileDate", ""),
            "download_url": _cf_resolve_download_url(file_data),
            "file_length": file_data.get("fileLength", 0),
            "game_versions": clean_versions,
            "loaders": loaders,
        })
    
    return files


def _cf_resolve_download_url(file_data: Dict[str, Any]) -> str:
    url = file_data.get("downloadUrl") or ""
    if url:
        return url
    file_id = file_data.get("id", 0)
    file_name = file_data.get("fileName", "")
    if file_id and file_name:
        file_id_str = str(int(file_id))
        if len(file_id_str) >= 4:
            part1 = file_id_str[:-3]
            part2 = str(int(file_id_str[-3:]))  # strip leading zeros
            encoded_name = urllib.parse.quote(str(file_name), safe="")
            return f"https://edge.forgecdn.net/files/{part1}/{part2}/{encoded_name}"
    return ""


# ==================== Modrinth API ====================

def _modrinth_request(endpoint: str, params: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
    url = f"{MODRINTH_API_BASE}{endpoint}"
    
    if params:
        url += "?" + urllib.parse.urlencode(params)
    
    headers = {
        "Accept": "application/json",
        "User-Agent": "Histolauncher/1.0"
    }
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data
    except Exception as e:
        logger.error(f"Modrinth API request failed: {e}")
        return None


def search_mods_modrinth(
    search_query: str = "",
    game_version: str = None,
    mod_loader: str = None,
    limit: int = 20,
    offset: int = 0
) -> Dict[str, Any]:
    facets = [["project_type:mod"]]
    
    if game_version:
        facets.append([f"versions:{game_version}"])
    
    if mod_loader:
        facets.append([f"categories:{mod_loader.lower()}"])
    
    params = {
        "query": search_query,
        "limit": min(limit, 100),
        "offset": offset,
        "facets": json.dumps(facets, separators=(",", ":")),
    }

    if not (search_query or "").strip():
        params["index"] = "downloads"

    cache_key = f"search:{json.dumps(params, sort_keys=True)}"
    cached = _modrinth_cache_get(cache_key)
    if cached is not None:
        return cached

    response = _modrinth_request("/search", params)
    
    if not response:
        return {"mods": [], "total": 0, "has_more": False}
    
    mods = []
    for hit in response.get("hits", []):
        pt = (hit.get("project_type") or "mod").lower()
        if pt != "mod":
            continue
        mods.append({
            "mod_id": hit.get("project_id", ""),
            "mod_slug": hit.get("slug", ""),
            "name": hit.get("title", ""),
            "summary": hit.get("description", ""),
            "icon_url": hit.get("icon_url", ""),
            "download_count": hit.get("downloads", 0),
            "date_modified": hit.get("date_modified", ""),
            "project_type": hit.get("project_type", ""),
            "categories": hit.get("categories", []) or [],
            "provider": "modrinth",
        })
    
    total = response.get("total_hits", 0)
    
    result = {
        "mods": mods,
        "total": total,
        "has_more": offset + limit < total,
    }
    _modrinth_cache_set(cache_key, result, _MODRINTH_SEARCH_TTL)
    return result


def get_mod_versions_modrinth(mod_id: str, game_version: str = None, mod_loader: str = None) -> List[Dict[str, Any]]:
    params = {}
    
    loaders = []
    if mod_loader:
        loaders.append(mod_loader.lower())
    
    game_versions = []
    if game_version:
        game_versions.append(game_version)
    
    if loaders:
        params["loaders"] = json.dumps(loaders)
    
    if game_versions:
        params["game_versions"] = json.dumps(game_versions)
    
    cache_key = f"versions:{mod_id}:{game_version}:{mod_loader}"
    cached = _modrinth_cache_get(cache_key)
    if cached is not None:
        return cached
    
    response = _modrinth_request(f"/project/{mod_id}/version", params)
    
    if not response or not isinstance(response, list):
        _modrinth_cache_set(cache_key, [], _MODRINTH_DETAIL_TTL)
        return []
    
    versions = []
    for version_data in response:
        files = version_data.get("files", [])
        if not files:
            continue
            
        primary_file = files[0]
        
        versions.append({
            "version_id": version_data.get("id", ""),
            "version_number": version_data.get("version_number", ""),
            "name": version_data.get("name", ""),
            "version_type": version_data.get("version_type", "release"),
            "date_published": version_data.get("date_published", ""),
            "download_url": primary_file.get("url", ""),
            "file_name": primary_file.get("filename", ""),
            "file_size": primary_file.get("size", 0),
            "game_versions": version_data.get("game_versions", []),
            "loaders": version_data.get("loaders", []),
        })
    
    _modrinth_cache_set(cache_key, versions, _MODRINTH_DETAIL_TTL)
    return versions


def download_mod_file(download_url: str, mod_loader: str, mod_slug: str, version_label: str, file_name: str) -> bool:
    if not _validate_jar_filename(file_name):
        logger.error(f"Refusing unsafe mod filename: {file_name}")
        return False

    ver_dir = get_mod_version_dir(mod_loader, mod_slug, version_label)
    safe_file_name = os.path.basename(file_name)
    file_path = os.path.join(ver_dir, safe_file_name)

    if not _is_within_dir(ver_dir, file_path):
        logger.error(f"Refusing unsafe output path for mod file: {file_name}")
        return False

    normalized_url = _normalize_download_url(download_url)
    url = _apply_url_proxy(normalized_url)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher/1.0"})
        with urllib.request.urlopen(req, timeout=30.0) as response:
            with open(file_path, "wb") as f:
                shutil.copyfileobj(response, f)

        logger.info(f"Downloaded mod file: {safe_file_name} to {ver_dir}")
        return True
    except Exception as e:
        logger.error(f"Failed to download mod file {file_name}: {e}")
        return False
