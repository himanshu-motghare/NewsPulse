"""Article cards and thumbnail loading."""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional, Tuple

import customtkinter as ctk
import requests
from PIL import Image, ImageOps

from config import USER_AGENT
from logger import get_logger
from models import Article
from ui import theme
from ui.base_page import AppContext
from ui.components import small_button
from ui.theme import font
from utils import open_url, time_ago, truncate

log = get_logger("ui.images")
MAX_IMAGE_BYTES = 3_000_000


class ImageLoader:
    """Downloads thumbnails in the background and caches them on disk and in memory."""

    def __init__(self, runner, cache_dir: Path) -> None:
        self._runner = runner
        self._dir = Path(cache_dir) / "images"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._failed: set = set()
        self._memory: "OrderedDict[Tuple[str, Tuple[int, int]], ctk.CTkImage]" = OrderedDict()

    def load(self, url: str, size: Tuple[int, int], owner, callback: Callable[[ctk.CTkImage], None]) -> None:
        if not url or url in self._failed:
            return
        key = (url, size)
        if key in self._memory:
            callback(self._memory[key])
            return

        def done(img: Optional[Image.Image]) -> None:
            if img is None:
                self._failed.add(url)
                return
            image = ctk.CTkImage(light_image=img, dark_image=img, size=size)
            self._memory[key] = image
            while len(self._memory) > 150:
                self._memory.popitem(last=False)
            callback(image)

        self._runner.run(lambda: self._fetch(url, size), done, owner=owner)

    def _fetch(self, url: str, size: Tuple[int, int]) -> Optional[Image.Image]:
        name = hashlib.sha1(f"{url}|{size}".encode()).hexdigest() + ".png"
        path = self._dir / name
        try:
            if path.exists():
                with Image.open(path) as cached:
                    return cached.copy()
            if not url.lower().startswith(("http://", "https://")):
                return None
            resp = requests.get(url, timeout=8, stream=True, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            if not resp.headers.get("Content-Type", "image/").lower().startswith("image/"):
                return None
            data = b""
            for chunk in resp.iter_content(65536):
                data += chunk
                if len(data) > MAX_IMAGE_BYTES:
                    return None
            img = Image.open(BytesIO(data))
            img.load()
            img = ImageOps.fit(img.convert("RGB"), (size[0] * 2, size[1] * 2), Image.LANCZOS)
            img.save(path, "PNG")
            return img
        except (requests.RequestException, OSError, ValueError, Image.DecompressionBombError) as exc:
            log.debug("Thumbnail failed for %s: %s", url, exc)
            return None


def category_badge(master, category: str) -> ctk.CTkLabel:
    color = theme.CATEGORY_COLORS.get(category, theme.MUTED if False else "#94A3B8")
    return ctk.CTkLabel(master, text=f" {category.title()} ", font=font(11, "bold"), text_color="white",
                        fg_color=color, corner_radius=8, height=20)


class ArticleCard(ctk.CTkFrame):
    """One article in a list: thumbnail, meta line, title, summary and actions."""

    IMG = (168, 104)

    def __init__(self, master, ctx: AppContext, article: Article,
                 on_change: Optional[Callable[[], None]] = None) -> None:
        super().__init__(master, fg_color=theme.CARD, corner_radius=theme.RADIUS, border_width=1,
                         border_color=theme.BORDER)
        self.ctx, self.article, self._on_change = ctx, article, on_change
        self._wrap = 0
        self.grid_columnconfigure(1, weight=1)

        self.thumb = ctk.CTkLabel(self, text=article.category[:1].upper() or "N", width=self.IMG[0],
                                  height=self.IMG[1], corner_radius=12, font=font(30, "bold"),
                                  text_color="white",
                                  fg_color=theme.CATEGORY_COLORS.get(article.category, "#475569"))
        self.thumb.grid(row=0, column=0, rowspan=2, padx=(14, 6), pady=14, sticky="n")
        if article.image_url:
            ctx.images.load(article.image_url, self.IMG, self, self._set_thumbnail)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=(12, 0))
        meta = ctk.CTkFrame(body, fg_color="transparent")
        meta.pack(anchor="w", fill="x")
        ctk.CTkLabel(meta, text=article.source_name, font=font(12, "bold"), text_color=theme.PURPLE).pack(side="left")
        ctk.CTkLabel(meta, text=f"  ·  {time_ago(article.published_at)}  ·  ", font=font(12),
                     text_color=theme.MUTED).pack(side="left")
        category_badge(meta, article.category).pack(side="left")
        if article.is_demo:
            ctk.CTkLabel(meta, text=" DEMO ", font=font(11, "bold"), text_color="black", fg_color=theme.WARNING,
                         corner_radius=8, height=20).pack(side="left", padx=(6, 0))

        self.title = ctk.CTkLabel(body, text=article.title, font=font(16, "bold"), text_color=theme.TEXT,
                                  anchor="w", justify="left", wraplength=520)
        self.title.pack(anchor="w", pady=(6, 2), fill="x")
        summary = truncate(article.description or "No description available.", 240)
        self.summary = ctk.CTkLabel(body, text=summary, font=font(13), text_color=theme.MUTED, anchor="w",
                                    justify="left", wraplength=520)
        self.summary.pack(anchor="w", fill="x")
        if article.note:
            ctk.CTkLabel(body, text=f"✎ {article.note}", font=font(12), text_color=theme.WARNING, anchor="w",
                         justify="left", wraplength=520).pack(anchor="w", pady=(4, 0))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=1, column=1, sticky="w", padx=(8, 16), pady=(6, 12))
        small_button(actions, "Read ↗", self._open, width=76).pack(side="left", padx=(0, 6))
        small_button(actions, "Details", lambda: ctx.open_article(self.article, self._changed), width=70).pack(side="left", padx=(0, 6))
        self.save_btn = small_button(actions, "", self._toggle_saved, width=84)
        self.save_btn.pack(side="left", padx=(0, 6))
        self._refresh_save_button()
        if article.is_saved:
            small_button(actions, "✎ Note", self._edit_note, width=74).pack(side="left")

        self.bind("<Configure>", self._on_resize)
        self._bind_hover(self)

    # ---------------------------------------------------------- behaviour --
    def _set_thumbnail(self, image: ctk.CTkImage) -> None:
        if self.thumb.winfo_exists():
            self.thumb.configure(image=image, text="", fg_color="transparent")

    def _on_resize(self, event) -> None:
        wrap = max(240, event.width - self.IMG[0] - 70)
        if abs(wrap - self._wrap) > 12:
            self._wrap = wrap
            self.title.configure(wraplength=wrap)
            self.summary.configure(wraplength=wrap)

    def _open(self) -> None:
        if not open_url(self.article.url):
            self.ctx.toast.show("Could not open the link in your browser.", "error")

    def _toggle_saved(self) -> None:
        try:
            if self.article.is_saved:
                self.ctx.service.unsave_article(self.article.id)
                self.ctx.toast.show("Removed from saved articles.", "info", 2500)
            else:
                self.ctx.service.save_article(self.article.id)
                self.ctx.toast.show("Saved! Find it under Saved Articles.", "success", 2500)
        except Exception as exc:  # noqa: BLE001
            self.ctx.show_error(exc)
            return
        self.article.is_saved = not self.article.is_saved
        self._refresh_save_button()
        self._changed()

    def _edit_note(self) -> None:
        dialog = ctk.CTkInputDialog(text="Note for this article:", title="Edit note")
        text = dialog.get_input()
        if text is None:
            return
        try:
            self.ctx.service.update_note(self.article.id, text.strip())
        except Exception as exc:  # noqa: BLE001
            self.ctx.show_error(exc)
            return
        self._changed()

    def _refresh_save_button(self) -> None:
        saved = self.article.is_saved
        self.save_btn.configure(text="★ Saved" if saved else "☆ Save",
                                fg_color=theme.PURPLE if saved else theme.HOVER,
                                hover_color=theme.PURPLE_HOVER if saved else theme.ACTIVE_NAV,
                                text_color="white" if saved else theme.TEXT)

    def _changed(self) -> None:
        if self._on_change:
            self._on_change()

    # -------------------------------------------------------------- hover --
    def _bind_hover(self, widget) -> None:
        widget.bind("<Enter>", self._hover_on, add="+")
        widget.bind("<Leave>", self._hover_off, add="+")
        for child in widget.winfo_children():
            self._bind_hover(child)

    def _hover_on(self, _event=None) -> None:
        self.configure(fg_color=theme.CARD_HOVER, border_color=theme.PURPLE)

    def _hover_off(self, _event=None) -> None:
        x, y = self.winfo_pointerxy()
        under = self.winfo_containing(x, y)
        if under is not None and str(under).startswith(str(self)):
            return
        self.configure(fg_color=theme.CARD, border_color=theme.BORDER)


