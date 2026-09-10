"""Small command-line smoke test for the A-share DataClient adapter."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import json

from .data.cached_client import CachedAShareDataClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Query A-share data through hedge_fund's DataClient protocol")
    parser.add_argument("ticker", help="A-share code, for example 600519 or 000001")
    parser.add_argument(
        "--start",
        default=(date.today() - timedelta(days=365)).isoformat(),
        help="Price/news start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        default=date.today().isoformat(),
        help="Price/news end date (YYYY-MM-DD)",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--adjust", choices=("qfq", "hfq", "none"), default="qfq")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Bypass both JSON and SQLite caches",
    )
    parser.add_argument(
        "--kind",
        choices=(
            "prices",
            "quote",
            "metrics",
            "statements",
            "flow",
            "snapshot",
            "news",
            "csi300",
            "all",
        ),
        default="all",
    )
    parser.add_argument(
        "--no-market-news",
        action="store_true",
        help="Skip the optional CSI 300 news lookup",
    )
    args = parser.parse_args()

    with CachedAShareDataClient(
        adjust=args.adjust,
        refresh=args.refresh,
    ) as client:
        payload = {}
        if args.kind in ("prices", "all"):
            payload["prices"] = [item.model_dump() for item in client.get_prices(args.ticker, args.start, args.end)]
        if args.kind in ("quote", "all"):
            payload["realtime_quote"] = client.get_realtime_quote(args.ticker)
        if args.kind in ("metrics", "all"):
            payload["financial_metrics"] = [item.model_dump() for item in client.get_financial_metrics(args.ticker, args.end, limit=args.limit)]
        if args.kind in ("statements", "all"):
            payload["financial_statements"] = client.get_financial_statements(args.ticker, args.end)
        if args.kind in ("flow", "all"):
            payload["fund_flow"] = client.get_fund_flow(args.ticker, args.end, args.limit)
        if args.kind in ("snapshot", "all"):
            payload["market_snapshot"] = client.get_market_snapshot(args.ticker, args.end)
        if args.kind in ("news", "all"):
            payload["news"] = [item.model_dump() for item in client.get_news(args.ticker, args.end, args.start, args.limit)]
        if args.kind in ("csi300", "all"):
            payload["csi300_analysis"] = client.get_csi300_analysis(
                args.end,
                include_news=not args.no_market_news,
            )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
