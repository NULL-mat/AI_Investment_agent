"""Structured query construction for stock and agent-specific news."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable


def _date_value(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text[:10] if text else None


@dataclass(frozen=True)
class NewsQuerySpec:
    ticker: str
    company_name: str | None = None
    industry: str | None = None
    agent_type: str | None = None
    start_date: date | datetime | str | None = None
    end_date: date | datetime | str | None = None
    max_results: int = 10
    include_domains: tuple[str, ...] = field(default_factory=tuple)
    exclude_domains: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not str(self.ticker).strip():
            raise ValueError("ticker is required")
        if self.max_results < 1:
            raise ValueError("max_results must be positive")
        object.__setattr__(self, "ticker", str(self.ticker).strip())
        object.__setattr__(self, "start_date", _date_value(self.start_date))
        object.__setattr__(self, "end_date", _date_value(self.end_date))
        object.__setattr__(self, "include_domains", tuple(str(x).strip() for x in self.include_domains if str(x).strip()))
        object.__setattr__(self, "exclude_domains", tuple(str(x).strip() for x in self.exclude_domains if str(x).strip()))


class QueryBuilder:
    """Build a deterministic human-readable search query."""

    def build(self, spec: NewsQuerySpec) -> str:
        parts = [spec.ticker]
        for value in (spec.company_name, spec.industry, spec.agent_type):
            if value and str(value).strip() not in parts:
                parts.append(str(value).strip())
        return " ".join(parts)

    def build_many(self, specs: Iterable[NewsQuerySpec]) -> list[str]:
        return [self.build(spec) for spec in specs]
