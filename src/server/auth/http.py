from __future__ import annotations

import json
import urllib.error
import urllib.request

from typing import Dict, Optional, Tuple

from core.settings import _apply_url_proxy


__all__ = ["ACCOUNT_API_URL", "TIMEOUT", "_make_request"]


ACCOUNT_API_URL = "https://accounts.histolauncher.org"

TIMEOUT = 10.0


def _make_request(
    method: str,
    endpoint: str,
    body: Optional[str] = None,
    use_proxy: bool = True,
) -> Tuple[int, Optional[Dict], Dict]:
    url = ACCOUNT_API_URL + endpoint
    if use_proxy:
        url = _apply_url_proxy(url)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Histolauncher/1.0",
    }

    req_body = body.encode("utf-8") if body else None
    req = urllib.request.Request(url, data=req_body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            status = getattr(response, "status", None) or response.getcode()
            resp_body = response.read().decode("utf-8")
            try:
                data = json.loads(resp_body)
            except json.JSONDecodeError:
                data = {"raw": resp_body}

            try:
                response_headers = dict(response.getheaders())
            except Exception:
                try:
                    response_headers = (
                        dict(response.headers.items()) if hasattr(response, "headers") else {}
                    )
                except Exception:
                    response_headers = {}

            return status, data, response_headers
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            resp_body = e.read().decode("utf-8")
            data = json.loads(resp_body)
        except (json.JSONDecodeError, AttributeError):
            data = {"error": str(e)}

        try:
            response_headers = dict(e.headers.items()) if hasattr(e, "headers") else {}
        except Exception:
            response_headers = {}

        return status, data, response_headers
    except Exception as e:
        return 500, {"error": str(e)}, {}
