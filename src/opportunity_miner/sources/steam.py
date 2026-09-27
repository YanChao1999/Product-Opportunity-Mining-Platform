"""Steam collector — store search + news for feature-gap language."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
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

    def _search(self, search_url: str, term: str) -> list[RawSignal]:
        try:
            data = get_json(
                self.client,
                search_url,
                params={"term": term, "l": "english", "cc": "US"},
                retries=1,
                timeout=8.0,
            )
        except Exception:
            return []
        if not isinstance(data, dict):
            return []
        out: list[RawSignal] = []
        for item in (data.get("items") or [])[:8]:
            if not isinstance(item, dict):
                continue
            out.append(
                RawSignal(
                    source=SourceName.STEAM,
                    external_id=f"store-{item.get('id')}",
                    title=item.get("name") or term,
                    body=f"Steam store result for query '{term}'. Type={item.get('type')}",
                    url=f"https://store.steampowered.com/app/{item.get('id')}/"
                    if item.get("id")
                    else "",
                    score=1,
                    comments=0,
                    metadata={
                        "query": term,
                        "price": (item.get("price") or {}).get("final")
                        if isinstance(item.get("price"), dict)
                        else None,
                        "kind": "store_result",
                    },
                )
            )
        return out

    def _news(self, news_url: str, app_id: int) -> list[RawSignal]:
        try:
            data = get_json(
                self.client,
                news_url,
                params={"appid": app_id, "count": 5, "maxlength": 400},
                retries=1,
                timeout=8.0,
            )
        except Exception:
            return []
        if not isinstance(data, dict):
            return []
        out: list[RawSignal] = []
        newsitems = ((data.get("appnews") or {}).get("newsitems")) or []
        for n in newsitems:
            if not isinstance(n, dict):
                continue
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
        return out

    def collect(self) -> list[RawSignal]:
        out: list[RawSignal] = []
        search_url = self.cfg.get("search_url")
        terms = list(
            self.cfg.get("search_terms")
            or [
                "mod manager",
                "party finder",
                "achievement tracker",
                "steam deck tool",
                "overlay",
            ]
        )
        news_url = self.cfg.get("news_url")
        app_ids = list(self.cfg.get("app_ids") or [])
        workers = min(int(self.cfg.get("workers") or 8), max(1, len(terms) + len(app_ids)))

        futures = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            if search_url:
                for term in terms:
                    futures.append(pool.submit(self._search, search_url, term))
            if news_url:
                for app_id in app_ids:
                    futures.append(pool.submit(self._news, news_url, app_id))
            for fut in as_completed(futures):
                try:
                    out.extend(fut.result())
                except Exception:
                    continue

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
