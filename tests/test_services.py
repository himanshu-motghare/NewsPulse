import unittest
from datetime import date

import requests

from config import CATEGORIES, Config
from errors import (InvalidAPIKeyError, MissingAPIKeyError, NetworkError, ServiceError)
from filters import ArticleFilter
from tests.helpers import (FakeResponse, FakeSession, TempDirTestCase, api_article, ok_payload)


def headlines(*arts):
    return FakeResponse(200, ok_payload(*arts))


class ConfigTests(TempDirTestCase):
    def test_key_storage_and_validation(self):
        cfg = Config(self.tmp)
        self.assertFalse(cfg.has_api_key)
        with self.assertRaises(ServiceError):
            cfg.save_api_key("short")
        with self.assertRaises(ServiceError):
            cfg.save_api_key("has spaces and is long enough!!")
        cfg.save_api_key("0123456789abcdef0123456789abcdef")
        self.assertEqual(Config(self.tmp).api_key, "0123456789abcdef0123456789abcdef")
        self.assertIn("NEWSAPI_KEY=0123456789abcdef", (self.tmp / ".env").read_text())
        cfg.clear_api_key()
        self.assertFalse(cfg.has_api_key)

    def test_placeholder_key_counts_as_missing(self):
        (self.tmp / ".env").write_text("NEWSAPI_KEY=your_api_key_here\n")
        self.assertFalse(Config(self.tmp).has_api_key)


class ServiceDemoTests(TempDirTestCase):
    def test_demo_mode_is_labelled_and_idempotent(self):
        svc = self.make_service(with_key=False)
        self.assertTrue(svc.needs_setup)
        svc.prefs.set("demo_mode", True)
        self.assertFalse(svc.needs_setup)
        r1 = svc.fetch_latest()
        r2 = svc.fetch_latest()
        self.assertEqual((r1.demo, r1.inserted, r2.inserted, r2.duplicates), (True, 20, 0, 20))
        page = svc.query()
        self.assertEqual(page.total, 20)
        self.assertTrue(all(a.is_demo and a.title.startswith("[DEMO]") for a in page.items))

    def test_demo_and_live_data_never_mix(self):
        session = FakeSession(headlines(api_article(1)))
        svc = self.make_service(session)
        svc.prefs.set("categories", "general")
        svc.fetch_latest()
        svc.prefs.set("demo_mode", True)
        svc.fetch_latest()
        self.assertEqual(svc.query().total, 20)                     # demo view: demo only
        self.assertEqual(svc.db.get_counts(True)["total"], 20)
        svc.prefs.set("demo_mode", False)
        page = svc.query()
        self.assertEqual((page.total, page.items[0].is_demo), (1, False))
        self.assertEqual(svc.source_names(), ["Test Wire"])

    def test_live_fetch_without_key_raises_friendly_error(self):
        svc = self.make_service(with_key=False)
        with self.assertRaisesRegex(MissingAPIKeyError, "demo mode"):
            svc.fetch_latest()

    def test_online_search_and_sources_blocked_in_demo(self):
        svc = self.make_service(with_key=False)
        svc.prefs.set("demo_mode", True)
        for call in (lambda: svc.search_online("ai"), svc.refresh_sources):
            with self.assertRaises(ServiceError):
                call()


