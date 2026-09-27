"""Hacker News collector (public Firebase API)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from opportunity_miner.models import RawSignal, SourceName
from opportunity_miner.sources.http import get_json


class HackerNewsCollector:
    name = SourceName.HACKERNEWS.value

    def __init__(self, client: httpx.Client, cfg: dict[str, Any]):
        self.client = client
        self.cfg = cfg

    def collect(self) -> list[RawSignal]:
        endpoints = self.cfg.get("endpoints", {})
        max_stories = int(self.cfg.get("max_stories", 60))
        ids: list[int] = []
        for key in ("ask", "new", "top"):
            url = endpoints.get(key)
            if not url:
                continue
            try:
                batch = get_json(self.client, url)
                if isinstance(batch, list):
                    ids.extend(int(x) for x in batch[: max_stories // 2])
            except Exception:
                continue

        # Deduplicate while preserving order
        seen: set[int] = set()
        unique_ids: list[int] = []
        for i in ids:
            if i not in seen:
                seen.add(i)
                unique_ids.append(i)
        unique_ids = unique_ids[:max_stories]

        item_tpl = endpoints.get("item", "https://hacker-news.firebaseio.com/v0/item/{id}.json")
        out: list[RawSignal] = []
        for sid in unique_ids:
            try:
                item = get_json(self.client, item_tpl.format(id=sid))
            except Exception:
                continue
            if not item or item.get("dead") or item.get("deleted"):
                continue
            title = item.get("title") or ""
            body = item.get("text") or ""
            # Prefer Ask HN / Show HN / wish-style discussions
            created = None
            if item.get("time"):
                created = datetime.fromtimestamp(int(item["time"]), tz=timezone.utc)
            out.append(
                RawSignal(
                    source=SourceName.HACKERNEWS,
                    external_id=str(item.get("id", sid)),
                    title=title,
                    body=body,
                    url=item.get("url")
                    or f"https://news.ycombinator.com/item?id={item.get('id', sid)}",
                    author=item.get("by") or "",
                    score=int(item.get("score") or 0),
                    comments=int(item.get("descendants") or 0),
                    created_at=created,
                    metadata={"type": item.get("type")},
                )
            )
        return out
