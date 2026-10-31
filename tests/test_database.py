import sqlite3
import unittest

from database import Database
from errors import DatabaseError
from filters import ArticleFilter
from tests.helpers import TempDirTestCase, make_article
from utils import utc_now


class DatabaseTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.db = Database(self.tmp / "t.db")

    def test_schema_created(self):
        with self.db.connect() as c:
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"articles", "sources", "saved_articles", "settings", "fetch_log"} <= tables)

    # --- duplicates ---------------------------------------------------------
    def test_duplicate_urls_are_not_stored(self):
        r = self.db.insert_articles([
            make_article(1, url="https://example.com/a"),
            make_article(2, url="https://www.example.com/a/?utm_source=tw"),   # same article
            make_article(3, url="https://example.com/b"),
        ])
        self.assertEqual((r.inserted, r.duplicates), (2, 1))
        self.assertEqual(self.db.count_articles(ArticleFilter()), 2)
        again = self.db.insert_articles([make_article(1, url="https://example.com/a")])
        self.assertEqual((again.inserted, again.duplicates), (0, 1))

    def test_unique_constraint_is_enforced_by_the_database(self):
        self.db.insert_articles([make_article(1)])
        with self.db.connect() as c:
            key = c.execute("SELECT url_key FROM articles").fetchone()[0]
        with self.assertRaises(DatabaseError):          # bypassing the API still cannot create a duplicate
            with self.db.connect() as c:
                c.execute("INSERT INTO articles (url,url_key,title,source_id,fetched_at) VALUES ('x',?,'t',1,'now')", (key,))

    def test_invalid_articles_skipped(self):
        r = self.db.insert_articles([make_article(1, url="not-a-url"), make_article(2, title="  ")])
        self.assertEqual((r.inserted, r.skipped), (0, 2))

    def test_duplicate_upgrades_category_and_fills_image(self):
        self.db.insert_articles([make_article(1, category="general")])
        r = self.db.insert_articles([make_article(1, category="technology", image_url="https://i.example/x.jpg")])
        self.assertEqual(r.duplicates, 1)
        a = self.db.query_articles(ArticleFilter())[0]
        self.assertEqual((a.category, a.image_url), ("technology", "https://i.example/x.jpg"))
        # an already-specific category is never overwritten
        self.db.insert_articles([make_article(1, category="business")])
        self.assertEqual(self.db.query_articles(ArticleFilter())[0].category, "technology")

    # --- querying -----------------------------------------------------------
    def _seed(self):
        self.db.insert_articles([
            make_article(1, title="AI chips surge", source_name="BBC News", category="technology", published_at="2026-10-30T09:00:00Z"),
            make_article(2, title="Football final tonight", source_name="ESPN", category="sports", published_at="2026-10-31T20:00:00Z"),
            make_article(3, title="AI regulation debate", source_name="Reuters", category="technology", published_at="2026-10-31T08:00:00Z"),
            make_article(4, title="Undated item", source_name="Reuters", published_at=""),
        ])

    def q(self, **kw):
        return [a.title for a in self.db.query_articles(ArticleFilter.from_inputs(**kw))]

    def test_keyword_source_category_filters(self):
        self._seed()
        self.assertEqual(sorted(self.q(keyword="ai")), ["AI chips surge", "AI regulation debate"])
        self.assertEqual(self.q(keyword="ai debate"), ["AI regulation debate"])          # AND semantics
        self.assertEqual(self.q(source="bbc"), ["AI chips surge"])
        self.assertEqual(self.q(category="sports"), ["Football final tonight"])
        self.assertEqual(self.q(keyword="technology"), ["AI regulation debate", "AI chips surge"])  # category matches keyword

    def test_filters_combine(self):
        self._seed()
        self.assertEqual(self.q(keyword="ai", source="reuters", category="technology"), ["AI regulation debate"])
        self.assertEqual(self.q(keyword="ai", source="espn"), [])

    def test_date_filter_inclusive_and_excludes_undated(self):
        self._seed()
        self.assertEqual(sorted(self.q(date_from="2026-10-31", date_to="2026-10-31")),
                         ["AI regulation debate", "Football final tonight"])
        self.assertEqual(self.q(date_to="2026-10-30"), ["AI chips surge"])
        self.assertEqual(len(self.q(date_from="2026-10-01", date_to="2026-10-31")), 3)

    def test_sorting(self):
        self._seed()
        self.assertEqual(self.q()[:3], ["Football final tonight", "AI regulation debate", "AI chips surge"])
        self.assertEqual(self.q()[-1], "Undated item")
        self.assertEqual(self.q(sort="oldest")[0], "AI chips surge")
        self.assertEqual(self.q(sort="oldest")[-1], "Undated item")
        self.assertEqual(self.q(sort="source")[0], "AI chips surge")  # BBC first

    def test_like_wildcards_are_escaped(self):
        self.db.insert_articles([make_article(1, title="100% growth"), make_article(2, title="Plain title")])
        self.assertEqual(self.q(keyword="100%"), ["100% growth"])
        self.assertEqual(self.q(keyword="%"), ["100% growth"])

    def test_pagination(self):
        self.db.insert_articles([make_article(i, published_at=f"2026-10-{i:02d}T00:00:00Z") for i in range(1, 26)])
        f = ArticleFilter()
        self.assertEqual(self.db.count_articles(f), 25)
        p1 = self.db.query_articles(f, limit=10, offset=0)
        p3 = self.db.query_articles(f, limit=10, offset=20)
        self.assertEqual((len(p1), len(p3)), (10, 5))
        self.assertEqual(p1[0].title, "Title 25")

    def test_demo_scope(self):
        self.db.insert_articles([make_article(1, is_demo=True), make_article(2)])
        self.assertEqual(self.db.count_articles(ArticleFilter(demo=True)), 1)
        self.assertEqual(self.db.count_articles(ArticleFilter(demo=False)), 1)
        self.assertEqual(self.db.count_articles(ArticleFilter()), 2)

    # --- saved / update / delete -------------------------------------------
    def test_save_unsave_note_and_cascade_delete(self):
        self.db.insert_articles([make_article(1), make_article(2)])
        aid = self.db.query_articles(ArticleFilter())[0].id
        self.assertTrue(self.db.save_article(aid, "first note"))
        self.assertFalse(self.db.save_article(9999))
        saved = self.db.query_articles(ArticleFilter(saved_only=True))
        self.assertEqual([(a.id, a.is_saved, a.note) for a in saved], [(aid, True, "first note")])
        self.assertTrue(self.db.update_note(aid, "edited"))
        self.assertEqual(self.db.get_article(aid).note, "edited")
        self.db.save_article(aid)                       # re-saving keeps the note
        self.assertEqual(self.db.get_article(aid).note, "edited")
        self.assertEqual(self.db.count_saved(), 1)
        self.assertTrue(self.db.unsave_article(aid))
        self.assertFalse(self.db.unsave_article(aid))
        self.db.save_article(aid)
        self.assertTrue(self.db.delete_article(aid))
        self.assertEqual(self.db.count_saved(), 0)      # ON DELETE CASCADE
        self.assertIsNone(self.db.get_article(aid))

    def test_saved_survive_reopen(self):
        self.db.insert_articles([make_article(1)])
        aid = self.db.query_articles(ArticleFilter())[0].id
        self.db.save_article(aid)
        reopened = Database(self.tmp / "t.db")
        self.assertEqual(reopened.count_saved(), 1)
        self.assertEqual(reopened.count_articles(ArticleFilter()), 1)

    def test_update_article_details_only_fills_blanks(self):
        self.db.insert_articles([make_article(1, description="", image_url="")])
        aid = self.db.query_articles(ArticleFilter())[0].id
        self.db.update_article_details(aid, "https://i.example/a.jpg", "Filled")
        self.db.update_article_details(aid, "https://other/b.jpg", "Overwritten?")
        a = self.db.get_article(aid)
        self.assertEqual((a.image_url, a.description), ("https://i.example/a.jpg", "Filled"))

    def test_purge_operations(self):
        old = "2020-01-01T00:00:00Z"
        recent = utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
        self.db.insert_articles([make_article(1, published_at=old), make_article(2, published_at=old),
                                 make_article(3, published_at=recent),
                                 make_article(4, is_demo=True, source_api_id="demo-x", source_name="Demo X")])
        keep = self.db.query_articles(ArticleFilter(keyword="Title 2"))[0].id
        self.db.save_article(keep)
        self.assertEqual(self.db.delete_older_than(30, demo=False), 1)    # saved old article is kept
        self.assertEqual(self.db.count_articles(ArticleFilter(demo=False)), 2)
        self.assertEqual(self.db.delete_demo_articles(), 1)
        self.assertEqual(self.db.list_sources(demo=True), [])
        self.db.clear_all()
        self.assertEqual(self.db.get_counts(False), {"total": 0, "today": 0, "sources": 0, "saved": 0})

    # --- statistics / settings / backup -------------------------------------
    def test_statistics(self):
        today = utc_now().strftime("%Y-%m-%d")
        self.db.insert_articles([make_article(1, published_at=f"{today}T01:00:00Z", category="sports"),
                                 make_article(2, source_name="Other", category="sports",
                                              published_at="2020-01-01T10:00:00Z"),
                                 make_article(3, category="health", published_at="2020-01-02T10:00:00Z")])
        c = self.db.get_counts(False)
        self.assertEqual((c["total"], c["today"], c["sources"]), (3, 1, 2))
        self.assertEqual(dict(self.db.count_by_category(False)), {"sports": 2, "health": 1})
        self.assertEqual(self.db.count_by_source(False)[0], ("Test Wire", 2))
        self.assertEqual(self.db.count_by_collection_day(False, 7), [(today, 3)])
        self.db.log_fetch("headlines", 3, 3, 0, "ok")
        self.assertEqual(self.db.last_fetch()["inserted"], 3)

    def test_settings_roundtrip(self):
        self.assertIsNone(self.db.get_setting("k"))
        self.db.set_setting("k", "v1")
        self.db.set_setting("k", "v2")
        self.assertEqual(self.db.get_setting("k"), "v2")

    def test_backup_is_a_valid_database(self):
        self.db.insert_articles([make_article(1)])
        dest = self.db.backup(self.tmp / "backups" / "b.db")
        con = sqlite3.connect(dest)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM articles").fetchone()[0], 1)
        con.close()

    def test_sources_listing_with_counts(self):
        self.db.insert_articles([make_article(1, source_name="A"), make_article(2, source_name="A"), make_article(3, source_name="B")])
        self.db.upsert_sources([{"id": "c", "name": "C", "category": "health"}])
        rows = self.db.list_sources(demo=False)
        self.assertEqual([(r["name"], r["article_count"]) for r in rows], [("A", 2), ("B", 1), ("C", 0)])
        self.assertEqual(len(self.db.list_sources(False, only_with_articles=True)), 2)


if __name__ == "__main__":
    unittest.main()
