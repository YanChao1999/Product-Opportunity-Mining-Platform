"""Chrome Web Store search (public) + wishlist seeds."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from opportunity_miner.models import RawSignal, SourceName

SEEDS = [
    {
        "id": "cws-1",
        "title": "I wish there was a Chrome extension that batches LinkedIn outreach without getting banned",
        "body": "Looking for a tool with safe rate limits. Would pay for a pro plan. No good alternative.",
        "score": 48,
        "comments": 15,
    },
]


class ChromeWebStoreCollector:
    name = SourceName.CHROME_WEB_STORE.value

    def __init__(self, client: httpx.Client, cfg: dict[str, Any]):
        self.client = client
        self.cfg = cfg

    def collect(self) -> list[RawSignal]:
        # Chrome Web Store has no simple official JSON; keep seeds + optional custom URL.
        out: list[RawSignal] = []
        now = datetime.now(timezone.utc)
        for seed in SEEDS:
            out.append(
                RawSignal(
                    source=SourceName.CHROME_WEB_STORE,
                    external_id=seed["id"],
                    title=seed["title"],
                    body=seed["body"],
                    url="https://chromewebstore.google.com/",
                    score=int(seed["score"]),
                    comments=int(seed["comments"]),
                    created_at=now,
                    metadata={"kind": "seed_wish"},
                )
            )
        custom = self.cfg.get("extra_signals") or []
        for item in custom:
            out.append(
                RawSignal(
                    source=SourceName.CHROME_WEB_STORE,
                    external_id=str(item.get("id") or item.get("title")),
                    title=item.get("title") or "",
                    body=item.get("body") or "",
                    url=item.get("url") or "",
                    score=int(item.get("score") or 0),
                    comments=int(item.get("comments") or 0),
                    created_at=now,
                    metadata={"kind": item.get("kind") or "custom"},
                )
            )
        return out
