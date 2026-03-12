# core/modloaders.py

import json
import urllib.request
import urllib.error
import urllib.parse
import time
import xml.etree.ElementTree as ET
import os

from typing import Dict, List, Optional, Tuple, Any
from core.settings import load_global_settings, _apply_url_proxy
from core.logger import colorize_log

FABRIC_META_API = "https://meta.fabricmc.net/v2"
FORGE_MAVEN_METADATA_API = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"

_fabric_cache = None
_forge_cache = None
_cache_timestamps = {}
_CACHE_TTL = 3600

TIMEOUT = 10.0


def _http_get_json(url: str, timeout: int = TIMEOUT) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        try:
            return json.loads(data.decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"Failed to parse JSON from {url}: {e}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} from {url}: {e.reason}")
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {url}: {e}")


# ============ FABRIC API ============


def fetch_fabric_loaders() -> Optional[List[Dict[str, Any]]]:
    global _fabric_cache, _cache_timestamps
    
    cache_key = "fabric"
    now = time.time()
    
    if _fabric_cache is not None and (now - _cache_timestamps.get(cache_key, 0)) < _CACHE_TTL:
        return _fabric_cache
    
    try:
        url = _apply_url_proxy(f"{FABRIC_META_API}/versions/loader")
        data = _http_get_json(url)
        
        if isinstance(data, list):
            _fabric_cache = data
            _cache_timestamps[cache_key] = now
            print(colorize_log(f"[modloaders] Fetched {len(data)} Fabric loader versions"))
            return data
        else:
            print(colorize_log(f"[modloaders] Unexpected Fabric response format"))
            return None
    except Exception as e:
        print(colorize_log(f"[modloaders] Failed to fetch Fabric loaders: {e}"))
        return None


def fetch_fabric_game_versions() -> Optional[List[Dict[str, Any]]]:
    try:
        url = _apply_url_proxy(f"{FABRIC_META_API}/versions/game")
        data = _http_get_json(url)
        
        if isinstance(data, list):
            print(colorize_log(f"[modloaders] Fetched {len(data)} Fabric game versions"))
            return data
        else:
            print(colorize_log(f"[modloaders] Unexpected Fabric game versions response format"))
            return None
    except Exception as e:
        print(colorize_log(f"[modloaders] Failed to fetch Fabric game versions: {e}"))
        return None


def get_fabric_loaders_for_version(mc_version: str, stable_only: bool = False) -> List[Dict[str, Any]]:
    loaders = fetch_fabric_loaders()
    if not loaders:
        return []
    if stable_only:
        return [l for l in loaders if l.get("stable", False)]
    
    return loaders


# ============ FORGE API ============


def fetch_forge_versions() -> Optional[List[str]]:
    global _forge_cache, _cache_timestamps
    
    cache_key = "forge"
    now = time.time()
    
    if _forge_cache is not None and (now - _cache_timestamps.get(cache_key, 0)) < _CACHE_TTL:
        return _forge_cache
    
    try:
        url = _apply_url_proxy(FORGE_MAVEN_METADATA_API)
        req = urllib.request.Request(url, headers={"User-Agent": "Histolauncher"})
        
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            xml_data = resp.read()
        
        root = ET.fromstring(xml_data)
        
        versions = []
        ns = {'': ''}
        
        for version_elem in root.findall('.//version'):
            if version_elem.text:
                versions.append(version_elem.text)
        
        if versions:
            _forge_cache = versions
            _cache_timestamps[cache_key] = now
            print(colorize_log(f"[modloaders] Fetched {len(versions)} Forge versions"))
            return versions
        else:
            print(colorize_log(f"[modloaders] No Forge versions found in metadata"))
            return None
    except Exception as e:
        print(colorize_log(f"[modloaders] Failed to fetch Forge versions: {e}"))
        return None


