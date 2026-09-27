"""Deterministic demo fixtures for offline runs / CI."""

from __future__ import annotations

from datetime import datetime, timezone

from opportunity_miner.models import RawSignal, SourceName


def demo_signals() -> list[RawSignal]:
    now = datetime.now(timezone.utc)
    return [
        RawSignal(
            source=SourceName.REDDIT,
            external_id="r1",
            title="Somebody make a SaaS that mines App Store 1-star reviews for feature gaps",
            body="I wish there was a tool for PMs. Would pay $49/mo. No good alternative.",
            url="https://reddit.com/r/SaaS/demo1",
            score=340,
            comments=88,
            created_at=now,
        ),
        RawSignal(
            source=SourceName.HACKERNEWS,
            external_id="hn1",
            title="Ask HN: Why isn't there a cross-platform Steam Deck mod conflict detector?",
            body="Looking for a tool that suggests load order before launch. Gap in the market.",
            url="https://news.ycombinator.com/item?id=1",
            score=210,
            comments=95,
            created_at=now,
        ),
        RawSignal(
            source=SourceName.STEAM,
            external_id="st1",
            title="I wish there was a universal cross-play party finder",
            body="Would pay for Steam + Discord + console party matching. Still can't find one.",
            url="https://steamcommunity.com/discussions/",
            score=120,
            comments=45,
            created_at=now,
            metadata={"kind": "seed_wish"},
        ),
        RawSignal(
            source=SourceName.APP_STORE,
            external_id="as1",
            title="[HabitApp] Missing Apple Health sync and widgets",
            body="Please add HealthKit sync. Looking for an alternative that actually syncs. 1 star.",
            url="https://apps.apple.com/app/id1",
            score=1,
            comments=0,
            created_at=now,
            metadata={"kind": "review", "rating": "1", "app_name": "HabitApp"},
        ),
        RawSignal(
            source=SourceName.PRODUCT_HUNT,
            external_id="ph1",
            title="IndieStack Audit: Somebody make a tool that rates idea competition before you build",
            body="No good alternative for indie hackers to score demand vs competition. Would pay for this SaaS.",
            url="https://www.producthunt.com/",
            score=210,
            comments=41,
            created_at=now,
        ),
        RawSignal(
            source=SourceName.REDDIT,
            external_id="r2",
            title="Looking for a B2B Steam refund-risk analytics tool for indie publishers",
            body="Still can't find a SaaS. Would pay enterprise pricing. Gap in the market.",
            url="https://reddit.com/r/gamedev/demo2",
            score=77,
            comments=23,
            created_at=now,
        ),
        RawSignal(
            source=SourceName.HACKERNEWS,
            external_id="hn2",
            title="Ask HN: Is there a no-code chrome extension builder for internal tools?",
            body="Need an app our ops team can maintain. Prefer template / no-code approach.",
            url="https://news.ycombinator.com/item?id=2",
            score=90,
            comments=40,
            created_at=now,
        ),
        RawSignal(
            source=SourceName.APP_STORE,
            external_id="as2",
            title="Budgetly",
            body="Personal finance budget app. Genre=Finance. Many competitors.",
            url="https://apps.apple.com/app/id2",
            score=50000,
            comments=0,
            metadata={"kind": "app_listing", "genre": "Finance"},
            created_at=now,
        ),
    ]
