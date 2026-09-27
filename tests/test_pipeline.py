"""Unit tests for extraction + scoring (offline)."""

from __future__ import annotations

from opportunity_miner.config import load_config
from opportunity_miner.extract.needs import extract_opportunity_candidates, filter_unmet_signals
from opportunity_miner.models import DimensionScores
from opportunity_miner.pipeline.demo_data import demo_signals
from opportunity_miner.pipeline.scan import run_scan
from opportunity_miner.scoring.engine import rank_opportunities


def test_dimension_opportunity_score_prefers_high_demand_low_competition():
    strong = DimensionScores(demand=9, competition=2, difficulty=3, monetization=8)
    weak = DimensionScores(demand=4, competition=9, difficulty=9, monetization=3)
    assert strong.opportunity_score() > weak.opportunity_score()


def test_unmet_need_patterns_catch_wish_language():
    cfg = load_config()
    scored = filter_unmet_signals(
        demo_signals(),
        cfg["extraction"]["unmet_need_patterns"],
        min_score=0.35,
    )
    assert len(scored) >= 4
    titles = " ".join(s.title for s, _ in scored).lower()
    assert "wish" in titles or "somebody" in titles or "looking" in titles


def test_demo_pipeline_produces_ranked_table(tmp_path, monkeypatch):
    cfg = load_config()
    cfg["output"] = {
        "dir": str(tmp_path / "reports"),
        "formats": ["markdown", "csv", "json"],
        "top_n": 20,
    }
    result, paths = run_scan(cfg, demo=True)
    assert result.opportunity_count >= 1
    assert result.opportunities[0].opportunity_score >= result.opportunities[-1].opportunity_score
    assert paths["markdown_latest"].exists()
    md = paths["markdown_latest"].read_text(encoding="utf-8")
    assert "Product Opportunity Report" in md
    assert "需求" in md
    assert paths["csv_latest"].exists()
    assert paths["json_latest"].exists()


def test_app_listings_are_not_ranked_as_opportunities():
    cfg = load_config()
    signals = demo_signals()
    candidates = extract_opportunity_candidates(signals, cfg["extraction"])
    titles = " ".join(c["title"].lower() for c in candidates)
    assert "budgetly" not in titles
    assert "claude" not in titles
    # Wish-language signals must survive
    assert any("wish" in c["title"].lower() or "somebody" in c["title"].lower() or "looking" in c["title"].lower() for c in candidates)


def test_rank_opportunities_assigns_categories():
    cfg = load_config()
    candidates = extract_opportunity_candidates(demo_signals(), cfg["extraction"])
    ranked = rank_opportunities(candidates, cfg["scoring"])
    assert ranked
    assert all(1 <= o.dimensions.demand <= 10 for o in ranked)
    assert all(o.category for o in ranked)
