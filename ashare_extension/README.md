# A-share data extension

`AShareDataClient` implements the existing `hedge_fund.data.protocol.DataClient`
without changing the upstream `hedge_fund` package. It migrates the latest
A_Share project's BaoStock history/calendar client and AkShare SQLite cache,
then converts the results to the upstream `Price`, `FinancialMetrics`,
`CompanyNews`, and `CompanyFacts` models.

The extension also exposes the A-share-only capabilities that do not belong to
the upstream `DataClient` protocol:

- complete BaoStock stock metadata;
- AkShare financial statements and capital-flow history;
- a unified quote, valuation, flow, and 52-week market snapshot;
- quantitative CSI 300 (`000300`) market-level analysis;
- optional LLM summaries through any object implementing
  `complete(system, user) -> str`.

Install the A-share runtime dependencies in the `scrapy312` environment:

```powershell
python -m pip install -r ashare_extension/requirements.txt
```

BaoStock `0.9.3+` is required because the current service uses
`public-api.baostock.com` and rejects the old `0.8.x` client.

Run a network smoke test (BaoStock/AkShare access is required):

```powershell
python -m ashare_extension.cli 600519 --kind all
python -m ashare_extension.cli 600519 --kind snapshot
python -m ashare_extension.cli 600519 --kind flow
python -m ashare_extension.cli 600519 --kind statements
python -m ashare_extension.cli 000300 --kind csi300 --no-market-news
```

Python API:

```python
from ashare_extension import AShareDataClient

with AShareDataClient() as client:
    quote = client.get_realtime_quote("600519")
    statements = client.get_financial_statements("600519", "2026-09-09")
    fund_flow = client.get_fund_flow("600519", "2026-09-09", limit=20)
    snapshot = client.get_market_snapshot("600519", "2026-09-09")
    market = client.get_csi300_analysis("2026-09-09")
```

Set `MARKET_CACHE_DB_PATH` to choose the SQLite location. The default is
`data/market_data_cache.db` in this repository. Proxy rotation follows the
A_Share environment variables `AKSHARE_PROXY_LIST`,
`AKSHARE_PROXY_MAX_ATTEMPTS`, `AKSHARE_PROXY_BASE_DELAY`,
`AKSHARE_PROXY_MAX_DELAY`, and `AKSHARE_PROXY_ALLOW_DIRECT`.

BaoStock network protection is controlled by `BAOSTOCK_SOCKET_TIMEOUT` (seconds)
and `BAOSTOCK_MAX_ATTEMPTS`; the `scrapy312` environment uses `15` and `3`.

For BaoStock's TCP protocol, the adapter uses the first non-`direct` entry in
`AKSHARE_PROXY_LIST` as an HTTP CONNECT proxy, and also accepts
`socks5://...` entries. Set `BAOSTOCK_PROXY` when it needs a different proxy,
for example `BAOSTOCK_PROXY=socks5://127.0.0.1:7897`. The proxy must allow
long-lived TCP/CONNECT traffic to `www.baostock.com:10030`; a web-only proxy
cannot carry BaoStock requests.

The primary one-symbol realtime quote path uses Tencent's quote endpoint.
This avoids downloading the full A-share quote table when Eastmoney rejects a
proxy connection. Capital flow keeps the AkShare/Eastmoney response schema and
uses Eastmoney's HTTP endpoint because some local HTTP proxies reject its HTTPS
CONNECT route.

For historical `as_of_date` values, snapshots deliberately omit realtime-only
valuation fields instead of leaking current PE/PB/market-cap data into a
backtest. Current-date snapshots include market cap, float market cap, PE, PB,
PS, capital flow, five-day average volume, and 52-week high/low.

The adapter intentionally returns empty values for SEC-specific insider trades
and earnings endpoints because those concepts are not supplied by the migrated
A-share sources.

## Cache policy

Use `CachedAShareDataClient` when one object must expose both the upstream
`DataClient` methods and the A-share-only methods:

```python
from ashare_extension import CachedAShareDataClient

with CachedAShareDataClient() as client:
    history = client.get_prices("600519", "2025-01-01", "2025-12-31")
    quote = client.get_realtime_quote("600519")
    snapshot = client.get_market_snapshot("600519")
```

Historical standard calls use the upstream JSON cache. Current-date calls
bypass that non-expiring layer and rely on the SQLite TTL. Pass `refresh=True`
to the constructor, or `force_refresh=True` to an individual A-share method,
to refresh the provider cache as well.

Historical `get_market_cap` calls return `None` instead of leaking a current
quote into a backtest. The SQLite layer uses WAL, atomic writes, a per-path
in-process lock, and SQLite lock retries. Set `MARKET_CACHE_SQLITE_TIMEOUT` to change the
SQLite lock wait in seconds; the default is `30`.

The extension CLI uses this facade by default. Add `--refresh` to any CLI
command to bypass both cache layers for that run.

## Shared network and news infrastructure

External calls made by the A-share adapters use the repository-level
`infrastructure.network` layer. Configure provider-specific tenacity policies
with `AKSHARE_RETRY_*`, `BAOSTOCK_RETRY_*`, and `TAVILY_RETRY_*` variables.
Existing `AKSHARE_PROXY_*` and `BAOSTOCK_MAX_ATTEMPTS` names remain accepted as
compatibility aliases. Proxy lists are rotated per attempt and end with a
direct fallback when `*_PROXY_ALLOW_DIRECT=true`.

The independent `news` package provides `NewsEngine`, `TavilySearchProvider`,
optional `RequestsContentFetcher`, normalized `NewsItem`/`Evidence`, URL/title/
content de-duplication, date filtering, provider fallback, and a query/date/
provider keyed JSON cache. It does not perform sentiment analysis or produce
investment decisions.
