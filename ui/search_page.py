"""Search page: instant search over stored articles, plus an online NewsAPI search."""
from __future__ import annotations

from typing import Optional

import customtkinter as ctk

from models import FetchResult
from ui import theme
from ui.article_browser import ArticleBrowser
from ui.base_page import AppContext, BasePage
from ui.components import Card, Spinner, secondary_button
from ui.news_pages import apply_deep_link
from ui.theme import font


class SearchPage(BasePage):
    def __init__(self, master, ctx: AppContext) -> None:
        super().__init__(master, ctx)
        info = Card(self)
        info.pack(fill="x", pady=(0, 10))
        row = ctk.CTkFrame(info, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=12)
        self.hint = ctk.CTkLabel(
            row, text="", font=font(13), text_color=theme.MUTED, anchor="w", justify="left", wraplength=640)
        self.hint.pack(side="left", fill="x", expand=True)
        self.spinner = Spinner(row, "Searching NewsAPI…")
        self.online_btn = secondary_button(row, "Search NewsAPI online", self._search_online, width=190)
        self.online_btn.pack(side="right", padx=(12, 0))

        self.browser = ArticleBrowser(
            self, ctx, empty_icon="⌕", empty_title="No matching articles",
            empty_message="Try a different keyword, or use “Search NewsAPI online” to look further back.")
        self.browser.pack(fill="both", expand=True)

    def on_show(self, keyword: Optional[str] = None, source: Optional[str] = None,
                category: Optional[str] = None, **_) -> None:
        demo = self.svc.demo_mode
        self.online_btn.configure(state="disabled" if demo else "normal")
        self.hint.configure(text=(
            "Demo mode: searching the sample articles only. Online search needs live mode." if demo else
            "Filters combine (keyword AND source AND category AND dates). The list searches articles stored "
            "on this computer; use “Search NewsAPI online” to pull more from NewsAPI’s archive."))
        self.browser.refresh_sources()
        apply_deep_link(self.browser, keyword, source, category)
        self.browser.reload()

    # ------------------------------------------------------- online search --
    def _search_online(self) -> None:
        flt = self.browser.bar.get_filter()
        if flt is None:
            return
        if len(flt.keyword) < 2:
            self.ctx.toast.show("Type a keyword (2+ characters) to search online.", "warning")
            return
        self.online_btn.configure(state="disabled")
        self.spinner.pack(side="right")
        self.spinner.start("Searching NewsAPI…")
        self.ctx.runner.run(
            lambda: self.svc.search_online(flt.keyword, flt.date_from, flt.date_to),
            self._online_done, self._online_failed, owner=self)

    def _finish_online(self) -> None:
        self.spinner.stop()
        self.spinner.pack_forget()
        self.online_btn.configure(state="disabled" if self.svc.demo_mode else "normal")

    def _online_done(self, result: FetchResult) -> None:
        self._finish_online()
        self.ctx.toast.show(result.summary(), "success" if result.inserted else "info")
        self.browser.refresh_sources()
        self.browser.reload()

    def _online_failed(self, exc: Exception) -> None:
        self._finish_online()
        self.ctx.show_error(exc)
