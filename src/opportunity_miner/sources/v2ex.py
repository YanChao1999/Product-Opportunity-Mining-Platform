"""V2EX hot topics (Chinese maker / tech community)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from opportunity_miner.models import RawSignal, SourceName
from opportunity_miner.sources.http import get_json


class V2EXCollector:
    name = SourceName.V2EX.value

    def __init__(self, client: httpx.Client, cfg: dict[str, Any]):
        self.client = client
        self.cfg = cfg

    def collect(self) -> list[RawSignal]:
        urls = self.cfg.get("urls") or [
            "https://www.v2ex.com/api/topics/hot.json",
            "https://www.v2ex.com/api/topics/latest.json",
        ]
        out: list[RawSignal] = []
        for url in urls:
            try:
                data = get_json(self.client, url)
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for item in data[: int(self.cfg.get("limit", 40))]:
                created = None
                if item.get("created"):
                    created = datetime.fromtimestamp(int(item["created"]), tz=timezone.utc)
                node = (item.get("node") or {}).get("name") or ""
                out.append(
                    RawSignal(
                        source=SourceName.V2EX,
                        external_id=str(item.get("id") or ""),
                        title=item.get("title") or "",
                        body=item.get("content") or "",
                        url=item.get("url") or f"https://www.v2ex.com/t/{item.get('id')}",
                        author=((item.get("member") or {}).get("username") or ""),
                        score=int(item.get("replies") or 0),
                        comments=int(item.get("replies") or 0),
                        created_at=created,
                        metadata={"node": node, "kind": "topic"},
                    )
                )
        return out
