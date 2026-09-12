"""Orchestrate multiple evidence providers without hiding source failures."""

from __future__ import annotations

import logging
from typing import Any, Iterable

from infrastructure.network import ProviderError

from .models import DataBundle, DataKind, SourceEvidence, SourceFailure

logger = logging.getLogger("tradingagents_extension.data_hub")


class MultiSourceDataError(RuntimeError):
    def __init__(self, bundle: DataBundle) -> None:
        self.bundle = bundle
        providers = ", ".join(failure.provider for failure in bundle.failures) or "none"
        super().__init__(f"No {bundle.kind} data available; failed providers: {providers}")


class MultiSourceDataHub:
    """Collect independent source results with explicit partial-failure state."""

    def __init__(
        self,
        *,
        price_providers: Iterable[Any] = (),
        fundamentals_providers: Iterable[Any] = (),
        news_providers: Iterable[Any] = (),
        macro_providers: Iterable[Any] = (),
    ) -> None:
        self._providers = {
            "prices": tuple(price_providers),
            "fundamentals": tuple(fundamentals_providers),
            "news": tuple(news_providers),
            "macro": tuple(macro_providers),
        }

    @classmethod
    def default(cls, *, include_ashare: bool = True, include_financial_datasets: bool = True, include_tradingagents: bool = True, include_news_engine: bool = True) -> "MultiSourceDataHub":
        from .providers import AShareProvider, FinancialDatasetsProvider, NewsEngineProvider, TradingAgentsProvider

        ashare = AShareProvider() if include_ashare else None
        financial = FinancialDatasetsProvider() if include_financial_datasets else None
        tradingagents = TradingAgentsProvider() if include_tradingagents else None
        search = NewsEngineProvider() if include_news_engine else None
        return cls(
            price_providers=[provider for provider in (ashare, financial, tradingagents) if provider],
            fundamentals_providers=[provider for provider in (ashare, financial, tradingagents) if provider],
            news_providers=[provider for provider in (search, ashare, financial, tradingagents) if provider],
            macro_providers=[provider for provider in (tradingagents,) if provider],
        )

    def prices(self, ticker: str, start_date: str, end_date: str, *, require_data: bool = True) -> DataBundle:
        return self._collect("prices", ticker, end_date, "get_prices", require_data, ticker, start_date, end_date)

    def fundamentals(self, ticker: str, as_of_date: str, *, require_data: bool = True) -> DataBundle:
        return self._collect("fundamentals", ticker, as_of_date, "get_fundamentals", require_data, ticker, as_of_date)

    def news(self, ticker: str, start_date: str, end_date: str, *, limit: int = 20, require_data: bool = True) -> DataBundle:
        return self._collect("news", ticker, end_date, "get_news", require_data, ticker, start_date, end_date, limit=limit)

    def macro(self, indicator: str, as_of_date: str, *, look_back_days: int = 365, require_data: bool = True) -> DataBundle:
        return self._collect("macro", None, as_of_date, "get_macro", require_data, indicator, as_of_date, look_back_days=look_back_days)

    def _collect(self, kind: DataKind, ticker: str | None, as_of_date: str, method: str, require_data: bool, *args: Any, **kwargs: Any) -> DataBundle:
        evidence: list[SourceEvidence] = []
        failures: list[SourceFailure] = []
        for provider in self._providers[kind]:
            try:
                item = getattr(provider, method)(*args, **kwargs)
                if item is not None:
                    evidence.append(item)
            except Exception as exc:  # independent sources must not block peers
                failure = SourceFailure(
                    provider=getattr(provider, "name", type(provider).__name__),
                    kind=kind,
                    error_type=getattr(exc, "error_type", type(exc).__name__),
                    message=str(exc),
                    retryable=getattr(exc, "retryable", None),
                )
                failures.append(failure)
                logger.warning(
                    "data source failed",
                    extra={"provider": failure.provider, "error_type": failure.error_type},
                )
        bundle = DataBundle(ticker, as_of_date, kind, tuple(evidence), tuple(failures))
        if require_data and not bundle.has_data:
            raise MultiSourceDataError(bundle)
        return bundle
