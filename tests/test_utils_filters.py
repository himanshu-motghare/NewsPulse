import unittest
from datetime import date

from errors import FilterError
from filters import ArticleFilter
from utils import (clean_text, extract_keywords, normalize_timestamp, normalize_url,
                   parse_date, truncate)


class UrlTests(unittest.TestCase):
    def test_equivalent_urls_share_a_key(self):
        base = normalize_url("https://example.com/news/story")
        for variant in ("HTTPS://Example.com/news/story/", "https://www.example.com/news/story#comments",
                        "https://example.com/news/story?utm_source=x&utm_medium=y&fbclid=1",
                        "https://example.com:443/news/story"):
            self.assertEqual(normalize_url(variant), base, variant)

    def test_meaningful_query_params_kept_and_sorted(self):
        self.assertEqual(normalize_url("https://e.com/a?b=2&a=1"), normalize_url("https://e.com/a?a=1&b=2"))
        self.assertNotEqual(normalize_url("https://e.com/a?id=1"), normalize_url("https://e.com/a?id=2"))

    def test_invalid_urls(self):
        for bad in ("", "ftp://x.com/a", "javascript:alert(1)", "not a url", None):
            with self.assertRaises(ValueError):
                normalize_url(bad)


class DateTextTests(unittest.TestCase):
    def test_parse_date(self):
        self.assertEqual(parse_date("2026-10-31"), date(2026, 10, 31))
        for bad in ("31-10-2026", "2026-13-01", "abc", "2026-02-30"):
            with self.assertRaises(ValueError):
                parse_date(bad)

    def test_normalize_timestamp(self):
        self.assertEqual(normalize_timestamp("2026-10-31T10:15:00Z"), "2026-10-31T10:15:00Z")
        self.assertEqual(normalize_timestamp("2026-10-31T15:45:00+05:30"), "2026-10-31T10:15:00Z")
        self.assertEqual(normalize_timestamp("2026-10-31T10:15:00.123Z"), "2026-10-31T10:15:00Z")
        self.assertEqual(normalize_timestamp("garbage"), "")

    def test_text_helpers(self):
        self.assertEqual(clean_text("<p>Hello&nbsp;&amp; <b>bye</b></p>"), "Hello & bye")
        self.assertEqual(truncate("abcdef", 4), "abc…")

    def test_keywords_ignore_stopwords_and_count_once_per_title(self):
        kws = dict(extract_keywords(["The AI boom and AI chips", "Chips for the future", "[DEMO] sample demo"]))
        self.assertEqual(kws["chips"], 2)
        self.assertEqual(kws["boom"], 1)
        self.assertNotIn("the", kws)
        self.assertNotIn("demo", kws)


class FilterValidationTests(unittest.TestCase):
    def test_valid_inputs(self):
        f = ArticleFilter.from_inputs(keyword=" ai ", category="Technology", date_from="2026-10-01", date_to="2026-10-31")
        self.assertEqual((f.keyword, f.category), ("ai", "technology"))
        self.assertTrue(f.is_active)
        self.assertIn("category=technology", f.describe())

    def test_invalid_inputs_raise_filter_error(self):
        for kwargs in ({"category": "cooking"}, {"date_from": "yesterday-ish"},
                       {"date_from": "2026-11-01", "date_to": "2026-10-01"}, {"sort": "random"},
                       {"keyword": "x" * 201}):
            with self.assertRaises(FilterError, msg=str(kwargs)):
                ArticleFilter.from_inputs(**kwargs)

    def test_all_means_no_filter(self):
        f = ArticleFilter.from_inputs(source="All sources", category="All")
        self.assertFalse(f.is_active)

    def test_sql_is_parameterised(self):
        f = ArticleFilter.from_inputs(keyword="'; DROP TABLE articles;--")
        where, params = f.to_sql()
        self.assertNotIn("DROP", where)                       # user text never reaches the SQL string
        self.assertTrue(any("DROP" in str(p) for p in params))  # ...it is bound as a parameter instead

    def test_quoted_phrases(self):
        f = ArticleFilter.from_inputs(keyword='"climate summit" report')
        self.assertEqual(f.terms(), ["climate summit", "report"])


if __name__ == "__main__":
    unittest.main()
