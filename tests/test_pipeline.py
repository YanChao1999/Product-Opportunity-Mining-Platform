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
    extract_cfg = dict(cfg["extraction"])
    extract_cfg["include_seeds"] = True
    candidates = extract_opportunity_candidates(demo_signals(), extract_cfg)
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
        include_seeds=True,
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
    result, paths, timings = run_scan(cfg, demo=True)
    assert result.opportunity_count >= 1
    assert result.opportunities[0].opportunity_score >= result.opportunities[-1].opportunity_score
    assert paths["markdown_latest"].exists()
    md = paths["markdown_latest"].read_text(encoding="utf-8")
    assert "Product Opportunity Report" in md
    assert "需求" in md
    assert "紧迫" in md or "urgency" in md.lower()
    assert paths["csv_latest"].exists()
    assert paths["json_latest"].exists()
    assert "phases" in timings
    assert timings["phases"]["total"] >= 0
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


def test_category_uses_whole_tokens_not_substrings():
    from opportunity_miner.extract.needs import _category_for

    # "ai" must not match inside "running"; "mod" must not match inside "mode"/"model"
    assert _category_for([], "What filesystem are you running on your NAS?") == "general"
    assert _category_for([], "Tell HN: Substack obfuscating text to break reading mode") == "general"
    assert _category_for(["agent", "access"], "Allow agents access to cloud files") == "ai"
    assert _category_for(["steam", "mod"], "Steam Workshop mod conflict detector") == "gaming"
    assert _category_for(["api", "deploy"], "CI deploy API for SaaS developers") == "devtools"


def test_live_extract_drops_seed_and_commit_noise():
    cfg = load_config()
    extract_cfg = dict(cfg["extraction"])
    extract_cfg["include_seeds"] = False
    signals = [
        RawSignal(
            source=SourceName.PRODUCT_HUNT,
            external_id="seed1",
            title="GapFinder AI: I wish there was a daily digest",
            body="Would pay for automated opportunity scanning",
            metadata={"kind": "fallback_post"},
        ),
        RawSignal(
            source=SourceName.GITHUB,
            external_id="c1",
            title="feat: Product Opportunity Mining — multi-source",
            body="I wish there was something",
        ),
        RawSignal(
            source=SourceName.HACKERNEWS,
            external_id="hn1",
            title="Ask HN: Is there a tool for refund-risk analytics?",
            body="Looking for a SaaS. Would pay. No good alternative.",
            score=40,
            comments=12,
        ),
    ]
    cands = extract_opportunity_candidates(signals, extract_cfg)
    titles = " ".join(c["title"] for c in cands).lower()
    assert "gapfinder" not in titles
    assert "feat: product opportunity" not in titles
    assert "refund" in titles or "ask hn" in titles


def test_lobsters_author_handles_string_submitter():
    from opportunity_miner.sources.lobsters import _author

    assert _author({"submitter_user": {"username": "alice"}}) == "alice"
    assert _author({"submitter_user": "bob"}) == "bob"
    assert _author({}) == ""


def test_get_json_does_not_retry_timeouts(httpx_mock):
    import httpx

    from opportunity_miner.sources.http import get_json

    httpx_mock.add_exception(httpx.ReadTimeout("slow"))
    with httpx.Client() as client:
        try:
            get_json(client, "https://example.com/x.json", retries=3)
            raise AssertionError("expected timeout")
        except httpx.ReadTimeout:
            pass
    # Only one request attempted — no retry storm
    assert len(httpx_mock.get_requests()) == 1


def test_collect_all_parallel_aggregates_results():
    import time

    import httpx

    from opportunity_miner.sources import collect_all

    class _FakeCollector:
        def __init__(self, name: str, n: int, delay: float = 0.08):
            self.name = name
            self._n = n
            self._delay = delay

        def collect(self):
            time.sleep(self._delay)
            return [
                RawSignal(
                    source=SourceName.RSS,
                    external_id=f"{self.name}-{i}",
                    title=f"{self.name}-{i}",
                )
                for i in range(self._n)
            ]

    def fake_build(client, config):
        return [_FakeCollector("a", 2), _FakeCollector("b", 3)]

    import opportunity_miner.sources as sources_mod

    original = sources_mod._build_collectors
    sources_mod._build_collectors = fake_build  # type: ignore[method-assign]
    try:
        with httpx.Client() as client:
            t0 = time.perf_counter()
            out = collect_all(client, {}, workers=2)
            elapsed = time.perf_counter() - t0
        assert out.stats == {"a": 2, "b": 3}
        assert len(out.signals) == 5
        assert set(out.timings) == {"a", "b"}
        # Parallel ≈ max(delay); sequential would be ~0.16s
        assert elapsed < 0.14
    finally:
        sources_mod._build_collectors = original  # type: ignore[method-assign]


def test_normalize_proxy_env_rewrites_socks_scheme(monkeypatch):
    import os

    from opportunity_miner.sources.http import normalize_proxy_env

    monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:7897/")
    monkeypatch.setenv("https_proxy", "socks://127.0.0.1:7897")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    normalize_proxy_env()
    assert os.environ["ALL_PROXY"] == "socks5://127.0.0.1:7897/"
    assert os.environ["https_proxy"] == "socks5://127.0.0.1:7897"
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7890"


def test_make_client_accepts_clash_socks_proxy(monkeypatch):
    import httpx

    from opportunity_miner.sources.http import make_client

    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:7897/")
    with make_client("test-agent") as client:
        assert isinstance(client, httpx.Client)
