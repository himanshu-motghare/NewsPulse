"""Search / filter controls shared by several pages."""
from __future__ import annotations

from datetime import timedelta
from typing import Callable, Optional, Sequence

import customtkinter as ctk

from config import CATEGORIES, SORT_OPTIONS
from errors import FilterError
from filters import ArticleFilter
from ui import theme
from ui.base_page import AppContext
from ui.components import Card, entry, option_menu, primary_button, secondary_button
from ui.theme import font
from utils import utc_now

ALL_SOURCES = "All sources"
ALL_CATEGORIES = "All categories"
DATE_PRESETS = ["Any time", "Today", "Last 7 days", "Last 30 days", "Custom"]
SORT_LABELS = list(SORT_OPTIONS.values())


class FilterBar(Card):
    """Keyword, source, category, date range and sort - combined with AND."""

    def __init__(self, master, ctx: AppContext, on_apply: Callable[[], None],
                 fields: Sequence[str] = ("keyword", "source", "category", "dates", "sort")) -> None:
        super().__init__(master)
        self.ctx, self._on_apply, self.fields = ctx, on_apply, set(fields)
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)
        row1 = ctk.CTkFrame(inner, fg_color="transparent")
        row1.pack(fill="x")
        row2 = ctk.CTkFrame(inner, fg_color="transparent")
        row2.pack(fill="x", pady=(8, 0))

        self.keyword = entry(row1, "Search headlines, descriptions, sources…", width=260)
        if "keyword" in self.fields:
            self.keyword.pack(side="left", fill="x", expand=True, padx=(0, 8))
            self.keyword.bind("<Return>", lambda _e: self._on_apply())
        self.source = option_menu(row1, [ALL_SOURCES], width=170, initial=ALL_SOURCES)
        if "source" in self.fields:
            self.source.pack(side="left", padx=(0, 8))
        self.category = option_menu(row1, [ALL_CATEGORIES] + [c.title() for c in CATEGORIES], width=160,
                                    initial=ALL_CATEGORIES)
        if "category" in self.fields:
            self.category.pack(side="left", padx=(0, 8))
        self.sort = option_menu(row1, SORT_LABELS, width=150, initial=SORT_OPTIONS["newest"])
        if "sort" in self.fields:
            self.sort.pack(side="left")

        self.preset = option_menu(row2, DATE_PRESETS, command=self._apply_preset, width=130, initial=DATE_PRESETS[0])
        self.date_from = entry(row2, "From YYYY-MM-DD", width=140)
        self.date_to = entry(row2, "To YYYY-MM-DD", width=140)
        if "dates" in self.fields:
            ctk.CTkLabel(row2, text="Date", font=font(12), text_color=theme.MUTED).pack(side="left", padx=(0, 8))
            self.preset.pack(side="left", padx=(0, 8))
            self.date_from.pack(side="left", padx=(0, 8))
            self.date_to.pack(side="left", padx=(0, 8))
            for e in (self.date_from, self.date_to):
                e.bind("<Return>", lambda _e: self._on_apply())
        self.actions = ctk.CTkFrame(row2, fg_color="transparent")
        self.actions.pack(side="right")
        secondary_button(self.actions, "Clear filters", self.clear, width=110).pack(side="left", padx=(0, 8))
        primary_button(self.actions, "Apply", self._on_apply, width=90).pack(side="left")

    # ----------------------------------------------------------- values ---
    def get_filter(self, saved_only: bool = False) -> Optional[ArticleFilter]:
        """Build a validated filter, or show an error toast and return None."""
        source = self.source.get()
        category = self.category.get()
        sort_key = next((k for k, v in SORT_OPTIONS.items() if v == self.sort.get()), "newest")
        try:
            return ArticleFilter.from_inputs(
                keyword=self.keyword.get() if "keyword" in self.fields else "",
                source="" if source == ALL_SOURCES or "source" not in self.fields else source,
                category="" if category == ALL_CATEGORIES or "category" not in self.fields else category,
                date_from=self.date_from.get() if "dates" in self.fields else "",
                date_to=self.date_to.get() if "dates" in self.fields else "",
                sort=sort_key, saved_only=saved_only)
        except FilterError as exc:
            self.ctx.toast.show(str(exc), "warning", 7000)
            return None

    def set_values(self, keyword: Optional[str] = None, source: Optional[str] = None,
                   category: Optional[str] = None) -> None:
        if keyword is not None:
            self.keyword.delete(0, "end")
            self.keyword.insert(0, keyword)
        if source is not None:
            self.source.set(source or ALL_SOURCES)
        if category is not None:
            self.category.set(category.title() if category else ALL_CATEGORIES)

    def refresh_sources(self) -> None:
        names = self.ctx.service.source_names()
        current = self.source.get()
        self.source.configure(values=[ALL_SOURCES] + names)
        if current not in names:
            self.source.set(ALL_SOURCES)

    def reset(self) -> None:
        """Return every control to its default value without reloading results."""
        self.keyword.delete(0, "end")
        self.date_from.delete(0, "end")
        self.date_to.delete(0, "end")
        self.source.set(ALL_SOURCES)
        self.category.set(ALL_CATEGORIES)
        self.sort.set(SORT_OPTIONS["newest"])
        self.preset.set(DATE_PRESETS[0])

    def clear(self) -> None:
        self.reset()
        self._on_apply()

    def _apply_preset(self, choice: str) -> None:
        today = utc_now().date()
        self.date_from.delete(0, "end")
        self.date_to.delete(0, "end")
        days = {"Today": 0, "Last 7 days": 6, "Last 30 days": 29}.get(choice)
        if days is not None:
            self.date_from.insert(0, (today - timedelta(days=days)).isoformat())
            self.date_to.insert(0, today.isoformat())
            self._on_apply()