class CompactRow(ctk.CTkFrame):
    """Dense one-article row used on the dashboard."""

    def __init__(self, master, ctx: AppContext, article: Article) -> None:
        super().__init__(master, fg_color="transparent", corner_radius=10, cursor="hand2")
        self.article = article
        bar = ctk.CTkFrame(self, width=4, height=40, corner_radius=2,
                           fg_color=theme.CATEGORY_COLORS.get(article.category, theme.PURPLE))
        bar.pack(side="left", padx=(8, 10), pady=8)
        text = ctk.CTkFrame(self, fg_color="transparent")
        text.pack(side="left", fill="x", expand=True, pady=6)
        ctk.CTkLabel(text, text=truncate(article.title, 95), font=font(13, "bold"), text_color=theme.TEXT,
                     anchor="w", justify="left", wraplength=520).pack(anchor="w", fill="x")
        ctk.CTkLabel(text, text=f"{article.source_name}  ·  {time_ago(article.published_at)}  ·  {article.category.title()}",
                     font=font(11), text_color=theme.MUTED, anchor="w").pack(anchor="w")
        for widget in (self, bar, text, *text.winfo_children()):
            widget.bind("<Button-1>", lambda _e: ctx.open_article(article), add="+")
            widget.bind("<Enter>", lambda _e: self.configure(fg_color=theme.HOVER), add="+")
            widget.bind("<Leave>", lambda _e: self.configure(fg_color="transparent"), add="+")
