"""Filter bar + paginated article list + loading / empty / error states."""
from __future__ import annotations

import dataclasses
from typing import Callable, Optional, Sequence

import customtkinter as ctk

from filters import ArticleFilter
from models import Page
from ui import theme
from ui.base_page import AppContext
from ui.components import EmptyState, Pagination, Spinner
from ui.filter_bar import FilterBar
from ui.news_cards import ArticleCard
from ui.theme import font


class ArticleBrowser(ctk.CTkFrame):
    """Reusable list view; every page that shows articles is a thin wrapper around it."""

    def __init__(self, master, ctx: AppContext, fields: Sequence[str] = ("keyword", "source", "category", "dates", "sort"),
                 saved_only: bool = False, empty_icon: str = "☰", empty_title: str = "No articles found",
                 empty_message: str = "Try different filters, or refresh to fetch the latest news.",
                 on_changed: Optional[Callable[[], None]] = None) -> None:
        super().__init__(master, fg_color="transparent")
        self.ctx = ctx
        self.saved_only = saved_only
        self.category_override: Optional[str] = None
        self._empty = (empty_icon, empty_title, empty_message)
        self._on_changed = on_changed
        self._page = 1
        self._token = 0

        self.bar = FilterBar(self, ctx, on_apply=lambda: self.reload(), fields=fields)
        self.bar.pack(fill="x", pady=(0, 10))

        status = ctk.CTkFrame(self, fg_color="transparent")
        status.pack(fill="x", pady=(0, 6))
        self.count_label = ctk.CTkLabel(status, text="", font=font(13, "bold"), text_color=theme.TEXT)
        self.count_label.pack(side="left")
        self.spinner = Spinner(status, "Loading…")

        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        self.list.pack(fill="both", expand=True)
        self.pager = Pagination(self, self._goto)
        self.pager.pack(pady=(8, 0))

    # ---------------------------------------------------------- loading ---
    def current_filter(self) -> Optional[ArticleFilter]:
        flt = self.bar.get_filter(saved_only=self.saved_only)
        if flt is not None and self.category_override:
            flt = dataclasses.replace(flt, category=self.category_override)
        return flt

    def refresh_sources(self) -> None:
        self.bar.refresh_sources()

    def reload(self, keep_page: bool = False) -> None:
        flt = self.current_filter()
        if flt is None:
            return
        if not keep_page:
            self._page = 1
        self._token += 1
        token, page = self._token, self._page
        self.spinner.pack(side="right")
        self.spinner.start("Loading…")
        self.ctx.runner.run(
            lambda: self.ctx.service.query(flt, page),
            lambda result: self._render(result, token),
            lambda exc: self._failed(exc, token), owner=self)

    def _goto(self, page: int) -> None:
        self._page = page
        self.reload(keep_page=True)

    def _item_changed(self) -> None:
        if self._on_changed:
            self._on_changed()
        if self.saved_only:          # an article was un-saved -> list must update
            self.reload(keep_page=True)

    # --------------------------------------------------------- rendering --
    def _clear_list(self) -> None:
        for child in self.list.winfo_children():
            child.destroy()

    def _render(self, result: Page, token: int) -> None:
        if token != self._token:
            return
        self.spinner.stop()
        self.spinner.pack_forget()
        self._page = result.page
        self._clear_list()
        self.count_label.configure(text=f"{result.total:,} article{'s' if result.total != 1 else ''}")
        self.pager.update_state(result.page, result.pages, result.total)
        if not result.items:
            icon, title, message = self._empty
            flt = self.bar.get_filter(self.saved_only)
            if flt is not None and flt.is_active:
                title, message = "No matching articles", "Nothing matches your filters. Try clearing some of them."
            EmptyState(self.list, icon, title, message).pack(pady=20)
            return
        for article in result.items:
            ArticleCard(self.list, self.ctx, article, self._item_changed).pack(fill="x", pady=(0, 10), padx=(0, 6))
        try:
            self.list._parent_canvas.yview_moveto(0)
        except Exception:  # noqa: BLE001 - private attribute; cosmetic only
            pass

    def _failed(self, exc: Exception, token: int) -> None:
        if token != self._token:
            return
        self.spinner.stop()
        self.spinner.pack_forget()
        self._clear_list()
        EmptyState(self.list, "⚠", "Could not load articles", str(exc)).pack(pady=20)
