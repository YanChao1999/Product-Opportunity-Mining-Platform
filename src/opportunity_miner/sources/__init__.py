"""Collector registry — all enabled sources from config."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from opportunity_miner.models import RawSignal
from opportunity_miner.sources.app_store import AppStoreCollector
from opportunity_miner.sources.chrome_web_store import ChromeWebStoreCollector
from opportunity_miner.sources.g2 import G2Collector
from opportunity_miner.sources.github import GitHubCollector
from opportunity_miner.sources.google_play import GooglePlayCollector
from opportunity_miner.sources.hackernews import HackerNewsCollector
from opportunity_miner.sources.indie_hackers import IndieHackersCollector
from opportunity_miner.sources.lobsters import LobstersCollector
from opportunity_miner.sources.product_hunt import ProductHuntCollector
from opportunity_miner.sources.reddit import RedditCollector
from opportunity_miner.sources.rss import RSSCollector
from opportunity_miner.sources.stackexchange import StackExchangeCollector
from opportunity_miner.sources.steam import SteamCollector
from opportunity_miner.sources.v2ex import V2EXCollector

OnSourceDone = Callable[[str, int, float, str | None], None]


@dataclass
class CollectOutcome:
    signals: list[RawSignal]
    stats: dict[str, int]
    timings: dict[str, float] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def _build_collectors(client: httpx.Client, config: dict[str, Any]) -> list[Any]:
    sources_cfg = config.get("sources") or {}
    secrets = config.get("secrets") or {}
    collectors: list[Any] = []

    def enabled(key: str) -> bool:
        return bool((sources_cfg.get(key) or {}).get("enabled", False))

    if enabled("hackernews"):
        collectors.append(HackerNewsCollector(client, sources_cfg["hackernews"]))
    if enabled("reddit"):
        collectors.append(RedditCollector(client, sources_cfg["reddit"]))
    if enabled("steam"):
        collectors.append(SteamCollector(client, sources_cfg["steam"]))
    if enabled("app_store"):
        collectors.append(AppStoreCollector(client, sources_cfg["app_store"]))
    if enabled("product_hunt"):
        collectors.append(
            ProductHuntCollector(
                client,
                sources_cfg["product_hunt"],
                token=secrets.get("product_hunt_token") or "",
            )
        )
    if enabled("github"):
        collectors.append(
            GitHubCollector(client, sources_cfg["github"], token=secrets.get("github_token") or "")
        )
    if enabled("lobsters"):
        collectors.append(LobstersCollector(client, sources_cfg["lobsters"]))
    if enabled("v2ex"):
        collectors.append(V2EXCollector(client, sources_cfg["v2ex"]))
    if enabled("stackexchange"):
        collectors.append(StackExchangeCollector(client, sources_cfg["stackexchange"]))
    if enabled("indie_hackers"):
        collectors.append(IndieHackersCollector(client, sources_cfg["indie_hackers"]))
    if enabled("google_play"):
        collectors.append(GooglePlayCollector(client, sources_cfg["google_play"]))
    if enabled("chrome_web_store"):
        collectors.append(ChromeWebStoreCollector(client, sources_cfg["chrome_web_store"]))
    if enabled("rss"):
        collectors.append(RSSCollector(client, sources_cfg["rss"]))
    if enabled("g2"):
        collectors.append(G2Collector(client, sources_cfg["g2"]))
    return collectors


def _run_collector(collector: Any) -> tuple[str, list[RawSignal], float, str | None]:
    name = collector.name
    t0 = time.perf_counter()
    err: str | None = None
    try:
        items = collector.collect()
    except Exception as exc:  # noqa: BLE001 — isolate flaky sources
        items = []
        err = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - t0
    return name, items, elapsed, err


def collect_all(
    client: httpx.Client,
    config: dict[str, Any],
    *,
    workers: int = 1,
    on_source_done: OnSourceDone | None = None,
) -> CollectOutcome:
    collectors = _build_collectors(client, config)
    all_signals: list[RawSignal] = []
    stats: dict[str, int] = {}
    timings: dict[str, float] = {}
    errors: dict[str, str] = {}

    def _consume(name: str, items: list[RawSignal], elapsed: float, err: str | None) -> None:
        stats[name] = len(items)
        timings[name] = elapsed
        if err:
            errors[name] = err
        all_signals.extend(items)
        if on_source_done is not None:
            on_source_done(name, len(items), elapsed, err)

    workers = max(1, int(workers))
    if workers == 1 or len(collectors) <= 1:
        for c in collectors:
            _consume(*_run_collector(c))
    else:
        with ThreadPoolExecutor(max_workers=min(workers, len(collectors))) as pool:
            futures = {pool.submit(_run_collector, c): c for c in collectors}
            for fut in as_completed(futures):
                _consume(*fut.result())

    return CollectOutcome(signals=all_signals, stats=stats, timings=timings, errors=errors)
