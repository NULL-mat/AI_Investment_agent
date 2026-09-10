"""Safe, typed errors used by outbound provider integrations."""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for provider failures.

    ``error_type`` is intentionally a small stable vocabulary so callers and
    logs do not need to parse exception text.
    """

    error_type = "provider_error"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        error_type: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        self.provider = provider
        self.status_code = status_code
        self.error_type = error_type or self.error_type
        self.retryable = self.retryable if retryable is None else retryable
        # Do not include response bodies, API keys, or proxy URLs in messages.
        super().__init__(message)


class ProviderRequestError(ProviderError):
    error_type = "network_error"
    retryable = True


class ProviderRateLimitError(ProviderError):
    error_type = "rate_limit"
    retryable = True


class ProviderAuthError(ProviderError):
    error_type = "authentication_error"
    retryable = False


class ProviderParameterError(ProviderError):
    error_type = "parameter_error"
    retryable = False


class ProviderResponseError(ProviderError):
    error_type = "response_error"
    retryable = False
