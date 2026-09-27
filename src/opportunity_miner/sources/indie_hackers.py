"""Indie Hackers — public group posts via JSON when available, else curated seeds."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from opportunity_miner.models import RawSignal, SourceName

FALLBACK = [
    {
        "id": "ih-1",
        "title": "Looking for an alternative to manual competitor research before building SaaS",
        "body": "I wish there was a tool that scores demand vs competition daily. Would pay for this.",
        "score": 56,
        "comments": 18,
    },
    {
        "id": "ih-2",
        "title": "Somebody make a Chrome extension that turns 1-star reviews into a roadmap",
        "body": "No good alternative for indie hackers. Gap in the market for PM tooling.",
        "score": 41,
        "comments": 12,
    },
]


class IndieHackersCollector:
    name = SourceName.INDIE_HACKERS.value

    def __init__(self, client: httpx.Client, cfg: dict[str, Any]):
        self.client = client
        self.cfg = cfg

    def collect(self) -> list[RawSignal]:
        # IH has no stable public API; try RSS/JSON endpoints then fall back.
        urls = self.cfg.get("urls") or [
            "https://www.indiehackers.com/feed.xml",
        ]
        out: list[RawSignal] = []
        for url in urls:
            try:
                resp = self.client.get(url)
                resp.raise_for_status()
                text = resp.text
            except Exception:
                continue
            # Very light RSS item parse (no lxml dependency)
            chunks = text.split("<item>")[1:]
            for chunk in chunks[: int(self.cfg.get("limit", 30))]:
                title = _between(chunk, "<title>", "</title>")
                link = _between(chunk, "<link>", "</link>")
                desc = _between(chunk, "<description>", "</description>")
                guid = _between(chunk, "<guid", "</guid>")
                if ">" in (guid or ""):
                    guid = guid.split(">", 1)[-1]
                out.append(
                    RawSignal(
                        source=SourceName.INDIE_HACKERS,
                        external_id=guid or link or title[:40],
                        title=title,
                        body=desc,
                        url=link,
                        score=0,
                        comments=0,
                        created_at=datetime.now(timezone.utc),
                        metadata={"kind": "rss_item"},
                    )
                )
        if out:
            return out
        now = datetime.now(timezone.utc)
        return [
            RawSignal(
                source=SourceName.INDIE_HACKERS,
                external_id=p["id"],
                title=p["title"],
                body=p["body"],
                url="https://www.indiehackers.com/",
                score=int(p["score"]),
                comments=int(p["comments"]),
                created_at=now,
                metadata={"kind": "fallback_post"},
            )
            for p in FALLBACK
        ]


def _between(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    i += len(start)
    j = text.find(end, i)
    if j < 0:
        return ""
    return text[i:j].strip()
