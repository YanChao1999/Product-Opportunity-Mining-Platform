"""HTTP helpers shared by source collectors."""

from __future__ import annotations

import os
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

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


def make_client(user_agent: str, timeout: float = 20.0) -> httpx.Client:
    normalize_proxy_env()
    return httpx.Client(
        timeout=timeout,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json,text/plain,*/*",
        },
        follow_redirects=True,
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4))
def get_json(client: httpx.Client, url: str, **kwargs: Any) -> Any:
    resp = client.get(url, **kwargs)
    resp.raise_for_status()
    return resp.json()