def get_forge_versions_for_mc(mc_version: str) -> List[Dict[str, str]]:
    versions = fetch_forge_versions()
    if not versions:
        return []

    def _forge_version_sort_key(v: str) -> tuple:
        """Sort Forge versions numerically, with non-numeric suffixes ranked lower.
        Examples:
        - 47.4.0 > 47.3.12
        - 14.23.5.2860 > 14.23.5.2859
        """
        if not isinstance(v, str):
            return (0,)

        main, sep, suffix = v.partition("-")
        numeric_parts = []
        for token in main.split("."):
            try:
                numeric_parts.append(int(token))
            except Exception:
                numeric_parts.append(0)

        # Keep tuple lengths comparable across versions
        while len(numeric_parts) < 6:
            numeric_parts.append(0)

        # Stable/release-like builds (no suffix) should appear before suffixed builds
        suffix_rank = 0 if not sep else -1
        return tuple(numeric_parts + [suffix_rank, suffix.lower() if suffix else ""])
    
    matching = []
    for version_str in versions:
        if "-" in version_str:
            parts = version_str.rsplit("-", 1)
            if len(parts) == 2:
                v_mc, v_forge = parts
                if v_mc == mc_version:
                    matching.append({
                        "mc_version": v_mc,
                        "forge_version": v_forge,
                        "full_version": version_str,
                    })

    matching.sort(key=lambda item: _forge_version_sort_key(item.get("forge_version", "")), reverse=True)
    return matching



def list_supported_mc_versions() -> Tuple[List[str], List[str]]:
    fabric_versions = []
    forge_mc_versions = []
    
    try:
        fabric_game_versions = fetch_fabric_game_versions()
        if fabric_game_versions:
            fabric_versions = [v.get("version") for v in fabric_game_versions if v.get("version")]
    except Exception:
        pass
    
    try:
        forge_versions = fetch_forge_versions()
        if forge_versions:
            seen = set()
            for version_str in forge_versions:
                if "-" in version_str:
                    mc_ver = version_str.rsplit("-", 1)[0]
                    if mc_ver not in seen:
                        forge_mc_versions.append(mc_ver)
                        seen.add(mc_ver)
    except Exception:
        pass
    
    return sorted(list(set(fabric_versions))), sorted(list(set(forge_mc_versions)), reverse=True)


# ============ DOWNLOAD URLS ============


def get_fabric_installer_url(mc_version: str, loader_version: str) -> Optional[str]:
    try:
        url = _apply_url_proxy(f"{FABRIC_META_API}/versions/installer")
        installers = _http_get_json(url)
        if isinstance(installers, list) and len(installers) > 0:
            latest_installer = installers[0].get("version", "1.0.1")
            return f"https://maven.fabricmc.net/net/fabricmc/fabric-installer/{latest_installer}/fabric-installer-{latest_installer}.jar"
    except Exception:
        pass
    
    return f"https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.0.1/fabric-installer-1.0.1.jar"


def get_forge_installer_url(mc_version: str, forge_version: str) -> Optional[str]:
    artifact_urls = get_forge_artifact_urls(mc_version, forge_version)
    for url in artifact_urls:
        if url.endswith("-installer.jar"):
            return url
    return artifact_urls[0] if artifact_urls else None


def get_forge_artifact_urls(mc_version: str, forge_version: str) -> List[str]:
    base = f"{mc_version}-{forge_version}"
    maven_root = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{base}"

    def _is_pre_1_6(version: str) -> bool:
        try:
            parts = (version or "").split(".")
            major = int(parts[0]) if len(parts) > 0 else 0
            minor = int(parts[1]) if len(parts) > 1 else 0
            return major == 1 and minor < 6
        except Exception:
            return False

    if _is_pre_1_6(mc_version):
        # Legacy Forge (1.5.x and below) generally ships universal/client
        # artifacts instead of installer jars.
        candidates = [
            f"{maven_root}/forge-{base}-universal.zip",
            f"{maven_root}/forge-{base}-universal.jar",
            f"{maven_root}/forge-{base}-client.zip",
            f"{maven_root}/minecraftforge-universal-{base}.zip",
            f"{maven_root}/minecraftforge-universal-{base}.jar",
            f"{maven_root}/minecraftforge-client-{base}.zip",
            # Keep installer last as a rare fallback.
            f"{maven_root}/forge-{base}-installer.jar",
        ]
    else:
        # Keep installer first for modern Forge, then try legacy package names.
        candidates = [
            f"{maven_root}/forge-{base}-installer.jar",
            f"{maven_root}/forge-{base}-universal.jar",
            f"{maven_root}/forge-{base}-universal.zip",
            f"{maven_root}/forge-{base}-client.zip",
            f"{maven_root}/minecraftforge-universal-{base}.jar",
            f"{maven_root}/minecraftforge-universal-{base}.zip",
            f"{maven_root}/minecraftforge-client-{base}.zip",
        ]

    # Deduplicate while preserving order.
    seen = set()
    deduped = []
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped


