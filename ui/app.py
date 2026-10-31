"""Main application window and the ``run_gui`` entry point."""
from __future__ import annotations

import sys
from typing import Callable, Dict, Optional

import customtkinter as ctk

from config import APP_NAME, APP_TAGLINE, Config
from errors import InvalidAPIKeyError, MissingAPIKeyError, NewsPulseError
from logger import get_logger, setup_logging
from models import FetchResult
from services import NewsService
from ui import theme
from ui.async_utils import TaskRunner
from ui.base_page import AppContext, BasePage
from ui.components import Card, GradientBar, Spinner, Toast, primary_button, secondary_button
from ui.graphics import draw_logo
from ui.news_cards import ImageLoader
from ui.sidebar import Sidebar
from ui.theme import font

log = get_logger("ui.app")

PAGE_META = {
    "dashboard": ("Dashboard", "Your news at a glance"),
    "news": ("All News", "Every headline stored on this computer"),
    "search": ("Search News", "Find articles by keyword, source, category and date"),
    "categories": ("Categories", "Browse headlines by topic"),
    "saved": ("Saved Articles", "Your bookmarked stories"),
    "sources": ("News Sources", "The publishers behind your news"),
    "export": ("Export Data", "Save articles as CSV, Excel or JSON"),
    "analytics": ("Analytics", "Charts about your news library"),
    "settings": ("Settings", "API key, preferences and data tools"),
    "about": ("About", "About NewsPulse"),
}


def _page_factory(key: str) -> Callable[..., BasePage]:
    """Import page classes lazily so start-up stays fast."""
    if key == "dashboard":
        from ui.dashboard import DashboardPage as cls
    elif key == "news":
        from ui.news_pages import AllNewsPage as cls
    elif key == "search":
        from ui.search_page import SearchPage as cls
    elif key == "categories":
        from ui.news_pages import CategoriesPage as cls
    elif key == "saved":
        from ui.news_pages import SavedPage as cls
    elif key == "sources":
        from ui.sources_page import SourcesPage as cls
    elif key == "export":
        from ui.export_page import ExportPage as cls
    elif key == "analytics":
        from ui.analytics_page import AnalyticsPage as cls
    elif key == "settings":
        from ui.settings_page import SettingsPage as cls
    else:
        from ui.about_page import AboutPage as cls
    return cls


