"""Analytics page: three Matplotlib charts rendered inside the window."""
from __future__ import annotations

from typing import Dict

import customtkinter as ctk
import pandas as pd

import analytics
from ui import theme
from ui.base_page import AppContext, BasePage
from ui.components import Card, ChartFrame, card_title, segmented, small_button
from ui.theme import font

RANGES = {"7 days": 7, "14 days": 14, "30 days": 30}


class AnalyticsPage(BasePage):
    def __init__(self, master, ctx: AppContext) -> None:
        super().__init__(master, ctx)
        self.days = 14
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        scroll.grid_columnconfigure(0, weight=1, uniform="a")
        scroll.grid_columnconfigure(1, weight=1, uniform="a")

        top = ctk.CTkFrame(scroll, fg_color="transparent")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self.summary = ctk.CTkLabel(top, text="", font=font(13), text_color=theme.MUTED)
        self.summary.pack(side="left")
        self.range = segmented(top, list(RANGES), self._range_changed)
        self.range.set("14 days")
        self.range.pack(side="right")
        ctk.CTkLabel(top, text="Daily chart range", font=font(12), text_color=theme.MUTED).pack(side="right", padx=10)

        self.charts: Dict[str, ChartFrame] = {}
        self._panel(scroll, "source", "Articles by source", "Top publishers in your library", 1, 0, 1)
        self._panel(scroll, "category", "Articles by category", "How your library is split by topic", 1, 1, 1)
        self._panel(scroll, "daily", "Daily news collection", "Articles stored per day", 2, 0, 2)

    def _panel(self, parent, kind: str, title: str, subtitle: str, row: int, col: int, span: int) -> None:
        card = Card(parent)
        card.grid(row=row, column=col, columnspan=span, sticky="nsew",
                  padx=(0 if col == 0 else 6, 0 if (col + span) == 2 else 6), pady=(0, 12))
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 0))
        card_title(head, title, subtitle).pack(side="left")
        small_button(head, "Save PNG", lambda k=kind: self._save(k), width=84).pack(side="right")
        chart = ChartFrame(card, height=300)
        chart.pack(fill="both", expand=True, padx=8, pady=(4, 12))
        self.charts[kind] = chart

    # ------------------------------------------------------------ loading --
    def on_show(self, **_) -> None:
        days = self.days
        self.ctx.runner.run(lambda: self.svc.analytics_frames(days), self._render, self.ctx.show_error, owner=self)

    def _range_changed(self, label: str) -> None:
        self.days = RANGES[label]
        self.on_show()

    def _render(self, frames: Dict[str, pd.DataFrame]) -> None:
        mode = theme.chart_theme()
        total = int(frames["category"]["articles"].sum()) if not frames["category"].empty else 0
        self.summary.configure(text=f"{total:,} articles analysed" + ("  ·  demo data" if self.svc.demo_mode else ""))
        self.charts["source"].show_figure(analytics.source_chart(frames["source"], mode, figsize=(4.6, 3.3)))
        self.charts["category"].show_figure(analytics.category_chart(frames["category"], mode, figsize=(4.6, 3.3)))
        self.charts["daily"].show_figure(analytics.daily_chart(frames["daily"], mode, figsize=(9.2, 3.2)))

    # --------------------------------------------------------------- save --
    def _save(self, kind: str) -> None:
        mode, days = theme.chart_theme(), self.days
        self.ctx.runner.run(
            lambda: self.svc.chart(kind, mode, days=days),
            lambda path: self.ctx.toast.show(f"Chart saved: {path.name} (see Export Data → Recent exports)", "success"),
            self.ctx.show_error, owner=self)
