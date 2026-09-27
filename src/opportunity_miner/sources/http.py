"""HTTP helpers shared by source collectors."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

# Clash / many local proxies set ALL_PROXY=socks://…; httpx only accepts socks5:// / socks4://.
_PROXY_ENV_KEYS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
)


def normalize_proxy_env() -> None:
    """Rewrite socks:// → socks5:// in proxy env vars so httpx can parse them."""
    for key in _PROXY_ENV_KEYS:
        val = os.environ.get(key)
        if not val:
            continue
        lower = val.lower()
        if lower.startswith("socks://"):
            os.environ[key] = "socks5://" + val[len("socks://") :]


def make_client(user_agent: str, timeout: float = 12.0) -> httpx.Client:
    normalize_proxy_env()
    return httpx.Client(
        timeout=timeout,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json,text/plain,*/*",
        },
        follow_redirects=True,
    )


def get_json(
    client: httpx.Client,
    url: str,
    *,
    retries: int = 2,
    timeout: float | None = None,
    **kwargs: Any,
) -> Any:
    """
    GET JSON with limited retries.

    Timeouts / connection errors fail immediately (no retry) — otherwise a blocked
    host can burn minutes per URL under the old tenacity policy.
    Only HTTP 5xx is retried.
    """
    retries = max(1, int(retries))
    if timeout is not None:
        kwargs["timeout"] = timeout
    last: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = client.get(url, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except (httpx.TimeoutException, httpx.ConnectError):
            raise
        except httpx.HTTPStatusError as exc:
            last = exc
            if exc.response.status_code < 500 or attempt + 1 >= retries:
                raise
            time.sleep(0.4 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt + 1 >= retries:
                raise
            time.sleep(0.4 * (attempt + 1))
    assert last is not None
    raise last
