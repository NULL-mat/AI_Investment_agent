import atexit
import os
import socket
import threading
from datetime import datetime
from typing import List
from urllib.parse import urlparse

try:
    import baostock as bs
except ImportError:  # pragma: no cover - exercised only without optional dependency
    bs = None
import pandas as pd
from infrastructure.network import (
    ProviderParameterError,
    ProviderRequestError,
    ProviderRetryPolicy,
    ProxyPool,
    execute_with_retry,
)

import logging

logger = logging.getLogger("ashare_extension.baostock_client")
_LOGIN_LOCK = threading.Lock()
_LOGGED_IN = False
_PROXY_PATCHED = False
BAOSTOCK_RETRY_POLICY = ProviderRetryPolicy.from_env("baostock")
BAOSTOCK_PROXY_POOL = ProxyPool.from_env("baostock")


def _configure_server() -> None:
    """Use BaoStock's current public API host, with an environment override."""
    if bs is None:
        return
    import baostock.common.contants as constants

    constants.BAOSTOCK_SERVER_IP = os.getenv("BAOSTOCK_SERVER_IP", "public-api.baostock.com")


FIELD_SET = [
    "date",
    "code",
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
    "turn",
    "pctChg",
]

ADJUST_FLAG_MAP = {
    "": "3",  # no adjustment
    "none": "3",
    "qfq": "2",  # pre-adjusted
    "hfq": "1",  # post-adjusted
}


def _proxy_url() -> str | None:
    """Return the proxy selected for the current public-layer attempt."""
    configured = (
        os.getenv("BAOSTOCK_ACTIVE_PROXY", "").strip()
        or os.getenv("HTTP_PROXY", "").strip()
        or os.getenv("BAOSTOCK_PROXY", "").strip()
    )
    if not configured or configured.lower() == "direct":
        return None
    return configured if "://" in configured else f"http://{configured}"


def _install_http_connect_proxy() -> None:
    """Install a bounded-time socket transport, optionally through a proxy.

    BaoStock speaks a plain TCP protocol on port 10030 and its upstream client
    has neither proxy support nor a read timeout. The patch is local to this
    extension and prevents a slow service response from hanging indefinitely.
    """
    global _PROXY_PATCHED
    if _PROXY_PATCHED or bs is None:
        return
    import baostock.common.contants as constants
    import baostock.common.context as context
    import baostock.util.socketutil as socketutil

    def connect_via_proxy(self) -> None:
        timeout = float(os.getenv("BAOSTOCK_SOCKET_TIMEOUT", "30"))
        target = f"{constants.BAOSTOCK_SERVER_IP}:{constants.BAOSTOCK_SERVER_PORT}"
        proxy_url = _proxy_url()
        parsed = urlparse(proxy_url) if proxy_url else None
        if parsed is not None and (parsed.hostname is None or parsed.port is None):
            raise ValueError("Invalid BaoStock proxy configuration")
        if parsed is None:
            sock = socket.create_connection(
                (constants.BAOSTOCK_SERVER_IP, constants.BAOSTOCK_SERVER_PORT),
                timeout=timeout,
            )
            sock.settimeout(timeout)
            setattr(context, "default_socket", sock)
            return

        sock = socket.create_connection((parsed.hostname, parsed.port), timeout=timeout)
        sock.settimeout(timeout)
        try:
            if parsed.scheme.lower() in {"socks5", "socks5h"}:
                # SOCKS5 no-auth handshake, including hostname resolution by proxy.
                sock.sendall(b"\x05\x01\x00")
                greeting = sock.recv(2)
                if greeting != b"\x05\x00":
                    raise OSError(f"SOCKS5 handshake failed: {greeting!r}")
                host_bytes = constants.BAOSTOCK_SERVER_IP.encode("idna")
                sock.sendall(b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes + constants.BAOSTOCK_SERVER_PORT.to_bytes(2, "big"))
                header = sock.recv(4)
                if len(header) != 4 or header[:2] != b"\x05\x00":
                    raise OSError(f"SOCKS5 CONNECT failed: {header!r}")
                address_type = header[3]
                if address_type == 1:
                    sock.recv(4)
                elif address_type == 3:
                    length = sock.recv(1)[0]
                    sock.recv(length)
                elif address_type == 4:
                    sock.recv(16)
                sock.recv(2)
            else:
                connect_request = (f"CONNECT {target} HTTP/1.1\r\n" f"Host: {target}\r\n" "Proxy-Connection: Keep-Alive\r\n\r\n").encode("ascii")
                sock.sendall(connect_request)
                response = b""
                while b"\r\n\r\n" not in response:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                    if len(response) > 65536:
                        break
                status_line = response.split(b"\r\n", 1)[0].decode("latin1", errors="replace")
                if " 200 " not in status_line:
                    raise OSError(f"HTTP proxy CONNECT failed: {status_line}")
            setattr(context, "default_socket", sock)
        except Exception:
            sock.close()
            raise

    socketutil.SocketUtil.connect = connect_via_proxy
    _PROXY_PATCHED = True


