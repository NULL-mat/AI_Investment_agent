"""Adapters for current project and TradingAgents data providers."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping

from .models import DataKind, SourceEvidence


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serializable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serializable(item) for item in value]
    if isinstance(value, tuple):
        return [_serializable(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _serializable(item) for key, item in value.items()}
    return value


def _is_empty_payload(payload: Any) -> bool:
    """Detect empty provider results without invoking ambiguous truthiness."""
    if payload is None:
        return True
    if isinstance(payload, str):
        return not payload.strip()
    if isinstance(payload, Mapping):
        return not payload or all(_is_empty_payload(item) for item in payload.values())
    if isinstance(payload, (list, tuple, set, frozenset)):
        return not payload or all(_is_empty_payload(item) for item in payload)
    # pandas objects expose ``empty`` but deliberately reject ``bool(frame)``.
    empty = getattr(payload, "empty", None)
    if empty is not None:
        try:
            return bool(empty)
        except (TypeError, ValueError):
            pass
    return False


def _is_error_payload(payload: Any) -> bool:
    """Recognize error sentinels returned as strings by TradingAgents dataflows."""
    if not isinstance(payload, str):
        return False
    normalized = payload.lstrip().upper()
    if normalized.startswith(("ERROR ", "ERROR:", "DATA_UNAVAILABLE:")):
        return True
    if normalized.startswith("{"):
        try:
            response = json.loads(payload)
        except (TypeError, ValueError):
            return False
        if isinstance(response, Mapping):
            return any(
                key.lower() in {"error", "error message", "error_message", "information"}
                for key in response
            )
    return False


def _is_no_data_payload(payload: Any) -> bool:
    """Recognize explicit no-data responses as normal empty results."""
    if not isinstance(payload, str):
        return False
    normalized = payload.lstrip().upper()
    return normalized.startswith(("NO_DATA_AVAILABLE:", "NO NEWS FOUND", "NO GLOBAL NEWS FOUND"))


def _limit_news_payload(payload: Any, limit: int) -> Any:
    """Apply the common article limit to the result shapes used by vendors."""
    if limit < 1:
        raise ValueError("news limit must be at least 1")
    if isinstance(payload, (list, tuple)):
        return payload[:limit]
    if isinstance(payload, Mapping):
        # Alpha Vantage returns an object whose ``feed`` member is the article list.
        feed = payload.get("feed")
        if isinstance(feed, (list, tuple)):
            return {**payload, "feed": feed[:limit]}
        return payload
    if isinstance(payload, str):
        # yfinance returns markdown. Preserve its report header and first N article sections.
        sections = payload.split("\n### ")
        if len(sections) > 1:
            return sections[0] + "".join(f"\n### {section}" for section in sections[1 : limit + 1])
    return payload


class TradingAgentsVendorError(RuntimeError):
    """Raised when every selected TradingAgents vendor fails for an operation."""

    error_type = "tradingagents_vendor_failure"
    retryable = True

    def __init__(self, method: str, failures: Mapping[str, Exception]) -> None:
        self.method = method
        self.failures = dict(failures)
        details = "; ".join(
            f"{vendor}: {type(error).__name__}: {error}"
            for vendor, error in self.failures.items()
        )
        super().__init__(f"TradingAgents {method} failed for all vendors: {details}")


def _evidence(provider: str, kind: DataKind, ticker: str | None, as_of_date: str, payload: Any, **metadata: Any) -> SourceEvidence | None:
    if _is_empty_payload(payload):
        return None
    return SourceEvidence(provider, kind, ticker, as_of_date, _serializable(payload), _now(), metadata)


class AShareProvider:
    """Expose the current A-share client as source-aware evidence."""

    name = "ashare"

    def __init__(self, client: AShareDataClient | None = None) -> None:
        if client is None:
            from ashare_extension import AShareDataClient

            client = AShareDataClient()
        self.client = client

    def get_prices(self, ticker: str, start_date: str, end_date: str) -> SourceEvidence | None:
        return _evidence(self.name, "prices", ticker, end_date, self.client.get_prices(ticker, start_date, end_date))

    def get_fundamentals(self, ticker: str, as_of_date: str) -> SourceEvidence | None:
        payload = {
            "company": self.client.get_company_facts(ticker),
            "metrics": self.client.get_financial_metrics(ticker, as_of_date),
            "statements": self.client.get_financial_statements(ticker, as_of_date),
        }
        return _evidence(self.name, "fundamentals", ticker, as_of_date, payload)

    def get_news(self, ticker: str, start_date: str, end_date: str, *, limit: int) -> SourceEvidence | None:
        return _evidence(self.name, "news", ticker, end_date, self.client.get_news(ticker, end_date, start_date, limit))


class FinancialDatasetsProvider:
    """Expose the existing Financial Datasets client without changing it."""

    name = "financial_datasets"

    def __init__(self, client: FDClient | None = None) -> None:
        if client is None:
            from hedge_fund.data.client import FDClient

            client = FDClient()
        self.client = client

    def get_prices(self, ticker: str, start_date: str, end_date: str) -> SourceEvidence | None:
        return _evidence(self.name, "prices", ticker, end_date, self.client.get_prices(ticker, start_date, end_date))

    def get_fundamentals(self, ticker: str, as_of_date: str) -> SourceEvidence | None:
        payload = {
            "company": self.client.get_company_facts(ticker),
            "metrics": self.client.get_financial_metrics(ticker, as_of_date),
            "earnings": self.client.get_earnings_history(ticker),
            "insider_trades": self.client.get_insider_trades(ticker, as_of_date),
        }
        return _evidence(self.name, "fundamentals", ticker, as_of_date, payload)

    def get_news(self, ticker: str, start_date: str, end_date: str, *, limit: int) -> SourceEvidence | None:
        return _evidence(self.name, "news", ticker, end_date, self.client.get_news(ticker, end_date, start_date, limit))


class NewsEngineProvider:
    """Expose normalized Tavily/fallback News Engine evidence."""

    name = "news_engine"

    def __init__(self, engine: NewsEngine | None = None) -> None:
        if engine is None:
            from news import NewsEngine

            engine = NewsEngine()
        self.engine = engine

    def get_news(self, ticker: str, start_date: str, end_date: str, *, limit: int) -> SourceEvidence | None:
        spec = NewsQuerySpec(ticker=ticker, start_date=start_date, end_date=end_date, max_results=limit)
        return _evidence(self.name, "news", ticker, end_date, self.engine.search(spec), query=self.engine.query_builder.build(spec))


class TradingAgentsProvider:
    """Use TradingAgents dataflows as optional providers, without vendoring them.

    The adapter loads the sibling checkout lazily. Missing optional dependencies
    therefore disable only this source and do not prevent the main application
    or A-share data layer from importing.
    """

    name = "tradingagents"

    def __init__(
        self,
        checkout: str | Path | None = None,
        *,
        stock_vendors: tuple[str, ...] = ("yfinance", "alpha_vantage"),
        fundamental_vendors: tuple[str, ...] = ("yfinance", "alpha_vantage"),
        news_vendors: tuple[str, ...] = ("yfinance", "alpha_vantage"),
    ) -> None:
        self.checkout = Path(checkout or Path(__file__).resolve().parents[1] / "TradingAgents")
        self.stock_vendors = stock_vendors
        self.fundamental_vendors = fundamental_vendors
        self.news_vendors = news_vendors

    def _load_interface(self):
        if not (self.checkout / "tradingagents" / "__init__.py").exists():
            raise RuntimeError(f"TradingAgents checkout not found: {self.checkout}")
        checkout = str(self.checkout)
        if checkout not in sys.path:
            sys.path.insert(0, checkout)
        from tradingagents.dataflows.interface import VENDOR_METHODS

        return VENDOR_METHODS

    def _call(self, method: str, vendor: str, *args: Any) -> Any:
        methods = self._load_interface()
        try:
            operation: Callable[..., Any] = methods[method][vendor]
        except KeyError as exc:
            raise ValueError(f"TradingAgents vendor {vendor!r} does not support {method!r}") from exc
        return operation(*args)

    def _collect(self, kind: DataKind, ticker: str | None, as_of_date: str, method: str, vendors: tuple[str, ...], *args: Any) -> SourceEvidence | None:
        results: dict[str, Any] = {}
        failures: dict[str, Exception] = {}
        empty_vendors: list[str] = []
        for vendor in vendors:
            try:
                payload = self._call(method, vendor, *args)
                if _is_error_payload(payload):
                    raise RuntimeError(payload)
                if _is_no_data_payload(payload) or _is_empty_payload(payload):
                    empty_vendors.append(vendor)
                    continue
                results[vendor] = payload
            except Exception as exc:
                failures[vendor] = exc
        if not results:
            if failures:
                raise TradingAgentsVendorError(method, failures)
            return None
        return _evidence(
            self.name,
            kind,
            ticker,
            as_of_date,
            results,
            vendors=list(vendors),
            empty_vendors=empty_vendors,
            vendor_failures={vendor: type(error).__name__ for vendor, error in failures.items()},
        )

    def get_prices(self, ticker: str, start_date: str, end_date: str) -> SourceEvidence | None:
        return self._collect("prices", ticker, end_date, "get_stock_data", self.stock_vendors, ticker, start_date, end_date)

    def get_fundamentals(self, ticker: str, as_of_date: str) -> SourceEvidence | None:
        reports: dict[str, dict[str, Any]] = {}
        failures: dict[str, Exception] = {}
        empty_vendors: list[str] = []
        for vendor in self.fundamental_vendors:
            report: dict[str, Any] = {}
            vendor_failures: dict[str, str] = {}
            for operation, operation_args in (
                ("overview", ("get_fundamentals", vendor, ticker, as_of_date)),
                ("balance_sheet", ("get_balance_sheet", vendor, ticker, "quarterly", as_of_date)),
                ("cashflow", ("get_cashflow", vendor, ticker, "quarterly", as_of_date)),
                ("income_statement", ("get_income_statement", vendor, ticker, "quarterly", as_of_date)),
            ):
                try:
                    payload = self._call(*operation_args)
                    if _is_error_payload(payload):
                        raise RuntimeError(payload)
                    if not _is_no_data_payload(payload) and not _is_empty_payload(payload):
                        report[operation] = payload
                except Exception as exc:
                    vendor_failures[operation] = type(exc).__name__
            if report:
                reports[vendor] = report
            elif vendor_failures:
                failures[vendor] = RuntimeError(
                    ", ".join(f"{operation}: {error_type}" for operation, error_type in vendor_failures.items())
                )
            else:
                empty_vendors.append(vendor)
        if not reports:
            if failures:
                raise TradingAgentsVendorError("fundamentals", failures)
            return None
        return _evidence(
            self.name,
            "fundamentals",
            ticker,
            as_of_date,
            reports,
            vendors=list(self.fundamental_vendors),
            empty_vendors=empty_vendors,
            vendor_failures={vendor: type(error).__name__ for vendor, error in failures.items()},
        )

    def get_news(self, ticker: str, start_date: str, end_date: str, *, limit: int) -> SourceEvidence | None:
        result = self._collect("news", ticker, end_date, "get_news", self.news_vendors, ticker, start_date, end_date)
        if result is None:
            return None
        limited = {vendor: _limit_news_payload(payload, limit) for vendor, payload in result.payload.items()}
        return replace(
            result,
            payload=limited,
            metadata={**result.metadata, "requested_limit": limit},
        )

    def get_macro(self, indicator: str, as_of_date: str, *, look_back_days: int) -> SourceEvidence | None:
        payload = self._call("get_macro_indicators", "fred", indicator, as_of_date, look_back_days)
        return _evidence(self.name, "macro", None, as_of_date, {"fred": payload}, indicator=indicator)
