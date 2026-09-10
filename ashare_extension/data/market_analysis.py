"""CSI 300 market-level analysis adapted from the A-share macro news agent."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
from typing import Any

import pandas as pd

from .akshare_cache import CACHE_PATH, get_price_history_df, get_stock_news
from .market_snapshot import (
    CSI300_CODE,
    CSI300_NAME,
    SummaryLLM,
    get_market_snapshot,
)
from .sqlite_cache import AkshareSQLiteCache


ANALYSIS_TABLE = "csi300_analysis_cache"
ANALYSIS_TTL_SECONDS = 24 * 3600

logger = logging.getLogger("ashare_extension.market_analysis")
cache = AkshareSQLiteCache(CACHE_PATH)


def _bounded(value: Any, low: float, high: float, default: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["暂无"]
    result = [str(item).strip() for item in value if str(item).strip()]
    return result or ["暂无"]


def _extract_json(raw: str) -> dict[str, Any]:
    from hedge_fund.llm.client import extract_json

    return extract_json(raw)


def _quantitative_payload(
    history: pd.DataFrame,
    snapshot: dict[str, Any],
    news_count: int,
) -> dict[str, Any]:
    closes = pd.to_numeric(history["close"], errors="coerce").dropna()
    if closes.empty:
        raise RuntimeError("CSI 300 history is empty")

    latest = float(closes.iloc[-1])
    momentum_20d = latest / float(closes.iloc[-21]) - 1 if len(closes) >= 21 else None
    momentum_60d = latest / float(closes.iloc[-61]) - 1 if len(closes) >= 61 else None
    ma20 = float(closes.tail(20).mean()) if len(closes) >= 20 else None
    ma60 = float(closes.tail(60).mean()) if len(closes) >= 60 else None
    returns = closes.pct_change().dropna()
    volatility_20d = float(returns.tail(20).std() * (252**0.5)) if len(returns) >= 2 else None

    score = 50.0
    if momentum_20d is not None:
        score += max(-15.0, min(15.0, momentum_20d * 150.0))
    if momentum_60d is not None:
        score += max(-15.0, min(15.0, momentum_60d * 75.0))
    if ma20 is not None:
        score += 5.0 if latest >= ma20 else -5.0
    if ma60 is not None:
        score += 5.0 if latest >= ma60 else -5.0
    score_int = int(round(max(0.0, min(100.0, score))))
    signal = "bullish" if score_int > 60 else "bearish" if score_int < 40 else "neutral"
    confidence = min(0.9, 0.5 + abs(score_int - 50) / 100.0)

    drivers: list[str] = []
    risks: list[str] = []
    if momentum_20d is not None:
        target = drivers if momentum_20d >= 0 else risks
        target.append(f"20日动量 {momentum_20d:.2%}")
    if momentum_60d is not None:
        target = drivers if momentum_60d >= 0 else risks
        target.append(f"60日动量 {momentum_60d:.2%}")
    if ma20 is not None:
        target = drivers if latest >= ma20 else risks
        target.append("指数位于20日均线上方" if latest >= ma20 else "指数位于20日均线下方")
    if volatility_20d is not None and volatility_20d > 0.25:
        risks.append(f"20日年化波动率较高（{volatility_20d:.2%}）")

    stance = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}[signal]
    summary = f"沪深300最新收盘 {latest:.2f}，量价趋势评分 {score_int}/100，" f"市场状态为{stance}。"
    insight = {
        "bullish": "可在风险预算内保持或逐步增加沪深300方向敞口。",
        "bearish": "控制仓位并等待趋势企稳，避免追高。",
        "neutral": "维持均衡仓位，等待指数突破后再调整方向敞口。",
    }[signal]

    return {
        "index": CSI300_NAME,
        "symbol": CSI300_CODE,
        "signal": signal,
        "confidence": confidence,
        "score": score_int,
        "summary": summary,
        "key_drivers": drivers or ["暂无"],
        "key_risks": risks or ["暂无"],
        "actionable_insight": insight,
        "momentum_20d": momentum_20d,
        "momentum_60d": momentum_60d,
        "moving_average_20d": ma20,
        "moving_average_60d": ma60,
        "volatility_20d": volatility_20d,
        "latest_price": snapshot.get("latest_price"),
        "change_pct": snapshot.get("change_pct"),
        "fifty_two_week_high": snapshot.get("fifty_two_week_high"),
        "fifty_two_week_low": snapshot.get("fifty_two_week_low"),
        "news_count": news_count,
        "from_cache": False,
        "generated_on": datetime.now().isoformat(timespec="seconds"),
    }


def _enrich_with_llm(
    payload: dict[str, Any],
    news_items: list[dict[str, Any]],
    llm_client: SummaryLLM,
) -> dict[str, Any]:
    system = "你是专注中国A股的宏观分析师。基于给定的沪深300量价指标和新闻，" "只返回JSON，字段为index、signal、confidence、score、summary、" "key_drivers、key_risks、actionable_insight。signal只能是" "bullish、bearish或neutral。"
    user = json.dumps(
        {"quantitative_analysis": payload, "news": news_items[:10]},
        ensure_ascii=False,
    )
    parsed = _extract_json(llm_client.complete(system, user))
    signal = str(parsed.get("signal", payload["signal"])).lower()
    if signal not in {"bullish", "bearish", "neutral"}:
        signal = payload["signal"]
    return {
        **payload,
        "index": CSI300_NAME,
        "signal": signal,
        "confidence": _bounded(parsed.get("confidence"), 0.0, 1.0, payload["confidence"]),
        "score": int(round(_bounded(parsed.get("score"), 0.0, 100.0, payload["score"]))),
        "summary": str(parsed.get("summary", payload["summary"])).strip() or payload["summary"],
        "key_drivers": _string_list(parsed.get("key_drivers", payload["key_drivers"])),
        "key_risks": _string_list(parsed.get("key_risks", payload["key_risks"])),
        "actionable_insight": str(parsed.get("actionable_insight", payload["actionable_insight"])).strip() or payload["actionable_insight"],
    }


def get_csi300_analysis(
    *,
    as_of_date: str | None = None,
    ttl_seconds: int = ANALYSIS_TTL_SECONDS,
    force_refresh: bool = False,
    include_news: bool = True,
    news_limit: int = 10,
    llm_client: SummaryLLM | None = None,
) -> dict[str, Any]:
    """Return a market-level CSI 300 analysis without modifying core agents."""
    today = datetime.now().strftime("%Y-%m-%d")
    cache_date = pd.to_datetime(as_of_date or today).strftime("%Y-%m-%d")
    effective_ttl = ttl_seconds if cache_date == today else None
    if not force_refresh and llm_client is None:
        cached = cache.fetch_records(
            ANALYSIS_TABLE,
            filters={"symbol": CSI300_CODE, "cache_date": cache_date},
            ttl_seconds=effective_ttl,
            limit=1,
        )
        if cached:
            result = json.loads(str(cached[0]["result_json"]))
            result["from_cache"] = True
            return result

    end = pd.to_datetime(cache_date).to_pydatetime()
    start = end - timedelta(days=400)
    history = get_price_history_df(
        CSI300_CODE,
        start,
        end,
        adjust="",
        force_refresh=force_refresh,
    )
    if history.empty:
        raise RuntimeError(f"No CSI 300 history available on or before {cache_date}")

    news_items: list[dict[str, Any]] = []
    if include_news:
        news_frame = get_stock_news(
            CSI300_CODE,
            date=cache_date,
            force_refresh=force_refresh,
        )
        if not news_frame.empty:
            news_items = news_frame.head(max(0, news_limit)).to_dict("records")

    snapshot = get_market_snapshot(
        CSI300_CODE,
        as_of_date=cache_date,
        force_refresh=force_refresh,
    )
    payload = _quantitative_payload(history, snapshot, len(news_items))
    if llm_client is not None:
        try:
            payload = _enrich_with_llm(payload, news_items, llm_client)
        except Exception as exc:  # noqa: BLE001
            logger.warning("CSI 300 LLM analysis failed; using quantitative result: %s", exc)

    cache.upsert_records(
        ANALYSIS_TABLE,
        [
            {
                "symbol": CSI300_CODE,
                "cache_date": cache_date,
                "result_json": json.dumps(payload, ensure_ascii=False),
            }
        ],
        key_columns=["symbol", "cache_date"],
    )
    return payload


__all__ = ["get_csi300_analysis"]
