"""Thread-safe proxy rotation with an explicit direct-connection fallback."""

from __future__ import annotations

from contextlib import contextmanager
import os
import threading
from typing import Iterable, Iterator


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalise_proxy(value: str) -> str:
    value = value.strip()
    if value.lower() == "direct":
        return "direct"
    if "://" not in value:
        return f"http://{value}"
    return value


def redact_proxy(proxy: str | None) -> str:
    """Return a non-sensitive label suitable for logs."""

    if not proxy or proxy.lower() == "direct":
        return "direct"
    try:
        from urllib.parse import urlsplit

        parsed = urlsplit(proxy)
        host = parsed.hostname or "proxy"
        return f"{parsed.scheme}://{host}:{parsed.port or ''}".rstrip(":")
    except ValueError:
        return "proxy"


class ProxyPool:
    """Round-robin proxy pool.

    ``None`` is the direct connection and is always appended when
    ``allow_direct`` is true, making direct fallback deterministic.
    """

    def __init__(self, proxies: Iterable[str] = (), *, allow_direct: bool = True) -> None:
        values: list[str] = []
        for value in proxies:
            if not value or value.strip().lower() == "direct":
                continue
            normalised = _normalise_proxy(value)
            if normalised not in values:
                values.append(normalised)
        self._targets: tuple[str | None, ...] = tuple(values) + ((None,) if allow_direct else ())
        if not self._targets:
            self._targets = (None,)
        self._index = 0
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, provider: str = "akshare") -> "ProxyPool":
        prefix = provider.upper().replace("-", "_")
        raw = os.getenv(f"{prefix}_PROXY_LIST", "")
        if not raw and provider.lower() == "baostock":
            raw = os.getenv("BAOSTOCK_PROXY", "")
        # AKShare historically used semicolon-separated values in .env files.
        values = [item.strip() for item in raw.replace(";", ",").split(",") if item.strip()]
        if _truthy(os.getenv(f"{prefix}_PROXY_FORCE_DIRECT")):
            values = []
            allow_direct = True
        else:
            allow_direct = _truthy(os.getenv(f"{prefix}_PROXY_ALLOW_DIRECT"), True)
        return cls(values, allow_direct=allow_direct)

    def next_proxy(self) -> str | None:
        with self._lock:
            target = self._targets[self._index % len(self._targets)]
            self._index += 1
            return target

    def __len__(self) -> int:
        return len(self._targets)

    def targets_for_testing(self) -> tuple[str | None, ...]:
        """Expose immutable targets for deterministic unit tests."""

        return self._targets

    def requests_proxies(self, proxy: str | None) -> dict[str, str] | dict:
        if proxy is None:
            return {}
        return {"http": proxy, "https": proxy}

    @contextmanager
    def environment(self, proxy: str | None) -> Iterator[None]:
        """Temporarily configure libraries that only read proxy env vars.

        This is used only around a single provider attempt. Requests-based
        clients use ``requests_proxies`` and do not mutate process state.
        """

        keys = (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "http_proxy",
            "https_proxy",
            "NO_PROXY",
            "no_proxy",
            "BAOSTOCK_ACTIVE_PROXY",
        )
        previous = {key: os.environ.get(key) for key in keys}
        try:
            if proxy is None:
                for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                    os.environ.pop(key, None)
                os.environ["NO_PROXY"] = "*"
                os.environ["no_proxy"] = "*"
                os.environ["BAOSTOCK_ACTIVE_PROXY"] = "direct"
            else:
                for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                    os.environ[key] = proxy
                os.environ.pop("NO_PROXY", None)
                os.environ.pop("no_proxy", None)
                os.environ["BAOSTOCK_ACTIVE_PROXY"] = proxy
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