def _logout() -> None:
    global _LOGGED_IN
    with _LOGIN_LOCK:
        if not _LOGGED_IN:
            return
        try:
            bs.logout()
            logger.info("BaoStock session closed.")
        finally:
            _LOGGED_IN = False


def _reset_session() -> None:
    """Close a failed socket without sending another request over it."""
    global _LOGGED_IN
    import baostock.common.context as context

    with _LOGIN_LOCK:
        sock = getattr(context, "default_socket", None)
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
            setattr(context, "default_socket", None)
        _LOGGED_IN = False


def _query_with_retry(factory, label: str):
    """Run one BaoStock request through the shared tenacity executor."""

    def operation(_proxy=None):
        try:
            ensure_login()
            result = factory()
        except Exception:
            _reset_session()
            raise
        if result.error_code == "0":
            return result
        _reset_session()
        raise ProviderRequestError(
            f"BaoStock {label} returned a provider error",
            provider="baostock",
        )

    try:
        return execute_with_retry(
            "baostock",
            operation,
            policy=BAOSTOCK_RETRY_POLICY,
            proxy_pool=BAOSTOCK_PROXY_POOL,
            log=logger,
        )
    except ProviderRequestError:
        raise


def ensure_login() -> None:
    global _LOGGED_IN
    if bs is None:
        raise ProviderParameterError(
            "BaoStock is not installed in the active environment",
            provider="baostock",
        )
    _configure_server()
    _install_http_connect_proxy()
    with _LOGIN_LOCK:
        if _LOGGED_IN:
            return
        rs = bs.login()
        if rs.error_code != "0":
            raise ProviderRequestError(
                "BaoStock login failed",
                provider="baostock",
            )
        _LOGGED_IN = True
        logger.info("BaoStock login successful.")
        atexit.register(_logout)


def format_symbol(symbol: str) -> str:
    symbol = symbol.strip()
    lowered = symbol.lower()
    aliases = {"沪深300": "000300", "沪深300指数": "000300", "csi300": "000300"}
    lowered = aliases.get(lowered, aliases.get(symbol, lowered))

    if lowered.startswith(("sh.", "sz.", "bj.")):
        return lowered
    if lowered.startswith(("sh", "sz", "bj")) and len(lowered) > 2:
        return f"{lowered[:2]}.{lowered[2:]}"

    # 000300 is the CSI 300 index listed by BaoStock as sh.000300.
    if lowered == "000300" or lowered.startswith(("5", "6", "9")):
        return f"sh.{lowered}"
    if lowered.startswith(("4", "8")):
        return f"bj.{lowered}"
    return f"sz.{lowered}"


def _coerce_dates(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return str(value)


def query_history_k_data_plus(
    symbol: str,
    start_date,
    end_date,
    adjust: str = "qfq",
) -> pd.DataFrame:
    bs_symbol = format_symbol(symbol)
    start = _coerce_dates(start_date)
    end = _coerce_dates(end_date)
    adjust_flag = ADJUST_FLAG_MAP.get(adjust.lower() if adjust else "", "2")

    fields = ",".join(FIELD_SET)
    rs = _query_with_retry(
        lambda: bs.query_history_k_data_plus(
            bs_symbol,
            fields,
            start_date=start,
            end_date=end,
            frequency="d",
            adjustflag=adjust_flag,
        ),
        "history query",
    )

    rows: List[List[str]] = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())

    df = pd.DataFrame(rows, columns=FIELD_SET)
    return df


def query_trade_dates(start_date, end_date) -> pd.DataFrame:
    start = _coerce_dates(start_date)
    end = _coerce_dates(end_date)
    rs = _query_with_retry(
        lambda: bs.query_trade_dates(start_date=start, end_date=end),
        "trade-date query",
    )
    rows: List[List[str]] = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return pd.DataFrame(columns=["calendar_date", "is_trading_day"])
    df = pd.DataFrame(rows, columns=rs.fields)
    return df


def query_stock_basic(code: str) -> pd.DataFrame:
    rs = _query_with_retry(
        lambda: bs.query_stock_basic(code=code),
        "stock-basic query",
    )

    rows: List[List[str]] = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return pd.DataFrame(columns=rs.fields)
    df = pd.DataFrame(rows, columns=rs.fields)
    return df
