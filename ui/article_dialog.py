"""Detail window for a single article."""
from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from models import Article
from ui import theme
from ui.base_page import AppContext
from ui.components import primary_button, secondary_button
from ui.news_cards import category_badge
from ui.theme import font
from utils import format_datetime, open_url


class ArticleDialog(ctk.CTkToplevel):
    IMG = (520, 260)

    def __init__(self, master, ctx: AppContext, article: Article, on_change: Optional[Callable[[], None]] = None) -> None:
        super().__init__(master, fg_color=theme.BG)
        self.ctx, self.article, self._on_change = ctx, article, on_change
        self.title("Article details")
        self.geometry("620x700")
        self.minsize(520, 520)
        self.transient(master)
        self.after(120, self.focus)

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=14, pady=(14, 6))

        self.image = ctk.CTkLabel(scroll, text="No image available", width=self.IMG[0], height=self.IMG[1],
                                  corner_radius=14, fg_color=theme.CARD, text_color=theme.MUTED, font=font(13))
        self.image.pack(pady=(0, 12))
        if article.image_url:
            ctx.images.load(article.image_url, self.IMG, self, self._set_image)

        meta = ctk.CTkFrame(scroll, fg_color="transparent")
        meta.pack(anchor="w", fill="x")
        ctk.CTkLabel(meta, text=article.source_name, font=font(13, "bold"), text_color=theme.PURPLE).pack(side="left")
        ctk.CTkLabel(meta, text="  ·  ", text_color=theme.MUTED).pack(side="left")
        category_badge(meta, article.category).pack(side="left")
        if article.is_demo:
            ctk.CTkLabel(meta, text=" DEMO DATA – not real news ", font=font(11, "bold"), text_color="black",
                         fg_color=theme.WARNING, corner_radius=8, height=20).pack(side="left", padx=8)

        ctk.CTkLabel(scroll, text=article.title, font=font(20, "bold"), text_color=theme.TEXT, anchor="w",
                     justify="left", wraplength=540).pack(anchor="w", pady=(10, 4), fill="x")
        byline = format_datetime(article.published_at) + (f"  ·  by {article.author}" if article.author else "")
        ctk.CTkLabel(scroll, text=byline, font=font(12), text_color=theme.MUTED, anchor="w",
                     wraplength=540, justify="left").pack(anchor="w")

        self.body = ctk.CTkLabel(scroll, text=self._body_text(), font=font(14), text_color=theme.TEXT, anchor="w",
                                 justify="left", wraplength=540)
        self.body.pack(anchor="w", pady=14, fill="x")
        self.status = ctk.CTkLabel(scroll, text="", font=font(12), text_color=theme.MUTED, anchor="w",
                                   wraplength=540, justify="left")
        self.status.pack(anchor="w")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=14, pady=(4, 14))
        primary_button(buttons, "Read full article ↗", self._open, width=160).pack(side="left")
        self.save_btn = secondary_button(buttons, "", self._toggle_saved, width=100)
        self.save_btn.pack(side="left", padx=8)
        self._refresh_save()
        secondary_button(buttons, "Copy link", self._copy, width=90).pack(side="left")
        self.more_btn = secondary_button(buttons, "Load more details", self._enrich, width=140,
                                         state="disabled" if article.is_demo else "normal")
        self.more_btn.pack(side="left", padx=8)

    def _body_text(self) -> str:
        a = self.article
        text = a.description or "No description available."
        if a.content and a.content not in text:
            text += "\n\n" + a.content
        return text

    def _set_image(self, image) -> None:
        if self.image.winfo_exists():
            self.image.configure(image=image, text="", fg_color="transparent")

    def _open(self) -> None:
        if not open_url(self.article.url):
            self.ctx.toast.show("Could not open the link.", "error")

    def _copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.article.url)
        self.status.configure(text="Link copied to clipboard.")

    def _refresh_save(self) -> None:
        self.save_btn.configure(text="★ Saved" if self.article.is_saved else "☆ Save")

    def _toggle_saved(self) -> None:
        try:
            if self.article.is_saved:
                self.ctx.service.unsave_article(self.article.id)
            else:
                self.ctx.service.save_article(self.article.id)
        except Exception as exc:  # noqa: BLE001
            self.status.configure(text=str(exc))
            return
        self.article.is_saved = not self.article.is_saved
        self._refresh_save()
        if self._on_change:
            self._on_change()

    def _enrich(self) -> None:
        self.more_btn.configure(state="disabled")
        self.status.configure(text="Reading the original page…")

        def done(updated: Article) -> None:
            self.article = updated
            self.body.configure(text=self._body_text())
            self.status.configure(text="Details updated from the article page.")
            if updated.image_url:
                self.ctx.images.load(updated.image_url, self.IMG, self, self._set_image)
            if self._on_change:
                self._on_change()

        def failed(exc: Exception) -> None:
            self.status.configure(text=str(exc))
            self.more_btn.configure(state="normal")

        self.ctx.runner.run(lambda: self.ctx.service.enrich_article(self.article.id), done, failed, owner=self)
