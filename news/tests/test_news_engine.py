from __future__ import annotations

from datetime import datetime, timezone

import pytest

from news.cache import NewsCache
from news.deduplicator import deduplicate
from news.models import NewsItem
from news.normalizer import normalize_result
from news.query_builder import NewsQuerySpec
from news.service import NewsEngine, NewsProviderError


def spec(**kwargs):
    return NewsQuerySpec(ticker="600000", company_name="Example Co", **kwargs)


def test_url_title_and_content_duplicates_keep_richer_content():
    first = NewsItem("Example earnings", "wire", "https://news.test/a?utm_source=x", datetime(2026, 1, 1, tzinfo=timezone.utc), "short", "600000", "q", "tavily")
    richer = NewsItem("EXAMPLE   EARNINGS", "wire", "https://news.test/a", first.published_at, "a much longer article body", "600000", "q", "tavily")
    same_content = NewsItem("Other headline", "wire", "https://news.test/b", first.published_at, richer.content, "600000", "q", "tavily")
    result = deduplicate([first, richer, same_content])
    assert len(result) == 1
    assert result[0].content == richer.content


def test_date_window_is_inclusive_and_missing_date_is_retained(tmp_path):
    query_spec = spec(start_date="2026-01-01", end_date="2026-01-31")
    assert normalize_result({"title": "start", "url": "https://x.test/1", "published_date": "2026-01-01"}, spec=query_spec, query="q", provider="tavily")
    provider = type("Provider", (), {"name": "fake", "search": lambda self, query, *, spec: [
        {"title": "inside", "url": "https://x.test/inside", "published_date": "2026-01-31", "content": "ok"},
        {"title": "outside", "url": "https://x.test/outside", "published_date": "2026-02-01"},
        {"title": "undated", "url": "https://x.test/undated"},
    ]})()
    items = NewsEngine((provider,), cache=NewsCache(tmp_path)).search(query_spec, refresh=True)
    assert {item.title for item in items} == {"inside", "undated"}


class SequenceProvider:
    name = "sequence"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def search(self, query, *, spec):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_provider_fallback_and_all_failed_error(tmp_path):
    failed = SequenceProvider([RuntimeError("tavily unavailable")])
    backup = SequenceProvider([[{"title": "backup", "url": "https://x.test/backup"}]])
    engine = NewsEngine((failed, backup), cache=NewsCache(tmp_path))
    assert [item.title for item in engine.search(spec(), refresh=True)] == ["backup"]
    assert failed.calls == 1 and backup.calls == 1

    all_failed = NewsEngine((SequenceProvider([RuntimeError("one")]), SequenceProvider([RuntimeError("two")])), cache=NewsCache(tmp_path / "failed"))
    with pytest.raises(NewsProviderError):
        all_failed.search(spec(), refresh=True)


def test_cache_hit_and_incremental_merge(tmp_path):
    provider = SequenceProvider([
        [{"title": "old", "url": "https://x.test/old", "published_date": "2026-01-01"}],
        [{"title": "new", "url": "https://x.test/new", "published_date": "2026-01-02"}],
    ])
    engine = NewsEngine((provider,), cache=NewsCache(tmp_path))
    assert [x.title for x in engine.search(spec(), refresh=True)] == ["old"]
    assert [x.title for x in engine.search(spec())] == ["old"]
    assert provider.calls == 1
    merged = engine.search(spec(), refresh=True, incremental=True)
    assert {x.title for x in merged} == {"old", "new"}
    assert provider.calls == 2
