from __future__ import annotations

from datetime import date

import pandas as pd

import ashare_extension.data.client as client_module
from ashare_extension.data.client import AShareDataClient


def test_historical_market_cap_never_reads_realtime_quote(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("historical market cap must not use a realtime quote")

    monkeypatch.setattr(client_module, "get_stock_spot_row", fail_if_called)

    assert AShareDataClient().get_market_cap("600519", "2020-01-31") is None


def test_current_market_cap_propagates_global_refresh(monkeypatch):
    calls: list[bool] = []

    def fake_spot(ticker, **kwargs):
        calls.append(kwargs["force_refresh"])
        return pd.Series({"总市值": 1_000_000.0})

    monkeypatch.setattr(client_module, "get_stock_spot_row", fake_spot)
    client = AShareDataClient(force_refresh=True)

    assert client.get_market_cap("600519", date.today().isoformat()) == 1_000_000.0
    assert calls == [True]


def test_realtime_quote_propagates_per_call_refresh(monkeypatch):
    calls: list[bool] = []

    def fake_spot(ticker, **kwargs):
        calls.append(kwargs["force_refresh"])
        return pd.Series({"代码": ticker, "最新价": 10.0})

    monkeypatch.setattr(client_module, "get_stock_spot_row", fake_spot)

    quote = AShareDataClient().get_realtime_quote(
        "600519",
        force_refresh=True,
    )

    assert quote is not None
    assert quote["最新价"] == 10.0
    assert calls == [True]


def test_prices_accepts_upstream_positional_interval_arguments(monkeypatch):
    calls: list[bool] = []

    def fake_history(*args, **kwargs):
        calls.append(kwargs["force_refresh"])
        return pd.DataFrame()

    monkeypatch.setattr(client_module, "get_price_history_df", fake_history)

    result = AShareDataClient().get_prices(
        "600519",
        "2020-01-01",
        "2020-01-31",
        "day",
        1,
    )

    assert result == []
    assert calls == [False]
