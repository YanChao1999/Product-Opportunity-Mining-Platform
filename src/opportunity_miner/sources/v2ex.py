"""V2EX hot topics (Chinese maker / tech community)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
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

    def _fetch(self, url: str) -> tuple[list[RawSignal], str | None]:
        try:
            data = get_json(self.client, url, retries=1, timeout=6.0)
        except Exception as exc:
            return [], f"{url}: {type(exc).__name__}: {exc}"
        if not isinstance(data, list):
            return [], f"{url}: unexpected JSON type {type(data).__name__}"
        out: list[RawSignal] = []
        for item in data[: int(self.cfg.get("limit", 40))]:
            if not isinstance(item, dict):
                continue
            created = None
            if item.get("created"):
                created = datetime.fromtimestamp(int(item["created"]), tz=timezone.utc)
            node_obj = item.get("node") or {}
            node = node_obj.get("name") if isinstance(node_obj, dict) else ""
            member = item.get("member") or {}
            author = member.get("username") if isinstance(member, dict) else ""
            out.append(
                RawSignal(
                    source=SourceName.V2EX,
                    external_id=str(item.get("id") or ""),
                    title=item.get("title") or "",
                    body=item.get("content") or "",
                    url=item.get("url") or f"https://www.v2ex.com/t/{item.get('id')}",
                    author=author or "",
                    score=int(item.get("replies") or 0),
                    comments=int(item.get("replies") or 0),
                    created_at=created,
                    metadata={"node": node, "kind": "topic"},
                )
            )
        return out, None

    def collect(self) -> list[RawSignal]:
        urls = list(
            self.cfg.get("urls")
            or [
                "https://www.v2ex.com/api/topics/hot.json",
                "https://www.v2ex.com/api/topics/latest.json",
            ]
        )
        out: list[RawSignal] = []
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(urls)))) as pool:
            futures = [pool.submit(self._fetch, url) for url in urls]
            for fut in as_completed(futures):
                items, err = fut.result()
                out.extend(items)
                if err:
                    errors.append(err)
        if not out and errors:
            raise RuntimeError("; ".join(errors[:3]))
        return out
