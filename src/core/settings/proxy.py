from __future__ import annotations

import urllib.parse

from core.settings.store import load_global_settings

__all__ = ["apply_url_proxy", "_apply_url_proxy"]


def _get_url_proxy_prefix() -> str:
    try:
        cfg = load_global_settings()
        return str(cfg.get("url_proxy") or "").strip()
    except Exception:
        return ""


def apply_url_proxy(url: str) -> str:
    raw_url = str(url or "").strip()
    if not raw_url:
        return raw_url

    prefix = _get_url_proxy_prefix()
    if not prefix:
        return raw_url

    if raw_url.startswith(prefix):
        return raw_url

    if "{url}" in prefix:
        return prefix.replace("{url}", urllib.parse.quote(raw_url, safe=""))

    try:
        parsed_prefix = urllib.parse.urlsplit(prefix)
        if parsed_prefix.scheme and parsed_prefix.netloc and parsed_prefix.query:
            query_pairs = urllib.parse.parse_qsl(parsed_prefix.query, keep_blank_values=True)
            updated_pairs: list[tuple[str, str]] = []
            replaced = False
            for key, value in query_pairs:
                if not replaced and str(key).lower() == "url":
                    updated_pairs.append((key, raw_url))
                    replaced = True
                else:
                    updated_pairs.append((key, value))

            if replaced:
                encoded_query = urllib.parse.urlencode(
                    updated_pairs,
                    doseq=True,
                    quote_via=urllib.parse.quote,
                    safe="",
                )
                return urllib.parse.urlunsplit(
                    (
                        parsed_prefix.scheme,
                        parsed_prefix.netloc,
                        parsed_prefix.path,
                        encoded_query,
                        parsed_prefix.fragment,
                    )
                )
    except (ValueError, TypeError):
        pass

    return prefix + raw_url


_apply_url_proxy = apply_url_proxy
