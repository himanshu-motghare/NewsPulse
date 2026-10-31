"""Headless GUI smoke tests.

These drive the *real* ``NewsPulseApp`` - real pages, service layer, SQLite
database and background threads - on top of the strict fake toolkit in
``fake_gui.py``.  They verify wiring and behaviour (does clicking Save store a
bookmark? does Export write a valid file? does a network failure show an error
instead of crashing?).  They do not verify pixels; ``test_gui_real.py`` runs
the same app on a real display when Tk and CustomTkinter are available.
"""
import importlib
import json
import logging
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import openpyxl
import pandas as pd
import requests

from filters import ArticleFilter
from tests import fake_gui
from utils import utc_now
from tests.helpers import (FakeResponse, FakeSession, TempDirTestCase, api_article, make_article,
                           ok_payload)

NAV_KEYS = ["dashboard", "news", "search", "categories", "saved", "sources", "export", "analytics",
            "settings", "about"]


def setUpModule():
    fake_gui.install()


def tearDownModule():
    fake_gui.uninstall()


class _ErrorLogs(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.records = []

    def emit(self, record):
        self.records.append(record)


class GuiTestCase(TempDirTestCase):
    def setUp(self):
        super().setUp()
        fake_gui.STATE.update(confirm=True, input_dialog="", appearance="Dark")
        self.futures = []
        original_submit = ThreadPoolExecutor.submit

        def tracking_submit(pool, fn, *a, **k):
            future = original_submit(pool, fn, *a, **k)
            self.futures.append(future)
            return future

        for patcher in (mock.patch.object(ThreadPoolExecutor, "submit", tracking_submit),
                        mock.patch("utils.subprocess.Popen"), mock.patch("webbrowser.open", return_value=True)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.error_logs = _ErrorLogs()
        logger = logging.getLogger("newspulse")
        logger.addHandler(self.error_logs)
        self.addCleanup(logger.removeHandler, self.error_logs)
        self.toasts = []

    # ----------------------------------------------------------- helpers --
    def make_app(self, demo=False, with_key=True, session=None):
        svc = self.make_service(session=session, with_key=with_key)
        if demo:
            svc.prefs.set("demo_mode", True)
        app_module = importlib.import_module("ui.app")
        app = app_module.NewsPulseApp(svc)
        original = app.toast.show

        def recording(message, kind="info", ms=6000):
            self.toasts.append((kind, message))
            original(message, kind, ms)

        app.toast.show = recording
        self.addCleanup(app._on_close)
        return app

    def settle(self, app, timeout=10.0):
        """Pump the event loop until all background work and callbacks are finished."""
        deadline, quiet = time.time() + timeout, 0
        while time.time() < deadline:
            app.pump()
            busy = (any(not f.done() for f in self.futures) or not app.runner._queue.empty() or app._busy)
            quiet = 0 if busy else quiet + 1
            if quiet >= 3:
                return
            time.sleep(0.004)
        self.fail("The GUI did not settle - a background task or callback never finished.")

    def go(self, app, key, **params):
        app.navigate(key, **params)
        self.settle(app)
        return app._pages[key]

    @staticmethod
    def buttons(widget, text=None):
        found = [w for w in widget.walk() if w.__class__.__name__ == "CTkButton"]
        return [b for b in found if text is None or b.cget("text") == text]

    def cards(self, page):
        cls = importlib.import_module("ui.news_cards").ArticleCard
        return [w for w in page.browser.list.walk() if isinstance(w, cls)]

    def last_toast(self):
        return self.toasts[-1] if self.toasts else (None, "")

    def assert_no_logged_errors(self):
        self.assertEqual([r.getMessage() for r in self.error_logs.records], [])


# ====================================================================== #
class DemoModeTests(GuiTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.make_app(demo=True, with_key=False)
        self.settle(self.app)           # initial auto-load of demo articles

    def test_every_page_opens_via_the_sidebar_without_errors(self):
        for key in NAV_KEYS:
            with self.subTest(page=key):
                self.app.sidebar._buttons[key].invoke()
                self.settle(self.app)
                self.assertEqual(self.app._current, key)
                self.assertEqual(self.app.title_label.cget("text"), importlib.import_module("ui.app").PAGE_META[key][0])
                self.assertTrue(self.app._pages[key].winfo_ismapped())
        self.assert_no_logged_errors()
        self.assertFalse([t for t in self.toasts if t[0] == "error"], self.toasts)

    def test_demo_banner_and_badge_are_shown_and_clearly_labelled(self):
        self.assertTrue(self.app.banner.winfo_ismapped())
        self.assertIn("not real news", self.app.banner_text.cget("text"))
        self.assertIn("DEMO", self.app.sidebar.mode_badge.cget("text"))

    def test_dashboard_numbers_match_the_database(self):
        page = self.go(self.app, "dashboard")
        counts = self.app.service.db.get_counts(True)
        self.assertGreater(counts["total"], 0)
        for key, card in page.cards.items():
            self.assertEqual(card.value.cget("text"), f"{counts[key]:,}", key)
        self.assertTrue(page.chart.figure is not None)
        self.assertTrue(page.recent_list.winfo_children())
        self.assertTrue(page.keyword_box.winfo_children())

    def test_trending_keyword_opens_search_with_that_keyword(self):
        page = self.go(self.app, "dashboard")
        first = self.buttons(page.keyword_box)[0]
        word = first.cget("text").split()[0]
        first.invoke()
        self.settle(self.app)
        self.assertEqual(self.app._current, "search")
        self.assertEqual(self.app._pages["search"].browser.bar.keyword.get(), word)
        expected = self.app.service.db.count_articles(ArticleFilter(keyword=word, demo=True))
        self.assertEqual(len(self.cards(self.app._pages["search"])), min(expected, 20))

    def test_all_news_lists_cards_and_marks_them_demo(self):
        page = self.go(self.app, "news")
        cards = self.cards(page)
        self.assertGreater(len(cards), 0)
        labels = [w.cget("text") for card in cards for w in card.walk() if w.__class__.__name__ == "CTkLabel"]
        self.assertIn(" DEMO ", labels)

    def test_save_and_unsave_from_a_card_persists_and_shows_on_saved_page(self):
        news = self.go(self.app, "news")
        card = self.cards(news)[0]
        article_id = card.article.id
        card.save_btn.invoke()
        self.assertEqual(self.app.service.db.count_saved(), 1)
        self.assertEqual(card.save_btn.cget("text"), "★ Saved")
        saved = self.go(self.app, "saved")
        self.assertEqual([c.article.id for c in self.cards(saved)], [article_id])
        self.cards(saved)[0].save_btn.invoke()          # un-save from the saved page
        self.settle(self.app)
        self.assertEqual(self.app.service.db.count_saved(), 0)
        self.assertEqual(self.cards(saved), [])
        self.assertTrue(any(isinstance(w, importlib.import_module("ui.components").EmptyState)
                            for w in saved.browser.list.walk()))

    def test_saved_note_can_be_edited(self):
        news = self.go(self.app, "news")
        card = self.cards(news)[0]
        card.save_btn.invoke()
        fake_gui.STATE["input_dialog"] = "remember this"
        card._edit_note()
        self.assertEqual(self.app.service.get_article(card.article.id).note, "remember this")

    def test_search_filters_combine_and_match_the_database(self):
        page = self.go(self.app, "search")
        bar = page.browser.bar
        db = self.app.service.db

        bar.keyword.type("python")
        bar._on_apply()
        self.settle(self.app)
        expected = db.count_articles(ArticleFilter(keyword="python", demo=True))
        self.assertGreater(expected, 0)
        self.assertEqual(len(self.cards(page)), expected)

        bar.category.set("Technology")                    # keyword AND category
        bar._on_apply()
        self.settle(self.app)
        expected = db.count_articles(ArticleFilter(keyword="python", category="technology", demo=True))
        self.assertEqual(len(self.cards(page)), expected)

        bar.clear()                                       # "Clear filters" button
        self.settle(self.app)
        self.assertEqual(bar.keyword.get(), "")
        self.assertEqual(bar.category.get(), "All categories")
        self.assertEqual(len(self.cards(page)), min(db.count_articles(ArticleFilter(demo=True)), 20))

    def test_category_filter_really_narrows_the_results(self):
        page = self.go(self.app, "search")
        bar, db = page.browser.bar, self.app.service.db
        total = db.count_articles(ArticleFilter(demo=True))
        bar.keyword.type("sample")                         # matches every demo headline...
        bar.category.set("Science")                        # ...so only the category can narrow it
        bar._on_apply()
        self.settle(self.app)
        science = db.count_articles(ArticleFilter(category="science", demo=True))
        self.assertTrue(0 < science < total)
        cards = self.cards(page)
        self.assertEqual(len(cards), science)
        self.assertTrue(all(c.article.category == "science" for c in cards))

    def test_source_and_date_filters_work_through_the_ui(self):
        page = self.go(self.app, "news")
        bar, db = page.browser.bar, self.app.service.db
        source = self.app.service.source_names()[0]
        bar.source.set(source)
        bar._on_apply()
        self.settle(self.app)
        self.assertEqual(len(self.cards(page)),
                         min(db.count_articles(ArticleFilter(source=source, demo=True)), 20))

        bar.reset()
        bar.preset.choose("Today")                         # fills both dates and applies
        self.settle(self.app)
        today = utc_now().date().isoformat()
        self.assertEqual((bar.date_from.get(), bar.date_to.get()), (today, today))
        flt = ArticleFilter(date_from=ArticleFilter.from_inputs(date_from=bar.date_from.get()).date_from,
                            date_to=ArticleFilter.from_inputs(date_to=bar.date_to.get()).date_to, demo=True)
        self.assertEqual(len(self.cards(page)), min(db.count_articles(flt), 20))

    def test_invalid_date_shows_a_warning_and_does_not_crash(self):
        page = self.go(self.app, "news")
        before = len(self.cards(page))
        page.browser.bar.date_from.type("31/10/2026")
        page.browser.bar._on_apply()
        self.settle(self.app)
        self.assertEqual(self.last_toast()[0], "warning")
        self.assertEqual(len(self.cards(page)), before)
        page.browser.bar.date_from.type("2026-12-01")
        page.browser.bar.date_to.type("2026-01-01")      # start after end
        page.browser.bar._on_apply()
        self.assertEqual(self.last_toast()[0], "warning")

    def test_no_results_shows_a_friendly_empty_state(self):
        page = self.go(self.app, "search")
        page.browser.bar.keyword.type("zzzz-no-such-word")
        page.browser.bar._on_apply()
        self.settle(self.app)
        self.assertEqual(self.cards(page), [])
        texts = [w.cget("text") for w in page.browser.list.walk() if w.__class__.__name__ == "CTkLabel"]
        self.assertIn("No matching articles", texts)

    def test_online_search_is_disabled_in_demo_mode(self):
        page = self.go(self.app, "search")
        self.assertEqual(page.online_btn.cget("state"), "disabled")

    def test_categories_page_chips_filter_the_list(self):
        page = self.go(self.app, "categories")
        chips = self.buttons(page.chips)
        self.assertEqual(len(chips), 8)                    # All + 7 categories
        tech = next(c for c in chips if c.cget("text").startswith("Technology"))
        tech.invoke()
        self.settle(self.app)
        db = self.app.service.db
        expected = db.count_articles(ArticleFilter(category="technology", demo=True))
        self.assertEqual(len(self.cards(page)), min(expected, 20))
        self.assertTrue(all(c.article.category == "technology" for c in self.cards(page)))

    def test_sources_page_lists_sources_and_view_articles_filters_news(self):
        page = self.go(self.app, "sources")
        self.assertEqual(page.refresh_btn.cget("state"), "disabled")       # needs live mode
        view = [b for b in self.buttons(page.list, "View articles") if b.cget("state") != "disabled"]
        self.assertTrue(view)
        view[0].invoke()
        self.settle(self.app)
        self.assertEqual(self.app._current, "news")
        news = self.app._pages["news"]
        chosen = news.browser.bar.source.get()
        self.assertNotEqual(chosen, "All sources")
        self.assertTrue(all(c.article.source_name == chosen for c in self.cards(news)))

    def test_sources_filter_box_narrows_the_list(self):
        page = self.go(self.app, "sources")
        everything = len(self.buttons(page.list, "View articles"))
        page.search.type("tech")
        page._render()
        self.assertLess(len(self.buttons(page.list, "View articles")), everything)
        page.search.type("no-such-publisher")
        page._render()
        self.assertEqual(self.buttons(page.list, "View articles"), [])

    def test_analytics_draws_all_three_charts_and_saves_png(self):
        page = self.go(self.app, "analytics")
        for kind, chart in page.charts.items():
            self.assertIsNotNone(chart.figure, kind)
        page.range.choose("7 days")
        self.settle(self.app)
        self.assertEqual(page.days, 7)
        for button in self.buttons(page, "Save PNG"):
            button.invoke()
        self.settle(self.app)
        pngs = [p for p in self.app.service.recent_exports() if p.suffix == ".png"]
        self.assertEqual(len(pngs), 3)
        self.assert_no_logged_errors()

    def test_theme_switch_redraws_without_error(self):
        self.go(self.app, "analytics")
        settings = self.go(self.app, "settings")
        settings.appearance.choose("Light")
        self.assertEqual(self.app.service.prefs.appearance, "Light")
        self.assertEqual(fake_gui.STATE["appearance"], "Light")
        self.assert_no_logged_errors()

    def test_about_page_shows_live_paths_and_counts(self):
        page = self.go(self.app, "about")
        text = page.info_label.cget("text")
        self.assertIn(str(self.app.service.config.paths.db_path), text)
        self.assertIn("DEMO", text)

    def test_article_dialog_opens_saves_and_copies_link(self):
        news = self.go(self.app, "news")
        card = self.cards(news)[0]
        details = [b for b in self.buttons(card) if b.cget("text") == "Details"][0]
        details.invoke()
        dialog = [w for w in self.app.walk() if w.__class__.__name__ == "ArticleDialog"][0]
        dialog._toggle_saved()
        self.assertEqual(self.app.service.db.count_saved(), 1)
        dialog._copy()
        self.assertEqual(fake_gui.STATE["clipboard"], card.article.url)
        self.assertEqual(dialog.more_btn.cget("state"), "disabled")       # demo article: no real page

    def test_keyboard_shortcuts_are_registered_for_every_page(self):
        self.assertIn("<F5>", self.app._bindings)
        for i in range(1, 10):
            self.assertIn(f"<Control-Key-{i}>", self.app._bindings)
        self.assertIn("<Control-Key-0>", self.app._bindings)
        self.app._bindings["<Control-Key-4>"][0](None)
        self.assertEqual(self.app._current, "categories")


# ====================================================================== #
class ExportPageTests(GuiTestCase):
    def test_export_all_three_formats_from_the_gui(self):
        app = self.make_app(demo=True, with_key=False)
        self.settle(app)
        page = self.go(app, "export")
        total = app.service.db.count_articles(ArticleFilter(demo=True))
        self.assertIn(f"{total:,} articles will be exported", page.count_label.cget("text"))

        for label in ("CSV", "Excel (.xlsx)", "JSON"):
            page.format.choose(label)
            page.export_btn.invoke()
            self.settle(app)
            self.assertEqual(self.last_toast()[0], "success", self.toasts)

        files = {p.suffix: p for p in app.service.recent_exports()}
        self.assertEqual(set(files), {".csv", ".xlsx", ".json"})
        self.assertEqual(len(pd.read_csv(files[".csv"])), total)
        sheet = openpyxl.load_workbook(files[".xlsx"]).worksheets[0]
        self.assertGreaterEqual(sheet.max_row, total + 1)
        data = json.loads(files[".json"].read_text(encoding="utf-8"))
        records = data["articles"] if isinstance(data, dict) else data
        self.assertEqual(len(records), total)
        self.assertEqual(len([b for b in self.buttons(page.history, "Open")]), 3)

    def test_export_respects_filters_saved_only_and_custom_filename(self):
        app = self.make_app(demo=True, with_key=False)
        self.settle(app)
        page = self.go(app, "export")
        page.bar.keyword.type("python")
        page._update_count()
        self.settle(app)
        expected = app.service.db.count_articles(ArticleFilter(keyword="python", demo=True))
        self.assertIn(f"{expected:,} article", page.count_label.cget("text"))
        page.filename.type("my-python-news")
        page.format.choose("CSV")
        page.export_btn.invoke()
        self.settle(app)
        path = next(p for p in app.service.recent_exports() if p.suffix == ".csv")
        self.assertTrue(path.name.startswith("my-python-news"))
        self.assertEqual(len(pd.read_csv(path)), expected)

        # saved-only scope via the navigation parameter used by the Saved page
        first = app.service.query(ArticleFilter(), 1).items[0]
        app.service.save_article(first.id)
        page = self.go(app, "export", saved_only=True)
        self.assertEqual(page.saved_switch.get(), 1)
        self.assertIn("1 article will be exported", page.count_label.cget("text"))

    def test_export_with_no_matching_articles_shows_an_error_not_a_crash(self):
        app = self.make_app(demo=True, with_key=False)
        self.settle(app)
        page = self.go(app, "export")
        page.bar.keyword.type("zzzz-nothing")
        page.export_btn.invoke()
        self.settle(app)
        self.assertEqual(self.last_toast()[0], "error")
        self.assertIn("no articles", self.last_toast()[1].lower())
        self.assertEqual(page.export_btn.cget("state"), "normal")          # recovered

    def test_delete_export_requires_confirmation(self):
        app = self.make_app(demo=True, with_key=False)
        self.settle(app)
        page = self.go(app, "export")
        page.export_btn.invoke()
        self.settle(app)
        self.assertEqual(len(app.service.recent_exports()), 1)
        fake_gui.STATE["confirm"] = False
        self.buttons(page.history, "Delete")[0].invoke()
        self.assertEqual(len(app.service.recent_exports()), 1)              # cancelled
        fake_gui.STATE["confirm"] = True
        self.buttons(page.history, "Delete")[0].invoke()
        self.assertEqual(app.service.recent_exports(), [])


# ====================================================================== #
class LiveModeTests(GuiTestCase):
    def payload_session(self, count=5):
        return FakeSession(FakeResponse(payload=ok_payload(*[api_article(i) for i in range(1, count + 1)])))

    def test_startup_fetches_live_news_and_refresh_deduplicates(self):
        session = self.payload_session(5)
        app = self.make_app(demo=False, with_key=True, session=session)
        self.settle(app)                                   # empty library -> automatic first fetch
        db = app.service.db
        self.assertEqual(db.get_counts(False)["total"], 5)
        self.assertEqual(db.get_counts(True)["total"], 0)  # nothing demo leaked in
        self.assertIn("5 new", self.last_toast()[1])
        calls_after_first = len(session.calls)
        self.assertGreater(calls_after_first, 1)           # one request per category

        app.refresh_btn.invoke()                           # refresh again: same URLs
        self.settle(app)
        self.assertEqual(db.get_counts(False)["total"], 5)
        self.assertIn("0 new", self.last_toast()[1])
        self.assertEqual(app.refresh_btn.cget("state"), "normal")
        self.assertEqual(app.refresh_btn.cget("text"), "⟳  Refresh news")
        self.assertFalse(app.banner.winfo_ismapped())      # live mode: no demo banner
        self.assertIn("Live", app.sidebar.mode_badge.cget("text"))
        self.assert_no_logged_errors()

    def test_f5_triggers_a_refresh(self):
        session = self.payload_session(3)
        app = self.make_app(demo=False, with_key=True, session=session)
        self.settle(app)
        before = len(session.calls)
        app._bindings["<F5>"][0](None)
        self.settle(app)
        self.assertGreater(len(session.calls), before)

    def test_network_failure_shows_an_error_and_the_app_recovers(self):
        session = FakeSession(requests.exceptions.ConnectionError("offline"))
        app = self.make_app(demo=False, with_key=True, session=session)
        self.settle(app)
        kind, message = self.last_toast()
        self.assertEqual(kind, "error")
        self.assertIn("internet connection", message)
        self.assertEqual(app.refresh_btn.cget("state"), "normal")
        self.assertFalse(app._busy)
        self.assertEqual(app.service.db.get_counts(False)["total"], 0)
        self.assertEqual(app._current, "dashboard")                         # stays usable
        self.go(app, "news")                                                  # and still navigable

    def test_invalid_api_key_sends_the_user_to_settings(self):
        session = FakeSession(FakeResponse(401, payload={"status": "error", "code": "apiKeyInvalid",
                                                         "message": "Your API key is invalid."}))
        app = self.make_app(demo=False, with_key=True, session=session)
        self.settle(app)
        self.assertEqual(app._current, "settings")
        self.assertEqual(self.last_toast()[0], "error")
        self.assertIn("rejected your API key", self.last_toast()[1])

    def test_online_search_adds_results_and_reports_duplicates(self):
        session = self.payload_session(4)
        app = self.make_app(demo=False, with_key=True, session=session)
        self.settle(app)
        search = self.go(app, "search")
        search.browser.bar.keyword.type("headline")
        search.online_btn.invoke()
        self.settle(app)
        self.assertIn("already stored", self.last_toast()[1])
        search.browser.bar.keyword.type("x")               # too short
        search.online_btn.invoke()
        self.assertEqual(self.last_toast()[0], "warning")

    def test_pagination_moves_between_pages(self):
        app = self.make_app(demo=False, with_key=True, session=self.payload_session(1))
        self.settle(app)
        app.service.db.insert_articles([make_article(100 + i, published_at=f"2026-10-{(i % 28) + 1:02d}T10:00:00Z")
                                        for i in range(45)])
        news = self.go(app, "news")
        self.assertEqual(len(self.cards(news)), 20)
        self.assertEqual(news.browser.count_label.cget("text"), "46 articles")
        news.browser.pager.next.invoke()
        self.settle(app)
        self.assertEqual(news.browser.pager.page, 2)
        self.assertEqual(len(self.cards(news)), 20)
        news.browser.pager.next.invoke()
        self.settle(app)
        self.assertEqual(len(self.cards(news)), 6)
        self.assertEqual(news.browser.pager.next.cget("state"), "disabled")
        news.browser.pager.prev.invoke()
        self.settle(app)
        self.assertEqual(news.browser.pager.page, 2)

    def test_sources_refresh_downloads_the_directory(self):
        sources = {"status": "ok", "sources": [
            {"id": "bbc-news", "name": "BBC News", "description": "UK public broadcaster", "url": "https://bbc.co.uk",
             "category": "general", "language": "en", "country": "gb"},
            {"id": "the-verge", "name": "The Verge", "description": "Tech news", "url": "https://theverge.com",
             "category": "technology", "language": "en", "country": "us"}]}
        session = FakeSession(FakeResponse(payload=ok_payload(api_article(1))))
        app = self.make_app(demo=False, with_key=True, session=session)
        self.settle(app)
        session.queue = [FakeResponse(payload=sources)]
        page = self.go(app, "sources")
        self.assertEqual(page.refresh_btn.cget("state"), "normal")
        page.refresh_btn.invoke()
        self.settle(app)
        names = [w.cget("text") for w in page.list.walk() if w.__class__.__name__ == "CTkLabel"]
        self.assertIn("BBC News", names)
        self.assertIn("The Verge", names)
        self.assertIn("Downloaded 2 sources", self.last_toast()[1])


# ====================================================================== #
class FirstRunAndSettingsTests(GuiTestCase):
    VALID_KEY = "abcdef0123456789abcdef0123456789"

    def test_first_run_without_key_guides_the_user_and_never_shows_fake_news(self):
        app = self.make_app(demo=False, with_key=False)
        self.settle(app)
        self.assertTrue(app.service.needs_setup)
        self.assertTrue(app.banner.winfo_ismapped())
        self.assertIn("NewsAPI key", app.banner_text.cget("text"))
        self.assertEqual(app.service.db.get_counts(True)["total"], 0)
        self.assertEqual(app.service.db.get_counts(False)["total"], 0)
        page = app._pages["dashboard"]
        texts = [w.cget("text") for w in page.empty.walk() if w.__class__.__name__ == "CTkLabel"]
        self.assertIn("Let’s get you set up", texts)
        app.refresh_btn.invoke()                            # refresh without key -> settings, with a hint
        self.settle(app)
        self.assertEqual(app._current, "settings")
        self.assertEqual(self.last_toast()[0], "warning")

    def test_banner_use_demo_mode_loads_labelled_samples(self):
        app = self.make_app(demo=False, with_key=False)
        self.settle(app)
        self.buttons(app.banner_buttons, "Use demo mode")[0].invoke()
        self.settle(app)
        self.assertTrue(app.service.demo_mode)
        self.assertGreater(app.service.db.get_counts(True)["total"], 0)
        self.assertEqual(app.service.db.get_counts(False)["total"], 0)

    def test_switch_to_live_without_key_is_refused(self):
        app = self.make_app(demo=True, with_key=False)
        self.settle(app)
        self.buttons(app.banner_buttons, "Switch to live")[0].invoke()
        self.settle(app)
        self.assertTrue(app.service.demo_mode)
        self.assertEqual(app._current, "settings")

    def test_api_key_validation_saving_and_removal(self):
        app = self.make_app(demo=True, with_key=False)
        self.settle(app)
        page = self.go(app, "settings")
        env = app.service.config.paths.env_file

        page.key_entry.type("not a key!")
        page._save_key()
        self.assertEqual(self.last_toast()[0], "error")
        self.assertFalse(app.service.config.has_api_key)

        fake_gui.STATE["confirm"] = False                   # decline "switch to live now?"
        page.key_entry.type(self.VALID_KEY)
        page._save_key()
        self.settle(app)
        self.assertTrue(app.service.config.has_api_key)
        self.assertIn(self.VALID_KEY, env.read_text())
        self.assertNotIn(self.VALID_KEY, page.key_status.cget("text"))     # never shown in full
        self.assertIn("…" + self.VALID_KEY[-4:], page.key_status.cget("text"))
        self.assertEqual(page.key_entry.get(), "")
        self.assertTrue(app.service.demo_mode)

        fake_gui.STATE["confirm"] = False
        page._remove_key()
        self.assertTrue(app.service.config.has_api_key)                    # cancelled
        fake_gui.STATE["confirm"] = True
        page._remove_key()
        self.assertFalse(app.service.config.has_api_key)

    def test_saving_key_can_switch_off_demo_mode(self):
        app = self.make_app(demo=True, with_key=False)
        self.settle(app)
        page = self.go(app, "settings")
        page.key_entry.type(self.VALID_KEY)
        fake_gui.STATE["confirm"] = True
        with mock.patch.object(app.service, "fetch_latest", return_value=mock.Mock(
                summary=lambda: "ok", errors=[], inserted=0)):
            page._save_key()
            self.settle(app)
        self.assertFalse(app.service.demo_mode)
        self.assertEqual(page.demo_switch.get(), 0)

    def test_connection_test_reports_success_and_failure(self):
        session = FakeSession(FakeResponse(payload=ok_payload()))
        app = self.make_app(demo=True, with_key=True, session=session)
        self.settle(app)
        page = self.go(app, "settings")
        page._test_key()
        self.settle(app)
        self.assertIn("✔", page.test_result.cget("text"))
        session.queue = [FakeResponse(401, payload={"status": "error", "code": "apiKeyInvalid", "message": "bad"})]
        page.key_entry.type(self.VALID_KEY)
        page._test_key()
        self.settle(app)
        self.assertIn("✖", page.test_result.cget("text"))

    def test_demo_switch_and_preferences_persist(self):
        app = self.make_app(demo=False, with_key=True, session=FakeSession(FakeResponse(payload=ok_payload())))
        self.settle(app)
        page = self.go(app, "settings")
        page.demo_switch.toggle()
        self.settle(app)
        self.assertTrue(app.service.prefs.demo_mode)
        self.assertTrue(app.banner.winfo_ismapped())
        page.demo_switch.toggle()
        self.settle(app)
        self.assertFalse(app.service.prefs.demo_mode)

        page.country.set("Germany (de)")
        page.fetch_size.set("50")
        page.page_size.set("10")
        page.category_vars["sports"].set(0)
        page.category_vars["health"].set(0)
        page._save_preferences()
        prefs = app.service.prefs
        self.assertEqual((prefs.country, prefs.fetch_size, prefs.page_size), ("de", 50, 10))
        self.assertNotIn("sports", prefs.categories)
        self.assertEqual(len(prefs.categories), 5)

        for var in page.category_vars.values():             # nothing selected -> validation error
            var.set(0)
        page._save_preferences()
        self.assertEqual(self.last_toast()[0], "error")

        reopened = self.go(app, "settings")                  # values survive re-opening the page
        self.assertEqual(reopened.country.get(), "Germany (de)")
        self.assertEqual(reopened.page_size.get(), "10")

    def test_data_tools_backup_cleanup_and_erase(self):
        app = self.make_app(demo=True, with_key=False)
        self.settle(app)
        page = self.go(app, "settings")
        db = app.service.db
        total = db.get_counts(True)["total"]
        self.assertGreater(total, 0)

        page._backup()
        self.settle(app)
        backups = list(app.service.config.paths.backups_dir.glob("*.db"))
        self.assertEqual(len(backups), 1)
        self.assertGreater(backups[0].stat().st_size, 0)

        page.days_entry.type("abc")
        page._purge_old()
        self.assertEqual(self.last_toast()[0], "warning")
        page.days_entry.type("0")
        page._purge_old()
        self.assertEqual(self.last_toast()[0], "warning")
        self.assertEqual(db.get_counts(True)["total"], total)

        fake_gui.STATE["confirm"] = False                    # cancelled -> nothing deleted
        page._erase_all()
        self.settle(app)
        self.assertEqual(db.get_counts(True)["total"], total)

        fake_gui.STATE["confirm"] = True
        page._purge_demo()
        self.settle(app)
        self.assertEqual(db.get_counts(True)["total"], 0)
        self.assertIn("Deleted", self.last_toast()[1])

    def test_erasing_data_in_live_mode_does_not_trigger_an_automatic_refetch(self):
        session = FakeSession(FakeResponse(payload=ok_payload(api_article(1), api_article(2))))
        app = self.make_app(demo=False, with_key=True, session=session)
        self.settle(app)
        page = self.go(app, "settings")
        calls = len(session.calls)
        page._erase_all()
        self.settle(app)
        self.assertEqual(app.service.db.get_counts(False)["total"], 0)
        self.assertEqual(len(session.calls), calls, "erasing data must not spend API quota")


if __name__ == "__main__":
    unittest.main()
