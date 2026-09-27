"""Four-dimension opportunity scoring."""

from __future__ import annotations

import math
import re
from typing import Any

from opportunity_miner.models import DimensionScores, Opportunity

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


def _clamp(value: float, lo: float = 1.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, value))


def score_demand(candidate: dict[str, Any]) -> float:
    n = len(candidate.get("evidence") or [])
    engagement = candidate.get("total_score", 0) + 2 * candidate.get("total_comments", 0)
    strength = float(candidate.get("avg_strength") or 0)
    sources = len(candidate.get("sources") or [])
    raw = (
        1.5 * math.log1p(n)
        + 1.2 * math.log1p(engagement)
        + 4.0 * strength
        + 0.8 * sources
    )
    return round(_clamp(raw), 2)


def score_competition(candidate: dict[str, Any]) -> float:
    """Higher = more competitive / crowded."""
    text = (candidate.get("text_blob") or "").lower()
    evidence = candidate.get("evidence") or []
    listings = candidate.get("competition_listings") or []
    store_hits = len(listings) + sum(
        1
        for e in evidence
        if (e.metadata or {}).get("kind") in {"store_result", "app_listing", "post"}
    )
    phrase_hits = sum(1 for p in COMPETITION_KEYWORDS if p in text)
    # Many existing apps for same keywords → higher competition
    raw = 2.0 + 0.4 * store_hits + 0.8 * phrase_hits
    # Multi-source wish with few store listings → lower competition
    if len(candidate.get("sources") or []) >= 2 and store_hits <= 2:
        raw -= 1.5
    return round(_clamp(raw), 2)


def score_difficulty(candidate: dict[str, Any]) -> float:
    """Higher = harder to build."""
    text = (candidate.get("text_blob") or "").lower()
    hard = sum(1 for k in HARD_KEYWORDS if k in text)
    easy = sum(1 for k in EASY_KEYWORDS if k in text)
    raw = 4.5 + 0.9 * hard - 0.8 * easy
    # Integrations / cross-platform bump difficulty
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
    # Engagement with explicit pay language
    if pay_hits and candidate.get("total_comments", 0) > 10:
        raw += 1.0
    return round(_clamp(raw), 2)


def score_candidate(candidate: dict[str, Any], scoring_cfg: dict[str, Any]) -> Opportunity:
    dims = DimensionScores(
        demand=score_demand(candidate),
        competition=score_competition(candidate),
        difficulty=score_difficulty(candidate),
        monetization=score_monetization(candidate),
    )
    weights = (scoring_cfg or {}).get("weights")
    opp = Opportunity(
        id=candidate["id"],
        title=candidate["title"],
        summary=candidate["summary"],
        category=candidate.get("category") or "general",
        sources=list(candidate.get("sources") or []),
        evidence=list(candidate.get("evidence") or []),
        keywords=list(candidate.get("keywords") or []),
        dimensions=dims,
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
