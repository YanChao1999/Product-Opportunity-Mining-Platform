"""Google Play — search via public endpoints + review-gap seeds."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

from opportunity_miner.models import RawSignal, SourceName
from opportunity_miner.sources.http import get_json

# Lightweight wish seeds when scraping Play Store HTML is fragile
SEED_WISHES = [
    {
        "id": "gp-wish-offline-habit",
        "title": "I wish there was a fully offline habit tracker without accounts on Android",
        "body": "Looking for an alternative that works airplane-mode first. Would pay one-time.",
        "score": 90,
        "comments": 33,
    },
    {
        "id": "gp-wish-family-budget",
        "title": "Somebody make a family shared budget app that doesn't sell my data",
        "body": "No good alternative on Google Play. Gap in the market for privacy-first finance.",
        "score": 70,
        "comments": 22,
    },
]


class GooglePlayCollector:
    name = SourceName.GOOGLE_PLAY.value

    def __init__(self, client: httpx.Client, cfg: dict[str, Any]):
        self.client = client
        self.cfg = cfg

    def collect(self) -> list[RawSignal]:
        out: list[RawSignal] = []
        # Use Google's suggest / Play-ish search is brittle; harvest via RSS of blog+seeds.
        # Optionally hit apkcombo/similar search JSON if configured.
        search_url = self.cfg.get("search_url")
        terms = self.cfg.get("search_terms") or [
            "habit tracker",
            "budget",
            "note taking",
            "password manager",
        ]
        if search_url:
            for term in terms:
                try:
                    data = get_json(
                        self.client,
                        search_url.format(query=quote_plus(term)),
                    )
                except Exception:
                    continue
                for item in (data if isinstance(data, list) else data.get("results") or [])[:8]:
                    out.append(
                        RawSignal(
                            source=SourceName.GOOGLE_PLAY,
                            external_id=str(item.get("appId") or item.get("id") or term),
                            title=item.get("title") or item.get("name") or term,
                            body=str(item.get("summary") or item.get("description") or "")[:1500],
                            url=item.get("url") or "",
                            score=int(item.get("reviews") or item.get("score") or 0),
                            comments=0,
                            metadata={"kind": "app_listing", "query": term},
                            created_at=datetime.now(timezone.utc),
                        )
                    )

        now = datetime.now(timezone.utc)
        for seed in SEED_WISHES:
            out.append(
                RawSignal(
                    source=SourceName.GOOGLE_PLAY,
                    external_id=seed["id"],
                    title=seed["title"],
                    body=seed["body"],
                    url="https://play.google.com/store/apps",
                    score=int(seed["score"]),
                    comments=int(seed["comments"]),
                    created_at=now,
                    metadata={"kind": "seed_wish"},
                )
            )
        return out
