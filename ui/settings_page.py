"""Settings: API key, demo mode, fetch preferences, appearance and data management."""
from __future__ import annotations

from typing import Dict

import customtkinter as ctk

from config import (APPEARANCE_MODES, CATEGORIES, COUNTRIES, FETCH_SIZES, PAGE_SIZES)
from errors import NewsPulseError
from ui import theme
from ui.base_page import AppContext, BasePage
from ui.components import (Card, Spinner, card_title, checkbox, confirm, danger_button, entry, option_menu,
                           primary_button, secondary_button, segmented, switch)
from ui.theme import font
from utils import open_path, open_url

REGISTER_URL = "https://newsapi.org/register"


def _country_label(code: str) -> str:
    return f"{COUNTRIES[code]} ({code})"


COUNTRY_LABELS = {_country_label(c): c for c in sorted(COUNTRIES, key=COUNTRIES.get)}


class SettingsPage(BasePage):
    def __init__(self, master, ctx: AppContext) -> None:
        super().__init__(master, ctx)
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True)
        self._build_api_card()
        self._build_mode_card()
        self._build_preferences_card()
        self._build_data_card()

    def _section(self, title: str, subtitle: str = "") -> ctk.CTkFrame:
        card = Card(self.scroll)
        card.pack(fill="x", pady=(0, 12), padx=(0, 6))
        card_title(card, title, subtitle).pack(anchor="w", padx=18, pady=(16, 8))
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=(0, 16))
        return body

    @staticmethod
    def _label(parent, text: str, muted: bool = False) -> ctk.CTkLabel:
        return ctk.CTkLabel(parent, text=text, font=font(13), anchor="w", justify="left", wraplength=640,
                            text_color=theme.MUTED if muted else theme.TEXT)

    # ------------------------------------------------------------ API key --
    def _build_api_card(self) -> None:
        body = self._section("NewsAPI key", "Needed for live news. The key is stored only in the .env file on "
                                            "this computer - never in the database or the code.")
        self.key_status = self._label(body, "")
        self.key_status.pack(anchor="w", pady=(0, 8))
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x")
        self.key_entry = entry(row, "Paste your API key here", width=340, show="•")
        self.key_entry.pack(side="left", padx=(0, 8))
        secondary_button(row, "Test connection", self._test_key, width=130).pack(side="left", padx=(0, 8))
        primary_button(row, "Save key", self._save_key, width=96).pack(side="left", padx=(0, 8))
        secondary_button(row, "Remove key", self._remove_key, width=110).pack(side="left")
        row2 = ctk.CTkFrame(body, fg_color="transparent")
        row2.pack(fill="x", pady=(10, 0))
        secondary_button(row2, "Get a free key ↗", lambda: open_url(REGISTER_URL), width=140).pack(side="left")
        self.test_spinner = Spinner(row2, "Testing…")
        self.test_result = self._label(row2, "")
        self.test_result.pack(side="left", padx=12)

    def _refresh_key_status(self) -> None:
        key = self.svc.config.api_key
        self.key_status.configure(
            text=f"✔ A key is configured (ends with …{key[-4:]})." if key else
                 "No key configured yet. Live news is unavailable until you add one - demo mode works without it.",
            text_color=theme.SUCCESS if key else theme.WARNING)

    def _test_key(self) -> None:
        typed = self.key_entry.get().strip()
        self.test_result.configure(text="")
        self.test_spinner.pack(side="left")
        self.test_spinner.start()
        self.ctx.runner.run(lambda: self.svc.test_api_key(typed or None), self._test_done,
                            self._test_failed, owner=self)

    def _test_done(self, outcome) -> None:
        ok, message = outcome
        self.test_spinner.stop()
        self.test_spinner.pack_forget()
        self.test_result.configure(text=("✔ " if ok else "✖ ") + message,
                                   text_color=theme.SUCCESS if ok else theme.DANGER)

    def _test_failed(self, exc: Exception) -> None:
        self._test_done((False, str(exc)))

    def _save_key(self) -> None:
        try:
            self.svc.config.save_api_key(self.key_entry.get())
        except NewsPulseError as exc:
            self.ctx.show_error(exc)
            return
        self.key_entry.delete(0, "end")
        self._refresh_key_status()
        self.ctx.toast.show("API key saved to your .env file.", "success")
        if self.svc.demo_mode and confirm("Switch to live news?",
                                          "Your key is saved. Turn off demo mode and use live news now?"):
            self.svc.prefs.set("demo_mode", False)
            self.demo_switch.deselect()
        self.ctx.on_mode_changed()

    def _remove_key(self) -> None:
        if not self.svc.config.has_api_key:
            self.ctx.toast.show("There is no saved key to remove.", "info")
            return
        if not confirm("Remove API key", "Remove the saved API key from .env? Live news will stop working "
                                         "until you add a key again."):
            return
        self.svc.config.clear_api_key()
        self._refresh_key_status()
        self.ctx.toast.show("API key removed.", "info")
        self.ctx.on_mode_changed()

    # --------------------------------------------------------------- mode --
    def _build_mode_card(self) -> None:
        body = self._section("Data mode", "Demo mode shows sample articles so you can try the app without a key. "
                                          "They are always marked DEMO and are never mixed with live news.")
        self.demo_switch = switch(body, "Demo mode (sample data, not real news)", self._toggle_demo)
        self.demo_switch.pack(anchor="w")

    def _toggle_demo(self) -> None:
        try:
            self.svc.prefs.set("demo_mode", bool(self.demo_switch.get()))
        except NewsPulseError as exc:
            self.ctx.show_error(exc)
            return
        self.ctx.on_mode_changed()

    # -------------------------------------------------------- preferences --
    def _build_preferences_card(self) -> None:
        body = self._section("Preferences", "How news is fetched and displayed.")
        grid = ctk.CTkFrame(body, fg_color="transparent")
        grid.pack(fill="x")
        self.country = option_menu(grid, list(COUNTRY_LABELS), width=240)
        self.fetch_size = option_menu(grid, [str(n) for n in FETCH_SIZES], width=100)
        self.page_size = option_menu(grid, [str(n) for n in PAGE_SIZES], width=100)
        for row, (text, widget) in enumerate([
                ("Headline country", self.country), ("Articles per category per fetch", self.fetch_size),
                ("Articles per page", self.page_size)]):
            self._label(grid, text).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 20))
            widget.grid(row=row, column=1, sticky="w", pady=5)

        self._label(body, "Categories to fetch", muted=True).pack(anchor="w", pady=(12, 4))
        boxes = ctk.CTkFrame(body, fg_color="transparent")
        boxes.pack(fill="x")
        self.category_vars: Dict[str, ctk.IntVar] = {}
        for i, category in enumerate(CATEGORIES):
            var = ctk.IntVar(value=1)
            self.category_vars[category] = var
            checkbox(boxes, category.title(), var).grid(row=i // 4, column=i % 4, sticky="w", padx=(0, 22), pady=4)

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.pack(fill="x", pady=(14, 0))
        primary_button(actions, "Save preferences", self._save_preferences, width=150).pack(side="left")

        self._label(body, "Appearance", muted=True).pack(anchor="w", pady=(18, 4))
        self.appearance = segmented(body, list(APPEARANCE_MODES), self._change_appearance)
        self.appearance.pack(anchor="w")

    def _save_preferences(self) -> None:
        chosen = [c for c, var in self.category_vars.items() if var.get()]
        try:
            self.svc.prefs.set("country", COUNTRY_LABELS[self.country.get()])
            self.svc.prefs.set("categories", chosen)
            self.svc.prefs.set("fetch_size", self.fetch_size.get())
            self.svc.prefs.set("page_size", self.page_size.get())
        except NewsPulseError as exc:
            self.ctx.show_error(exc)
            return
        self.ctx.toast.show("Preferences saved. They apply to the next refresh.", "success")

    def _change_appearance(self, mode: str) -> None:
        try:
            self.svc.prefs.set("appearance", mode)
        except NewsPulseError as exc:
            self.ctx.show_error(exc)
            return
        self.ctx.on_appearance_changed()

    # ---------------------------------------------------------- data tools --
    def _build_data_card(self) -> None:
        body = self._section("Your data", "Everything is stored locally in a SQLite database.")
        self.paths_label = self._label(body, "", muted=True)
        self.paths_label.pack(anchor="w", pady=(0, 10))

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x")
        secondary_button(row, "Back up database", self._backup, width=150).pack(side="left", padx=(0, 8))
        secondary_button(row, "Open data folder", lambda: self._open(self.svc.config.paths.base_dir), width=150).pack(
            side="left", padx=(0, 8))
        secondary_button(row, "Open log folder", lambda: self._open(self.svc.config.paths.logs_dir), width=150).pack(
            side="left")

        clean = ctk.CTkFrame(body, fg_color="transparent")
        clean.pack(fill="x", pady=(16, 0))
        self._label(clean, "Delete articles older than").pack(side="left")
        self.days_entry = entry(clean, "30", width=64)
        self.days_entry.pack(side="left", padx=8)
        self._label(clean, "days (saved articles are always kept)").pack(side="left", padx=(0, 10))
        secondary_button(clean, "Delete old articles", self._purge_old, width=160).pack(side="left")

        danger = ctk.CTkFrame(body, fg_color="transparent")
        danger.pack(fill="x", pady=(14, 0))
        danger_button(danger, "Delete demo data", self._purge_demo, width=150).pack(side="left", padx=(0, 8))
        danger_button(danger, "Erase all data", self._erase_all, width=150).pack(side="left")

    def _open(self, path) -> None:
        if not open_path(path):
            self.ctx.toast.show(f"Could not open it. The location is {path}", "warning")

    def _backup(self) -> None:
        self.ctx.runner.run(
            self.svc.backup_database,
            lambda path: self.ctx.toast.show(f"Backup saved: {path}", "success", 9000),
            self.ctx.show_error, owner=self)

    def _purge_old(self) -> None:
        text = self.days_entry.get().strip()
        if not text.isdigit() or int(text) < 1:
            self.ctx.toast.show("Enter a whole number of days (1 or more).", "warning")
            return
        days = int(text)
        if not confirm("Delete old articles", f"Delete all unsaved articles older than {days} days?"):
            return
        self._run_cleanup(lambda: self.svc.purge_older_than(days), "Deleted {n} old article(s).")

    def _purge_demo(self) -> None:
        if confirm("Delete demo data", "Remove all sample articles? Live news is not affected."):
            self._run_cleanup(self.svc.purge_demo_data, "Deleted {n} demo article(s).")

    def _erase_all(self) -> None:
        if confirm("Erase all data", "This permanently deletes every article, source and saved bookmark. "
                                     "Your API key and preferences are kept.\n\nContinue?"):
            self._run_cleanup(lambda: (self.svc.clear_all_data(), 0)[1], "All article data erased.")

    def _run_cleanup(self, work, message: str) -> None:
        self.ctx.runner.run(work, lambda n: (self.ctx.toast.show(message.format(n=n), "success"), self._after_cleanup()),
                            self.ctx.show_error, owner=self)

    def _after_cleanup(self) -> None:
        # Deliberately NOT on_mode_changed(): that may auto-fetch and spend API quota.
        self.on_show()

    # ------------------------------------------------------------- showing --
    def on_show(self, **_) -> None:
        prefs = self.svc.prefs
        self._refresh_key_status()
        (self.demo_switch.select if prefs.demo_mode else self.demo_switch.deselect)()
        self.country.set(_country_label(prefs.country))
        self.fetch_size.set(str(prefs.fetch_size) if prefs.fetch_size in FETCH_SIZES else str(FETCH_SIZES[1]))
        self.page_size.set(str(prefs.page_size))
        chosen = set(prefs.categories)
        for category, var in self.category_vars.items():
            var.set(1 if category in chosen else 0)
        self.appearance.set(prefs.appearance)
        paths = self.svc.config.paths
        self.paths_label.configure(text=f"Database: {paths.db_path}\nExports: {paths.exports_dir}\nLogs: {paths.logs_dir}")

    def on_theme_changed(self) -> None:  # nothing to redraw
        pass
