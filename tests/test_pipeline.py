"""Unit tests for extraction + scoring (offline)."""

from __future__ import annotations

from opportunity_miner.config import load_config
from opportunity_miner.extract.classifier import (
    NeedClassifier,
    classify_logistic,
    classify_naive_bayes,
    train_naive_bayes,
)
from opportunity_miner.extract.needs import extract_opportunity_candidates, filter_unmet_signals
from opportunity_miner.models import DimensionScores, RawSignal, SourceName
from opportunity_miner.pipeline.demo_data import demo_signals
from opportunity_miner.pipeline.scan import run_scan
from opportunity_miner.scoring.engine import rank_opportunities


def test_dimension_opportunity_score_prefers_high_demand_low_competition():
    spec = [
        {"id": "demand", "invert": False, "weight": 1.0},
        {"id": "competition", "invert": True, "weight": 1.0},
        {"id": "difficulty", "invert": True, "weight": 1.0},
        {"id": "monetization", "invert": False, "weight": 1.0},
    ]
    strong = DimensionScores(
        raw={"demand": 9, "competition": 2, "difficulty": 3, "monetization": 8},
        spec=spec,
    )
    weak = DimensionScores(
        raw={"demand": 4, "competition": 9, "difficulty": 9, "monetization": 3},
        spec=spec,
    )
    assert strong.opportunity_score() > weak.opportunity_score()


def test_extended_dimensions_change_ranking():
    cfg = load_config()
    candidates = extract_opportunity_candidates(demo_signals(), cfg["extraction"])
    ranked = rank_opportunities(candidates, cfg["scoring"])
    assert ranked
    dims = ranked[0].dimensions.raw
    assert "urgency" in dims
    assert "market_size" in dims
    assert "time_to_revenue" in dims
    assert len(dims) >= 7


def test_local_classifier_flags_wish_not_listing():
    wish = RawSignal(
        source=SourceName.REDDIT,
        external_id="w",
        title="I wish there was a tool for this",
        body="Would pay for a SaaS. No good alternative.",
        score=10,
        comments=3,
    )
    listing = RawSignal(
        source=SourceName.APP_STORE,
        external_id="l",
        title="Budgetly",
        body="Personal finance app",
        score=50000,
        metadata={"kind": "app_listing"},
    )
    assert classify_logistic(wish).is_need
    assert classify_logistic(wish).confidence > 0.55
    assert not classify_logistic(listing).is_need


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


def test_demo_pipeline_produces_ranked_table(tmp_path):
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
    assert "紧迫" in md or "urgency" in md.lower()
    assert paths["csv_latest"].exists()
    assert paths["json_latest"].exists()
    # Expanded demo sources present in stats
    assert result.source_stats.get("github", 0) >= 1
    assert result.source_stats.get("g2", 0) >= 1


def test_app_listings_are_not_ranked_as_opportunities():
    cfg = load_config()
    signals = demo_signals()
    candidates = extract_opportunity_candidates(signals, cfg["extraction"])
    titles = " ".join(c["title"].lower() for c in candidates)
    assert "budgetly" not in titles
    assert any(
        "wish" in c["title"].lower()
        or "somebody" in c["title"].lower()
        or "looking" in c["title"].lower()
        or "有没有" in c["title"]
        for c in candidates
    )


def test_rank_opportunities_assigns_categories():
    cfg = load_config()
    candidates = extract_opportunity_candidates(demo_signals(), cfg["extraction"])
    ranked = rank_opportunities(candidates, cfg["scoring"])
    assert ranked
    assert all(1 <= o.dimensions.demand <= 10 for o in ranked)
    assert all(o.category for o in ranked)


def test_classifier_backend_logistic_filter():
    clf = NeedClassifier({"backend": "logistic", "threshold": 0.45})
    out = clf.filter(demo_signals())
    assert any(c.is_need for _, c in out)


def test_naive_bayes_trained_local_model():
    model = train_naive_bayes()
    wish = RawSignal(
        source=SourceName.REDDIT,
        external_id="nb1",
        title="I wish there was a tool for offline CRM",
        body="Would pay. No good alternative.",
    )
    noise = RawSignal(
        source=SourceName.RSS,
        external_id="nb2",
        title="We're hiring a senior engineer",
        body="Changelog and launch day giveaway",
    )
    assert classify_naive_bayes(wish, model).confidence > 0.6
    assert classify_naive_bayes(noise, model).confidence < 0.4


def test_ensemble_backend_not_string_only():
    clf = NeedClassifier({"backend": "ensemble", "threshold": 0.45, "blend_patterns": False})
    wish = RawSignal(
        source=SourceName.HACKERNEWS,
        external_id="e1",
        title="Need a local-first habit tracker without accounts",
        body="Privacy focused. Willing to subscribe monthly.",
    )
    # No exact POS_PHRASES match required — NB n-grams + logistic features decide
    result = clf.classify(wish)
    assert result.backend == "ensemble"
    assert result.confidence > 0.4
