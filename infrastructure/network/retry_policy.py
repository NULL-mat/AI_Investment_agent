"""Provider-specific tenacity retry policies and safe attempt logging."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import logging
import os
import time
from typing import Any, Callable, TypeVar

from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_random, wait_random_exponential

from .errors import ProviderError, ProviderParameterError, ProviderRequestError, ProviderResponseError
from .proxy_pool import ProxyPool, redact_proxy

_T = TypeVar("_T")
logger = logging.getLogger("infrastructure.network")


@dataclass(frozen=True)
class ProviderRetryPolicy:
    provider: str
    max_attempts: int = 3
    initial_delay: float = 0.5
    max_delay: float = 8.0
    jitter: float = 0.25

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_attempts", max(1, int(self.max_attempts)))
        object.__setattr__(self, "initial_delay", max(0.0, float(self.initial_delay)))
        object.__setattr__(self, "max_delay", max(self.initial_delay, float(self.max_delay)))
        object.__setattr__(self, "jitter", max(0.0, float(self.jitter)))

    @classmethod
    def from_env(cls, provider: str) -> "ProviderRetryPolicy":
        prefix = provider.upper().replace("-", "_")

        def configured(name: str, legacy: str | None, default: str) -> str:
            value = os.getenv(f"{prefix}_RETRY_{name}")
            if value is not None:
                return value
            if legacy:
                value = os.getenv(legacy)
                if value is not None:
                    return value
            return default

        def number(name: str, default: str, legacy: str | None = None) -> float:
            try:
                return float(configured(name, legacy, default))
            except ValueError:
                return float(default)

        try:
            attempts = int(configured("MAX_ATTEMPTS", f"{prefix}_MAX_ATTEMPTS" if provider.lower() == "baostock" else f"{prefix}_PROXY_MAX_ATTEMPTS", "3"))
        except ValueError:
            attempts = 3
        return cls(
            provider=provider,
            max_attempts=attempts,
            initial_delay=number("INITIAL_DELAY", "0.5", f"{prefix}_PROXY_BASE_DELAY" if provider.lower() == "akshare" else None),
            max_delay=number("MAX_DELAY", "8", f"{prefix}_PROXY_MAX_DELAY" if provider.lower() == "akshare" else None),
            jitter=number("JITTER", "0.25", f"{prefix}_PROXY_JITTER" if provider.lower() == "akshare" else None),
        )

    def retrying(self, log: logging.Logger | None = None) -> Retrying:
        active_logger = log or logger
        wait = wait_random_exponential(multiplier=self.initial_delay, max=self.max_delay)
        if self.jitter:
            wait = wait + wait_random(0, self.jitter)

        def before_sleep(state) -> None:
            exc = state.outcome.exception() if state.outcome else None
            active_logger.warning(
                "provider request failed; retrying",
                extra={
                    "provider": self.provider,
                    "attempt": state.attempt_number,
                    "latency_ms": getattr(exc, "latency_ms", None),
                    "error_type": getattr(exc, "error_type", type(exc).__name__),
                },
            )

        return Retrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait,
            retry=retry_if_exception(lambda exc: isinstance(exc, ProviderError) and exc.retryable),
            reraise=True,
            before_sleep=before_sleep,
        )


_POLICY_CACHE: dict[str, ProviderRetryPolicy] = {}


def get_retry_policy(provider: str) -> ProviderRetryPolicy:
    """Return an independently configurable policy for one provider."""

    # Environment is intentionally read on first use; tests and long-running
    # applications can clear this cache when changing configuration.
    if provider not in _POLICY_CACHE:
        _POLICY_CACHE[provider] = ProviderRetryPolicy.from_env(provider)
    return _POLICY_CACHE[provider]


def _safe_error(provider: str, exc: Exception) -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc
    try:
        import requests

        if isinstance(exc, requests.HTTPError):
            status = exc.response.status_code if exc.response is not None else None
            if status == 429:
                from .errors import ProviderRateLimitError

                return ProviderRateLimitError(f"{provider} rate limited", provider=provider, status_code=status)
            if status in {401, 403}:
                from .errors import ProviderAuthError

                return ProviderAuthError(f"{provider} rejected access", provider=provider, status_code=status)
            if status in {400, 404, 422}:
                return ProviderParameterError(f"{provider} rejected request parameters", provider=provider, status_code=status)
            if status == 408 or (status is not None and status >= 500):
                return ProviderRequestError(f"{provider} temporary HTTP failure", provider=provider, status_code=status)
            return ProviderResponseError(f"{provider} returned an HTTP error", provider=provider, status_code=status)
    except ImportError:  # pragma: no cover - requests is a project dependency
        pass
    if isinstance(exc, (ValueError, TypeError)):
        return ProviderParameterError(
            f"{provider} request has invalid parameters",
            provider=provider,
        )
    # requests.RequestException is deliberately detected without importing
    # requests at module import time, keeping infrastructure lightweight.
    if exc.__class__.__module__.split(".", 1)[0] == "requests":
        return ProviderRequestError(
            f"{provider} request failed due to a network error",
            provider=provider,
        )
    if isinstance(exc, (OSError, TimeoutError, ConnectionError)):
        return ProviderRequestError(
            f"{provider} request failed due to a network error",
            provider=provider,
        )
    return ProviderResponseError(
        f"{provider} provider operation failed",
        provider=provider,
    )


def execute_with_retry(
    provider: str,
    operation: Callable[[str | None], _T] | Callable[[], _T],
    *,
    policy: ProviderRetryPolicy | None = None,
    proxy_pool: ProxyPool | None = None,
    log: logging.Logger | None = None,
) -> _T:
    """Execute one provider operation using tenacity and proxy rotation."""

    active_policy = policy or get_retry_policy(provider)
    pool = proxy_pool or ProxyPool.from_env(provider)
    active_logger = log or logger
    accepts_proxy = False
    try:
        accepts_proxy = len(inspect.signature(operation).parameters) > 0
    except (TypeError, ValueError):
        accepts_proxy = True

    def attempt(proxy: str | None, attempt_number: int) -> _T:
        started = time.perf_counter()
        try:
            with pool.environment(proxy):
                result = operation(proxy) if accepts_proxy else operation()  # type: ignore[call-arg]
            active_logger.info(
                "provider request completed",
                extra={
                    "provider": provider,
                    "attempt": attempt_number,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "error_type": None,
                    "proxy": redact_proxy(proxy),
                },
            )
            return result
        except Exception as raw_exc:  # noqa: BLE001
            error = _safe_error(provider, raw_exc)
            error.latency_ms = round((time.perf_counter() - started) * 1000, 2)
            active_logger.warning(
                "provider request attempt failed",
                extra={
                    "provider": provider,
                    "attempt": attempt_number,
                    "latency_ms": error.latency_ms,
                    "error_type": error.error_type,
                    "proxy": redact_proxy(proxy),
                },
            )
            raise error from raw_exc

    attempt_number = 0

    def call() -> _T:
        nonlocal attempt_number
        attempt_number += 1
        return attempt(pool.next_proxy(), attempt_number)

    try:
        return active_policy.retrying(active_logger)(call)
    except ProviderError:
        raise
    except Exception as exc:  # pragma: no cover - defensive tenacity guard
        raise ProviderRequestError(
            f"{provider} request failed after retry policy was exhausted",
            provider=provider,
        ) from exc
    raise ProviderRequestError(
        f"{provider} request failed without a result",
        provider=provider,
    )
