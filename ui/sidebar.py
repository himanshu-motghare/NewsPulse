"""Left navigation bar: logo, the ten navigation entries and the data-mode badge."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

import customtkinter as ctk
from PIL import Image

from config import APP_NAME, APP_TAGLINE, APP_VERSION
from ui import theme
from ui.graphics import draw_logo
from ui.theme import font


class Sidebar(ctk.CTkFrame):
    WIDTH = 236

    def __init__(self, master, on_select: Callable[[str], None], logo_path: Optional[Path] = None) -> None:
        super().__init__(master, width=self.WIDTH, corner_radius=0, fg_color=theme.SIDEBAR)
        self.pack_propagate(False)
        self._buttons: Dict[str, ctk.CTkButton] = {}
        self._on_select = on_select
        self._active: Optional[str] = None

        brand = ctk.CTkFrame(self, fg_color="transparent")
        brand.pack(fill="x", padx=18, pady=(22, 18))
        image = self._load_logo(logo_path)
        ctk.CTkLabel(brand, text="", image=image).pack(side="left")
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(names, text=APP_NAME, font=font(20, "bold"), text_color=theme.TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(names, text=APP_TAGLINE, font=font(11), text_color=theme.MUTED, anchor="w").pack(anchor="w")

        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.pack(fill="x", padx=12)
        for key, label, icon in theme.NAV_ITEMS:
            button = ctk.CTkButton(
                nav, text=f"  {icon}    {label}", anchor="w", height=42, corner_radius=12,
                fg_color="transparent", hover_color=theme.HOVER, text_color=theme.MUTED,
                font=font(14), command=lambda k=key: self._on_select(k))
            button.pack(fill="x", pady=2)
            self._buttons[key] = button

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=18, pady=18)
        self.mode_badge = ctk.CTkLabel(footer, text="", font=font(12, "bold"), corner_radius=10, height=28)
        self.mode_badge.pack(anchor="w")
        ctk.CTkLabel(footer, text=f"Version {APP_VERSION}", font=font(11), text_color=theme.MUTED).pack(
            anchor="w", pady=(8, 0))

    @staticmethod
    def _load_logo(path: Optional[Path]) -> ctk.CTkImage:
        img = None
        if path and Path(path).exists():
            try:
                img = Image.open(path).convert("RGBA")
            except OSError:
                img = None
        img = img or draw_logo(96)
        return ctk.CTkImage(light_image=img, dark_image=img, size=(44, 44))

    def set_active(self, key: str) -> None:
        for name, button in self._buttons.items():
            active = name == key
            button.configure(fg_color=theme.ACTIVE_NAV if active else "transparent",
                             text_color=theme.TEXT if active else theme.MUTED,
                             font=font(14, "bold" if active else "normal"))
        self._active = key

    def set_mode(self, demo: bool) -> None:
        if demo:
            self.mode_badge.configure(text="  DEMO MODE · sample data  ", fg_color=theme.WARNING, text_color="black")
        else:
            self.mode_badge.configure(text="  ● Live news  ", fg_color=theme.SUCCESS, text_color="black")
