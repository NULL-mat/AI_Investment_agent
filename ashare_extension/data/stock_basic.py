from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from .sqlite_cache import AkshareSQLiteCache
from .baostock_client import format_symbol, query_stock_basic
import logging

BASE_DIR = Path(__file__).resolve().parents[2]
_default_cache_path = BASE_DIR / "data" / "market_data_cache.db"
CACHE_PATH = Path(os.getenv("MARKET_CACHE_DB_PATH", str(_default_cache_path)))

STOCK_BASIC_TABLE = "stock_basic"
logger = logging.getLogger("ashare_extension.stock_basic")
cache = AkshareSQLiteCache(CACHE_PATH)


def get_stock_basic(
    symbol: str,
    *,
    ttl_seconds: int = 30 * 24 * 3600,
    force_refresh: bool = False,
) -> Optional[Dict[str, Any]]:
    # 股票基础信息缓存改为“无 TTL 常驻”；ttl_seconds 参数仅保留兼容性
    if not symbol:
        return None

    bs_symbol = format_symbol(symbol)
    if force_refresh:
        logger.info("?? 强制刷新股票基础信息: %s", symbol)
    else:
        cached = cache.fetch_records(
            table=STOCK_BASIC_TABLE,
            filters={"code": bs_symbol},
            order_by='"缓存时间" DESC',
            limit=1,
        )
        if cached:
            record = dict(cached[0])
            record.pop("缓存时间", None)
            return record

    df = query_stock_basic(bs_symbol)
    if df is None or df.empty:
        return None

    record = df.iloc[0].to_dict()
    record["code"] = bs_symbol
    cache.upsert_records(
        STOCK_BASIC_TABLE,
        [record],
        key_columns=["code"],
    )
    return record


def get_stock_name(
    symbol: str,
    *,
    ttl_seconds: int = 30 * 24 * 3600,
    force_refresh: bool = False,
) -> Optional[str]:
    record = get_stock_basic(
        symbol,
        ttl_seconds=ttl_seconds,
        force_refresh=force_refresh,
    )
    return record.get("code_name") if record else None


def enrich_symbol(symbol: str, company_name: Optional[str]) -> str:
    symbol = symbol.strip()
    name = (company_name or "").strip()
    if not name or name == symbol:
        return symbol
    return f"{symbol} {name}"
