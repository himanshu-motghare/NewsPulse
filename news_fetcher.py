"""NewsAPI client (https://newsapi.org).

Responsibilities: build requests, send the API key in a header (never in the
URL, so it cannot leak into logs), retry transient failures, translate every
failure mode into a specific :class:`errors.NewsAPIError` subclass and convert
JSON into :class:`models.Article` objects.  No database access happens here.
"""
from __future__ import annotations

import time
from datetime import date
from typing import Any, Dict, List, Optional

import requests

from config import NEWSAPI_BASE_URL, USER_AGENT
from errors import (InvalidAPIKeyError, MissingAPIKeyError, NetworkError,
                    NewsAPIError, RateLimitError)
from logger import get_logger
from models import Article
from utils import clean_text, normalize_timestamp

log = get_logger("newsapi")

_REMOVED_MARKERS = ("[removed]", "removed.com")
_INVALID_KEY_CODES = {"apiKeyInvalid", "apiKeyMissing", "apiKeyDisabled"}
_RATE_LIMIT_CODES = {"rateLimited", "apiKeyExhausted"}


class NewsAPIClient:
    """Small, testable wrapper around the NewsAPI v2 REST interface."""

    def __init__(self, api_key: str, session: Optional[requests.Session] = None,
                 timeout: float = 15.0, max_retries: int = 2, backoff: float = 1.0,
                 base_url: str = NEWSAPI_BASE_URL) -> None:
        self.api_key = (api_key or "").strip()
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.base_url = base_url.rstrip("/")

    # ------------------------------------------------------------ HTTP --
    def _get(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key:
            raise MissingAPIKeyError(
                "No NewsAPI key configured. Add NEWSAPI_KEY to your .env file "
                "(or Settings in the app), or use demo mode."
            )
        params = {k: v for k, v in params.items() if v not in (None, "")}
        headers = {"X-Api-Key": self.api_key, "User-Agent": USER_AGENT}
        url = f"{self.base_url}/{endpoint}"
        failure: Optional[NewsAPIError] = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.exceptions.Timeout:
                failure = NetworkError("The request to NewsAPI timed out. Check your connection and try again.")
            except requests.exceptions.ConnectionError:
                failure = NetworkError("Cannot reach NewsAPI. Check your internet connection.")
            except requests.exceptions.RequestException as exc:
                failure = NetworkError(f"Network problem while contacting NewsAPI: {exc}")
            else:
                if response.status_code >= 500 and attempt < self.max_retries:
                    failure = NewsAPIError(f"NewsAPI server error (HTTP {response.status_code}).")
                else:
                    return self._handle_response(response)
            log.warning("Request to %s failed (attempt %d/%d): %s", endpoint, attempt + 1,
                        self.max_retries + 1, failure)
            if attempt < self.max_retries:
                time.sleep(self.backoff * (2 ** attempt))
        assert failure is not None
        raise failure

    @staticmethod
    def _handle_response(response: requests.Response) -> Dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            raise NewsAPIError(f"NewsAPI returned an unreadable response (HTTP {response.status_code}).") from None
        if not isinstance(data, dict):
            raise NewsAPIError("NewsAPI returned an unexpected response format.")
        if response.status_code == 200 and data.get("status") == "ok":
            return data

        code = data.get("code", "")
        message = data.get("message") or f"HTTP {response.status_code}"
        log.error("NewsAPI error %s (HTTP %s): %s", code, response.status_code, message)
        if code in _INVALID_KEY_CODES or response.status_code == 401:
            raise InvalidAPIKeyError("NewsAPI rejected your API key. Check NEWSAPI_KEY in Settings or .env.")
        if code in _RATE_LIMIT_CODES or response.status_code == 429:
            raise RateLimitError("NewsAPI request limit reached. Wait a while (free plans allow 100 requests/day).")
        if code == "maximumResultsReached":
            raise NewsAPIError("Your NewsAPI plan does not allow results this deep (free plans: first 100 results).")
        raise NewsAPIError(f"NewsAPI error: {message}")

    # ---------------------------------------------------------- parsing --
    @staticmethod
    def parse_article(raw: Dict[str, Any], category: str = "general") -> Optional[Article]:
        """Convert one API article; returns None for removed/unusable entries."""
        title = clean_text(raw.get("title") or "")
        url = (raw.get("url") or "").strip()
        if not title or not url:
            return None
        if any(m in title.lower() or m in url.lower() for m in _REMOVED_MARKERS):
            return None
        source = raw.get("source") or {}
        return Article(
            title=title,
            url=url,
            source_name=clean_text(source.get("name") or "") or "Unknown source",
            source_api_id=source.get("id") or "",
            description=clean_text(raw.get("description") or ""),
            content=clean_text(raw.get("content") or ""),
            author=clean_text(raw.get("author") or ""),
            image_url=(raw.get("urlToImage") or "").strip(),
            published_at=normalize_timestamp(raw.get("publishedAt") or ""),
            category=category,
        )

    def _articles(self, data: Dict[str, Any], category: str) -> List[Article]:
        parsed = (self.parse_article(r, category) for r in data.get("articles", []) if isinstance(r, dict))
        return [a for a in parsed if a]

    # ---------------------------------------------------------- public --
    def top_headlines(self, country: str = "us", category: str = "", sources: str = "",
                      query: str = "", page_size: int = 30, page: int = 1) -> List[Article]:
        """Latest headlines. NOTE: NewsAPI forbids mixing ``sources`` with country/category."""
        params: Dict[str, Any] = {"pageSize": page_size, "page": page, "q": query}
        if sources:
            params["sources"] = sources
        else:
            params.update(country=country, category=category)
        data = self._get("top-headlines", params)
        return self._articles(data, category or "general")

    def search(self, query: str, date_from: Optional[date] = None, date_to: Optional[date] = None,
               sources: str = "", language: str = "en", sort_by: str = "publishedAt",
               page_size: int = 50, page: int = 1) -> List[Article]:
        """Full-text search across NewsAPI's archive (``/everything``)."""
        data = self._get("everything", {
            "q": query, "sources": sources, "language": language, "sortBy": sort_by,
            "from": date_from.isoformat() if date_from else None,
            "to": date_to.isoformat() if date_to else None,
            "pageSize": page_size, "page": page,
        })
        return self._articles(data, "general")

    def list_sources(self, country: str = "", language: str = "", category: str = "") -> List[Dict[str, str]]:
        data = self._get("top-headlines/sources", {"country": country, "language": language, "category": category})
        return [s for s in data.get("sources", []) if isinstance(s, dict) and s.get("name")]

    def verify_key(self) -> None:
        """Make the cheapest possible request; raises if the key/network is bad."""
        self._get("top-headlines", {"country": "us", "pageSize": 1})
