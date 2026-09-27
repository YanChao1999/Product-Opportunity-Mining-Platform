"""Reddit collector via public JSON endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from opportunity_miner.models import RawSignal, SourceName
from opportunity_miner.sources.http import get_json


class RedditCollector:
    name = SourceName.REDDIT.value

    def __init__(self, client: httpx.Client, cfg: dict[str, Any]):
        self.client = client
        self.cfg = cfg

    def collect(self) -> list[RawSignal]:
        subs = self.cfg.get("subreddits") or []
        sort = self.cfg.get("sort", "new")
        limit = int(self.cfg.get("limit", 40))
        out: list[RawSignal] = []

        for sub in subs:
            # Prefer old.reddit.com JSON — less aggressive bot filtering than www
            urls = [
                f"https://old.reddit.com/r/{quote(sub)}/{sort}.json",
                f"https://www.reddit.com/r/{quote(sub)}/{sort}.json",
            ]
            data = None
            for url in urls:
                try:
                    data = get_json(
                        self.client,
                        url,
                        params={"limit": limit, "raw_json": 1},
                    )
                    break
                except Exception:
                    continue
            if not data:
                continue
            children = (data.get("data") or {}).get("children") or []
            for child in children:
                post = child.get("data") or {}
                if post.get("stickied"):
                    continue
                created = None
                if post.get("created_utc"):
                    created = datetime.fromtimestamp(float(post["created_utc"]), tz=timezone.utc)
                permalink = post.get("permalink") or ""
                out.append(
                    RawSignal(
                        source=SourceName.REDDIT,
                        external_id=str(post.get("id") or ""),
                        title=post.get("title") or "",
                        body=post.get("selftext") or "",
                        url=f"https://www.reddit.com{permalink}" if permalink else post.get("url") or "",
                        author=post.get("author") or "",
                        score=int(post.get("score") or 0),
                        comments=int(post.get("num_comments") or 0),
                        created_at=created,
                        metadata={
                            "subreddit": post.get("subreddit"),
                            "upvote_ratio": post.get("upvote_ratio"),
                            "flair": post.get("link_flair_text"),
                        },
                    )
                )
        return out
