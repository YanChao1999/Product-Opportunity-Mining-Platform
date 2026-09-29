"""Hacker News collector (public Firebase API)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
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

    def _fetch_item(self, item_tpl: str, sid: int) -> RawSignal | None:
        try:
            item = get_json(
                self.client,
                item_tpl.format(id=sid),
                retries=1,
                timeout=8.0,
            )
        except Exception:
            return None
        if not item or not isinstance(item, dict) or item.get("dead") or item.get("deleted"):
            return None
        created = None
        if item.get("time"):
            created = datetime.fromtimestamp(int(item["time"]), tz=timezone.utc)
        hn_id = item.get("id", sid)
        discussion = f"https://news.ycombinator.com/item?id={hn_id}"
        external = (item.get("url") or "").strip()
        return RawSignal(
            source=SourceName.HACKERNEWS,
            external_id=str(hn_id),
            title=item.get("title") or "",
            body=item.get("text") or "",
            # Always link to the HN thread — external article URLs confuse opportunity evidence.
            url=discussion,
            author=item.get("by") or "",
            score=int(item.get("score") or 0),
            comments=int(item.get("descendants") or 0),
            created_at=created,
            metadata={
                "type": item.get("type"),
                "external_url": external,
            },
        )

    def collect(self) -> list[RawSignal]:
        endpoints = self.cfg.get("endpoints", {})
        max_stories = int(self.cfg.get("max_stories", 60))
        ids: list[int] = []
        # Prefer Ask HN (richest for unmet needs), then new/top
        for key in ("ask", "new", "top"):
            url = endpoints.get(key)
            if not url:
                continue
            try:
                batch = get_json(self.client, url, retries=1, timeout=8.0)
                if isinstance(batch, list):
                    # Take more from ask, fewer from top/new
                    take = max_stories if key == "ask" else max_stories // 2
                    ids.extend(int(x) for x in batch[:take])
            except Exception:
                continue

        seen: set[int] = set()
        unique_ids: list[int] = []
        for i in ids:
            if i not in seen:
                seen.add(i)
                unique_ids.append(i)
        unique_ids = unique_ids[:max_stories]

        item_tpl = endpoints.get("item", "https://hacker-news.firebaseio.com/v0/item/{id}.json")
        workers = min(int(self.cfg.get("workers") or 20), max(1, len(unique_ids)))
        out: list[RawSignal] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self._fetch_item, item_tpl, sid) for sid in unique_ids]
            for fut in as_completed(futures):
                sig = fut.result()
                if sig is not None:
                    out.append(sig)
        # Stable-ish order: higher score first (Firebase returns unordered under concurrency)
        out.sort(key=lambda s: s.score, reverse=True)
        return out
