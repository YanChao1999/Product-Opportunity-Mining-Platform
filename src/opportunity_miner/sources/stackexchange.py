"""Stack Exchange / Stack Overflow question search."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

from opportunity_miner.models import RawSignal, SourceName
from opportunity_miner.sources.http import get_json


class StackExchangeCollector:
    name = SourceName.STACKEXCHANGE.value

    def __init__(self, client: httpx.Client, cfg: dict[str, Any]):
        self.client = client
        self.cfg = cfg

    def collect(self) -> list[RawSignal]:
        sites = self.cfg.get("sites") or ["stackoverflow", "softwareengineering", "apple"]
        tagged = self.cfg.get("tagged") or ["feature-request", "recommendation"]
        pagesize = int(self.cfg.get("pagesize", 20))
        out: list[RawSignal] = []
        for site in sites:
            for tag in tagged:
                url = (
                    "https://api.stackexchange.com/2.3/questions"
                    f"?order=desc&sort=activity&tagged={quote_plus(tag)}"
                    f"&site={quote_plus(site)}&pagesize={pagesize}&filter=withbody"
                )
                try:
                    data = get_json(self.client, url)
                except Exception:
                    continue
                for item in data.get("items") or []:
                    created = None
                    if item.get("creation_date"):
                        created = datetime.fromtimestamp(int(item["creation_date"]), tz=timezone.utc)
                    out.append(
                        RawSignal(
                            source=SourceName.STACKEXCHANGE,
                            external_id=f"{site}-{item.get('question_id')}",
                            title=item.get("title") or "",
                            body=(item.get("body_markdown") or item.get("body") or "")[:2000],
                            url=item.get("link") or "",
                            author=((item.get("owner") or {}).get("display_name") or ""),
                            score=int(item.get("score") or 0),
                            comments=int(item.get("answer_count") or 0),
                            created_at=created,
                            metadata={
                                "site": site,
                                "tags": item.get("tags") or [],
                                "kind": "question",
                            },
                        )
                    )
        return out
