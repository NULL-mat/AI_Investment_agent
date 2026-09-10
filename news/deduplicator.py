"""URL, title, and content fingerprint de-duplication."""

from __future__ import annotations

import hashlib
import re
from typing import Iterable

from .models import NewsItem
from .normalizer import canonical_url


def _fingerprint(value: str) -> str:
    normalized = re.sub(r"\W+", " ", value.casefold(), flags=re.UNICODE).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def item_fingerprints(item: NewsItem) -> tuple[str, ...]:
    values = [_fingerprint(canonical_url(item.url)), _fingerprint(item.title)]
    if item.content:
        values.append(_fingerprint(item.content))
    return tuple(values)


def _quality(item: NewsItem) -> tuple[int, int, int]:
    return (len(item.content or ""), int(bool(item.source)), int(bool(item.published_at)))


def deduplicate(items: Iterable[NewsItem]) -> list[NewsItem]:
    output: list[NewsItem] = []
    fingerprints: dict[str, int] = {}
    for item in items:
        matches = {fingerprints[fingerprint] for fingerprint in item_fingerprints(item) if fingerprint in fingerprints}
        if not matches:
            index = len(output)
            output.append(item)
        else:
            index = min(matches)
            if _quality(item) <= _quality(output[index]):
                continue
            output[index] = item
        for fingerprint in item_fingerprints(output[index]):
            fingerprints[fingerprint] = index
    return output
