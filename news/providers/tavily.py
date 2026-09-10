"""Tavily search adapter using the shared HTTP reliability layer."""

from __future__ import annotations

import os
from typing import Any

from infrastructure.network import ProviderAuthError, ReliableHttpClient

from ..query_builder import NewsQuerySpec


class TavilySearchProvider:
    name = "tavily"

    def __init__(self, *, api_key: str | None = None, http_client: ReliableHttpClient | None = None) -> None:
        self._api_key = api_key or os.getenv("TAVILY_API_KEY")
        self._http = http_client or ReliableHttpClient("tavily")

    def search(self, query: str, *, spec: NewsQuerySpec) -> list[dict[str, Any]]:
        if not self._api_key:
            raise ProviderAuthError("Tavily API key is not configured", provider=self.name)
        payload: dict[str, Any] = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": spec.max_results,
            "include_raw_content": True,
        }
        if spec.start_date:
            payload["start_date"] = spec.start_date
        if spec.end_date:
            payload["end_date"] = spec.end_date
        if spec.include_domains:
            payload["include_domains"] = list(spec.include_domains)
        if spec.exclude_domains:
            payload["exclude_domains"] = list(spec.exclude_domains)
        response = self._http.post("https://api.tavily.com/search", json=payload)
        body = response.json()
        results = body.get("results") if isinstance(body, dict) else None
        return results if isinstance(results, list) else []
