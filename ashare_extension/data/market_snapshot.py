"""Unified A-share quote, valuation, capital-flow, and history snapshot.

The cache layout and public ``get_market_snapshot`` entry are migrated from
``A_Share_investment_Agent``. Numeric fields come from AkShare/BaoStock rather
than being estimated by an LLM; an optional LLM is used only for the summary.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
from typing import Any, Protocol

import pandas as pd

from .akshare_cache import (
    CACHE_PATH,
    get_fund_flow,
    get_price_history_df,
    get_stock_news,
    get_stock_spot_row,
    get_ttm_revenue,
)
from .baostock_client import format_symbol
from .sqlite_cache import AkshareSQLiteCache
from .stock_basic import get_stock_name


SNAPSHOT_TABLE = "market_snapshot_cache"
SNAPSHOT_TTL_SECONDS = 24 * 3600
CSI300_CODE = "000300"
CSI300_NAME = "沪深300指数"

logger = logging.getLogger("ashare_extension.market_snapshot")
cache = AkshareSQLiteCache(CACHE_PATH)


class SummaryLLM(Protocol):
    def complete(self, system: str, user: str) -> str: ...  # noqa: E704


def normalize_symbol(symbol: str) -> str:
    """Return the six-digit code accepted by AkShare endpoints."""
    return format_symbol(symbol).split(".", 1)[1]


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if pd.notna(parsed) else None


def _value(row: pd.Series | None, *names: str) -> Any:
    if row is None:
        return None
    for name in names:
        if name in row.index:
            return row[name]
    return None


def _latest_before(
    frame: pd.DataFrame,
    as_of_date: str,
    *date_columns: str,
) -> pd.Series | None:
    if frame is None or frame.empty:
        return None
    date_column = next((name for name in date_columns if name in frame.columns), None)
    if date_column is None:
        return frame.iloc[-1]
    work = frame.copy()
    work[date_column] = pd.to_datetime(work[date_column], errors="coerce")
    cutoff = pd.to_datetime(as_of_date).normalize() + pd.Timedelta(days=1)
    work = work[work[date_column].notna() & (work[date_column] < cutoff)]
    if work.empty:
        return None
    return work.sort_values(date_column).iloc[-1]


def _price_to_sales(
    symbol: str,
    as_of_date: str,
    market_cap: float | None,
    *,
    force_refresh: bool = False,
) -> float | None:
    if not market_cap:
        return None
    revenue = get_ttm_revenue(symbol, as_of_date, force_refresh=force_refresh)
    return market_cap / revenue if revenue and revenue > 0 else None


def _numeric_summary(snapshot: dict[str, Any]) -> str:
    name = snapshot["name"]
    latest = snapshot.get("latest_price")
    change = snapshot.get("change_pct")
    price_text = "暂无最新价格" if latest is None else f"最新价 {latest:.2f}"
    change_text = "" if change is None else f"，涨跌幅 {change:.2f}%"
    flow = snapshot.get("main_net_inflow")
    flow_text = "" if flow is None else f"，主力净流入 {flow:,.0f} 元"
    return f"{name}（{snapshot['symbol']}）{price_text}{change_text}{flow_text}。"


def _llm_summary(
    snapshot: dict[str, Any],
    llm_client: SummaryLLM,
    news_items: list[dict[str, Any]],
) -> str:
    system = "你是中国A股市场数据分析师。只能根据给定的真实数值和新闻，" "用一到两句中文总结当前市场状态；不要修改、猜测或补充数值。"
    payload = {
        "market_data": snapshot,
        "news": news_items[:10],
    }
    return str(llm_client.complete(system, json.dumps(payload, ensure_ascii=False))).strip()


def get_market_snapshot(
    symbol: str,
    ttl_seconds: int = SNAPSHOT_TTL_SECONDS,
    *,
    as_of_date: str | None = None,
    force_refresh: bool = False,
    llm_client: SummaryLLM | None = None,
) -> dict[str, Any]:
    """Build one cacheable snapshot from real A-share market data."""
    code = normalize_symbol(symbol)
    today = datetime.now().strftime("%Y-%m-%d")
    cache_date = pd.to_datetime(as_of_date or today).strftime("%Y-%m-%d")
    effective_ttl = ttl_seconds if cache_date == today else None

    if not force_refresh and llm_client is None:
        cached = cache.fetch_records(
            SNAPSHOT_TABLE,
            filters={"symbol": code, "cache_date": cache_date},
            ttl_seconds=effective_ttl,
            limit=1,
        )
        if cached:
            result = dict(cached[0])
            result.pop("缓存时间", None)
            return result

    end = pd.to_datetime(cache_date).to_pydatetime()
    start = end - timedelta(days=370)
    history = get_price_history_df(
        code,
        start,
        end,
        adjust="" if code == CSI300_CODE else "qfq",
        force_refresh=force_refresh,
    )
    if not history.empty:
        history = history.sort_values("date")
    latest_history = history.iloc[-1] if not history.empty else None
    previous_history = history.iloc[-2] if len(history) > 1 else None

    is_index = code == CSI300_CODE
    spot = None
    if not is_index and cache_date == today:
        spot = get_stock_spot_row(
            code,
            ttl_seconds=ttl_seconds,
            force_refresh=force_refresh,
        )

    if latest_history is None and spot is None:
        raise RuntimeError(f"No market data available for {code} on or before {cache_date}")

    latest_price = _float(_value(spot, "最新价")) or _float(_value(latest_history, "close"))
    open_price = _float(_value(spot, "今开")) or _float(_value(latest_history, "open"))
    high_price = _float(_value(spot, "最高")) or _float(_value(latest_history, "high"))
    low_price = _float(_value(spot, "最低")) or _float(_value(latest_history, "low"))
    previous_close = _float(_value(spot, "昨收")) or _float(_value(previous_history, "close"))
    change_amount = _float(_value(spot, "涨跌额"))
    change_pct = _float(_value(spot, "涨跌幅"))
    if change_amount is None and latest_price is not None and previous_close is not None:
        change_amount = latest_price - previous_close
    if change_pct is None and change_amount is not None and previous_close:
        change_pct = change_amount / previous_close * 100

    recent = history.tail(252) if not history.empty else history
    volume = _float(_value(spot, "成交量")) or _float(_value(latest_history, "volume"))
    amount = _float(_value(spot, "成交额")) or _float(_value(latest_history, "amount"))
    average_volume = _float(recent.tail(5)["volume"].mean()) if not recent.empty else None
    fifty_two_week_high = _float(recent["high"].max()) if not recent.empty else high_price
    fifty_two_week_low = _float(recent["low"].min()) if not recent.empty else low_price

    market_cap = _float(_value(spot, "总市值", "market_cap"))
    float_market_cap = _float(_value(spot, "流通市值"))
    pe_ratio = _float(_value(spot, "市盈率-动态", "市盈率"))
    price_to_book = _float(_value(spot, "市净率"))
    price_to_sales = (
        None
        if is_index
        else _price_to_sales(
            code,
            cache_date,
            market_cap,
            force_refresh=force_refresh,
        )
    )

    flow_row = None
    if not is_index:
        fund_flow = get_fund_flow(code, force_refresh=force_refresh)
        flow_row = _latest_before(fund_flow, cache_date, "日期")

    name = CSI300_NAME if is_index else (get_stock_name(code, force_refresh=force_refresh) or code)
    snapshot: dict[str, Any] = {
        "symbol": code,
        "name": name,
        "cache_date": cache_date,
        "latest_price": latest_price,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "previous_close": previous_close,
        "change_amount": change_amount,
        "change_pct": change_pct,
        "volume": volume,
        "amount": amount,
        "average_volume": average_volume,
        "turnover_rate": _float(_value(spot, "换手率")) or _float(_value(latest_history, "turnover")),
        "amplitude": _float(_value(spot, "振幅")) or _float(_value(latest_history, "amplitude")),
        "fifty_two_week_high": fifty_two_week_high,
        "fifty_two_week_low": fifty_two_week_low,
        "market_cap": market_cap,
        "float_market_cap": float_market_cap,
        "pe_ratio": pe_ratio,
        "price_to_book_ratio": price_to_book,
        "price_to_sales_ratio": price_to_sales,
        "main_net_inflow": _float(_value(flow_row, "主力净流入-净额")),
        "main_net_inflow_ratio": _float(_value(flow_row, "主力净流入-净占比")),
        "super_large_net_inflow": _float(_value(flow_row, "超大单净流入-净额")),
        "large_net_inflow": _float(_value(flow_row, "大单净流入-净额")),
        "medium_net_inflow": _float(_value(flow_row, "中单净流入-净额")),
        "small_net_inflow": _float(_value(flow_row, "小单净流入-净额")),
        "news_count": 0,
        "summary": "",
        "generated_on": datetime.now().isoformat(timespec="seconds"),
        "source": "BaoStock+AkShare+Tencent",
    }
    snapshot["summary"] = _numeric_summary(snapshot)

    if llm_client is not None:
        news_frame = get_stock_news(
            code,
            date=cache_date,
            force_refresh=force_refresh,
        )
        news_items = news_frame.to_dict("records") if not news_frame.empty else []
        snapshot["news_count"] = len(news_items)
        try:
            generated_summary = _llm_summary(snapshot, llm_client, news_items)
            if generated_summary:
                snapshot["summary"] = generated_summary
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM snapshot summary failed for %s: %s", code, exc)

    cache.upsert_records(
        SNAPSHOT_TABLE,
        [snapshot],
        key_columns=["symbol", "cache_date"],
    )
    return snapshot


__all__ = [
    "CSI300_CODE",
    "CSI300_NAME",
    "SummaryLLM",
    "get_market_snapshot",
    "normalize_symbol",
]
