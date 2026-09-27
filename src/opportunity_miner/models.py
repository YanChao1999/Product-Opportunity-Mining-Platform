"""Core domain models — extensible sources & multi-dimension scores."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field, field_validator


class SourceName(str, Enum):
    """Known collectors. New sources can be added without breaking old reports."""

    HACKERNEWS = "hackernews"
    REDDIT = "reddit"
    STEAM = "steam"
    APP_STORE = "app_store"
    PRODUCT_HUNT = "product_hunt"
    GOOGLE_PLAY = "google_play"
    GITHUB = "github"
    LOBSTERS = "lobsters"
    INDIE_HACKERS = "indie_hackers"
    V2EX = "v2ex"
    STACKEXCHANGE = "stackexchange"
    CHROME_WEB_STORE = "chrome_web_store"
    RSS = "rss"
    G2 = "g2"


# Default dimension definitions (overridden by config/scoring.dimensions)
DEFAULT_DIMENSIONS: list[dict[str, Any]] = [
    {"id": "demand", "label": "需求强度", "invert": False, "weight": 1.0, "table": True},
    {"id": "competition", "label": "竞争程度", "invert": True, "weight": 1.0, "table": True},
    {"id": "difficulty", "label": "开发难度", "invert": True, "weight": 1.0, "table": True},
    {"id": "monetization", "label": "付费可能性", "invert": False, "weight": 1.0, "table": True},
    {"id": "urgency", "label": "紧迫性", "invert": False, "weight": 0.85, "table": True},
    {"id": "market_size", "label": "市场规模", "invert": False, "weight": 0.9, "table": True},
    {"id": "trend", "label": "趋势热度", "invert": False, "weight": 0.8, "table": False},
    {"id": "defensibility", "label": "护城河", "invert": False, "weight": 0.75, "table": False},
    {"id": "viral", "label": "传播潜力", "invert": False, "weight": 0.7, "table": False},
    {"id": "regulatory_risk", "label": "监管风险", "invert": True, "weight": 0.7, "table": False},
    {"id": "time_to_revenue", "label": "变现速度", "invert": False, "weight": 0.85, "table": True},
]


class RawSignal(BaseModel):
    """A single scraped post / review / comment before opportunity extraction."""

    source: SourceName
    external_id: str
    title: str = ""
    body: str = ""
    url: str = ""
    author: str = ""
    score: int = 0
    comments: int = 0
    created_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}".strip()


class DimensionScores(BaseModel):
    """
    Extensible multi-dimension scores (each raw value on 1–10).

    Dimensions with invert=True contribute via (11 - raw) so that
    high competition / difficulty / regulatory risk lowers opportunity.
    """

    raw: dict[str, float] = Field(default_factory=dict)
    # Spec snapshot used for scoring/display (from config)
    spec: list[dict[str, Any]] = Field(default_factory=lambda: list(DEFAULT_DIMENSIONS))

    @field_validator("raw")
    @classmethod
    def _clamp_raw(cls, v: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for k, val in (v or {}).items():
            try:
                out[k] = float(max(1.0, min(10.0, float(val))))
            except (TypeError, ValueError):
                continue
        return out

    def get(self, dim_id: str, default: float = 5.0) -> float:
        return float(self.raw.get(dim_id, default))

    # Backward-compatible accessors used by older tests / callers
    @property
    def demand(self) -> float:
        return self.get("demand")

    @property
    def competition(self) -> float:
        return self.get("competition")

    @property
    def difficulty(self) -> float:
        return self.get("difficulty")

    @property
    def monetization(self) -> float:
        return self.get("monetization")

    @property
    def competition_gap(self) -> float:
        return round((11.0 - self.competition) / 10.0 * 10.0, 2)

    @property
    def feasibility(self) -> float:
        return round((11.0 - self.difficulty) / 10.0 * 10.0, 2)

    def contribution(self, dim: dict[str, Any]) -> float:
        """Value that enters the multiplicative score (after optional invert)."""
        raw = self.get(dim["id"], 5.0)
        if dim.get("invert"):
            return round((11.0 - raw) / 10.0 * 10.0, 2)
        return raw

    def opportunity_score(self, weights: dict[str, float] | None = None) -> float:
        """
        Geometric mean of active dimension contributions, scaled to 0–100.

        Using a geometric mean (instead of a fixed 4-factor product) keeps scores
        comparable as dimensions are added/removed in config.
        """
        specs = [d for d in self.spec if d.get("id")]
        if not specs:
            specs = list(DEFAULT_DIMENSIONS)
        product = 1.0
        weight_sum = 0.0
        for dim in specs:
            dim_id = dim["id"]
            w = float((weights or {}).get(dim_id, dim.get("weight", 1.0)))
            if w <= 0:
                continue
            contrib = max(0.1, self.contribution(dim))
            product *= contrib ** w
            weight_sum += w
        if weight_sum <= 0:
            return 0.0
        # Geometric mean on 1–10 scale → map to 0–100
        geo = product ** (1.0 / weight_sum)
        return round(min(100.0, (geo / 10.0) * 100.0), 2)

    def table_columns(self) -> list[tuple[str, str, float]]:
        """(id, short_label, raw_value) for dimensions marked table:true."""
        cols: list[tuple[str, str, float]] = []
        for dim in self.spec:
            if not dim.get("table", True):
                continue
            label = dim.get("short") or dim.get("label") or dim["id"]
            cols.append((dim["id"], label, self.get(dim["id"])))
        return cols


class Opportunity(BaseModel):
    """A clustered unmet-need opportunity with scores and evidence."""

    id: str
    title: str
    summary: str
    category: str = "general"
    sources: list[SourceName] = Field(default_factory=list)
    evidence: list[RawSignal] = Field(default_factory=list)
    signal_count: int = 0
    dimensions: DimensionScores
    opportunity_score: float = 0.0
    keywords: list[str] = Field(default_factory=list)
    need_confidence: float = 0.0
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def refresh_score(self, weights: dict[str, float] | None = None) -> None:
        self.opportunity_score = self.dimensions.opportunity_score(weights)
        self.signal_count = len(self.evidence)


class ScanResult(BaseModel):
    scanned_at: datetime
    raw_count: int
    opportunity_count: int
    opportunities: list[Opportunity]
    source_stats: dict[str, int] = Field(default_factory=dict)
    dimension_labels: list[str] = Field(default_factory=list)
