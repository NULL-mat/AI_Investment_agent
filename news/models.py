"""Standard news evidence models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class NewsItem:
    title: str
    source: str | None
    url: str
    published_at: datetime | None
    content: str | None
    ticker: str | None
    query: str
    provider: str


@dataclass(frozen=True)
class Evidence:
    item: NewsItem
    snippet: str | None
    retrieved_at: datetime
