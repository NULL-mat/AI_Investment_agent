"""Source-aware data contracts for the TradingAgents integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

DataKind = Literal["prices", "fundamentals", "news", "macro"]


@dataclass(frozen=True)
class SourceEvidence:
    provider: str
    kind: DataKind
    ticker: str | None
    as_of_date: str
    payload: Any
    retrieved_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceFailure:
    provider: str
    kind: DataKind
    error_type: str
    message: str
    retryable: bool | None = None


@dataclass(frozen=True)
class DataBundle:
    ticker: str | None
    as_of_date: str
    kind: DataKind
    evidence: tuple[SourceEvidence, ...] = ()
    failures: tuple[SourceFailure, ...] = ()

    @property
    def providers(self) -> tuple[str, ...]:
        return tuple(item.provider for item in self.evidence)

    @property
    def has_data(self) -> bool:
        return bool(self.evidence)
