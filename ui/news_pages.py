"""Pages that list stored articles: All News, Categories and Saved Articles.

All three are thin wrappers around :class:`ui.article_browser.ArticleBrowser`.
"""
from __future__ import annotations

from typing import Optional

import customtkinter as ctk

from config import CATEGORIES
from ui import theme
from ui.article_browser import ArticleBrowser
from ui.base_page import AppContext, BasePage
from ui.components import chip, secondary_button
from ui.theme import font


def apply_deep_link(browser: ArticleBrowser, keyword: Optional[str], source: Optional[str],
                    category: Optional[str]) -> None:
    """Pre-fill filters when another page navigates here (e.g. Sources -> its articles)."""
    if keyword is None and source is None and category is None:
        return
    browser.bar.reset()
    browser.bar.set_values(keyword=keyword, source=source, category=category)


class AllNewsPage(BasePage):
    def __init__(self, master, ctx: AppContext) -> None:
        super().__init__(master, ctx)
        self.browser = ArticleBrowser(
            self, ctx, empty_title="No news yet",
            empty_message="Press “Refresh news” in the top-right corner to fetch the latest headlines.")
        self.browser.pack(fill="both", expand=True)

    def on_show(self, keyword: Optional[str] = None, source: Optional[str] = None,
                category: Optional[str] = None, **_) -> None:
        self.browser.refresh_sources()
        apply_deep_link(self.browser, keyword, source, category)
        self.browser.reload()


class SavedPage(BasePage):
    def __init__(self, master, ctx: AppContext) -> None:
        super().__init__(master, ctx)
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(bar, text="Articles you starred are kept here, even after old news is cleaned up.",
                     font=font(13), text_color=theme.MUTED).pack(side="left")
        secondary_button(bar, "Export saved…", lambda: ctx.navigate("export", saved_only=True),
                         width=130).pack(side="right")
        self.browser = ArticleBrowser(
            self, ctx, saved_only=True, empty_icon="★", empty_title="No saved articles yet",
            empty_message="Press ☆ Save on any article and it will appear here.")
        self.browser.pack(fill="both", expand=True)

    def on_show(self, **_) -> None:
        self.browser.refresh_sources()
        self.browser.reload()


class CategoriesPage(BasePage):
    def __init__(self, master, ctx: AppContext) -> None:
        super().__init__(master, ctx)
        self.selected: Optional[str] = None
        self.chips = ctk.CTkFrame(self, fg_color="transparent")
        self.chips.pack(fill="x", pady=(0, 10))
        self.browser = ArticleBrowser(
            self, ctx, fields=("keyword", "source", "dates", "sort"), empty_icon="▤",
            empty_title="Nothing in this category",
            empty_message="Refresh the news, or pick another category above.")
        self.browser.pack(fill="both", expand=True)

    def on_show(self, category: Optional[str] = None, **_) -> None:
        if category is not None:
            self.selected = category or None
        self._build_chips()
        self.browser.category_override = self.selected
        self.browser.refresh_sources()
        self.browser.reload()

    def _build_chips(self) -> None:
        for child in self.chips.winfo_children():
            child.destroy()
        counts = self.svc.category_counts()
        chip(self.chips, f"All  {sum(counts.values()):,}", lambda: self._select(None),
             selected=self.selected is None).pack(side="left", padx=(0, 8))
        for category in CATEGORIES:
            chip(self.chips, f"{category.title()}  {counts[category]:,}", lambda c=category: self._select(c),
                 selected=self.selected == category).pack(side="left", padx=(0, 8))

    def _select(self, category: Optional[str]) -> None:
        self.selected = category
        self._build_chips()
        self.browser.category_override = category
        self.browser.reload()
