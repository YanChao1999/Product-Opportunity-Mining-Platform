"""Reddit collector via public JSON endpoints."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
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

    def _fetch_sub(self, sub: str, sort: str, limit: int) -> tuple[list[RawSignal], str | None]:
        # Prefer old.reddit.com JSON — less aggressive bot filtering than www.
        urls = [
            f"https://old.reddit.com/r/{quote(sub)}/{sort}.json",
            f"https://www.reddit.com/r/{quote(sub)}/{sort}.json",
        ]
        errors: list[str] = []
        data = None
        for url in urls:
            try:
                data = get_json(
                    self.client,
                    url,
                    params={"limit": limit, "raw_json": 1},
                    retries=1,
                    timeout=6.0,
                )
                break
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__}")
                continue
        if not data or not isinstance(data, dict):
            return [], (errors[0] if errors else f"r/{sub}: empty")
        out: list[RawSignal] = []
        children = (data.get("data") or {}).get("children") or []
        for child in children:
            if not isinstance(child, dict):
                continue
            post = child.get("data") or {}
            if not isinstance(post, dict) or post.get("stickied"):
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
        return out, None

    def collect(self) -> list[RawSignal]:
        subs = list(self.cfg.get("subreddits") or [])
        sort = self.cfg.get("sort", "new")
        limit = int(self.cfg.get("limit", 40))
        if not subs:
            return []

        workers = min(int(self.cfg.get("workers") or 6), len(subs))
        out: list[RawSignal] = []
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(self._fetch_sub, sub, sort, limit): sub for sub in subs}
            for fut in as_completed(futures):
                try:
                    items, err = fut.result()
                    out.extend(items)
                    if err:
                        errors.append(err)
                except Exception as exc:
                    errors.append(f"{futures[fut]}: {type(exc).__name__}: {exc}")
        if not out and errors:
            # Surface block/timeout so -v shows Status=error instead of silent 0/ok
            raise RuntimeError(
                f"no posts fetched ({len(errors)} sub failures); e.g. {errors[0]}"
            )
        return out
