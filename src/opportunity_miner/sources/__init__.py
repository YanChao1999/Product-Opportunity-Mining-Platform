"""Collector registry."""

from __future__ import annotations

from typing import Any

import httpx

from opportunity_miner.models import RawSignal
from opportunity_miner.sources.app_store import AppStoreCollector
from opportunity_miner.sources.hackernews import HackerNewsCollector
from opportunity_miner.sources.product_hunt import ProductHuntCollector
from opportunity_miner.sources.reddit import RedditCollector
from opportunity_miner.sources.steam import SteamCollector


def collect_all(client: httpx.Client, config: dict[str, Any]) -> tuple[list[RawSignal], dict[str, int]]:
    sources_cfg = config.get("sources") or {}
    secrets = config.get("secrets") or {}
    collectors = []

    if (sources_cfg.get("hackernews") or {}).get("enabled", True):
        collectors.append(HackerNewsCollector(client, sources_cfg["hackernews"]))
    if (sources_cfg.get("reddit") or {}).get("enabled", True):
        collectors.append(RedditCollector(client, sources_cfg["reddit"]))
    if (sources_cfg.get("steam") or {}).get("enabled", True):
        collectors.append(SteamCollector(client, sources_cfg["steam"]))
    if (sources_cfg.get("app_store") or {}).get("enabled", True):
        collectors.append(AppStoreCollector(client, sources_cfg["app_store"]))
    if (sources_cfg.get("product_hunt") or {}).get("enabled", True):
        collectors.append(
            ProductHuntCollector(
                client,
                sources_cfg["product_hunt"],
                token=secrets.get("product_hunt_token") or "",
            )
        )

    all_signals: list[RawSignal] = []
    stats: dict[str, int] = {}
    for c in collectors:
        try:
            items = c.collect()
        except Exception:
            items = []
        stats[c.name] = len(items)
        all_signals.extend(items)
    return all_signals, stats
