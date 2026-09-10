from __future__ import annotations

from datetime import date

from hedge_fund.data.models import Price
from hedge_fund.data.protocol import DataClient

from ashare_extension.data.cached_client import CachedAShareDataClient


class StubAShareClient:
    def __init__(self) -> None:
        self.price_calls = 0
        self.snapshot_refresh_values: list[bool] = []

    def close(self) -> None:
        pass

    def get_prices(
        self,
        ticker,
        start_date,
        end_date,
        interval="day",
        interval_multiplier=1,
        **kwargs,
    ):
        self.price_calls += 1
        return [
            Price(
                open=1.0,
                close=2.0,
                high=2.0,
                low=1.0,
                volume=100,
                time=start_date,
            )
        ]

    def get_financial_metrics(self, ticker, end_date, period="ttm", limit=10, **kwargs):
        return []

    def get_news(self, ticker, end_date, start_date=None, limit=1000, **kwargs):
        return []

    def get_insider_trades(self, ticker, end_date, start_date=None, limit=1000):
        return []

    def get_company_facts(self, ticker, **kwargs):
        return None

    def get_earnings(self, ticker):
        return None

    def get_earnings_history(self, ticker, limit=12):
        return []

    def get_market_cap(self, ticker, end_date, **kwargs):
        return None

    def get_market_snapshot(self, ticker, as_of_date=None, *, force_refresh=False):
        self.snapshot_refresh_values.append(force_refresh)
        return {"symbol": ticker, "cache_date": as_of_date}


def test_historical_standard_calls_use_json_cache(tmp_path):
    raw = StubAShareClient()
    client = CachedAShareDataClient(raw, cache_dir=tmp_path)

    first = client.get_prices("600519", "2020-01-01", "2020-01-31")
    second = client.get_prices("600519", "2020-01-01", "2020-01-31")

    assert isinstance(client, DataClient)
    assert raw.price_calls == 1
    assert second[0].close == first[0].close


def test_current_standard_calls_bypass_non_expiring_json_cache(tmp_path):
    raw = StubAShareClient()
    client = CachedAShareDataClient(raw, cache_dir=tmp_path)
    today = date.today().isoformat()

    client.get_prices("600519", today, today)
    client.get_prices("600519", today, today)

    assert raw.price_calls == 2
    assert list(tmp_path.glob("*.json")) == []


def test_global_refresh_reaches_extension_methods(tmp_path):
    raw = StubAShareClient()
    client = CachedAShareDataClient(raw, cache_dir=tmp_path, refresh=True)

    result = client.get_market_snapshot("600519", "2020-01-31")

    assert result["symbol"] == "600519"
    assert raw.snapshot_refresh_values == [True]
