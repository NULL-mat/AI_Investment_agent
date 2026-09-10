"""Small JSON cache for normalized news with incremental merge support."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable

from .deduplicator import deduplicate
from .models import NewsItem
from .query_builder import NewsQuerySpec
from .normalizer import parse_published_at


class NewsCache:
    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory or os.getenv("NEWS_CACHE_DIR", "data/news_cache")).expanduser()
        self.directory.mkdir(parents=True, exist_ok=True)

    def key(self, spec: NewsQuerySpec, provider: str, query: str) -> str:
        payload = {
            "provider": provider,
            "query": query,
            "ticker": spec.ticker,
            "start_date": spec.start_date,
            "end_date": spec.end_date,
            "max_results": spec.max_results,
            "include_domains": spec.include_domains,
            "exclude_domains": spec.exclude_domains,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, spec: NewsQuerySpec, provider: str, query: str) -> list[NewsItem] | None:
        path = self._path(self.key(spec, provider, query))
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return [self._from_dict(row) for row in payload.get("items", [])]
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None

    def merge(self, spec: NewsQuerySpec, provider: str, query: str, items: Iterable[NewsItem]) -> list[NewsItem]:
        existing = self.get(spec, provider, query) or []
        merged = deduplicate([*existing, *items])
        return self._write(spec, provider, query, merged)

    def set(self, spec: NewsQuerySpec, provider: str, query: str, items: Iterable[NewsItem]) -> list[NewsItem]:
        """Replace a cache entry after a non-incremental refresh."""

        return self._write(spec, provider, query, deduplicate(items))

    def _write(self, spec: NewsQuerySpec, provider: str, query: str, items: Iterable[NewsItem]) -> list[NewsItem]:
        merged = list(items)
        merged.sort(key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        merged = merged[: spec.max_results]
        path = self._path(self.key(spec, provider, query))
        payload = {"provider": provider, "query": query, "updated_at": datetime.now(timezone.utc).isoformat(), "items": [asdict(item) for item in merged]}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
        temporary.replace(path)
        return merged

    @staticmethod
    def _from_dict(row: dict) -> NewsItem:
        return NewsItem(
            title=row["title"],
            source=row.get("source"),
            url=row["url"],
            published_at=parse_published_at(row.get("published_at")),
            content=row.get("content"),
            ticker=row.get("ticker"),
            query=row["query"],
            provider=row["provider"],
        )
