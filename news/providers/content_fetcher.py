"""Optional full-content fetcher independent from search providers."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from infrastructure.network import ReliableHttpClient


class ContentFetcher(Protocol):
    def fetch(self, url: str) -> str | None: ...


class RequestsContentFetcher:
    def __init__(self, *, http_client: ReliableHttpClient | None = None, min_content_chars: int = 280) -> None:
        self._http = http_client or ReliableHttpClient("content_fetcher")
        self._min_content_chars = max(1, min_content_chars)

    def fetch(self, url: str) -> str | None:
        response = self._http.get(url, headers={"User-Agent": "ai-investment-agent/1.0"})
        soup = BeautifulSoup(response.content, "html.parser")
        for node in soup(["script", "style", "noscript"]):
            node.decompose()
        text = " ".join(soup.stripped_strings)
        return text if len(text) >= self._min_content_chars else None


class FirecrawlContentFetcher:
    """Adapter slot for deployments that provide Firecrawl separately."""

    def fetch(self, url: str) -> str | None:  # pragma: no cover - integration slot
        raise NotImplementedError("Configure a Firecrawl adapter before using it")
