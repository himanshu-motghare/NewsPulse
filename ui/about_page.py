"""About page: what NewsPulse is, where data comes from, and where files live."""
from __future__ import annotations

import customtkinter as ctk

from config import APP_NAME, APP_TAGLINE, APP_VERSION
from ui import theme
from ui.base_page import AppContext, BasePage
from ui.components import Card, card_title, secondary_button
from ui.theme import font
from utils import open_path, open_url

NEWSAPI_URL = "https://newsapi.org"
STACK = ("Python 3.11+ · CustomTkinter · SQLite · Requests · BeautifulSoup · Pandas · OpenPyXL · Matplotlib")
SHORTCUTS = [("F5", "Refresh news"), ("Ctrl+1 … Ctrl+9, Ctrl+0", "Jump to a page in sidebar order"),
             ("Enter", "Apply filters while typing in a search box")]


class AboutPage(BasePage):
    def __init__(self, master, ctx: AppContext) -> None:
        super().__init__(master, ctx)
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        hero = Card(scroll)
        hero.pack(fill="x", pady=(0, 12), padx=(0, 6))
        ctk.CTkLabel(hero, text=APP_NAME, font=font(30, "bold"), text_color=theme.TEXT).pack(anchor="w", padx=22, pady=(20, 0))
        ctk.CTkLabel(hero, text=f"{APP_TAGLINE}  ·  version {APP_VERSION}", font=font(14),
                     text_color=theme.PURPLE).pack(anchor="w", padx=22)
        ctk.CTkLabel(
            hero, justify="left", anchor="w", wraplength=700, font=font(13), text_color=theme.MUTED,
            text=("NewsPulse collects headlines from many publishers into one searchable library on your own "
                  "computer. Articles are de-duplicated by URL, stored in SQLite, and can be filtered, saved, "
                  "analysed and exported. The same features are available from the command line: "
                  "run “python main.py --help”.")).pack(anchor="w", padx=22, pady=(10, 18))

        self.info = Card(scroll)
        self.info.pack(fill="x", pady=(0, 12), padx=(0, 6))
        self.info_label = ctk.CTkLabel(self.info, text="", justify="left", anchor="w", wraplength=700, font=font(13),
                                       text_color=theme.TEXT)
        card_title(self.info, "Your installation").pack(anchor="w", padx=22, pady=(16, 6))
        self.info_label.pack(anchor="w", padx=22, pady=(0, 10))
        row = ctk.CTkFrame(self.info, fg_color="transparent")
        row.pack(anchor="w", padx=22, pady=(0, 16))
        secondary_button(row, "Open data folder", lambda: open_path(self.svc.config.paths.base_dir), width=150).pack(
            side="left", padx=(0, 8))
        secondary_button(row, "Open log folder", lambda: open_path(self.svc.config.paths.logs_dir), width=150).pack(side="left")

        credits = Card(scroll)
        credits.pack(fill="x", pady=(0, 12), padx=(0, 6))
        card_title(credits, "Credits").pack(anchor="w", padx=22, pady=(16, 6))
        ctk.CTkLabel(credits, text="Live headlines are provided by NewsAPI.org. Article text and images belong to "
                                   "their publishers - NewsPulse stores headlines and short summaries and links to "
                                   "the original page.", justify="left", anchor="w", wraplength=700, font=font(13),
                     text_color=theme.MUTED).pack(anchor="w", padx=22)
        ctk.CTkLabel(credits, text=f"Built with {STACK}", justify="left", anchor="w", wraplength=700,
                     font=font(12), text_color=theme.MUTED).pack(anchor="w", padx=22, pady=(8, 8))
        secondary_button(credits, "Visit newsapi.org ↗", lambda: open_url(NEWSAPI_URL), width=160).pack(
            anchor="w", padx=22, pady=(0, 16))

        keys = Card(scroll)
        keys.pack(fill="x", padx=(0, 6))
        card_title(keys, "Keyboard shortcuts").pack(anchor="w", padx=22, pady=(16, 6))
        for combo, meaning in SHORTCUTS:
            line = ctk.CTkFrame(keys, fg_color="transparent")
            line.pack(fill="x", padx=22, pady=2)
            ctk.CTkLabel(line, text=combo, width=210, anchor="w", font=font(13, "bold"), text_color=theme.TEXT).pack(side="left")
            ctk.CTkLabel(line, text=meaning, anchor="w", font=font(13), text_color=theme.MUTED).pack(side="left")
        ctk.CTkFrame(keys, height=12, fg_color="transparent").pack()

    def on_show(self, **_) -> None:
        paths = self.svc.config.paths
        counts = self.svc.db.get_counts(self.svc.demo_mode)
        self.info_label.configure(text=(
            f"Mode: {self.svc.mode_label}\nArticles in library: {counts['total']:,}   ·   Saved: {counts['saved']:,}\n"
            f"Database: {paths.db_path}\nExports: {paths.exports_dir}\nLogs: {paths.logs_dir}"))

    def on_theme_changed(self) -> None:
        pass
