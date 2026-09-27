"""GitHub Issues / Discussions search for unmet-need language."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

from opportunity_miner.models import RawSignal, SourceName
from opportunity_miner.sources.http import get_json


class GitHubCollector:
    name = SourceName.GITHUB.value

    def __init__(self, client: httpx.Client, cfg: dict[str, Any], token: str = ""):
        self.client = client
        self.cfg = cfg
        self.token = token

    def collect(self) -> list[RawSignal]:
        queries = self.cfg.get("queries") or [
            '"I wish there was" OR "looking for a tool" in:title,body',
            '"feature request" OR "somebody build" in:title,body',
            '"no good alternative" OR "gap in the market" in:title,body',
        ]
        per_query = int(self.cfg.get("per_query", 20))
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        out: list[RawSignal] = []
        for q in queries:
            url = f"https://api.github.com/search/issues?q={quote_plus(q)}&sort=updated&order=desc&per_page={per_query}"
            try:
                data = get_json(self.client, url, headers=headers)
            except Exception:
                continue
            for item in data.get("items") or []:
                created = None
                if item.get("created_at"):
                    try:
                        created = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
                    except ValueError:
                        created = None
                out.append(
                    RawSignal(
                        source=SourceName.GITHUB,
                        external_id=str(item.get("id") or item.get("number") or ""),
                        title=item.get("title") or "",
                        body=(item.get("body") or "")[:2000],
                        url=item.get("html_url") or "",
                        author=((item.get("user") or {}).get("login") or ""),
                        score=int(item.get("reactions", {}).get("total_count") or 0)
                        if isinstance(item.get("reactions"), dict)
                        else 0,
                        comments=int(item.get("comments") or 0),
                        created_at=created or datetime.now(timezone.utc),
                        metadata={
                            "repo": (item.get("repository_url") or "").split("/")[-1],
                            "state": item.get("state"),
                            "kind": "issue",
                        },
                    )
                )
        return out
