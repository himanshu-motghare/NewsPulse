import csv
import json
import unittest

import openpyxl

from errors import ExportError, ScraperError
from exporter import export_articles
from scraper import ArticleScraper
from tests.helpers import FakeResponse, FakeSession, TempDirTestCase, make_article

PAGE = """<html><head><title>Fallback</title>
<meta property="og:title" content="OG Title"><meta property="og:image" content="/img/hero.jpg">
<meta name="description" content="Plain description"><meta property="og:description" content="OG description">
</head><body></body></html>"""


class ScraperTests(unittest.TestCase):
    def test_parse_metadata(self):
        m = ArticleScraper.parse_metadata(PAGE, "https://news.example.org/a/b")
        self.assertEqual((m.title, m.description, m.image_url),
                         ("OG Title", "OG description", "https://news.example.org/img/hero.jpg"))

    def test_fetch_respects_robots_txt(self):
        session = FakeSession(FakeResponse(200, text="User-agent: *\nDisallow: /"))
        with self.assertRaisesRegex(ScraperError, "robots.txt"):
            ArticleScraper(session).fetch_metadata("https://news.example.org/a")
        self.assertEqual(len(session.calls), 1)       # the article page itself was never requested

    def test_fetch_success_when_allowed(self):
        # first request = robots.txt (404 -> allowed), second = the page itself
        session = FakeSession(FakeResponse(404), FakeResponse(200, text=PAGE, headers={"Content-Type": "text/html"}))
        m = ArticleScraper(session).fetch_metadata("https://news.example.org/a")
        self.assertEqual(m.title, "OG Title")

    def test_rejects_non_http_and_non_html(self):
        with self.assertRaises(ScraperError):
            ArticleScraper(FakeSession(FakeResponse())).fetch_metadata("file:///etc/passwd")
        session = FakeSession(FakeResponse(404), FakeResponse(200, text="x", headers={"Content-Type": "application/pdf"}))
        with self.assertRaisesRegex(ScraperError, "web page"):
            ArticleScraper(session).fetch_metadata("https://news.example.org/file")


class ExporterTests(TempDirTestCase):
    def articles(self):
        a = [make_article(i, id=i, description="Line with, comma and \"quotes\"") for i in range(1, 4)]
        a[0].title = "=HYPERLINK(\"http://evil\")"
        a[1].title = "Ünïcödé headline – “quotes”"
        a[2].is_saved = True
        return a

    def test_csv(self):
        path = export_articles(self.articles(), "csv", self.tmp, "keyword='x'")
        self.assertEqual(path.suffix, ".csv")
        with path.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0][:3], ["ID", "Title", "Source"])
        self.assertEqual(len(rows), 4)
        self.assertTrue(rows[1][1].startswith("'="))              # formula injection neutralised
        self.assertEqual(rows[2][1], "Ünïcödé headline – “quotes”")
        self.assertEqual(rows[1][5], 'Line with, comma and "quotes"')
        self.assertEqual(rows[3][9], "yes")                         # Saved column

    def test_excel(self):
        path = export_articles(self.articles(), "excel", self.tmp, "category=sports")
        self.assertEqual(path.suffix, ".xlsx")
        wb = openpyxl.load_workbook(path)
        self.assertEqual(wb.sheetnames, ["Articles", "Export info"])
        ws = wb["Articles"]
        self.assertEqual(ws.max_row, 4)
        self.assertEqual(ws["B1"].value, "Title")
        self.assertEqual(ws["B3"].value, "Ünïcödé headline – “quotes”")
        self.assertTrue(ws["B2"].value.startswith("'="))
        self.assertTrue(ws["H2"].hyperlink is not None)
        self.assertEqual(ws.freeze_panes, "A2")
        info = {r[0].value: r[1].value for r in wb["Export info"].iter_rows(min_row=2)}
        self.assertEqual(info["Filters"], "category=sports")

    def test_json(self):
        path = export_articles(self.articles(), "json", self.tmp, "all", demo=True)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((data["count"], data["demo_data"], data["filters"]), (3, True, "all"))
        self.assertEqual(data["articles"][1]["title"], "Ünïcödé headline – “quotes”")
        self.assertIn("DEMO", path.name)

    def test_errors(self):
        with self.assertRaisesRegex(ExportError, "no articles"):
            export_articles([], "csv", self.tmp)
        with self.assertRaisesRegex(ExportError, "Unsupported"):
            export_articles(self.articles(), "pdf", self.tmp)

    def test_never_overwrites_and_sanitises_filename(self):
        p1 = export_articles(self.articles(), "csv", self.tmp, filename="my/report")
        p2 = export_articles(self.articles(), "csv", self.tmp, filename="my/report")
        self.assertNotEqual(p1, p2)
        self.assertEqual(p1.parent, self.tmp)
        self.assertTrue(p1.name.startswith("my_report"))

    def test_file_containing_demo_articles_is_always_labelled_demo(self):
        """Regression: a saved-only export made in live mode may hold demo rows."""
        arts = [make_article(1), make_article(2, is_demo=True)]
        path = export_articles(arts, "json", self.tmp, demo=False)      # caller did not flag it
        self.assertIn("DEMO", path.name)
        self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["demo_data"])
        live = export_articles([make_article(3)], "json", self.tmp, demo=False)
        self.assertNotIn("DEMO", live.name)
        self.assertFalse(json.loads(live.read_text(encoding="utf-8"))["demo_data"])


if __name__ == "__main__":
    unittest.main()
