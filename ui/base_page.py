"""Shared application context and the base class for all pages."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

import customtkinter as ctk

from models import Article
from services import NewsService
from ui.async_utils import TaskRunner


@dataclass
class AppContext:
    """Everything a page needs; passed around instead of globals."""

    root: Any
    service: NewsService
    runner: TaskRunner
    images: Any                       # ui.news_cards.ImageLoader
    toast: Any                        # ui.components.Toast
    navigate: Callable[..., None]
    refresh_news: Callable[[], None]
    on_mode_changed: Callable[[], None]
    on_appearance_changed: Callable[[], None]

    def open_article(self, article: Article, on_change: Optional[Callable[[], None]] = None) -> None:
        from ui.article_dialog import ArticleDialog
        ArticleDialog(self.root, self, article, on_change)

    def show_error(self, exc: Exception) -> None:
        self.toast.show(str(exc) or exc.__class__.__name__, "error", 9000)


class BasePage(ctk.CTkFrame):
    """A full-size page. ``on_show`` runs every time the page becomes visible."""

    def __init__(self, master, ctx: AppContext) -> None:
        super().__init__(master, fg_color="transparent")
        self.ctx = ctx
        self.svc = ctx.service

    def on_show(self, **params) -> None:  # pragma: no cover - overridden
        """Refresh the page's data. ``params`` come from ``navigate(key, **params)``."""

    def on_theme_changed(self) -> None:
        self.on_show()
