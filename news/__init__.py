"""Traceable news search and evidence normalization."""

from .models import Evidence, NewsItem
from .query_builder import NewsQuerySpec, QueryBuilder
from .service import NewsEngine, NewsProviderError

__all__ = ["Evidence", "NewsEngine", "NewsItem", "NewsProviderError", "NewsQuerySpec", "QueryBuilder"]
