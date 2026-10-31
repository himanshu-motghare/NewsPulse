import unittest
from datetime import date

import requests

from errors import (InvalidAPIKeyError, MissingAPIKeyError, NetworkError, NewsAPIError, RateLimitError)
from news_fetcher import NewsAPIClient
from tests.helpers import FakeResponse, FakeSession, api_article, ok_payload


def client(*queue, **kw):
    session = FakeSession(*queue)
    return NewsAPIClient("0123456789abcdef0123456789abcdef", session=session, backoff=0, **kw), session


class NewsAPIClientTests(unittest.TestCase):
    def test_top_headlines_parses_articles(self):
        c, s = client(FakeResponse(200, ok_payload(api_article(1), api_article(2))))
        arts = c.top_headlines(country="us", category="technology")
        self.assertEqual([a.title for a in arts], ["Headline number 1", "Headline number 2"])
        a = arts[0]
        self.assertEqual((a.category, a.source_name, a.published_at, a.is_demo),
                         ("technology", "Test Wire", "2026-10-31T10:00:00Z", False))

    def test_api_key_is_sent_in_header_not_url(self):
        c, s = client(FakeResponse(200, ok_payload()))
        c.top_headlines()
        url, kwargs = s.calls[0]
        self.assertEqual(kwargs["headers"]["X-Api-Key"], c.api_key)
        self.assertNotIn(c.api_key, url)
        self.assertNotIn(c.api_key, str(kwargs["params"]))

    def test_removed_and_incomplete_articles_skipped(self):
        c, _ = client(FakeResponse(200, ok_payload(
            api_article(1, title="[Removed]", url="https://removed.com"), api_article(2, title="   "),
            {"title": "No url"}, api_article(3))))
        self.assertEqual([a.title for a in c.top_headlines()], ["Headline number 3"])

    def test_html_in_text_is_cleaned(self):
        c, _ = client(FakeResponse(200, ok_payload(api_article(1, description="<p>Hi &amp; <b>bye</b></p>"))))
        self.assertEqual(c.top_headlines()[0].description, "Hi & bye")

    def test_sources_cannot_mix_with_country_or_category(self):
        c, s = client(FakeResponse(200, ok_payload()))
        c.top_headlines(country="us", category="sports", sources="bbc-news")
        params = s.calls[0][1]["params"]
        self.assertEqual(params["sources"], "bbc-news")
        self.assertNotIn("country", params)
        self.assertNotIn("category", params)

    def test_search_sends_dates(self):
        c, s = client(FakeResponse(200, ok_payload(api_article(1))))
        c.search("ai", date(2026, 10, 1), date(2026, 10, 31))
        url, kw = s.calls[0]
        self.assertTrue(url.endswith("/everything"))
        self.assertEqual((kw["params"]["from"], kw["params"]["to"], kw["params"]["q"]), ("2026-10-01", "2026-10-31", "ai"))

    def test_invalid_key(self):
        c, _ = client(FakeResponse(401, {"status": "error", "code": "apiKeyInvalid", "message": "bad"}))
        with self.assertRaises(InvalidAPIKeyError):
            c.top_headlines()

    def test_rate_limited(self):
        c, _ = client(FakeResponse(429, {"status": "error", "code": "rateLimited", "message": "slow"}))
        with self.assertRaises(RateLimitError):
            c.top_headlines()

    def test_other_api_error_message_is_surfaced(self):
        c, _ = client(FakeResponse(400, {"status": "error", "code": "parametersMissing", "message": "Missing q"}))
        with self.assertRaisesRegex(NewsAPIError, "Missing q"):
            c.search("x")

    def test_missing_key(self):
        with self.assertRaises(MissingAPIKeyError):
            NewsAPIClient("", session=FakeSession(FakeResponse())).top_headlines()

    def test_network_errors_are_retried_then_reported(self):
        c, s = client(requests.exceptions.ConnectionError("dns"))
        with self.assertRaisesRegex(NetworkError, "internet connection"):
            c.top_headlines()
        self.assertEqual(len(s.calls), 3)             # 1 try + 2 retries

    def test_timeout(self):
        c, _ = client(requests.exceptions.Timeout())
        with self.assertRaisesRegex(NetworkError, "timed out"):
            c.top_headlines()

    def test_retry_recovers_from_transient_failure(self):
        c, s = client(requests.exceptions.ConnectionError("blip"), FakeResponse(503, {"status": "error"}),
                      FakeResponse(200, ok_payload(api_article(1))))
        self.assertEqual(len(c.top_headlines()), 1)
        self.assertEqual(len(s.calls), 3)

    def test_non_json_response(self):
        c, _ = client(FakeResponse(200, None, text="<html>oops</html>"))
        with self.assertRaisesRegex(NewsAPIError, "unreadable"):
            c.top_headlines()

    def test_list_sources_and_verify(self):
        c, _ = client(FakeResponse(200, {"status": "ok", "sources": [{"id": "bbc-news", "name": "BBC News"}, {"id": "x"}]}))
        self.assertEqual([s["name"] for s in c.list_sources()], ["BBC News"])
        c2, _ = client(FakeResponse(200, ok_payload()))
        c2.verify_key()


if __name__ == "__main__":
    unittest.main()
