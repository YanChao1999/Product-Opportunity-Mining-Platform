"""App Store / iTunes collector — search + customer reviews."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from opportunity_miner.models import RawSignal, SourceName
from opportunity_miner.sources.http import get_json


class AppStoreCollector:
    name = SourceName.APP_STORE.value

    def __init__(self, client: httpx.Client, cfg: dict[str, Any]):
        self.client = client
        self.cfg = cfg

    def collect(self) -> list[RawSignal]:
        out: list[RawSignal] = []
        search_url = self.cfg.get("search_url", "https://itunes.apple.com/search")
        terms = self.cfg.get("search_terms") or []
        max_apps = int(self.cfg.get("max_apps_per_term", 8))
        reviews_per = int(self.cfg.get("reviews_per_app", 20))
        countries = self.cfg.get("countries") or ["us"]
        country = countries[0]

        app_ids: list[tuple[int, str]] = []
        for term in terms:
            try:
                data = get_json(
                    self.client,
                    search_url,
                    params={
                        "term": term,
                        "entity": "software",
                        "limit": max_apps,
                        "country": country,
                    },
                )
            except Exception:
                continue
            for r in data.get("results") or []:
                app_id = r.get("trackId")
                name = r.get("trackName") or ""
                if not app_id:
                    continue
                app_ids.append((int(app_id), name))
                out.append(
                    RawSignal(
                        source=SourceName.APP_STORE,
                        external_id=f"app-{app_id}",
                        title=name,
                        body=(
                            f"{r.get('description') or ''}\n"
                            f"Genre={r.get('primaryGenreName')}; "
                            f"Rating={r.get('averageUserRating')}; "
                            f"RatingsCount={r.get('userRatingCount')}"
                        )[:2000],
                        url=r.get("trackViewUrl") or "",
                        score=int(r.get("userRatingCount") or 0),
                        comments=int(r.get("userRatingCountForCurrentVersion") or 0),
                        metadata={
                            "genre": r.get("primaryGenreName"),
                            "price": r.get("price"),
                            "bundle": r.get("bundleId"),
                            "avg_rating": r.get("averageUserRating"),
                            "kind": "app_listing",
                            "search_term": term,
                        },
                    )
                )

        # Pull recent reviews — 1–3★ often contain "missing feature / looking for"
        rss_tpl = self.cfg.get(
            "rss_url",
            "https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortBy=mostRecent/json",
        )
        seen_apps: set[int] = set()
        for app_id, name in app_ids:
            if app_id in seen_apps:
                continue
            seen_apps.add(app_id)
            if len(seen_apps) > 25:
                break
            url = rss_tpl.format(country=country, app_id=app_id)
            try:
                data = get_json(self.client, url)
            except Exception:
                continue
            entries = (data.get("feed") or {}).get("entry") or []
            # First entry is often the app metadata
            for entry in entries[1 : reviews_per + 1]:
                title = ((entry.get("title") or {}).get("label")) or ""
                body = ((entry.get("content") or {}).get("label")) or ""
                rating = ((entry.get("im:rating") or {}).get("label")) or "0"
                author = ((entry.get("author") or {}).get("name") or {}).get("label") or ""
                updated = ((entry.get("updated") or {}).get("label")) or ""
                created = None
                if updated:
                    try:
                        created = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                    except ValueError:
                        created = None
                out.append(
                    RawSignal(
                        source=SourceName.APP_STORE,
                        external_id=f"review-{app_id}-{((entry.get('id') or {}).get('label')) or hash(title+body)}",
                        title=f"[{name}] {title}",
                        body=body,
                        url=f"https://apps.apple.com/app/id{app_id}",
                        author=author,
                        score=int(rating) if str(rating).isdigit() else 0,
                        comments=0,
                        created_at=created or datetime.now(timezone.utc),
                        metadata={
                            "app_id": app_id,
                            "app_name": name,
                            "rating": rating,
                            "kind": "review",
                        },
                    )
                )
        return out
