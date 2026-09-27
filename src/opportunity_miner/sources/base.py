"""Source collector protocol."""

from __future__ import annotations

from typing import Protocol

from opportunity_miner.models import RawSignal


class SourceCollector(Protocol):
    name: str

    def collect(self) -> list[RawSignal]:
        ...
