"""Provider protocols implemented by current and TradingAgents data sources."""

from __future__ import annotations

from typing import Protocol

from .models import SourceEvidence


class PriceProvider(Protocol):
    name: str

    def get_prices(self, ticker: str, start_date: str, end_date: str) -> SourceEvidence | None: ...


class FundamentalsProvider(Protocol):
    name: str

    def get_fundamentals(self, ticker: str, as_of_date: str) -> SourceEvidence | None: ...


class NewsProvider(Protocol):
    name: str

    def get_news(self, ticker: str, start_date: str, end_date: str, *, limit: int) -> SourceEvidence | None: ...


class MacroProvider(Protocol):
    name: str

    def get_macro(self, indicator: str, as_of_date: str, *, look_back_days: int) -> SourceEvidence | None: ...
