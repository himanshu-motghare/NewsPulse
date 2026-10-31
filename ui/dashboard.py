"""Dashboard: headline numbers, recent news, trending keywords, category chart."""
from __future__ import annotations

from typing import Dict

import customtkinter as ctk

import analytics
from ui import theme
from ui.base_page import AppContext, BasePage
from ui.components import (Card, ChartFrame, EmptyState, StatCard, card_title, chip,
                           secondary_button)
from ui.news_cards import CompactRow
from ui.theme import font
from utils import time_ago

KEYWORD_COLUMNS = 3


class DashboardPage(BasePage):
    def __init__(self, master, ctx: AppContext) -> None:
        super().__init__(master, ctx)
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True)
        self.updated = ctk.CTkLabel(self.scroll, text="", font=font(12), text_color=theme.MUTED, anchor="w")
        self.updated.pack(anchor="w", pady=(0, 8))

        # --- headline numbers ---------------------------------------------
        stats = ctk.CTkFrame(self.scroll, fg_color="transparent")
        stats.pack(fill="x")
        self.cards: Dict[str, StatCard] = {}
        specs = [("total", "☰", "Total articles", theme.PURPLE),
                 ("today", "⚡", "Today’s headlines", theme.BLUE),
                 ("sources", "◉", "News sources", "#22D3EE"),
                 ("saved", "★", "Saved articles", "#F472B6")]
        for col, (key, icon, label, accent) in enumerate(specs):
            stats.grid_columnconfigure(col, weight=1, uniform="stat")
            card = StatCard(stats, icon, label, accent)
            card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0 if col == 3 else 6))
            self.cards[key] = card

        # --- empty state (shown instead of the body when nothing is stored) ---
        self.empty = ctk.CTkFrame(self.scroll, fg_color="transparent")

        # --- body ---------------------------------------------------------
        self.body = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self.body.pack(fill="both", expand=True, pady=(12, 0))
        self.body.grid_columnconfigure(0, weight=3, uniform="body")
        self.body.grid_columnconfigure(1, weight=2, uniform="body")

        recent = Card(self.body)
        recent.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 6))
        head = ctk.CTkFrame(recent, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 4))
        card_title(head, "Recent news", "The latest articles in your library").pack(side="left")
        secondary_button(head, "View all", lambda: ctx.navigate("news"), width=80).pack(side="right")
        self.recent_list = ctk.CTkFrame(recent, fg_color="transparent")
        self.recent_list.pack(fill="both", expand=True, padx=8, pady=(0, 12))

        keywords = Card(self.body)
        keywords.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 6))
        card_title(keywords, "Trending keywords", "Click a word to search for it").pack(
            anchor="w", padx=16, pady=(14, 6))
        self.keyword_box = ctk.CTkFrame(keywords, fg_color="transparent")
        self.keyword_box.pack(fill="x", padx=12, pady=(0, 14))

        distribution = Card(self.body)
        distribution.grid(row=1, column=1, sticky="nsew", padx=(6, 0), pady=(6, 0))
        card_title(distribution, "News category distribution").pack(anchor="w", padx=16, pady=(14, 0))
        self.chart = ChartFrame(distribution, height=250)
        self.chart.pack(fill="both", expand=True, padx=8, pady=(4, 12))

    # ------------------------------------------------------------ loading --
    def on_show(self, **_) -> None:
        self.ctx.runner.run(self.svc.dashboard, self._render, self.ctx.show_error, owner=self)

    def _render(self, data: Dict) -> None:
        counts = data["counts"]
        for key, card in self.cards.items():
            card.set_value(counts[key])
        last = data["last_fetch"]
        self.updated.configure(
            text=(f"Last update {time_ago(last['started_at'])} · {last['inserted']} new article"
                  f"{'s' if last['inserted'] != 1 else ''}") if last else "No updates yet")

        if counts["total"] == 0:
            self._show_empty()
            return
        self.empty.pack_forget()
        if not self.body.winfo_ismapped():
            self.body.pack(fill="both", expand=True, pady=(12, 0))

        for child in self.recent_list.winfo_children():
            child.destroy()
        for article in data["recent"]:
            CompactRow(self.recent_list, self.ctx, article).pack(fill="x")

        for child in self.keyword_box.winfo_children():
            child.destroy()
        if data["keywords"]:
            for i, (word, n) in enumerate(data["keywords"]):
                chip(self.keyword_box, f"{word}  {n}", lambda w=word: self.ctx.navigate("search", keyword=w)).grid(
                    row=i // KEYWORD_COLUMNS, column=i % KEYWORD_COLUMNS, padx=3, pady=3, sticky="w")
        else:
            ctk.CTkLabel(self.keyword_box, text="Not enough headlines yet.", font=font(12),
                         text_color=theme.MUTED).pack(anchor="w", padx=4)

        frame = analytics.to_frame(data["categories"], "category")
        self.chart.show_figure(analytics.category_chart(frame, theme.chart_theme(), figsize=(4.4, 3.0)))

    def _show_empty(self) -> None:
        self.body.pack_forget()
        for child in self.empty.winfo_children():
            child.destroy()
        if self.svc.needs_setup:
            EmptyState(self.empty, "⚙", "Let’s get you set up",
                       "Add your free NewsAPI key to fetch live headlines, or switch on demo mode to explore "
                       "with clearly labelled sample articles.",
                       "Open settings", lambda: self.ctx.navigate("settings")).pack()
        else:
            label = "Load demo articles" if self.svc.demo_mode else "Fetch latest news"
            EmptyState(self.empty, "☰", "Your library is empty",
                       "Fetch articles to fill the dashboard." if not self.svc.demo_mode else
                       "Demo mode is on - load the sample articles to explore the app.",
                       label, self.ctx.refresh_news).pack()
        self.empty.pack(fill="both", expand=True, pady=20)
        self.chart.clear()
