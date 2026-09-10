"""News Engine orchestration: search, enrich, normalize, deduplicate, cache."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Iterable, Protocol

from infrastructure.network import ProviderError

from .cache import NewsCache
from .deduplicator import deduplicate
from .models import Evidence, NewsItem
from .normalizer import normalize_result, within_date_window
from .query_builder import NewsQuerySpec, QueryBuilder

logger = logging.getLogger("news.service")


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, spec: NewsQuerySpec) -> Iterable[object]: ...


class NewsProviderError(RuntimeError):
    """Raised when all configured news providers fail."""

    def __init__(self, message: str, *, errors: list[Exception] | None = None) -> None:
        self.errors = errors or []
        super().__init__(message)


@dataclass
class NewsEngine:
    providers: tuple[SearchProvider, ...] = field(default_factory=tuple)
    query_builder: QueryBuilder = field(default_factory=QueryBuilder)
    cache: NewsCache = field(default_factory=NewsCache)
    content_fetcher: object | None = None
    min_content_chars: int = 280

    def __post_init__(self) -> None:
        if not self.providers:
            from .providers.content_fetcher import RequestsContentFetcher
            from .providers.tavily import TavilySearchProvider

            self.providers = (TavilySearchProvider(),)
            if self.content_fetcher is None:
                self.content_fetcher = RequestsContentFetcher()
        self.providers = tuple(self.providers)

    def search(self, spec: NewsQuerySpec, *, refresh: bool = False, incremental: bool = False) -> list[NewsItem]:
        query = self.query_builder.build(spec)
        failures: list[Exception] = []
        for provider in self.providers:
            cached = self.cache.get(spec, provider.name, query)
            if cached is not None and not refresh and not incremental:
                return cached
            try:
                raw_results = provider.search(query, spec=spec)
                normalized: list[NewsItem] = []
                for raw in raw_results:
                    item = normalize_result(raw, spec=spec, query=query, provider=provider.name)
                    if item is None or not within_date_window(item, spec):
                        continue
                    if self.content_fetcher is not None and len(item.content or "") < self.min_content_chars:
                        try:
                            content = self.content_fetcher.fetch(item.url)
                        except Exception as exc:  # content enrichment is best effort
                            logger.warning("content fetch failed", extra={"provider": provider.name, "error_type": type(exc).__name__})
                        else:
                            if content:
                                item = NewsItem(item.title, item.source, item.url, item.published_at, content, item.ticker, item.query, item.provider)
                    normalized.append(item)
                result = deduplicate(normalized)
                if incremental:
                    return self.cache.merge(spec, provider.name, query, result)
                return self.cache.set(spec, provider.name, query, result)
            except ProviderError as exc:
                failures.append(exc)
                logger.warning("news provider failed; trying fallback", extra={"provider": provider.name, "error_type": exc.error_type})
                continue
            except Exception as exc:  # provider adapters must not make failures silent
                failures.append(exc)
                logger.warning("news provider failed; trying fallback", extra={"provider": provider.name, "error_type": type(exc).__name__})
                continue
        raise NewsProviderError("All configured news providers failed", errors=failures)

    def evidence(self, spec: NewsQuerySpec, **kwargs) -> list[Evidence]:
        items = self.search(spec, **kwargs)
        now = datetime.now(timezone.utc)
        return [Evidence(item=item, snippet=item.content, retrieved_at=now) for item in items]
