"""HTTP helpers shared by source collectors."""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


def make_client(user_agent: str, timeout: float = 20.0) -> httpx.Client:
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
