"""Product Hunt collector — GraphQL when token present, else curated demo posts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from opportunity_miner.models import RawSignal, SourceName

FALLBACK_POSTS: list[dict[str, Any]] = [
    {
        "id": "ph-1",
        "name": "GapFinder AI",
        "tagline": "I wish there was a daily digest of unmet SaaS needs from social",
        "description": (
            "Looking for an alternative to manual market research. "
            "Would pay for automated opportunity scanning across Reddit and HN."
        ),
        "votes": 420,
        "comments": 67,
        "url": "https://www.producthunt.com/",
    },
    {
        "id": "ph-2",
        "name": "IndieStack Audit",
        "tagline": "Somebody make a tool that rates idea competition before you build",
        "description": (
            "No good alternative for indie hackers to score demand vs competition "
            "before writing code. Gap in the market for pre-build diligence."
        ),
        "votes": 210,
        "comments": 41,
        "url": "https://www.producthunt.com/",
    },
    {
        "id": "ph-3",
        "name": "ReviewGap",
        "tagline": "Why isn't there an app that mines 1-star App Store reviews for feature gaps?",
        "description": (
            "Still can't find a SaaS that clusters missing-feature complaints "
            "and estimates willingness to pay. Need an app for product managers."
        ),
        "votes": 155,
        "comments": 28,
        "url": "https://www.producthunt.com/",
    },
]

POSTS_QUERY = """
query Posts($first: Int) {
  posts(first: $first, order: VOTES) {
    edges {
      node {
        id
        name
        tagline
        description
        url
        votesCount
        commentsCount
        createdAt
        topics { edges { node { name } } }
      }
    }
  }
}
"""


class ProductHuntCollector:
    name = SourceName.PRODUCT_HUNT.value

    def __init__(self, client: httpx.Client, cfg: dict[str, Any], token: str = ""):
        self.client = client
        self.cfg = cfg
        self.token = token

    def collect(self) -> list[RawSignal]:
        if self.token:
            live = self._collect_live()
            if live:
                return live
        return self._fallback()

    def _collect_live(self) -> list[RawSignal]:
        url = self.cfg.get("graphql_url", "https://api.producthunt.com/v2/api/graphql")
        limit = int(self.cfg.get("posts_limit", 40))
        try:
            resp = self.client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={"query": POSTS_QUERY, "variables": {"first": limit}},
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return []

        edges = (((payload.get("data") or {}).get("posts") or {}).get("edges")) or []
        out: list[RawSignal] = []
        for edge in edges:
            node = edge.get("node") or {}
            topics = [
                ((t.get("node") or {}).get("name") or "")
                for t in ((node.get("topics") or {}).get("edges") or [])
            ]
            created = None
            if node.get("createdAt"):
                try:
                    created = datetime.fromisoformat(node["createdAt"].replace("Z", "+00:00"))
                except ValueError:
                    created = None
            out.append(
                RawSignal(
                    source=SourceName.PRODUCT_HUNT,
                    external_id=str(node.get("id") or ""),
                    title=f"{node.get('name') or ''}: {node.get('tagline') or ''}".strip(": "),
                    body=node.get("description") or node.get("tagline") or "",
                    url=node.get("url") or "",
                    score=int(node.get("votesCount") or 0),
                    comments=int(node.get("commentsCount") or 0),
                    created_at=created,
                    metadata={"topics": topics, "kind": "post"},
                )
            )
        return out

    def _fallback(self) -> list[RawSignal]:
        now = datetime.now(timezone.utc)
        return [
            RawSignal(
                source=SourceName.PRODUCT_HUNT,
                external_id=p["id"],
                title=f"{p['name']}: {p['tagline']}",
                body=p["description"],
                url=p["url"],
                score=int(p["votes"]),
                comments=int(p["comments"]),
                created_at=now,
                metadata={"kind": "fallback_post"},
            )
            for p in FALLBACK_POSTS
        ]
