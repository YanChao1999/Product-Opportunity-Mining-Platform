"""Generic RSS / Atom feed collector — plug any blog, forum, newsletter."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from opportunity_miner.models import RawSignal, SourceName


class RSSCollector:
    name = SourceName.RSS.value

    def __init__(self, client: httpx.Client, cfg: dict[str, Any]):
        self.client = client
        self.cfg = cfg

    def collect(self) -> list[RawSignal]:
        feeds = self.cfg.get("feeds") or []
        limit = int(self.cfg.get("limit_per_feed", 25))
        out: list[RawSignal] = []
        for feed in feeds:
            url = feed if isinstance(feed, str) else feed.get("url")
            label = feed if isinstance(feed, str) else (feed.get("name") or url)
            if not url:
                continue
            try:
                resp = self.client.get(url)
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
            except Exception:
                continue
            items = list(root.iter())
            # RSS <item> or Atom <entry>
            entries = [n for n in items if n.tag.endswith("item") or n.tag.endswith("entry")]
            for entry in entries[:limit]:
                title = _child_text(entry, "title")
                link = _child_text(entry, "link") or _atom_link(entry)
                body = _child_text(entry, "description") or _child_text(entry, "summary") or _child_text(entry, "content")
                body = re.sub(r"<[^>]+>", " ", body or "")
                eid = _child_text(entry, "guid") or _child_text(entry, "id") or link or title
                out.append(
                    RawSignal(
                        source=SourceName.RSS,
                        external_id=hashlib.sha1((eid or "").encode()).hexdigest()[:16],
                        title=title,
                        body=body[:2000],
                        url=link,
                        score=0,
                        comments=0,
                        created_at=datetime.now(timezone.utc),
                        metadata={"feed": label, "kind": "rss_item"},
                    )
                )
        return out


def _child_text(node: ET.Element, local: str) -> str:
    for child in list(node):
        if child.tag.endswith(local):
            # Atom link may be attribute-only
            if child.text:
                return (child.text or "").strip()
            href = child.attrib.get("href")
            if href:
                return href.strip()
    return ""


def _atom_link(node: ET.Element) -> str:
    for child in list(node):
        if child.tag.endswith("link"):
            href = child.attrib.get("href")
            if href:
                return href
    return ""
