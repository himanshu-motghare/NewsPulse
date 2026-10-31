"""Opens the real window on a real display (skipped when Tk / CustomTkinter / a display is missing).

Run it on your own machine:        python -m unittest tests.test_gui_real -v
On a headless Linux server / CI:   xvfb-run -a python -m unittest tests.test_gui_real -v

This complements ``test_gui_smoke.py``, which uses a fake toolkit and therefore
cannot check real CustomTkinter keyword arguments or rendering.
"""
import time
import unittest

from tests.helpers import TempDirTestCase

NAV_KEYS = ["dashboard", "news", "search", "categories", "saved", "sources", "export", "analytics",
            "settings", "about"]


def _display_available() -> bool:
    try:
        import customtkinter  # noqa: F401
        import tkinter
        root = tkinter.Tk()
        root.destroy()
        return True
    except Exception:  # noqa: BLE001 - ImportError, TclError (no display) ...
        return False


@unittest.skipUnless(_display_available(), "needs customtkinter, Tk and a display (try xvfb-run on Linux)")
class RealGuiTests(TempDirTestCase):
    def pump(self, app, seconds=0.4):
        end = time.time() + seconds
        while time.time() < end:
            app.update()
            time.sleep(0.01)

    def test_every_page_opens_in_demo_mode(self):
        from ui.app import NewsPulseApp
        service = self.make_service(with_key=False)
        service.prefs.set("demo_mode", True)
        app = NewsPulseApp(service)
        try:
            self.pump(app, 1.0)                      # initial demo load + dashboard render
            for key in NAV_KEYS:
                app.navigate(key)
                self.pump(app)
                self.assertEqual(app._current, key)
            self.assertGreater(service.db.get_counts(True)["total"], 0)
        finally:
            app._on_close()


if __name__ == "__main__":
    unittest.main()