# ============ UTILITY FUNCTIONS ============


def parse_loader_type(loader_str: str) -> Optional[str]:
    loader_lower = (loader_str or "").lower().strip()
    if "fabric" in loader_lower:
        return "fabric"
    if "forge" in loader_lower:
        return "forge"
    return None


def fetch_fabric_loader_dependencies(loader_version: str, mc_version: str) -> Optional[List[Tuple[str, str]]]:
    try:
        import tempfile
        import zipfile
        import json
        
        maven_base = "https://maven.fabricmc.net"
        group = "net/fabricmc"
        artifact = "fabric-loader"
        # URL-encode the version string to handle special characters like '+' -> '%2B'
        loader_version_encoded = urllib.parse.quote(loader_version, safe='')
        lib_url = f"{maven_base}/{group}/{artifact}/{loader_version_encoded}/{artifact}-{loader_version_encoded}.jar"
        
        print(colorize_log(f"[modloaders] Downloading fabric-loader {loader_version} to extract dependencies..."))
        
        with tempfile.NamedTemporaryFile(suffix=".jar", delete=False) as tmp:
            tmp_path = tmp.name
        
        try:
            proxied_url = _apply_url_proxy(lib_url)
            req = urllib.request.Request(proxied_url, headers={"User-Agent": "Histolauncher"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                with open(tmp_path, 'wb') as f:
                    f.write(resp.read())
            
            with zipfile.ZipFile(tmp_path, 'r') as jar:
                try:
                    installer_json = jar.read('fabric-installer.json').decode('utf-8')
                    installer_data = json.loads(installer_json)
                except KeyError:
                    print(colorize_log(f"[modloaders] fabric-installer.json not found in fabric-loader JAR"))
                    return None
            
            dependencies = []
            
            dependencies.append((f"net.fabricmc:fabric-loader:{loader_version}", "https://maven.fabricmc.net"))
            print(colorize_log(f"[modloaders]   + net.fabricmc:fabric-loader:{loader_version} from https://maven.fabricmc.net"))
            
            libraries = installer_data.get("libraries", {})
            
            for lib_entry in libraries.get("common", []):
                lib_name = lib_entry.get("name", "")
                lib_url_override = lib_entry.get("url", "https://maven.fabricmc.net")
                
                if lib_name:
                    dependencies.append((lib_name, lib_url_override))
                    print(colorize_log(f"[modloaders]   + {lib_name} from {lib_url_override}"))
            
            if len(dependencies) > 1:
                print(colorize_log(f"[modloaders] Extracted {len(dependencies)} official dependencies from fabric-loader {loader_version}"))
                return dependencies
            else:
                print(colorize_log(f"[modloaders] No common libraries found in fabric-installer.json"))
                return None
                
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
                
    except Exception as e:
        print(colorize_log(f"[modloaders] Failed to extract fabric-installer.json: {e}"))
        return None


def get_fabric_loader_libraries(loader_version: str, mc_version: str) -> List[Tuple[str, str]]:
    print(colorize_log(f"[modloaders] Fetching official Fabric libraries for {loader_version}..."))
    extracted_deps = fetch_fabric_loader_dependencies(loader_version, mc_version)
    if extracted_deps:
        return extracted_deps
    
    print(colorize_log(f"[modloaders] Using fallback dependencies for {loader_version}"))
    return [
        ("net.fabricmc:fabric-loader:" + loader_version, "https://maven.fabricmc.net"),
        ("net.fabricmc:sponge-mixin:0.17.0+mixin.0.8.7", "https://maven.fabricmc.net"),
        ("org.ow2.asm:asm:9.9", "https://maven.fabricmc.net"),
        ("org.ow2.asm:asm-analysis:9.9", "https://maven.fabricmc.net"),
        ("org.ow2.asm:asm-commons:9.9", "https://maven.fabricmc.net"),
        ("org.ow2.asm:asm-tree:9.9", "https://maven.fabricmc.net"),
        ("org.ow2.asm:asm-util:9.9", "https://maven.fabricmc.net"),
    ]


def clear_loader_cache():
    global _fabric_cache, _forge_cache, _cache_timestamps
    _fabric_cache = None
    _forge_cache = None
    _cache_timestamps.clear()
    print("[modloaders] Cleared cache")
