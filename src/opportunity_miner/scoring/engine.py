"""Extensible multi-dimension opportunity scoring."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Callable

from opportunity_miner.models import DEFAULT_DIMENSIONS, DimensionScores, Opportunity

HARD_KEYWORDS = {
    "ml", "ai", "llm", "blockchain", "crypto", "hardware", "chip", "medical",
    "fda", "realtime", "real-time", "multiplayer", "3d", "engine", "compliance",
    "hipaa", "bank", "payment", "infrastructure", "kubernetes", "distributed",
}
EASY_KEYWORDS = {
    "chrome extension", "notion", "template", "landing page", "newsletter",
    "directory", "checklist", "wrapper", "bot", "script", "csv", "spreadsheet",
    "notion template", "no-code", "zapier",
}
PAY_KEYWORDS = {
    "would pay", "willing to pay", "shut up and take my money", "订阅", "付费",
    "pricing", "saas", "b2b", "enterprise", "subscription", "pro plan",
    "i'd pay", "id pay", "budget for",
}
COMPETITION_KEYWORDS = {
    "alternative to", "like notion", "like figma", "like slack", "vs ",
    "compared to", "competitor", "saturated", "crowded", "too many apps",
}
URGENT_KEYWORDS = {
    "asap", "urgent", "blocking", "broken", "can't ship", "losing money",
    "churn", "deadline", "immediately", "right now", "每天", "立刻", "阻塞",
}
TREND_KEYWORDS = {
    "ai", "llm", "agent", "gpt", "claude", "viral", "tiktok", "shorts",
    "local-first", "privacy", "on-device", "indie", "solopreneur", "mcp",
}
DEFENSE_KEYWORDS = {
    "network effect", "data moat", "community", "marketplace", "protocol",
    "standard", "integration", "workflow", "switching cost", "proprietary",
}
VIRAL_KEYWORDS = {
    "share", "invite", "referral", "community", "template", "ugc", "social",
    "multiplayer", "collab", "team", "viral",
}
REGULATORY_KEYWORDS = {
    "hipaa", "gdpr", "fda", "pci", "kyc", "aml", "finance", "bank", "medical",
    "crypto", "gambling", "kids", "coppa", "license", "compliance",
}
FAST_REVENUE_KEYWORDS = {
    "would pay", "subscription", "saas", "freelance", "agency", "template",
    "chrome extension", "digital download", "pro plan", "b2b",
}
MARKET_KEYWORDS = {
    "enterprise", "everyone", "millions", "market", "industry", "smbs",
    "developers", "creators", "teams", "global", "worldwide",
}


def _clamp(value: float, lo: float = 1.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, value))


def score_demand(candidate: dict[str, Any]) -> float:
    n = len(candidate.get("evidence") or [])
    engagement = candidate.get("total_score", 0) + 2 * candidate.get("total_comments", 0)
    strength = float(candidate.get("avg_strength") or 0)
    sources = len(candidate.get("sources") or [])
    need_conf = float(candidate.get("need_confidence") or 0)
    raw = (
        1.5 * math.log1p(n)
        + 1.2 * math.log1p(engagement)
        + 3.5 * strength
        + 0.8 * sources
        + 2.0 * need_conf
    )
    return round(_clamp(raw), 2)


def score_competition(candidate: dict[str, Any]) -> float:
    text = (candidate.get("text_blob") or "").lower()
    evidence = candidate.get("evidence") or []
    listings = candidate.get("competition_listings") or []
    store_hits = len(listings) + sum(
        1
        for e in evidence
        if (e.metadata or {}).get("kind") in {"store_result", "app_listing", "post"}
    )
    phrase_hits = sum(1 for p in COMPETITION_KEYWORDS if p in text)
    raw = 2.0 + 0.4 * store_hits + 0.8 * phrase_hits
    if len(candidate.get("sources") or []) >= 2 and store_hits <= 2:
        raw -= 1.5
    return round(_clamp(raw), 2)


def score_difficulty(candidate: dict[str, Any]) -> float:
    text = (candidate.get("text_blob") or "").lower()
    hard = sum(1 for k in HARD_KEYWORDS if k in text)
    easy = sum(1 for k in EASY_KEYWORDS if k in text)
    raw = 4.5 + 0.9 * hard - 0.8 * easy
    if re.search(r"cross[- ]?platform|integrat|api|sync", text):
        raw += 1.2
    if re.search(r"extension|script|template|checklist", text):
        raw -= 1.0
    return round(_clamp(raw), 2)


def score_monetization(candidate: dict[str, Any]) -> float:
    text = (candidate.get("text_blob") or "").lower()
    pay_hits = sum(1 for k in PAY_KEYWORDS if k in text)
    category = candidate.get("category") or "general"
    category_boost = {
        "devtools": 1.5,
        "fintech": 1.8,
        "ai": 1.3,
        "productivity": 1.0,
        "gaming": 0.6,
        "health": 0.9,
        "mobile": 0.8,
        "general": 0.5,
    }.get(category, 0.5)
    b2b = 1.2 if any(x in text for x in ("b2b", "enterprise", "publisher", "team", "saas")) else 0.0
    raw = 3.0 + 1.4 * pay_hits + category_boost + b2b
    if pay_hits and candidate.get("total_comments", 0) > 10:
        raw += 1.0
    return round(_clamp(raw), 2)


def score_urgency(candidate: dict[str, Any]) -> float:
    text = (candidate.get("text_blob") or "").lower()
    hits = sum(1 for k in URGENT_KEYWORDS if k in text)
    # Fresh multi-source demand feels more urgent
    sources = len(candidate.get("sources") or [])
    engagement = candidate.get("total_comments", 0)
    raw = 3.5 + 1.3 * hits + 0.4 * sources + 0.15 * math.log1p(engagement)
    return round(_clamp(raw), 2)


def score_market_size(candidate: dict[str, Any]) -> float:
    text = (candidate.get("text_blob") or "").lower()
    hits = sum(1 for k in MARKET_KEYWORDS if k in text)
    category = candidate.get("category") or "general"
    cat_boost = {
        "devtools": 1.2,
        "fintech": 1.5,
        "ai": 1.4,
        "productivity": 1.3,
        "gaming": 1.1,
        "health": 1.2,
        "mobile": 1.3,
        "general": 0.6,
    }.get(category, 0.6)
    sources = len(candidate.get("sources") or [])
    raw = 3.0 + 0.9 * hits + cat_boost + 0.5 * sources
    return round(_clamp(raw), 2)


def score_trend(candidate: dict[str, Any]) -> float:
    text = (candidate.get("text_blob") or "").lower()
    hits = sum(1 for k in TREND_KEYWORDS if k in text)
    # Recency of evidence
    now = datetime.now(timezone.utc)
    ages = []
    for e in candidate.get("evidence") or []:
        if e.created_at:
            ages.append(max(0.0, (now - e.created_at).total_seconds() / 3600.0))
    freshness = 2.0
    if ages:
        avg_h = sum(ages) / len(ages)
        freshness = 3.0 if avg_h < 48 else (2.0 if avg_h < 168 else 1.0)
    raw = 3.0 + 1.1 * hits + freshness
    return round(_clamp(raw), 2)


def score_defensibility(candidate: dict[str, Any]) -> float:
    text = (candidate.get("text_blob") or "").lower()
    hits = sum(1 for k in DEFENSE_KEYWORDS if k in text)
    raw = 3.5 + 1.2 * hits
    if "b2b" in text or "workflow" in text or "integration" in text:
        raw += 1.0
    return round(_clamp(raw), 2)


def score_viral(candidate: dict[str, Any]) -> float:
    text = (candidate.get("text_blob") or "").lower()
    hits = sum(1 for k in VIRAL_KEYWORDS if k in text)
    raw = 3.0 + 1.1 * hits
    if candidate.get("category") in {"gaming", "mobile", "ai"}:
        raw += 0.8
    return round(_clamp(raw), 2)


def score_regulatory_risk(candidate: dict[str, Any]) -> float:
    """Higher = more regulatory risk (will be inverted in opportunity score)."""
    text = (candidate.get("text_blob") or "").lower()
    hits = sum(1 for k in REGULATORY_KEYWORDS if k in text)
    raw = 2.0 + 1.3 * hits
    if candidate.get("category") in {"fintech", "health"}:
        raw += 1.5
    return round(_clamp(raw), 2)


def score_time_to_revenue(candidate: dict[str, Any]) -> float:
    """Higher = faster path to first dollar."""
    text = (candidate.get("text_blob") or "").lower()
    hits = sum(1 for k in FAST_REVENUE_KEYWORDS if k in text)
    difficultyish = score_difficulty(candidate)
    raw = 3.5 + 1.2 * hits + (10.0 - difficultyish) * 0.25
    return round(_clamp(raw), 2)


SCORERS: dict[str, Callable[[dict[str, Any]], float]] = {
    "demand": score_demand,
    "competition": score_competition,
    "difficulty": score_difficulty,
    "monetization": score_monetization,
    "urgency": score_urgency,
    "market_size": score_market_size,
    "trend": score_trend,
    "defensibility": score_defensibility,
    "viral": score_viral,
    "regulatory_risk": score_regulatory_risk,
    "time_to_revenue": score_time_to_revenue,
}


def resolve_dimension_spec(scoring_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    dims = scoring_cfg.get("dimensions")
    if isinstance(dims, list) and dims:
        return dims
    # Legacy weights-only config → enable core four + extras with defaults
    return list(DEFAULT_DIMENSIONS)


def score_candidate(candidate: dict[str, Any], scoring_cfg: dict[str, Any]) -> Opportunity:
    spec = resolve_dimension_spec(scoring_cfg)
    raw: dict[str, float] = {}
    for dim in spec:
        dim_id = dim["id"]
        scorer = SCORERS.get(dim_id)
        if scorer:
            raw[dim_id] = scorer(candidate)
        else:
            # Unknown custom dimension → neutral mid score (pluggable later)
            raw[dim_id] = float(dim.get("default", 5.0))

    dims = DimensionScores(raw=raw, spec=spec)
    weights = {
        d["id"]: float(d.get("weight", 1.0))
        for d in spec
    }
    # Allow top-level weights override
    weights.update((scoring_cfg or {}).get("weights") or {})

    opp = Opportunity(
        id=candidate["id"],
        title=candidate["title"],
        summary=candidate["summary"],
        category=candidate.get("category") or "general",
        sources=list(candidate.get("sources") or []),
        evidence=list(candidate.get("evidence") or []),
        keywords=list(candidate.get("keywords") or []),
        dimensions=dims,
        need_confidence=float(candidate.get("need_confidence") or 0),
    )
    opp.refresh_score(weights)
    return opp


def rank_opportunities(
    candidates: list[dict[str, Any]],
    scoring_cfg: dict[str, Any],
) -> list[Opportunity]:
    scored = [score_candidate(c, scoring_cfg) for c in candidates]
    scored.sort(key=lambda o: o.opportunity_score, reverse=True)
    return scored
