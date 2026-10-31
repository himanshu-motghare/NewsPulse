import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import requests

import cli
import main as main_module
from tests.helpers import (FakeResponse, FakeSession, TempDirTestCase, api_article, ok_payload)

ROOT = Path(__file__).resolve().parent.parent


class CliTests(TempDirTestCase):
    def run_cli(self, *argv, svc=None):
        svc = svc or self.make_service(with_key=False)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.run(list(argv), service=svc)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def demo(self):
        svc = self.make_service(with_key=False)
        self.run_cli("--demo", "--fetch", svc=svc)
        return svc

    # ---- basics -----------------------------------------------------------
    def test_help_and_version(self):
        code, out, _ = self.run_cli("--help")
        self.assertEqual(code, 0)
        for flag in ("--fetch", "--search", "--source", "--date", "--export", "--list-saved"):
            self.assertIn(flag, out)
        code, out, _ = self.run_cli("--version")
        self.assertEqual(code, 0)
        self.assertIn("NewsPulse", out)

    def test_no_arguments_prints_help(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("usage:", out)

    def test_fetch_without_key_shows_setup_help(self):
        code, out, err = self.run_cli("--fetch")
        self.assertEqual(code, 1)
        self.assertIn("newsapi.org/register", err)
        self.assertIn("--demo", err)

    # ---- demo + listing -----------------------------------------------------
    def test_demo_fetch_and_search(self):
        svc = self.make_service(with_key=False)
        code, out, _ = self.run_cli("--demo", "--fetch", svc=svc)
        self.assertEqual(code, 0)
        self.assertIn("DEMO MODE", out)
        self.assertIn("20 new", out)
        code, out, _ = self.run_cli("--fetch", svc=svc)
        self.assertIn("0 new, 20 already stored", out)           # dedup through the CLI
        code, out, _ = self.run_cli("--search", "technology", "--limit", "2", svc=svc)
        self.assertEqual(code, 0)
        self.assertIn("[DEMO]", out)
        self.assertIn("page 1 of", out)
        self.assertIn("--page 2", out)

    def test_filters_via_cli(self):
        svc = self.demo()
        _, out, _ = self.run_cli("--source", "Sports", svc=svc)
        self.assertIn("3 article(s)", out)
        _, out, _ = self.run_cli("--category", "health", "--search", "sleep", svc=svc)
        self.assertIn("1 article(s)", out)
        _, out, _ = self.run_cli("--date", "2001-01-01", svc=svc)
        self.assertIn("No articles match", out)
        _, out, _ = self.run_cli("--from-date", "2000-01-01", "--to-date", "2100-01-01", svc=svc)
        self.assertIn("20 article(s)", out)
        _, out, _ = self.run_cli("--search", "zzzzqqq", svc=svc)
        self.assertIn("No articles match", out)

    def test_invalid_input_exit_codes(self):
        svc = self.demo()
        self.assertEqual(self.run_cli("--date", "31/10/2026", svc=svc)[0], 2)
        self.assertEqual(self.run_cli("--category", "cooking", svc=svc)[0], 2)
        self.assertEqual(self.run_cli("--from-date", "2026-12-01", "--to-date", "2026-01-01", svc=svc)[0], 2)
        self.assertEqual(self.run_cli("--limit", "0", "--search", "x", svc=svc)[0], 2)
        self.assertEqual(self.run_cli("--date", "2026-10-31", "--from-date", "2026-10-01", svc=svc)[0], 2)
        self.assertEqual(self.run_cli("--export", "pdf", svc=svc)[0], 2)
        _, _, err = self.run_cli("--date", "nope", svc=svc)
        self.assertIn("YYYY-MM-DD", err)

    # ---- export -------------------------------------------------------------
    def test_exports(self):
        svc = self.demo()
        exports = svc.config.paths.exports_dir
        for fmt, ext in (("csv", ".csv"), ("excel", ".xlsx"), ("json", ".json")):
            code, out, _ = self.run_cli("--export", fmt, svc=svc)
            self.assertEqual(code, 0, fmt)
            self.assertIn("Exported 20 articles", out)
            self.assertEqual(len(list(exports.glob(f"*{ext}"))), 1)
        code, out, _ = self.run_cli("--search", "sports", "--export", "json", "--output", "sports_only", svc=svc)
        data = json.loads((exports / "sports_only.json").read_text(encoding="utf-8"))
        self.assertEqual(data["count"], len(data["articles"]))
        self.assertTrue(0 < data["count"] < 20)
        self.assertIn("sports", data["filters"])

    def test_export_with_no_matches_fails_cleanly(self):
        code, _, err = self.run_cli("--export", "csv", "--search", "zzzz", svc=self.demo())
        self.assertEqual(code, 1)
        self.assertIn("no articles", err.lower())

    # ---- saved --------------------------------------------------------------
    def test_save_list_unsave(self):
        svc = self.demo()
        aid = svc.query().items[0].id
        code, out, _ = self.run_cli("--save", str(aid), "--note", "read later", svc=svc)
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli("--list-saved", svc=svc)
        self.assertIn("1 article(s)", out)
        self.assertIn("read later", out)
        self.assertIn("[SAVED]", out)
        self.run_cli("--export", "json", "--list-saved", "--output", "saved", svc=svc)
        self.assertEqual(json.loads((svc.config.paths.exports_dir / "saved.json").read_text("utf-8"))["count"], 1)
        code, out, _ = self.run_cli("--unsave", str(aid), svc=svc)
        self.assertEqual(code, 0)
        _, out, _ = self.run_cli("--list-saved", svc=svc)
        self.assertIn("No articles match", out)
        self.assertEqual(self.run_cli("--unsave", str(aid), svc=svc)[0], 1)
        self.assertEqual(self.run_cli("--save", "99999", svc=svc)[0], 1)

    def test_show_and_delete(self):
        svc = self.demo()
        aid = svc.query().items[0].id
        code, out, _ = self.run_cli("--show", str(aid), svc=svc)
        self.assertIn("Title:", out)
        self.assertEqual(self.run_cli("--show", "99999", svc=svc)[0], 1)
        self.assertEqual(self.run_cli("--delete", str(aid), svc=svc)[0], 0)
        self.assertEqual(svc.query().total, 19)
        self.assertEqual(self.run_cli("--delete", str(aid), svc=svc)[0], 1)

    # ---- misc ---------------------------------------------------------------
    def test_stats_sources_chart_backup(self):
        svc = self.demo()
        _, out, _ = self.run_cli("--stats", svc=svc)
        self.assertIn("Total articles:     20", out)
        self.assertIn("Trending keywords", out)
        _, out, _ = self.run_cli("--sources", svc=svc)
        self.assertIn("Demo Wire", out)
        code, out, _ = self.run_cli("--chart", "category", svc=svc)
        self.assertEqual(code, 0)
        self.assertEqual(len(list(svc.config.paths.exports_dir.glob("*.png"))), 1)
        code, out, _ = self.run_cli("--backup", svc=svc)
        self.assertEqual(len(list(svc.config.paths.backups_dir.glob("*.db"))), 1)

    def test_live_mode_switch_and_fetch_with_fake_api(self):
        session = FakeSession(FakeResponse(200, ok_payload(api_article(1), api_article(2))))
        svc = self.make_service(session)
        svc.prefs.set("categories", "general")
        code, out, _ = self.run_cli("--fetch", svc=svc)
        self.assertEqual(code, 0)
        self.assertNotIn("DEMO", out)
        self.assertIn("2 new", out)
        _, out, _ = self.run_cli("--source", "Test Wire", svc=svc)
        self.assertIn("2 article(s)", out)
        self.run_cli("--demo", svc=svc)
        self.assertTrue(svc.demo_mode)
        self.run_cli("--live", svc=svc)
        self.assertFalse(svc.demo_mode)

    def test_online_search(self):
        svc = self.make_service(FakeSession(FakeResponse(200, ok_payload(api_article(9, title="Quantum computing milestone")))))
        code, out, _ = self.run_cli("--search", "quantum", "--online", svc=svc)
        self.assertEqual(code, 0)
        self.assertIn("1 new", out)
        self.assertIn("Quantum computing milestone", out)

    def test_network_failure_message(self):
        svc = self.make_service(FakeSession(requests.exceptions.ConnectionError("down")))
        code, _, err = self.run_cli("--fetch", svc=svc)
        self.assertEqual(code, 1)
        self.assertIn("internet connection", err)
        self.assertNotIn("Traceback", err)

    def test_invalid_key_message(self):
        svc = self.make_service(FakeSession(FakeResponse(401, {"status": "error", "code": "apiKeyInvalid", "message": "x"})))
        code, _, err = self.run_cli("--fetch", svc=svc)
        self.assertEqual(code, 1)
        self.assertIn("rejected your API key", err)


class EntryPointTests(TempDirTestCase):
    def test_main_runs_as_a_script_end_to_end(self):
        env = dict(os.environ, NEWSPULSE_HOME=str(self.tmp))
        env.pop("NEWSAPI_KEY", None)
        run = lambda *a: subprocess.run([sys.executable, str(ROOT / "main.py"), *a], env=env,
                                        capture_output=True, text=True, cwd=ROOT, timeout=60)
        r = run("--demo", "--fetch")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("--search", "sleep")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[DEMO]", r.stdout)
        self.assertTrue((self.tmp / "database" / "newspulse.db").exists())
        self.assertTrue((self.tmp / "logs" / "newspulse.log").exists())
        self.assertEqual(run("--date", "bad").returncode, 2)

    def test_gui_launch_failure_is_friendly(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main_module.launch_gui() if not self._gui_available() else 1
        if not self._gui_available():
            self.assertEqual(code, 1)
            self.assertIn("pip install -r requirements.txt", err.getvalue())

    @staticmethod
    def _gui_available():
        try:
            import customtkinter, tkinter  # noqa: F401
            return True
        except ImportError:
            return False


if __name__ == "__main__":
    unittest.main()
