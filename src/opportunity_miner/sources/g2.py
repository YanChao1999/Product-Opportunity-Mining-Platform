"""G2-style B2B review gap seeds (public API rarely available without key)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from opportunity_miner.models import RawSignal, SourceName

SEEDS = [
    {
        "id": "g2-1",
        "title": "Looking for an alternative to HubSpot that doesn't force a sales suite",
        "body": "Would pay for a focused CRM for indie B2B. Missing feature: simple pipeline + email without upsells.",
        "score": 120,
        "comments": 40,
    },
    {
        "id": "g2-2",
        "title": "Why isn't there a lightweight alternative to Jira for 5-person teams?",
        "body": "Still can't find a tool that is issue-tracker only. Gap in the market. Shut up and take my money.",
        "score": 200,
        "comments": 65,
    },
]


class G2Collector:
    name = SourceName.G2.value

    def __init__(self, client: httpx.Client, cfg: dict[str, Any]):
        self.client = client
        self.cfg = cfg

    def collect(self) -> list[RawSignal]:
        now = datetime.now(timezone.utc)
        out = [
            RawSignal(
                source=SourceName.G2,
                external_id=s["id"],
                title=s["title"],
                body=s["body"],
                url="https://www.g2.com/",
                score=int(s["score"]),
                comments=int(s["comments"]),
                created_at=now,
                metadata={"kind": "seed_wish"},
            )
            for s in SEEDS
        ]
        # Optional: if user provides a reviews JSON URL
        url = self.cfg.get("reviews_url")
        if url:
            try:
                data = self.client.get(url).json()
                for item in (data if isinstance(data, list) else data.get("reviews") or [])[:40]:
                    out.append(
                        RawSignal(
                            source=SourceName.G2,
                            external_id=str(item.get("id") or item.get("title")),
                            title=item.get("title") or "",
                            body=item.get("body") or item.get("content") or "",
                            url=item.get("url") or "",
                            score=int(item.get("score") or item.get("rating") or 0),
                            comments=0,
                            created_at=now,
                            metadata={"kind": "review", "rating": item.get("rating")},
                        )
                    )
            except Exception:
                pass
        return out
