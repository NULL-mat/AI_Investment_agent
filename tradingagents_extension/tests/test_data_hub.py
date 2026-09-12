from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tradingagents_extension import (
    DataBundle,
    MultiSourceDataError,
    MultiSourceDataHub,
    SourceEvidence,
    TradingAgentsVendorError,
    TradingAgentsProvider,
)


def evidence(provider: str, kind: str = "prices") -> SourceEvidence:
    return SourceEvidence(
        provider=provider,
        kind=kind,
        ticker="600000",
        as_of_date="2026-09-10",
        payload={"provider_value": provider},
        retrieved_at=datetime.now(timezone.utc),
    )


class GoodProvider:
    name = "good"

    def get_prices(self, ticker, start_date, end_date):
        return evidence(self.name)


class BrokenProvider:
    name = "broken"

    def get_prices(self, ticker, start_date, end_date):
        raise TimeoutError("temporary upstream failure")


class EmptyProvider:
    name = "empty"

    def get_prices(self, ticker, start_date, end_date):
        return None


def test_hub_keeps_all_successful_sources_and_records_failures():
    bundle = MultiSourceDataHub(price_providers=(BrokenProvider(), GoodProvider())).prices(
        "600000", "2026-09-01", "2026-09-10"
    )
    assert isinstance(bundle, DataBundle)
    assert bundle.providers == ("good",)
    assert bundle.failures[0].provider == "broken"
    assert bundle.failures[0].error_type == "TimeoutError"


def test_all_sources_failed_is_explicit():
    with pytest.raises(MultiSourceDataError) as exc_info:
        MultiSourceDataHub(price_providers=(EmptyProvider(), BrokenProvider())).prices(
            "600000", "2026-09-01", "2026-09-10"
        )
    assert exc_info.value.bundle.has_data is False
    assert [failure.provider for failure in exc_info.value.bundle.failures] == ["broken"]


def test_require_data_false_allows_optional_empty_bundle():
    bundle = MultiSourceDataHub(price_providers=(EmptyProvider(),)).prices(
        "600000", "2026-09-01", "2026-09-10", require_data=False
    )
    assert bundle.has_data is False
    assert bundle.failures == ()


def test_tradingagents_adapter_keeps_vendor_identity_without_importing_graph(monkeypatch, tmp_path):
    checkout = tmp_path / "TradingAgents"
    (checkout / "tradingagents").mkdir(parents=True)
    (checkout / "tradingagents" / "__init__.py").write_text("", encoding="utf-8")
    provider = TradingAgentsProvider(checkout, stock_vendors=("yfinance", "alpha_vantage"))
    provider._load_interface = lambda: {
        "get_stock_data": {
            "yfinance": lambda ticker, start, end: "yf-data",
            "alpha_vantage": lambda ticker, start, end: "av-data",
        }
    }
    result = provider.get_prices("600000", "2026-09-01", "2026-09-10")
    assert result is not None
    assert result.provider == "tradingagents"
    assert result.metadata["vendors"] == ["yfinance", "alpha_vantage"]
    assert result.payload == {"yfinance": "yf-data", "alpha_vantage": "av-data"}


def test_tradingagents_vendor_failure_keeps_successful_peer(tmp_path):
    checkout = tmp_path / "TradingAgents"
    (checkout / "tradingagents").mkdir(parents=True)
    (checkout / "tradingagents" / "__init__.py").write_text("", encoding="utf-8")
    provider = TradingAgentsProvider(checkout, stock_vendors=("yfinance", "alpha_vantage"))

    def broken(*args):
        raise TimeoutError("temporary failure")

    provider._load_interface = lambda: {
        "get_stock_data": {
            "yfinance": broken,
            "alpha_vantage": lambda ticker, start, end: "av-data",
        }
    }
    result = provider.get_prices("600000", "2026-09-01", "2026-09-10")
    assert result is not None
    assert result.payload == {"alpha_vantage": "av-data"}
    assert result.metadata["vendor_failures"] == {"yfinance": "TimeoutError"}


def test_tradingagents_all_vendor_failures_are_explicit(tmp_path):
    checkout = tmp_path / "TradingAgents"
    (checkout / "tradingagents").mkdir(parents=True)
    (checkout / "tradingagents" / "__init__.py").write_text("", encoding="utf-8")
    provider = TradingAgentsProvider(checkout, stock_vendors=("yfinance",))
    provider._load_interface = lambda: {"get_stock_data": {"yfinance": lambda *args: "Error fetching prices"}}
    with pytest.raises(TradingAgentsVendorError, match="all vendors"):
        provider.get_prices("600000", "2026-09-01", "2026-09-10")


def test_tradingagents_json_error_response_is_not_evidence(tmp_path):
    checkout = tmp_path / "TradingAgents"
    (checkout / "tradingagents").mkdir(parents=True)
    (checkout / "tradingagents" / "__init__.py").write_text("", encoding="utf-8")
    provider = TradingAgentsProvider(checkout, stock_vendors=("alpha_vantage",))
    provider._load_interface = lambda: {
        "get_stock_data": {"alpha_vantage": lambda *args: '{"Error Message":"invalid symbol"}'}
    }
    with pytest.raises(TradingAgentsVendorError):
        provider.get_prices("BAD", "2026-09-01", "2026-09-10")


def test_tradingagents_news_applies_requested_limit(tmp_path):
    checkout = tmp_path / "TradingAgents"
    (checkout / "tradingagents").mkdir(parents=True)
    (checkout / "tradingagents" / "__init__.py").write_text("", encoding="utf-8")
    provider = TradingAgentsProvider(checkout, news_vendors=("yfinance",))
    provider._load_interface = lambda: {
        "get_news": {
            "yfinance": lambda ticker, start, end: "## News\n\n### first\nbody\n\n### second\nbody\n"
        }
    }
    result = provider.get_news("AAPL", "2026-09-01", "2026-09-10", limit=1)
    assert result is not None
    assert "### first" in result.payload["yfinance"]
    assert "### second" not in result.payload["yfinance"]
    assert result.metadata["requested_limit"] == 1


def test_tradingagents_fundamentals_pass_vendor_to_each_operation(tmp_path):
    checkout = tmp_path / "TradingAgents"
    (checkout / "tradingagents").mkdir(parents=True)
    (checkout / "tradingagents" / "__init__.py").write_text("", encoding="utf-8")
    provider = TradingAgentsProvider(checkout, fundamental_vendors=("yfinance",))
    calls = []

    def operation(*args):
        calls.append(args)
        return "usable"

    provider._load_interface = lambda: {
        "get_fundamentals": {"yfinance": operation},
        "get_balance_sheet": {"yfinance": operation},
        "get_cashflow": {"yfinance": operation},
        "get_income_statement": {"yfinance": operation},
    }
    result = provider.get_fundamentals("AAPL", "2026-09-10")
    assert result is not None
    assert result.payload["yfinance"]["overview"] == "usable"
    assert calls == [
        ("AAPL", "2026-09-10"),
        ("AAPL", "quarterly", "2026-09-10"),
        ("AAPL", "quarterly", "2026-09-10"),
        ("AAPL", "quarterly", "2026-09-10"),
    ]
