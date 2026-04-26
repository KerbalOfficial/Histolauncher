from __future__ import annotations

import os
from typing import Optional, Set

from core.downloader.errors import DownloadCancelled, DownloadFailed
from core.downloader.http import CLIENT
from core.logger import colorize_log


_YARN_MAX_BUILD_ATTEMPTS = 20
_YARN_FAILED_FILE = ".failed_yarn_builds.txt"


def _get_failed_yarn_builds(version_dir: str) -> Set[str]:
    failed_file = os.path.join(version_dir, _YARN_FAILED_FILE)
    if not os.path.exists(failed_file):
        return set()
    try:
        with open(failed_file, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except Exception:
        return set()


def _record_failed_yarn_build(version_dir: str, build_id: str) -> None:
    failed_file = os.path.join(version_dir, _YARN_FAILED_FILE)
    try:
        existing = _get_failed_yarn_builds(version_dir)
        if build_id not in existing:
            with open(failed_file, "a", encoding="utf-8") as f:
                f.write(f"{build_id}\n")
    except Exception:
        pass


def _download_yarn_mappings(
    version_dir: str, mc_version: str, version_key: str
) -> Optional[str]:
    try:
        try:
            for filename in os.listdir(version_dir):
                if (
                    filename.startswith(f"yarn-{mc_version}-")
                    and filename.endswith(".jar")
                ):
                    yarn_path = os.path.join(version_dir, filename)
                    print(colorize_log(f"[fabric] Using existing Yarn mappings: {filename}"))
                    return yarn_path
        except Exception:
            pass

        # Ask the metadata server what the latest build is, so we don't have to brute-force 404s
        import urllib.parse
        from core.modloaders._http import _http_get_json

        mc_enc = urllib.parse.quote(mc_version, safe="")
        meta_url = f"https://meta.fabricmc.net/v2/versions/yarn/{mc_enc}"

        try:
            meta_data = _http_get_json(meta_url)
        except Exception as exc:
            print(colorize_log(f"[fabric] Failed to fetch Yarn metadata: {exc}"))
            meta_data = None

        if meta_data and isinstance(meta_data, list) and len(meta_data) > 0:
            latest = meta_data[0]
            version = latest.get("version")
            build_num = latest.get("build")

            if version and build_num is not None:
                build_id = f"build.{build_num}"
                safe_filename = f"yarn-{(version.replace('+', '-'))}.jar"
                yarn_path = os.path.join(version_dir, safe_filename)

                url_version_enc = urllib.parse.quote(version, safe="")
                url = (
                    f"https://maven.fabricmc.net/net/fabricmc/yarn/{url_version_enc}/"
                    f"yarn-{url_version_enc}.jar"
                )

                try:
                    CLIENT.download(url, yarn_path)
                    
                    if os.path.exists(yarn_path) and os.path.getsize(yarn_path) > 0:
                        size_mb = os.path.getsize(yarn_path) / (1024 * 1024)
                        print(colorize_log(
                            f"[fabric] Downloaded Yarn {build_id} via API ({size_mb:.1f}MB)"
                        ))
                        return yarn_path
                except Exception as exc:
                    print(colorize_log(f"[fabric] Failed downloading Yarn JAR from API: {exc}"))
                    if os.path.exists(yarn_path):
                        try:
                            os.remove(yarn_path)
                        except Exception:
                            pass

        # Fallback to brute force mechanism
        # Try to fetch current metadata for the given version
        import urllib.parse
        from core.modloaders._http import _http_get_json
        
        mc_enc = urllib.parse.quote(mc_version, safe="")
        meta_url = f"https://meta.fabricmc.net/v2/versions/yarn/{mc_enc}"
        
        try:
            meta_data = _http_get_json(meta_url)
        except Exception as exc:
            print(colorize_log(f"[fabric] Failed to fetch Yarn metadata: {exc}"))
            meta_data = None
            
        if not meta_data or not isinstance(meta_data, list):
            print(colorize_log(f"[fabric] Could not find any Yarn mappings for {mc_version} (metadata empty/invalid)"))
            return None
            
        # Get latest build
        latest = meta_data[0]
        version = latest.get("version")
        if not version:
            print(colorize_log(f"[fabric] Yarn explicitly missing version from meta API response for {mc_version}"))
            return None
            
        build_id = f"build.{latest.get('build', 'unknown')}"
        safe_filename = f"yarn-{(version.replace('+', '-'))}.jar"
        yarn_path = os.path.join(version_dir, safe_filename)
        
        url_version_enc = urllib.parse.quote(version, safe="")
        url = (
            f"https://maven.fabricmc.net/net/fabricmc/yarn/{url_version_enc}/"
            f"yarn-{url_version_enc}.jar"
        )

        try:
            CLIENT.download(url, yarn_path)
            
            if os.path.exists(yarn_path) and os.path.getsize(yarn_path) > 0:
                size_mb = os.path.getsize(yarn_path) / (1024 * 1024)
                print(colorize_log(
                    f"[fabric] Downloaded Yarn {build_id} ({size_mb:.1f}MB)"
                ))
                return yarn_path
                
        except DownloadCancelled:
            raise
        except Exception as exc:
            print(colorize_log(f"[fabric] Failed downloading Yarn JAR: {exc}"))
            if os.path.exists(yarn_path):
                try:
                    os.remove(yarn_path)
                except Exception:
                    pass
            return None

        return None

    except DownloadCancelled:
        raise
    except Exception as e:
        print(colorize_log(f"[fabric] ERROR downloading Yarn: {e}"))
        return None


__all__ = [
    "_download_yarn_mappings",
    "_get_failed_yarn_builds",
    "_record_failed_yarn_build",
]
