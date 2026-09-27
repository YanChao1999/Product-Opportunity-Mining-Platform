"""Core domain models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field


class SourceName(str, Enum):
    HACKERNEWS = "hackernews"
    REDDIT = "reddit"
    STEAM = "steam"
    APP_STORE = "app_store"
    PRODUCT_HUNT = "product_hunt"


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
    """Four scoring dimensions, each on a 1–10 scale."""

    demand: float = Field(ge=1, le=10, description="需求强度")
    competition: float = Field(ge=1, le=10, description="竞争程度 (higher = more crowded)")
    difficulty: float = Field(ge=1, le=10, description="开发难度 (higher = harder)")
    monetization: float = Field(ge=1, le=10, description="付费可能性")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def competition_gap(self) -> float:
        """Inverted competition: low competition → high gap score."""
        return round((11.0 - self.competition) / 10.0 * 10.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def feasibility(self) -> float:
        """Inverted difficulty: easier builds → higher feasibility."""
        return round((11.0 - self.difficulty) / 10.0 * 10.0, 2)

    def opportunity_score(self, weights: dict[str, float] | None = None) -> float:
        """
        Opportunity = demand × competition_gap × feasibility × monetization
        (normalized to a comparable 0–10000-ish range, then scaled to 0–100).
        """
        w = weights or {
            "demand": 1.0,
            "competition_gap": 1.0,
            "feasibility": 1.0,
            "monetization": 1.0,
        }
        raw = (
            (self.demand ** w["demand"])
            * (self.competition_gap ** w["competition_gap"])
            * (self.feasibility ** w["feasibility"])
            * (self.monetization ** w["monetization"])
        )
        # Max theoretical ≈ 10^4 = 10000 → map to 0–100
        return round(min(100.0, (raw / 10000.0) * 100.0), 2)


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