class ServiceLiveTests(TempDirTestCase):
    def test_fetch_stores_each_category_and_dedupes(self):
        session = FakeSession(headlines(api_article(1), api_article(2)))
        svc = self.make_service(session)
        svc.prefs.set("categories", "technology,sports")
        r = svc.fetch_latest()
        # same 2 URLs returned for both categories -> 2 new, 2 duplicates
        self.assertEqual((r.fetched, r.inserted, r.duplicates), (4, 2, 2))
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0][1]["params"]["country"], "us")
        self.assertEqual({a.category for a in svc.query().items}, {"technology"})   # first category wins over 'general' only
        r2 = svc.fetch_latest()
        self.assertEqual((r2.inserted, r2.duplicates), (0, 4))

    def test_progress_callback(self):
        svc = self.make_service(FakeSession(headlines(api_article(1))))
        svc.prefs.set("categories", "business,health")
        seen = []
        svc.fetch_latest(progress=lambda i, n, m: seen.append((i, n)))
        self.assertEqual(seen, [(0, 2), (1, 2), (2, 2)])

    def test_invalid_key_aborts(self):
        svc = self.make_service(FakeSession(FakeResponse(401, {"status": "error", "code": "apiKeyInvalid", "message": "x"})))
        with self.assertRaises(InvalidAPIKeyError):
            svc.fetch_latest()
        self.assertEqual(svc.db.last_fetch(successful_only=False)["status"], "error")

    def test_network_failure_everywhere_raises(self):
        svc = self.make_service(FakeSession(requests.exceptions.ConnectionError("down")))
        with self.assertRaises(NetworkError):
            svc.fetch_latest()

    def test_partial_failure_keeps_good_results(self):
        svc = self.make_service(FakeSession(headlines(api_article(1)),
                                            FakeResponse(400, {"status": "error", "code": "x", "message": "bad"})))
        svc.prefs.set("categories", "business,health")
        r = svc.fetch_latest()
        self.assertEqual((r.inserted, len(r.errors)), (1, 1))
        self.assertIn("health", r.errors[0])

    def test_online_search_stores_results(self):
        svc = self.make_service(FakeSession(headlines(api_article(7, title="Quantum leap"))))
        r = svc.search_online("quantum", date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(r.inserted, 1)
        self.assertEqual(svc.query(ArticleFilter.from_inputs(keyword="quantum")).total, 1)
        with self.assertRaises(ServiceError):
            svc.search_online("x")

    def test_refresh_sources_and_key_test(self):
        svc = self.make_service(FakeSession(FakeResponse(200, {"status": "ok", "sources": [
            {"id": "bbc-news", "name": "BBC News", "category": "general", "country": "gb"}]})))
        self.assertEqual(svc.refresh_sources(), 1)
        self.assertEqual(svc.list_sources()[0]["name"], "BBC News")
        ok, msg = svc.test_api_key()
        bad = self.make_service(FakeSession(FakeResponse(401, {"status": "error", "code": "apiKeyInvalid", "message": "x"})))
        ok, msg = bad.test_api_key("0123456789abcdef0123456789abcdef")
        self.assertFalse(ok)
        self.assertIn("rejected", msg)
        good = self.make_service(FakeSession(headlines()))
        self.assertTrue(good.test_api_key()[0])

    def test_pagination_and_page_clamping(self):
        svc = self.make_service(with_key=False)
        svc.prefs.set("demo_mode", True)
        svc.prefs.set("page_size", 10)
        svc.fetch_latest()
        p = svc.query(page=2)
        self.assertEqual((p.total, p.pages, len(p.items), p.page), (20, 2, 10, 2))
        self.assertEqual(svc.query(page=99).page, 2)
        self.assertEqual(svc.query(page=-5).page, 1)

    def test_saved_articles_visible_in_any_mode(self):
        svc = self.make_service(with_key=False)
        svc.prefs.set("demo_mode", True)
        svc.fetch_latest()
        aid = svc.query().items[0].id
        svc.save_article(aid, "keep")
        svc.prefs.set("demo_mode", False)
        saved = svc.query(ArticleFilter(saved_only=True))
        self.assertEqual((saved.total, saved.items[0].note), (1, "keep"))
        with self.assertRaises(ServiceError):
            svc.save_article(99999)
        with self.assertRaises(ServiceError):
            svc.unsave_article(99999)

    def test_enrich(self):
        from scraper import PageMetadata

        class FakeScraper:
            def fetch_metadata(self, url):
                return PageMetadata(description="From page", image_url="https://i.example/p.jpg")
        svc = self.make_service(FakeSession(headlines(api_article(1, description="", urlToImage=None))))
        svc._scraper = FakeScraper()
        svc.prefs.set("categories", "general")
        svc.fetch_latest()
        art = svc.query().items[0]
        self.assertEqual(svc.enrich_article(art.id).image_url, "https://i.example/p.jpg")
        with self.assertRaises(ServiceError):
            svc.enrich_article(424242)

    def test_export_respects_filters_and_mode(self):
        svc = self.make_service(with_key=False)
        svc.prefs.set("demo_mode", True)
        svc.fetch_latest()
        path, count = svc.export("csv", ArticleFilter.from_inputs(category="sports"))
        self.assertEqual(count, 3)
        self.assertIn("DEMO", path.name)
        with self.assertRaises(Exception):
            svc.export("csv", ArticleFilter.from_inputs(keyword="nothing-matches-this"))

    def test_dashboard_analytics_and_charts(self):
        svc = self.make_service(with_key=False)
        svc.prefs.set("demo_mode", True)
        svc.fetch_latest()
        d = svc.dashboard()
        self.assertEqual((d["counts"]["total"], d["counts"]["sources"], len(d["recent"])), (20, 5, 6))
        self.assertTrue(d["keywords"])
        frames = svc.analytics_frames()
        self.assertEqual(int(frames["daily"]["articles"].sum()), 20)
        self.assertEqual(int(frames["category"]["articles"].sum()), 20)
        for kind in ("source", "category", "daily"):
            png = svc.chart(kind, theme="light")
            self.assertTrue(png.read_bytes().startswith(b"\x89PNG"), kind)
        with self.assertRaises(ServiceError):
            svc.chart("nope")

    def test_empty_database_charts_do_not_crash(self):
        svc = self.make_service(with_key=False)
        svc.prefs.set("demo_mode", True)
        for kind in ("source", "category", "daily"):
            self.assertTrue(svc.chart(kind).exists())

    def test_preferences_validation_and_persistence(self):
        svc = self.make_service(with_key=False)
        for key, bad in (("country", "zz"), ("categories", "cooking"), ("page_size", 7),
                         ("fetch_size", "abc"), ("appearance", "Neon"), ("nope", "x")):
            with self.assertRaises(ServiceError, msg=key):
                svc.prefs.set(key, bad)
        svc.prefs.set("country", "IN")
        svc.prefs.set("categories", ["sports", "health", "sports"])
        svc.prefs.set("appearance", "Light")
        again = self.make_service(with_key=False)
        self.assertEqual((again.prefs.country, again.prefs.categories, again.prefs.appearance),
                         ("in", ["sports", "health"], "Light"))

    def test_maintenance(self):
        svc = self.make_service(with_key=False)
        svc.prefs.set("demo_mode", True)
        svc.fetch_latest()
        self.assertTrue(svc.backup_database().exists())
        with self.assertRaises(ServiceError):
            svc.purge_older_than(0)
        self.assertEqual(svc.purge_older_than(365), 0)
        self.assertEqual(svc.purge_demo_data(), 20)
        svc.fetch_latest()
        svc.clear_all_data()
        self.assertEqual(svc.query().total, 0)


if __name__ == "__main__":
    unittest.main()


class ExportManagementTests(TempDirTestCase):
    def test_category_counts_are_zero_filled(self):
        svc = self.make_service()
        svc.prefs.set("demo_mode", True)
        svc.fetch_latest()
        counts = svc.category_counts()
        self.assertEqual(set(counts), set(CATEGORIES))
        self.assertEqual(sum(counts.values()), svc.db.get_counts(True)["total"])

    def test_recent_exports_lists_and_deletes_only_inside_folder(self):
        svc = self.make_service()
        svc.prefs.set("demo_mode", True)
        svc.fetch_latest()
        path, _ = svc.export("csv")
        self.assertEqual(svc.recent_exports(), [path])
        outside = self.tmp / "outside.csv"
        outside.write_text("x")
        with self.assertRaises(ServiceError):
            svc.delete_export(outside)
        self.assertTrue(outside.exists())
        svc.delete_export(path)
        self.assertEqual(svc.recent_exports(), [])
        with self.assertRaises(ServiceError):
            svc.delete_export(path)
