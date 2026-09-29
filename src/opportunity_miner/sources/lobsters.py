"""Lobsters collector (public JSON / hottest)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from opportunity_miner.models import RawSignal, SourceName
from opportunity_miner.sources.http import get_json


def _author(item: dict[str, Any]) -> str:
    submitter = item.get("submitter_user")
    if isinstance(submitter, dict):
        return str(submitter.get("username") or "")
    if isinstance(submitter, str):
        return submitter
    return ""


class LobstersCollector:
    name = SourceName.LOBSTERS.value

    def __init__(self, client: httpx.Client, cfg: dict[str, Any]):
        self.client = client
        self.cfg = cfg

    def collect(self) -> list[RawSignal]:
        urls = self.cfg.get("urls") or [
            "https://lobste.rs/hottest.json",
            "https://lobste.rs/newest.json",
            "https://lobste.rs/t/ask.json",
        ]
        out: list[RawSignal] = []
        for url in urls:
            try:
                data = get_json(self.client, url, timeout=10.0)
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for item in data[: int(self.cfg.get("limit", 40))]:
                if not isinstance(item, dict):
                    continue
                created = None
                if item.get("created_at"):
                    try:
                        created = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
                    except ValueError:
                        created = None
                tags = item.get("tags") or []
                if not isinstance(tags, list):
                    tags = []
                comments_url = (item.get("comments_url") or "").strip()
                external = (item.get("url") or "").strip()
                out.append(
                    RawSignal(
                        source=SourceName.LOBSTERS,
                        external_id=str(item.get("short_id") or ""),
                        title=item.get("title") or "",
                        body=" ".join(str(t) for t in tags) + "\n" + (item.get("description") or ""),
                        # Prefer discussion page; keep outbound link in metadata.
                        url=comments_url or external,
                        author=_author(item),
                        score=int(item.get("score") or 0),
                        comments=int(item.get("comment_count") or 0),
                        created_at=created,
                        metadata={
                            "tags": tags,
                            "kind": "story",
                            "external_url": external if comments_url and external != comments_url else "",
                        },
                    )
                )
        return out
