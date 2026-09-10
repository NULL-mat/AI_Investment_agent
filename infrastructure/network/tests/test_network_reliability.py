from __future__ import annotations

import logging

import pytest

from infrastructure.network import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderRetryPolicy,
    ProxyPool,
    ReliableHttpClient,
    execute_with_retry,
)


def fast_policy(provider: str, attempts: int = 3) -> ProviderRetryPolicy:
    return ProviderRetryPolicy(provider, max_attempts=attempts, initial_delay=0, max_delay=0, jitter=0)


def test_retry_uses_tenacity_and_direct_fallback(caplog):
    pool = ProxyPool(["proxy-a:8080", "proxy-b:8080"])
    state = {"calls": 0, "proxies": []}

    def operation(proxy):
        state["calls"] += 1
        state["proxies"].append(proxy)
        if state["calls"] < 3:
            raise ConnectionError("temporary")
        return "ok"

    with caplog.at_level(logging.WARNING):
        assert execute_with_retry("akshare", operation, policy=fast_policy("akshare"), proxy_pool=pool) == "ok"
    assert state == {"calls": 3, "proxies": ["http://proxy-a:8080", "http://proxy-b:8080", None]}
    assert "error_type" in caplog.records[0].__dict__


def test_rate_limit_retries_then_raises():
    calls = {"count": 0}

    def operation(_proxy):
        calls["count"] += 1
        raise ProviderRateLimitError("limited", provider="tavily", status_code=429)

    with pytest.raises(ProviderRateLimitError):
        execute_with_retry("tavily", operation, policy=fast_policy("tavily", 2), proxy_pool=ProxyPool())
    assert calls["count"] == 2


def test_auth_error_is_immediate():
    calls = {"count": 0}

    def operation(_proxy):
        calls["count"] += 1
        raise ProviderAuthError("unauthorized", provider="tavily", status_code=401)

    with pytest.raises(ProviderAuthError):
        execute_with_retry("tavily", operation, policy=fast_policy("tavily", 5), proxy_pool=ProxyPool())
    assert calls["count"] == 1


def test_empty_data_is_a_valid_provider_result():
    assert execute_with_retry("akshare", lambda: [], policy=fast_policy("akshare"), proxy_pool=ProxyPool()) == []


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self.content = b"{}"
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.trust_env = True

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_http_429_retries_and_401_does_not():
    rate_session = FakeSession([FakeResponse(429), FakeResponse(200, {"ok": True})])
    rate_client = ReliableHttpClient("tavily", policy=fast_policy("tavily"), proxy_pool=ProxyPool(), session=rate_session)
    assert rate_client.get("https://example.test") .json() == {"ok": True}
    assert len(rate_session.calls) == 2

    auth_session = FakeSession([FakeResponse(401)])
    auth_client = ReliableHttpClient("tavily", policy=fast_policy("tavily"), proxy_pool=ProxyPool(), session=auth_session)
    with pytest.raises(ProviderAuthError):
        auth_client.get("https://example.test")
    assert len(auth_session.calls) == 1

    forbidden_session = FakeSession([FakeResponse(403)])
    forbidden_client = ReliableHttpClient("tavily", policy=fast_policy("tavily"), proxy_pool=ProxyPool(), session=forbidden_session)
    with pytest.raises(ProviderAuthError):
        forbidden_client.get("https://example.test")
    assert len(forbidden_session.calls) == 1


def test_http_network_failure_is_explicit():
    class FailingSession(FakeSession):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            raise TimeoutError("timed out")

    client = ReliableHttpClient("akshare", policy=fast_policy("akshare", 2), proxy_pool=ProxyPool(), session=FailingSession([]))
    with pytest.raises(ProviderRequestError):
        client.get("https://example.test")
