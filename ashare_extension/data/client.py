"""Adapter exposing A-share data through ``hedge_fund.data.protocol``.

The provider functions are migrated from ``A_Share_investment_Agent`` and are
kept in sibling modules.  This file only translates their DataFrames into the
upstream project's Pydantic models, so the original ``hedge_fund`` package does
not need A-share-specific changes.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from hedge_fund.data.models import (
    CompanyFacts,
    CompanyNews,
    Earnings,
    EarningsRecord,
    FinancialMetrics,
    InsiderTrade,
    Price,
)

from .akshare_cache import (
    get_financial_indicators,
    get_financial_report as _get_financial_report,
    get_fund_flow as _get_fund_flow,
    get_price_history_df,
    get_stock_news,
    get_stock_spot_row,
    get_ttm_revenue,
)
from .market_analysis import get_csi300_analysis as _get_csi300_analysis
from .market_snapshot import SummaryLLM, get_market_snapshot as _get_market_snapshot
from .stock_basic import get_stock_basic as _get_stock_basic
from .stock_basic import get_stock_name


REPORT_BALANCE_SHEET = "资产负债表"
REPORT_INCOME_STATEMENT = "利润表"
REPORT_CASH_FLOW = "现金流量表"


def _text(value: Any, default: str = "") -> str:
    if value is None or pd.isna(value):
        return default
    return str(value)


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        try:
            result = float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return None
    return result if pd.notna(result) else None


def _date_string(value: Any) -> str:
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.strftime("%Y-%m-%d")
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.strftime("%Y-%m-%d") if pd.notna(parsed) else _text(value)


def _column(row: pd.Series, *names: str) -> Any:
    for name in names:
        if name in row.index:
            return row[name]
    return None


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in frame.to_dict("records"):
        clean: dict[str, Any] = {}
        for key, value in record.items():
            if isinstance(value, (datetime, date, pd.Timestamp)):
                clean[key] = _date_string(value)
            elif value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
                clean[key] = None
            elif hasattr(value, "item"):
                clean[key] = value.item()
            else:
                clean[key] = value
        result.append(clean)
    return result


class AShareDataClient:
    """A-share implementation of the upstream ``DataClient`` protocol."""

    def __init__(
        self,
        *,
        adjust: str = "qfq",
        llm_client: SummaryLLM | None = None,
        force_refresh: bool = False,
    ) -> None:
        self.adjust = adjust
        self.llm_client = llm_client
        self.force_refresh = force_refresh

    def _refresh(self, requested: bool = False) -> bool:
        return self.force_refresh or requested

    def __enter__(self) -> "AShareDataClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        """Compatibility hook; provider caches use short-lived SQLite connections."""

    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        interval: str = "day",
        interval_multiplier: int = 1,
        **kwargs: Any,
    ) -> list[Price]:
        if interval != "day" or interval_multiplier != 1:
            raise ValueError("AShareDataClient currently supports only one-day price bars")
        adjust = kwargs.get("adjust", self.adjust)
        adjust = "" if adjust == "none" else adjust
        frame = get_price_history_df(
            ticker,
            pd.to_datetime(start_date).to_pydatetime(),
            pd.to_datetime(end_date).to_pydatetime(),
            adjust=adjust,
            force_refresh=self._refresh(bool(kwargs.get("force_refresh", False))),
        )
        if frame.empty:
            return []
        prices: list[Price] = []
        for _, row in frame.iterrows():
            volume = _float(row.get("volume")) or 0.0
            prices.append(
                Price(
                    open=float(row["open"]),
                    close=float(row["close"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    volume=int(volume),
                    time=_date_string(row["date"]),
                )
            )
        return prices

    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
        *,
        force_refresh: bool = False,
    ) -> list[FinancialMetrics]:
        refresh = self._refresh(force_refresh)
        cutoff = pd.to_datetime(end_date)
        frame = get_financial_indicators(
            ticker,
            start_year=str(max(1990, cutoff.year - 5)),
            force_refresh=refresh,
        )
        if frame.empty:
            return []
        if "日期" in frame.columns:
            frame = frame.copy()
            frame["日期"] = pd.to_datetime(frame["日期"], errors="coerce")
            frame = frame[frame["日期"].notna() & (frame["日期"] <= cutoff)]
            frame = frame.sort_values("日期", ascending=False)
        use_realtime = cutoff.normalize() >= pd.Timestamp.today().normalize()
        spot = get_stock_spot_row(ticker, force_refresh=refresh) if use_realtime else None
        market_cap = _float(_column(spot, "总市值", "market_cap")) if spot is not None else None
        pe_ratio = _float(_column(spot, "市盈率-动态", "市盈率")) if spot is not None else None
        price_to_book = _float(_column(spot, "市净率")) if spot is not None else None
        total_revenue = get_ttm_revenue(ticker, end_date, force_refresh=refresh)
        price_to_sales = market_cap / total_revenue if market_cap and total_revenue and total_revenue > 0 else None
        rows: list[FinancialMetrics] = []
        for _, row in frame.head(max(0, limit)).iterrows():

            def pct(*names: str) -> float | None:
                value = _float(_column(row, *names))
                return value / 100 if value is not None else None

            rows.append(
                FinancialMetrics(
                    ticker=ticker,
                    report_period=_date_string(_column(row, "日期")),
                    period=period,
                    currency="CNY",
                    market_cap=market_cap,
                    price_to_earnings_ratio=pe_ratio,
                    price_to_book_ratio=price_to_book,
                    price_to_sales_ratio=price_to_sales,
                    return_on_equity=pct("净资产收益率(%)"),
                    net_margin=pct("销售净利率(%)"),
                    operating_margin=pct("营业利润率(%)"),
                    revenue_growth=pct("主营业务收入增长率(%)"),
                    earnings_growth=pct("净利润增长率(%)"),
                    book_value_growth=pct("净资产增长率(%)"),
                    current_ratio=_float(_column(row, "流动比率")),
                    debt_to_assets=pct("资产负债率(%)"),
                    free_cash_flow_per_share=_float(_column(row, "每股经营性现金流(元)")),
                    earnings_per_share=_float(_column(row, "加权每股收益(元)", "每股收益")),
                )
            )
        return rows

    def get_market_cap(
        self,
        ticker: str,
        end_date: str,
        *,
        force_refresh: bool = False,
    ) -> float | None:
        cutoff = pd.to_datetime(end_date).normalize()
        if cutoff < pd.Timestamp.today().normalize():
            return None
        row = get_stock_spot_row(
            ticker,
            force_refresh=self._refresh(force_refresh),
        )
        return _float(_column(row, "总市值", "market_cap")) if row is not None else None

    def get_realtime_quote(
        self,
        ticker: str,
        *,
        ttl_seconds: int = 600,
        force_refresh: bool = False,
    ) -> dict[str, Any] | None:
        row = get_stock_spot_row(
            ticker,
            ttl_seconds=ttl_seconds,
            force_refresh=self._refresh(force_refresh),
        )
        return _records(row.to_frame().T)[0] if row is not None else None

    def get_fund_flow(
        self,
        ticker: str,
        end_date: str | None = None,
        limit: int = 20,
        *,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        frame = _get_fund_flow(
            ticker,
            force_refresh=self._refresh(force_refresh),
        )
        if frame.empty:
            return []
        frame = frame.copy()
        if "日期" in frame:
            frame["日期"] = pd.to_datetime(frame["日期"], errors="coerce")
            if end_date:
                frame = frame[frame["日期"].notna() & (frame["日期"] <= pd.to_datetime(end_date))]
            frame = frame.sort_values("日期", ascending=False)
        return _records(frame.head(max(0, limit)))

    def get_financial_report(
        self,
        ticker: str,
        report_type: str,
        end_date: str | None = None,
        *,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        frame = _get_financial_report(
            ticker,
            report_type,
            force_refresh=self._refresh(force_refresh),
        )
        if frame.empty:
            return []
        frame = frame.copy()
        report_col = next((name for name in ("报告日", "日期") if name in frame), None)
        if report_col:
            frame[report_col] = pd.to_datetime(frame[report_col], errors="coerce")
            if end_date:
                frame = frame[frame[report_col].notna() & (frame[report_col] <= pd.to_datetime(end_date))]
            frame = frame.sort_values(report_col, ascending=False)
        return _records(frame)

    def get_financial_statements(
        self,
        ticker: str,
        end_date: str | None = None,
        *,
        force_refresh: bool = False,
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "balance_sheet": self.get_financial_report(
                ticker,
                REPORT_BALANCE_SHEET,
                end_date,
                force_refresh=self._refresh(force_refresh),
            ),
            "income_statement": self.get_financial_report(
                ticker,
                REPORT_INCOME_STATEMENT,
                end_date,
                force_refresh=self._refresh(force_refresh),
            ),
            "cash_flow_statement": self.get_financial_report(
                ticker,
                REPORT_CASH_FLOW,
                end_date,
                force_refresh=self._refresh(force_refresh),
            ),
        }

    def get_stock_basic(
        self,
        ticker: str,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any] | None:
        return _get_stock_basic(
            ticker,
            force_refresh=self._refresh(force_refresh),
        )

    def get_market_snapshot(
        self,
        ticker: str,
        as_of_date: str | None = None,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        return _get_market_snapshot(
            ticker,
            as_of_date=as_of_date,
            force_refresh=self._refresh(force_refresh),
            llm_client=self.llm_client,
        )

    def get_csi300_analysis(
        self,
        as_of_date: str | None = None,
        *,
        force_refresh: bool = False,
        include_news: bool = True,
    ) -> dict[str, Any]:
        return _get_csi300_analysis(
            as_of_date=as_of_date,
            force_refresh=self._refresh(force_refresh),
            include_news=include_news,
            llm_client=self.llm_client,
        )

    def get_news(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
        *,
        force_refresh: bool = False,
    ) -> list[CompanyNews]:
        frame = get_stock_news(
            ticker,
            date=end_date,
            force_refresh=self._refresh(force_refresh),
        )
        if frame.empty:
            return []
        date_col = next((c for c in ("发布时间", "日期", "date") if c in frame), None)
        if date_col:
            dates = pd.to_datetime(frame[date_col], errors="coerce")
            # Compare calendar days so an end date includes all timestamps on that day.
            frame = frame[dates.notna() & (dates.dt.normalize() <= pd.to_datetime(end_date).normalize())]
            if start_date:
                frame = frame[dates.notna() & (dates.dt.normalize() >= pd.to_datetime(start_date).normalize())]
        title_col = next((c for c in ("新闻标题", "标题", "title") if c in frame), None)
        source_col = next((c for c in ("文章来源", "来源", "source") if c in frame), None)
        url_col = next((c for c in ("新闻链接", "链接", "url") if c in frame), None)
        result: list[CompanyNews] = []
        for _, row in frame.head(max(0, limit)).iterrows():
            result.append(
                CompanyNews(
                    ticker=ticker,
                    title=_text(row[title_col]) if title_col else "",
                    source=_text(row[source_col], "AkShare") if source_col else "AkShare",
                    date=_date_string(row[date_col]) if date_col else None,
                    url=_text(row[url_col]) if url_col else None,
                )
            )
        return result

    def get_company_facts(
        self,
        ticker: str,
        *,
        force_refresh: bool = False,
    ) -> CompanyFacts | None:
        name = get_stock_name(
            ticker,
            force_refresh=self._refresh(force_refresh),
        )
        if not name:
            return None
        lowered = ticker.strip().lower()
        if lowered.startswith(("4", "8", "bj")):
            exchange = "BSE"
        elif lowered.startswith(("5", "6", "9", "sh")) or lowered in {
            "000300",
            "沪深300",
            "沪深300指数",
            "csi300",
        }:
            exchange = "SSE"
        else:
            exchange = "SZSE"
        return CompanyFacts(ticker=ticker, name=name, exchange=exchange, is_active=True, location="China")

    def get_insider_trades(self, ticker: str, end_date: str, start_date: str | None = None, limit: int = 1000) -> list[InsiderTrade]:
        return []

    def get_earnings(self, ticker: str) -> Earnings | None:
        return None

    def get_earnings_history(self, ticker: str, limit: int = 12) -> list[EarningsRecord]:
        return []


__all__ = ["AShareDataClient"]
