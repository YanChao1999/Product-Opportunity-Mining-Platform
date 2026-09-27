"""End-to-end daily scan pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from opportunity_miner.extract.needs import extract_opportunity_candidates
from opportunity_miner.models import ScanResult
from opportunity_miner.report.writer import write_reports
from opportunity_miner.scoring.engine import rank_opportunities
from opportunity_miner.sources import collect_all
from opportunity_miner.sources.http import make_client


def run_scan(config: dict[str, Any], *, demo: bool = False) -> tuple[ScanResult, dict]:
    scan_cfg = config.get("scan") or {}
    ua = scan_cfg.get(
        "user_agent",
        "OpportunityMiner/0.1 (+https://github.com/YanChao1999/Product-Opportunity-Mining-Platform)",
    )

    if demo:
        from opportunity_miner.pipeline.demo_data import demo_signals

        signals = demo_signals()
        stats = {}
        for s in signals:
            stats[s.source.value] = stats.get(s.source.value, 0) + 1
    else:
        with make_client(ua) as client:
            signals, stats = collect_all(client, config)
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

    scoring_cfg = config.get("scoring") or {}
    candidates = extract_opportunity_candidates(signals, config.get("extraction") or {})
    opportunities = rank_opportunities(candidates, scoring_cfg)
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
    paths = write_reports(result, config.get("output") or {}, scoring_cfg=scoring_cfg)
    return result, paths
