"""End-to-end daily scan pipeline."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from opportunity_miner.extract.needs import extract_opportunity_candidates
from opportunity_miner.models import ScanResult
from opportunity_miner.report.writer import write_reports
from opportunity_miner.scoring.engine import rank_opportunities
from opportunity_miner.sources import collect_all
from opportunity_miner.sources.http import make_client

OnSourceDone = Callable[[str, int, float, str | None], None]


def run_scan(
    config: dict[str, Any],
    *,
    demo: bool = False,
    workers: int = 1,
    on_source_done: OnSourceDone | None = None,
) -> tuple[ScanResult, dict, dict[str, Any]]:
    """
    Run one scan cycle.

    Returns (result, report_paths, timings) where timings has phase seconds and
    optional per-source collect timings under key ``sources``.
    """
    from opportunity_miner.extract.classifier import ensure_default_model

    timings: dict[str, Any] = {"phases": {}, "sources": {}, "errors": {}}
    t_all = time.perf_counter()

    # Ensure local NB model exists before extraction
    t0 = time.perf_counter()
    clf_cfg = ((config.get("extraction") or {}).get("classifier") or {})
    if clf_cfg.get("enabled", True):
        ensure_default_model()
    timings["phases"]["ensure_model"] = time.perf_counter() - t0

    scan_cfg = config.get("scan") or {}
    ua = scan_cfg.get(
        "user_agent",
        "OpportunityMiner/0.2 (+https://github.com/YanChao1999/Product-Opportunity-Mining-Platform)",
    )
    request_timeout = float(scan_cfg.get("request_timeout") or 12.0)
    workers = max(1, int(workers))

    t0 = time.perf_counter()
    if demo:
        from opportunity_miner.pipeline.demo_data import demo_signals

        signals = demo_signals()
        stats: dict[str, int] = {}
        for s in signals:
            stats[s.source.value] = stats.get(s.source.value, 0) + 1
        timings["source_counts"] = dict(stats)
        if on_source_done is not None:
            for name, count in stats.items():
                on_source_done(name, count, 0.0, None)
    else:
        with make_client(ua, timeout=request_timeout) as client:
            outcome = collect_all(
                client,
                config,
                workers=workers,
                on_source_done=on_source_done,
            )
            signals = outcome.signals
            stats = outcome.stats
            timings["sources"] = outcome.timings
            timings["errors"] = outcome.errors
            timings["source_counts"] = dict(outcome.stats)
            # Cap per source if configured
            max_per = int(scan_cfg.get("max_items_per_source") or 0)
            if max_per > 0:
                capped = []
                counts: dict[str, int] = {}
                for s in signals:
                    key = s.source.value
                    if counts.get(key, 0) >= max_per:
                        continue
                    counts[key] = counts.get(key, 0) + 1
                    capped.append(s)
                signals = capped
                stats = counts
    timings["phases"]["collect"] = time.perf_counter() - t0

    scoring_cfg = config.get("scoring") or {}
    extraction_cfg = dict(config.get("extraction") or {})
    # Demo fixtures are curated seeds — keep them. Live scans drop seed/fallback placeholders.
    if demo:
        extraction_cfg["include_seeds"] = True
    t0 = time.perf_counter()
    candidates = extract_opportunity_candidates(signals, extraction_cfg)
    timings["phases"]["extract"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    opportunities = rank_opportunities(candidates, scoring_cfg)
    timings["phases"]["rank"] = time.perf_counter() - t0

    dim_labels = [
        str(d.get("label") or d.get("id"))
        for d in (scoring_cfg.get("dimensions") or [])
    ]
    result = ScanResult(
        scanned_at=datetime.now(timezone.utc),
        raw_count=len(signals),
        opportunity_count=len(opportunities),
        opportunities=opportunities,
        source_stats=stats,
        dimension_labels=dim_labels,
    )

    t0 = time.perf_counter()
    paths = write_reports(result, config.get("output") or {}, scoring_cfg=scoring_cfg)
    timings["phases"]["write_reports"] = time.perf_counter() - t0
    timings["phases"]["total"] = time.perf_counter() - t_all
    timings["workers"] = workers
    timings["demo"] = demo
    return result, paths, timings
