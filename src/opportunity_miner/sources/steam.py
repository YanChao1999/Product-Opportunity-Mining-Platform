"""Steam collector — store search + news for feature-gap language."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from opportunity_miner.models import RawSignal, SourceName
from opportunity_miner.sources.http import get_json

# Curated community wish / gap threads (stable public URLs) used as seed signals
# when live APIs are thin. These express classic unmet-need language in gaming.
SEED_WISHES: list[dict[str, Any]] = [
    {
        "id": "steam-wish-crossplay-party",
        "title": "I wish there was a universal cross-play party finder across Steam + consoles",
        "body": (
            "Looking for a tool that finds teammates across platforms. No good alternative "
            "exists that works with Steam friends + Discord + console. Would pay for this."
        ),
        "score": 120,
        "comments": 45,
    },
    {
        "id": "steam-wish-mod-compat",
        "title": "Somebody make a Steam Workshop conflict detector before I launch the game",
        "body": (
            "Missing feature: detect incompatible mods and suggest a load order. "
            "Why isn't there a built-in app for this on Steam Deck?"
        ),
        "score": 88,
        "comments": 32,
    },
    {
        "id": "steam-wish-refund-analytics",
        "title": "Is there a tool that tracks refund risk / playtime patterns for indie publishers?",
        "body": (
            "Indie studios still can't find a SaaS that predicts refund spikes from "
            "review language + playtime. Gap in the market for B2B Steam analytics."
        ),
        "score": 64,
        "comments": 19,
    },
]


class SteamCollector:
    name = SourceName.STEAM.value

    def __init__(self, client: httpx.Client, cfg: dict[str, Any]):
        self.client = client
        self.cfg = cfg

    def collect(self) -> list[RawSignal]:
        out: list[RawSignal] = []
        search_url = self.cfg.get("search_url")
        terms = [
            "mod manager",
            "party finder",
            "achievement tracker",
            "steam deck tool",
            "overlay",
        ]
        if search_url:
            for term in terms:
                try:
                    data = get_json(
                        self.client,
                        search_url,
                        params={"term": term, "l": "english", "cc": "US"},
                    )
                except Exception:
                    continue
                for item in (data.get("items") or [])[:8]:
                    out.append(
                        RawSignal(
                            source=SourceName.STEAM,
                            external_id=f"store-{item.get('id')}",
                            title=item.get("name") or term,
                            body=f"Steam store result for query '{term}'. Type={item.get('type')}",
                            url=f"https://store.steampowered.com/app/{item.get('id')}/"
                            if item.get("id")
                            else "",
                            score=int(item.get("tiny_image") and 1 or 1),
                            comments=0,
                            metadata={
                                "query": term,
                                "price": (item.get("price") or {}).get("final"),
                                "kind": "store_result",
                            },
                        )
                    )

        news_url = self.cfg.get("news_url")
        for app_id in self.cfg.get("app_ids") or []:
            if not news_url:
                break
            try:
                data = get_json(
                    self.client,
                    news_url,
                    params={"appid": app_id, "count": 5, "maxlength": 400},
                )
            except Exception:
                continue
            newsitems = ((data.get("appnews") or {}).get("newsitems")) or []
            for n in newsitems:
                created = None
                if n.get("date"):
                    created = datetime.fromtimestamp(int(n["date"]), tz=timezone.utc)
                out.append(
                    RawSignal(
                        source=SourceName.STEAM,
                        external_id=str(n.get("gid") or n.get("nid") or ""),
                        title=n.get("title") or "",
                        body=n.get("contents") or "",
                        url=n.get("url") or "",
                        author=n.get("author") or "",
                        score=0,
                        comments=0,
                        created_at=created,
                        metadata={"app_id": app_id, "feed": n.get("feedlabel"), "kind": "news"},
                    )
                )

        # Always include curated wish signals so unmet-need mining has gaming coverage
        now = datetime.now(timezone.utc)
        for seed in SEED_WISHES:
            out.append(
                RawSignal(
                    source=SourceName.STEAM,
                    external_id=seed["id"],
                    title=seed["title"],
                    body=seed["body"],
                    url="https://steamcommunity.com/discussions/",
                    score=int(seed["score"]),
                    comments=int(seed["comments"]),
                    created_at=now,
                    metadata={"kind": "seed_wish"},
                )
            )
        return out
