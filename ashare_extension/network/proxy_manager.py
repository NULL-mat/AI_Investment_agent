"""Backward-compatible facade over :mod:`infrastructure.network`.

New provider code should import ``ProxyPool`` and ``execute_with_retry`` from
the infrastructure package directly. This facade remains so downstream A
Share integrations do not break while the retry/proxy implementation has one
owner.
"""

from __future__ import annotations

from typing import Callable, Iterable

from infrastructure.network import ProxyPool, ProviderRetryPolicy, execute_with_retry


class ProxyManager:
    """Compatibility wrapper with no local retry or backoff implementation."""

    def __init__(
        self,
        proxies: Iterable[str] | None = None,
        *,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 8.0,
        jitter: float = 0.25,
        logger=None,
    ) -> None:
        self.pool = ProxyPool(proxies or (), allow_direct=True)
        self.policy = ProviderRetryPolicy(
            provider="akshare",
            max_attempts=max_attempts,
            initial_delay=base_delay,
            max_delay=max_delay,
            jitter=jitter,
        )
        self.logger = logger

    @classmethod
    def from_env(cls, logger=None) -> "ProxyManager":
        pool = ProxyPool.from_env("akshare")
        policy = ProviderRetryPolicy.from_env("akshare")
        manager = cls([], logger=logger)
        manager.pool = pool
        manager.policy = policy
        return manager

    def run(self, func: Callable, label: str):
        return execute_with_retry(
            "akshare",
            func,
            policy=self.policy,
            proxy_pool=self.pool,
            log=self.logger,
        )


proxy_manager = ProxyManager.from_env()

__all__ = ["ProxyManager", "proxy_manager"]
