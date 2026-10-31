"""News Sources page: the publishers behind your articles, with live counts."""
from __future__ import annotations

from typing import Dict, List

import customtkinter as ctk

from ui import theme
from ui.base_page import AppContext, BasePage
from ui.components import Card, EmptyState, Spinner, entry, secondary_button, small_button
from ui.theme import font
from utils import truncate

MAX_ROWS = 150


class SourcesPage(BasePage):
    def __init__(self, master, ctx: AppContext) -> None:
        super().__init__(master, ctx)
        self._sources: List[Dict] = []

        bar = Card(self)
        bar.pack(fill="x", pady=(0, 10))
        row = ctk.CTkFrame(bar, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)
        self.search = entry(row, "Filter sources by name or description…", width=260)
        self.search.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.search.bind("<KeyRelease>", lambda _e: self._render())
        self.spinner = Spinner(row, "Downloading sources…")
        self.refresh_btn = secondary_button(row, "Refresh source list", self._refresh, width=160)
        self.refresh_btn.pack(side="right")

        self.summary = ctk.CTkLabel(self, text="", font=font(13, "bold"), text_color=theme.TEXT, anchor="w")
        self.summary.pack(fill="x", pady=(0, 6))
        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list.pack(fill="both", expand=True)

    def on_show(self, **_) -> None:
        self.refresh_btn.configure(state="disabled" if self.svc.demo_mode else "normal")
        self.ctx.runner.run(self.svc.list_sources, self._loaded, self.ctx.show_error, owner=self)

    def _loaded(self, sources: List[Dict]) -> None:
        self._sources = sources
        self._render()

    def _render(self) -> None:
        for child in self.list.winfo_children():
            child.destroy()
        needle = self.search.get().strip().lower()
        shown = [s for s in self._sources
                 if not needle or needle in s["name"].lower() or needle in (s["description"] or "").lower()]
        with_articles = sum(1 for s in self._sources if s["article_count"])
        self.summary.configure(text=f"{len(shown)} of {len(self._sources)} sources  ·  "
                                    f"{with_articles} have articles in your library")
        if not shown:
            if self._sources:
                EmptyState(self.list, "◉", "No sources match", "Try a shorter search word.").pack(pady=20)
            else:
                EmptyState(self.list, "◉", "No sources yet",
                           "Sources appear as you fetch news. In live mode you can also download NewsAPI’s "
                           "full directory with “Refresh source list”.").pack(pady=20)
            return
        for source in shown[:MAX_ROWS]:
            self._row(source)
        if len(shown) > MAX_ROWS:
            ctk.CTkLabel(self.list, text=f"Showing the first {MAX_ROWS}. Use the filter to narrow the list.",
                         font=font(12), text_color=theme.MUTED).pack(pady=10)

    def _row(self, source: Dict) -> None:
        card = Card(self.list)
        card.pack(fill="x", pady=(0, 8), padx=(0, 6))
        card.grid_columnconfigure(0, weight=1)
        text = ctk.CTkFrame(card, fg_color="transparent")
        text.grid(row=0, column=0, sticky="w", padx=16, pady=12)
        ctk.CTkLabel(text, text=source["name"], font=font(15, "bold"), text_color=theme.TEXT, anchor="w").pack(anchor="w")
        facts = "  ·  ".join(x for x in (
            (source["category"] or "").title(), (source["country"] or "").upper(), (source["language"] or "").upper()) if x)
        if facts:
            ctk.CTkLabel(text, text=facts, font=font(11), text_color=theme.PURPLE, anchor="w").pack(anchor="w")
        if source["description"]:
            ctk.CTkLabel(text, text=truncate(source["description"], 150), font=font(12), text_color=theme.MUTED,
                         anchor="w", justify="left", wraplength=560).pack(anchor="w", pady=(2, 0))
        count = source["article_count"]
        ctk.CTkLabel(card, text=f"{count:,} article{'s' if count != 1 else ''}", font=font(13, "bold"),
                     text_color=theme.TEXT).grid(row=0, column=1, padx=12)
        small_button(card, "View articles", lambda n=source["name"]: self.ctx.navigate("news", source=n),
                     width=110, state="normal" if count else "disabled").grid(row=0, column=2, padx=(0, 16))

    # ------------------------------------------------------------ refresh --
    def _refresh(self) -> None:
        self.refresh_btn.configure(state="disabled")
        self.spinner.pack(side="right", padx=(0, 12))
        self.spinner.start()
        self.ctx.runner.run(self.svc.refresh_sources, self._refreshed, self._refresh_failed, owner=self)

    def _done(self) -> None:
        self.spinner.stop()
        self.spinner.pack_forget()
        self.refresh_btn.configure(state="disabled" if self.svc.demo_mode else "normal")

    def _refreshed(self, stored: int) -> None:
        self._done()
        self.ctx.toast.show(f"Downloaded {stored} sources from NewsAPI.", "success")
        self.on_show()

    def _refresh_failed(self, exc: Exception) -> None:
        self._done()
        self.ctx.show_error(exc)
