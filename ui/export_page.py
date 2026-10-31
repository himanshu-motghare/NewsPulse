"""Export page: choose filters + format, write CSV / Excel / JSON, manage past exports."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional, Tuple

import customtkinter as ctk

from ui import theme
from ui.base_page import AppContext, BasePage
from ui.components import (Card, EmptyState, Spinner, card_title, confirm, entry, primary_button,
                           secondary_button, segmented, small_button, switch)
from ui.filter_bar import FilterBar
from ui.theme import font
from utils import open_path

FORMATS = {"CSV": "csv", "Excel (.xlsx)": "excel", "JSON": "json"}


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB"):
        if size < 1024 or unit == "MB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size} B"


class ExportPage(BasePage):
    def __init__(self, master, ctx: AppContext) -> None:
        super().__init__(master, ctx)
        self._count_token = 0
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # 1. what ---------------------------------------------------------
        what = Card(scroll)
        what.pack(fill="x", pady=(0, 10), padx=(0, 6))
        card_title(what, "1 · Choose what to export",
                   "Only articles matching these filters are exported.").pack(anchor="w", padx=16, pady=(14, 8))
        self.bar = FilterBar(what, ctx, on_apply=self._update_count)
        self.bar.pack(fill="x", padx=12)
        row = ctk.CTkFrame(what, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=12)
        self.saved_switch = switch(row, "Saved articles only", self._update_count)
        self.saved_switch.pack(side="left")
        self.count_label = ctk.CTkLabel(row, text="", font=font(13, "bold"), text_color=theme.PURPLE)
        self.count_label.pack(side="right")

        # 2. how ----------------------------------------------------------
        how = Card(scroll)
        how.pack(fill="x", pady=(0, 10), padx=(0, 6))
        card_title(how, "2 · Choose a format").pack(anchor="w", padx=16, pady=(14, 8))
        controls = ctk.CTkFrame(how, fg_color="transparent")
        controls.pack(fill="x", padx=16, pady=(0, 16))
        self.format = segmented(controls, list(FORMATS))
        self.format.set("CSV")
        self.format.pack(side="left", padx=(0, 12))
        self.filename = entry(controls, "File name (optional)", width=200)
        self.filename.pack(side="left", padx=(0, 12))
        self.spinner = Spinner(controls, "Exporting…")
        self.export_btn = primary_button(controls, "Export", self._export, width=110)
        self.export_btn.pack(side="right")

        # 3. history ------------------------------------------------------
        past = Card(scroll)
        past.pack(fill="x", padx=(0, 6))
        head = ctk.CTkFrame(past, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 6))
        card_title(head, "Recent exports", "Saved in the exports folder").pack(side="left")
        secondary_button(head, "Open folder", self._open_folder, width=110).pack(side="right")
        self.history = ctk.CTkFrame(past, fg_color="transparent")
        self.history.pack(fill="x", padx=12, pady=(0, 12))

    # ------------------------------------------------------------ showing --
    def on_show(self, saved_only: Optional[bool] = None, **_) -> None:
        self.bar.refresh_sources()
        if saved_only is not None:
            self.bar.reset()           # arriving from "Export saved…": don't inherit stale filters
            (self.saved_switch.select if saved_only else self.saved_switch.deselect)()
        self._update_count()
        self._render_history()

    def _current_filter(self):
        return self.bar.get_filter(saved_only=bool(self.saved_switch.get()))

    def _update_count(self) -> None:
        flt = self._current_filter()
        if flt is None:
            return
        self._count_token += 1
        token = self._count_token
        self.count_label.configure(text="Counting…")
        self.ctx.runner.run(
            lambda: self.svc.query(flt, 1, page_size=1).total,
            lambda total: self._set_count(total, token),
            lambda exc: self.count_label.configure(text=str(exc)), owner=self)

    def _set_count(self, total: int, token: int) -> None:
        if token == self._count_token:
            self.count_label.configure(text=f"{total:,} article{'s' if total != 1 else ''} will be exported")

    # ------------------------------------------------------------- export --
    def _export(self) -> None:
        flt = self._current_filter()
        if flt is None:
            return
        fmt = FORMATS[self.format.get()]
        name = self.filename.get().strip() or None
        self.export_btn.configure(state="disabled")
        self.spinner.pack(side="right", padx=(0, 12))
        self.spinner.start()
        self.ctx.runner.run(lambda: self.svc.export(fmt, flt, name), self._exported, self._export_failed, owner=self)

    def _finish(self) -> None:
        self.spinner.stop()
        self.spinner.pack_forget()
        self.export_btn.configure(state="normal")

    def _exported(self, result: Tuple[Path, int]) -> None:
        self._finish()
        path, count = result
        self.ctx.toast.show(f"Exported {count:,} articles to {path.name}", "success")
        self._render_history()

    def _export_failed(self, exc: Exception) -> None:
        self._finish()
        self.ctx.show_error(exc)

    # ------------------------------------------------------------ history --
    def _open_folder(self) -> None:
        if not open_path(self.svc.config.paths.exports_dir):
            self.ctx.toast.show(f"Could not open the folder. It is at {self.svc.config.paths.exports_dir}", "error")

    def _render_history(self) -> None:
        for child in self.history.winfo_children():
            child.destroy()
        files = self.svc.recent_exports()
        if not files:
            EmptyState(self.history, "⇩", "Nothing exported yet",
                       "Your exported files will be listed here.").pack(pady=6)
            return
        for path in files:
            row = ctk.CTkFrame(self.history, fg_color=theme.INPUT_BG, corner_radius=10)
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=path.name, font=font(13, "bold"), text_color=theme.TEXT, anchor="w").pack(
                side="left", padx=(12, 8), pady=8)
            stat = path.stat()
            when = dt.datetime.fromtimestamp(stat.st_mtime).strftime("%d %b %Y %H:%M")
            ctk.CTkLabel(row, text=f"{_human_size(stat.st_size)}  ·  {when}", font=font(11),
                         text_color=theme.MUTED).pack(side="left")
            small_button(row, "Delete", lambda p=path: self._delete(p), width=64).pack(side="right", padx=(4, 10))
            small_button(row, "Open", lambda p=path: self._open(p), width=64).pack(side="right", padx=4)

    def _open(self, path: Path) -> None:
        if not open_path(path):
            self.ctx.toast.show("No application is available to open this file type.", "warning")

    def _delete(self, path: Path) -> None:
        if not confirm("Delete export", f"Delete {path.name}? This cannot be undone."):
            return
        try:
            self.svc.delete_export(path)
        except Exception as exc:  # noqa: BLE001
            self.ctx.show_error(exc)
            return
        self._render_history()
