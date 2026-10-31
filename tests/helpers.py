"""Shared test utilities: fake HTTP session, sample payloads, service factory."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from config import Config
from models import Article
from news_fetcher import NewsAPIClient
from services import NewsService


class FakeResponse:
    def __init__(self, status=200, payload=None, text="", headers=None, content=None):
        self.status_code = status
        self._payload = payload
        self.text = text or ""
        self.headers = headers or {}
        self._content = content if content is not None else self.text.encode()
        self.encoding = "utf-8"

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1):
        yield self._content


class FakeSession:
    """Returns queued responses (or raises queued exceptions) and records calls."""

    def __init__(self, *queue):
        self.queue = list(queue)
        self.calls = []
        self.headers = {}

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        item = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        if isinstance(item, Exception):
            raise item
        return item


def api_article(n, title=None, source="Test Wire", url=None, published="2026-10-31T10:00:00Z", **extra):
    data = {"source": {"id": f"test-wire", "name": source}, "author": "A. Writer",
            "title": title or f"Headline number {n}", "description": f"Description {n}",
            "url": url or f"https://news.example.org/story-{n}", "urlToImage": f"https://img.example.org/{n}.jpg",
            "publishedAt": published, "content": f"Content {n} [+100 chars]"}
    data.update(extra)
    return data


def ok_payload(*articles):
    return {"status": "ok", "totalResults": len(articles), "articles": list(articles)}


def make_article(n=1, **kw):
    base = dict(title=f"Title {n}", url=f"https://news.example.org/a{n}", source_name="Test Wire",
                description=f"Desc {n}", published_at="2026-10-31T10:00:00Z", category="general")
    base.update(kw)
    return Article(**base)


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        env = mock.patch.dict("os.environ", {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        import os
        os.environ.pop("NEWSAPI_KEY", None)

    def make_service(self, session=None, with_key=True):
        config = Config(self.tmp)
        if with_key:
            config.save_api_key("0123456789abcdef0123456789abcdef")
        factory = (lambda key: NewsAPIClient(key, session=session, backoff=0)) if session else None
        return NewsService(config, client_factory=factory)
