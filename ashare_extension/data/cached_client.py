"""Cache-aware facade for the A-share data provider.

Historical standard ``DataClient`` calls use the upstream JSON cache. Calls
whose end date is today or later bypass that non-expiring cache and rely on the
provider's SQLite TTL instead. A-share-only methods stay available on the same
object and share one force-refresh policy with both cache layers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from hedge_fund.data.cached import CachedDataClient

from .client import AShareDataClient
from .market_snapshot import SummaryLLM


class CachedAShareDataClient:
    """Compose A-share SQLite caching with the upstream historical cache."""

    def __init__(
        self,
        client: AShareDataClient | None = None,
        *,
        cache_dir: Path | str | None = None,
        refresh: bool = False,
        adjust: str = "qfq",
        llm_client: SummaryLLM | None = None,
    ) -> None:
        self._refresh = refresh
        self._client = client or AShareDataClient(
            adjust=adjust,
            llm_client=llm_client,
            force_refresh=refresh,
        )
        cache_kwargs: dict[str, Any] = {"refresh": refresh}
        if cache_dir is not None:
            cache_kwargs["cache_dir"] = cache_dir
        self._historical_cache = CachedDataClient(self._client, **cache_kwargs)

    @property
    def raw_client(self) -> AShareDataClient:
        return self._client

    def __enter__(self) -> "CachedAShareDataClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _use_historical_cache(
        self,
        end_date: str,
        force_refresh: bool = False,
    ) -> bool:
        cutoff = pd.to_datetime(end_date).normalize()
        return cutoff < pd.Timestamp.today().normalize() and not self._refresh and not force_refresh

    # Standard DataClient methods -------------------------------------------------

    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        interval: str = "day",
        interval_multiplier: int = 1,
        **kwargs: Any,
    ):
        force_refresh = bool(kwargs.pop("force_refresh", False))
        if self._use_historical_cache(end_date, force_refresh):
            return self._historical_cache.get_prices(
                ticker,
                start_date,
                end_date,
                interval,
                interval_multiplier,
            )
        return self._client.get_prices(
            ticker,
            start_date,
            end_date,
            interval=interval,
            interval_multiplier=interval_multiplier,
            force_refresh=self._refresh or force_refresh,
            **kwargs,
        )

    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
        *,
        force_refresh: bool = False,
    ):
        if self._use_historical_cache(end_date, force_refresh):
            return self._historical_cache.get_financial_metrics(
                ticker,
                end_date,
                period,
                limit,
            )
        return self._client.get_financial_metrics(
            ticker,
            end_date,
            period,
            limit,
            force_refresh=self._refresh or force_refresh,
        )

    def get_news(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
        *,
        force_refresh: bool = False,
    ):
        if self._use_historical_cache(end_date, force_refresh):
            return self._historical_cache.get_news(
                ticker,
                end_date,
                start_date,
                limit,
            )
        return self._client.get_news(
            ticker,
            end_date,
            start_date,
            limit,
            force_refresh=self._refresh or force_refresh,
        )

    def get_insider_trades(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
    ):
        return self._historical_cache.get_insider_trades(
            ticker,
            end_date,
            start_date,
            limit,
        )

    def get_company_facts(
        self,
        ticker: str,
        *,
        force_refresh: bool = False,
    ):
        if self._refresh or force_refresh:
            return self._client.get_company_facts(ticker, force_refresh=True)
        return self._historical_cache.get_company_facts(ticker)

    def get_earnings(self, ticker: str):
        return self._historical_cache.get_earnings(ticker)

    def get_earnings_history(self, ticker: str, limit: int = 12):
        return self._historical_cache.get_earnings_history(ticker, limit)

    def get_market_cap(
        self,
        ticker: str,
        end_date: str,
        *,
        force_refresh: bool = False,
    ):
        if self._use_historical_cache(end_date, force_refresh):
            return self._historical_cache.get_market_cap(ticker, end_date)
        return self._client.get_market_cap(
            ticker,
            end_date,
            force_refresh=self._refresh or force_refresh,
        )

    # A-share extension methods ---------------------------------------------------

    def get_realtime_quote(
        self,
        ticker: str,
        *,
        ttl_seconds: int = 600,
        force_refresh: bool = False,
    ):
        return self._client.get_realtime_quote(
            ticker,
            ttl_seconds=ttl_seconds,
            force_refresh=self._refresh or force_refresh,
        )

    def get_fund_flow(
        self,
        ticker: str,
        end_date: str | None = None,
        limit: int = 20,
        *,
        force_refresh: bool = False,
    ):
        return self._client.get_fund_flow(
            ticker,
            end_date,
            limit,
            force_refresh=self._refresh or force_refresh,
        )

    def get_financial_report(
        self,
        ticker: str,
        report_type: str,
        end_date: str | None = None,
        *,
        force_refresh: bool = False,
    ):
        return self._client.get_financial_report(
            ticker,
            report_type,
            end_date,
            force_refresh=self._refresh or force_refresh,
        )

    def get_financial_statements(
        self,
        ticker: str,
        end_date: str | None = None,
        *,
        force_refresh: bool = False,
    ):
        return self._client.get_financial_statements(
            ticker,
            end_date,
            force_refresh=self._refresh or force_refresh,
        )

    def get_stock_basic(
        self,
        ticker: str,
        *,
        force_refresh: bool = False,
    ):
        return self._client.get_stock_basic(
            ticker,
            force_refresh=self._refresh or force_refresh,
        )

    def get_market_snapshot(
        self,
        ticker: str,
        as_of_date: str | None = None,
        *,
        force_refresh: bool = False,
    ):
        return self._client.get_market_snapshot(
            ticker,
            as_of_date,
            force_refresh=self._refresh or force_refresh,
        )

    def get_csi300_analysis(
        self,
        as_of_date: str | None = None,
        *,
        force_refresh: bool = False,
        include_news: bool = True,
    ):
        return self._client.get_csi300_analysis(
            as_of_date,
            force_refresh=self._refresh or force_refresh,
            include_news=include_news,
        )


__all__ = ["CachedAShareDataClient"]
