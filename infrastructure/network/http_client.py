"""Requests client backed by the shared retry and proxy infrastructure."""

from __future__ import annotations

import logging
from typing import Any

import requests

from .errors import ProviderAuthError, ProviderParameterError, ProviderRateLimitError, ProviderRequestError
from .proxy_pool import ProxyPool
from .retry_policy import ProviderRetryPolicy, execute_with_retry, get_retry_policy


class ReliableHttpClient:
    """Small requests wrapper with provider-specific policy and proxy pool."""

    def __init__(
        self,
        provider: str,
        *,
        policy: ProviderRetryPolicy | None = None,
        proxy_pool: ProxyPool | None = None,
        session: requests.Session | None = None,
        timeout: float = 20.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.provider = provider
        self.policy = policy or get_retry_policy(provider)
        self.proxy_pool = proxy_pool or ProxyPool.from_env(provider)
        self.session = session or requests.Session()
        # Only the configured ProxyPool controls routing; ambient shell proxy
        # variables must not silently bypass direct fallback.
        self.session.trust_env = False
        self.timeout = timeout
        self.logger = logger

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        timeout = kwargs.pop("timeout", self.timeout)
        headers = kwargs.pop("headers", None)

        def operation(proxy: str | None) -> requests.Response:
            response = self.session.request(
                method,
                url,
                timeout=timeout,
                headers=headers,
                proxies=self.proxy_pool.requests_proxies(proxy),
                **kwargs,
            )
            status = response.status_code
            if status == 429:
                raise ProviderRateLimitError(
                    f"{self.provider} rate limited (HTTP 429)",
                    provider=self.provider,
                    status_code=status,
                )
            if status in {401, 403}:
                raise ProviderAuthError(
                    f"{self.provider} rejected credentials or access (HTTP {status})",
                    provider=self.provider,
                    status_code=status,
                )
            if status in {400, 404, 422}:
                raise ProviderParameterError(
                    f"{self.provider} rejected request parameters (HTTP {status})",
                    provider=self.provider,
                    status_code=status,
                )
            if status == 408 or status >= 500:
                raise ProviderRequestError(
                    f"{self.provider} temporary HTTP failure (HTTP {status})",
                    provider=self.provider,
                    status_code=status,
                )
            if status >= 400:
                raise ProviderRequestError(
                    f"{self.provider} HTTP failure (HTTP {status})",
                    provider=self.provider,
                    status_code=status,
                    retryable=False,
                )
            return response

        return execute_with_retry(
            self.provider,
            operation,
            policy=self.policy,
            proxy_pool=self.proxy_pool,
            log=self.logger,
        )

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", url, **kwargs)