class NewsPulseApp(ctk.CTk):
    def __init__(self, service: NewsService) -> None:
        ctk.set_appearance_mode(service.prefs.appearance)
        ctk.set_default_color_theme("blue")
        super().__init__(fg_color=theme.BG)
        self.service = service
        self.title(f"{APP_NAME} – {APP_TAGLINE}")
        self.geometry("1320x840")
        self.minsize(1100, 680)
        self._set_icon()
        self.report_callback_exception = self._on_tk_error

        self.runner = TaskRunner(self)
        self.toast = Toast(self)
        self.images = ImageLoader(self.runner, service.config.paths.cache_dir)
        self.ctx = AppContext(root=self, service=service, runner=self.runner, images=self.images,
                              toast=self.toast, navigate=self.navigate, refresh_news=self.refresh_news,
                              on_mode_changed=self._on_mode_changed,
                              on_appearance_changed=self._on_appearance_changed)
        self._pages: Dict[str, BasePage] = {}
        self._current: Optional[str] = None
        self._busy = False
        self._progress_text = ""

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.sidebar = Sidebar(self, self.navigate, service.config.paths.assets_dir / "logo.png")
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self._build_main()
        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._update_mode_ui()
        self.navigate("dashboard")
        self.after(700, self._maybe_initial_fetch)

    # ------------------------------------------------------------- layout --
    def _build_main(self) -> None:
        main = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)
        GradientBar(main, height=5).grid(row=0, column=0, sticky="ew")

        header = ctk.CTkFrame(main, fg_color="transparent")
        header.grid(row=1, column=0, sticky="ew", padx=theme.PAD, pady=(16, 8))
        header.grid_columnconfigure(0, weight=1)
        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.grid(row=0, column=0, sticky="w")
        self.title_label = ctk.CTkLabel(titles, text="", font=font(26, "bold"), text_color=theme.TEXT, anchor="w")
        self.title_label.pack(anchor="w")
        self.subtitle_label = ctk.CTkLabel(titles, text="", font=font(13), text_color=theme.MUTED, anchor="w")
        self.subtitle_label.pack(anchor="w")
        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")
        self.spinner = Spinner(actions, "Fetching…")
        self.refresh_btn = primary_button(actions, "⟳  Refresh news", self.refresh_news, width=150)
        self.refresh_btn.pack(side="right")

        self.body = ctk.CTkFrame(main, fg_color="transparent")
        self.body.grid(row=2, column=0, sticky="nsew", padx=theme.PAD, pady=(0, theme.PAD))
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(1, weight=1)

        self.banner = Card(self.body, border_color=theme.PURPLE)
        self.banner_text = ctk.CTkLabel(self.banner, text="", font=font(13), text_color=theme.TEXT, anchor="w",
                                        justify="left", wraplength=640)
        self.banner_text.pack(side="left", padx=16, pady=12, fill="x", expand=True)
        self.banner_buttons = ctk.CTkFrame(self.banner, fg_color="transparent")
        self.banner_buttons.pack(side="right", padx=12)
        self.content = ctk.CTkFrame(self.body, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

    def _set_icon(self) -> None:
        try:
            from PIL import ImageTk
            self._icon = ImageTk.PhotoImage(draw_logo(64))
            self.iconphoto(True, self._icon)
        except Exception:  # noqa: BLE001 - purely cosmetic
            log.debug("Could not set window icon", exc_info=True)

    def _bind_shortcuts(self) -> None:
        self.bind("<F5>", lambda _e: self.refresh_news())
        keys = [item[0] for item in theme.NAV_ITEMS]
        for i, key in enumerate(keys):
            digit = str((i + 1) % 10)
            self.bind(f"<Control-Key-{digit}>", lambda _e, k=key: self.navigate(k))

    # --------------------------------------------------------- navigation --
    def navigate(self, key: str, **params) -> None:
        if key not in PAGE_META:
            log.warning("Unknown page requested: %s", key)
            return
        page = self._pages.get(key)
        if page is None:
            page = _page_factory(key)(self.content, self.ctx)
            self._pages[key] = page
        if self._current and self._current != key:
            self._pages[self._current].grid_remove()
        page.grid(row=0, column=0, sticky="nsew")
        self._current = key
        title, subtitle = PAGE_META[key]
        self.title_label.configure(text=title)
        self.subtitle_label.configure(text=subtitle)
        self.sidebar.set_active(key)
        try:
            page.on_show(**params)
        except Exception as exc:  # noqa: BLE001 - one broken page must not crash the app
            log.exception("Page %s failed to load", key)
            self.ctx.show_error(exc)

    def _reload_current(self) -> None:
        if self._current:
            try:
                self._pages[self._current].on_show()
            except Exception as exc:  # noqa: BLE001
                log.exception("Reload failed")
                self.ctx.show_error(exc)

    # -------------------------------------------------------------- modes --
    def _update_mode_ui(self) -> None:
        svc = self.service
        self.sidebar.set_mode(svc.demo_mode)
        for child in self.banner_buttons.winfo_children():
            child.destroy()
        if svc.needs_setup:
            self.banner_text.configure(text=(
                "Welcome to NewsPulse! Add your free NewsAPI key to fetch live headlines - or explore with "
                "clearly labelled demo articles."))
            primary_button(self.banner_buttons, "Add API key", lambda: self.navigate("settings"), width=120).pack(
                side="left", padx=4)
            secondary_button(self.banner_buttons, "Use demo mode", self._enable_demo, width=130).pack(side="left", padx=4)
            self.banner.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        elif svc.demo_mode:
            self.banner_text.configure(text=(
                "DEMO MODE - these are made-up sample articles, not real news. Switch to live mode to see "
                "real headlines."))
            secondary_button(self.banner_buttons, "Switch to live", self._disable_demo, width=130).pack(side="left", padx=4)
            self.banner.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        else:
            self.banner.grid_forget()

    def _enable_demo(self) -> None:
        self.service.prefs.set("demo_mode", True)
        self._on_mode_changed()

    def _disable_demo(self) -> None:
        if not self.service.config.has_api_key:
            self.toast.show("Add a NewsAPI key first to switch to live news.", "warning")
            self.navigate("settings")
            return
        self.service.prefs.set("demo_mode", False)
        self._on_mode_changed()

    def _on_mode_changed(self) -> None:
        self._update_mode_ui()
        self._reload_current()
        self.after(300, self._maybe_initial_fetch)

    def _on_appearance_changed(self) -> None:
        ctk.set_appearance_mode(self.service.prefs.appearance)
        if self._current:
            self._pages[self._current].on_theme_changed()

    # ------------------------------------------------------------ fetching --
    def _maybe_initial_fetch(self) -> None:
        """Fill an empty library automatically (live fetch needs a key; demo is local)."""
        svc = self.service
        if self._busy or svc.needs_setup:
            return
        if svc.db.get_counts(svc.demo_mode)["total"] == 0:
            self.refresh_news()

    def refresh_news(self) -> None:
        if self._busy:
            return
        if self.service.needs_setup:
            self.toast.show("Add your NewsAPI key first - or switch on demo mode.", "warning")
            self.navigate("settings")
            return
        self._busy = True
        self._progress_text = "Loading…" if self.service.demo_mode else "Contacting NewsAPI…"
        self.refresh_btn.configure(state="disabled", text="Refreshing…")
        self.spinner.pack(side="right", padx=(0, 14))
        self.spinner.start(self._progress_text)
        self.after(250, self._tick_progress)
        self.runner.run(lambda: self.service.fetch_latest(progress=self._on_progress),
                        self._fetch_done, self._fetch_failed)

    def _on_progress(self, done: int, total: int, message: str) -> None:
        self._progress_text = message          # called from a worker thread: only store text

    def _tick_progress(self) -> None:
        if self._busy:
            self.spinner.start(self._progress_text)
            self.after(250, self._tick_progress)

    def _finish_fetch(self) -> None:
        self._busy = False
        self.spinner.stop()
        self.spinner.pack_forget()
        self.refresh_btn.configure(state="normal", text="⟳  Refresh news")

    def _fetch_done(self, result: FetchResult) -> None:
        self._finish_fetch()
        kind = "warning" if result.errors else ("success" if result.inserted else "info")
        self.toast.show(result.summary(), kind, 8000)
        self._reload_current()

    def _fetch_failed(self, exc: Exception) -> None:
        self._finish_fetch()
        self.ctx.show_error(exc)
        if isinstance(exc, (MissingAPIKeyError, InvalidAPIKeyError)):
            self.navigate("settings")

    # ----------------------------------------------------------- lifecycle --
    def _on_tk_error(self, exc_type, exc, tb) -> None:
        log.error("Unhandled UI error", exc_info=(exc_type, exc, tb))
        try:
            self.toast.show(f"Something went wrong: {exc}. Details are in the log file.", "error", 9000)
        except Exception:  # noqa: BLE001
            pass

    def _on_close(self) -> None:
        self.runner.shutdown()
        self.destroy()


def run_gui() -> int:
    config = Config()
    setup_logging(config.paths.logs_dir, config.log_level, console=False)
    log.info("Starting GUI")
    try:
        service = NewsService(config)
        app = NewsPulseApp(service)
    except NewsPulseError as exc:
        print(f"Could not start NewsPulse: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - typically TclError when there is no display
        if exc.__class__.__name__ == "TclError":
            print("NewsPulse could not open a window (no display available).\n"
                  "Use the command-line interface instead: python main.py --help", file=sys.stderr)
            return 1
        raise
    app.mainloop()
    return 0
