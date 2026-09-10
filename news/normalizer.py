"""Normalize search-provider records into traceable NewsItem objects."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import NewsItem
from .query_builder import NewsQuerySpec

_TRACKING_KEYS = {"gclid", "fbclid", "mc_cid", "mc_eid"}


def canonical_url(url: str) -> str:
    parsed = urlsplit(str(url).strip())
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_KEYS]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", urlencode(sorted(query)), ""))


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_published_at(value: object) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def normalize_result(raw: object, *, spec: NewsQuerySpec, query: str, provider: str) -> NewsItem | None:
    if isinstance(raw, NewsItem):
        return raw
    if not isinstance(raw, dict):
        return None
    url = canonical_url(raw.get("url", "")) if raw.get("url") else ""
    title = _clean(raw.get("title") or raw.get("headline"))
    if not url or not title:
        return None
    source = _clean(raw.get("source") or raw.get("domain")) or None
    content = _clean(raw.get("content") or raw.get("raw_content") or raw.get("snippet")) or None
    return NewsItem(
        title=title,
        source=source,
        url=url,
        published_at=parse_published_at(raw.get("published_at") or raw.get("published_date") or raw.get("date")),
        content=content,
        ticker=raw.get("ticker") or spec.ticker,
        query=query,
        provider=provider,
    )


def within_date_window(item: NewsItem, spec: NewsQuerySpec) -> bool:
    if item.published_at is None:
        return True
    item_date = item.published_at.date().isoformat()
    return (not spec.start_date or item_date >= spec.start_date) and (not spec.end_date or item_date <= spec.end_date)
