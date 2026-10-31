"""Design tokens for the NewsPulse UI.

Colours are ``(light, dark)`` tuples - CustomTkinter picks the right one when
the appearance mode changes, so the whole app can switch themes live.
The default look is a dark navy dashboard with purple / blue accents.
"""
from __future__ import annotations

from functools import lru_cache

import customtkinter as ctk

# Surfaces ------------------------------------------------------------------
BG = ("#F3F5FD", "#0B1020")
SIDEBAR = ("#FFFFFF", "#0E1530")
CARD = ("#FFFFFF", "#141C3A")
CARD_HOVER = ("#F2F0FF", "#1B2552")
BORDER = ("#E1E5F5", "#242F5E")
INPUT_BG = ("#F3F5FD", "#0F1731")
ACTIVE_NAV = ("#ECE8FF", "#232C61")
HOVER = ("#E9ECFB", "#1A2350")

# Text ----------------------------------------------------------------------
TEXT = ("#1B2147", "#E8ECFF")
MUTED = ("#6B7399", "#8B95C9")

# Accents -------------------------------------------------------------------
PURPLE = "#7C5CFF"
PURPLE_HOVER = "#6A49F0"
BLUE = "#3B82F6"
BLUE_HOVER = "#2F6FDB"
SUCCESS = "#22C55E"
WARNING = "#F59E0B"
DANGER = "#EF4444"
DANGER_HOVER = "#DC2626"

CATEGORY_COLORS = {
    "business": "#F59E0B", "entertainment": "#F472B6", "general": "#94A3B8",
    "health": "#34D399", "science": "#22D3EE", "sports": "#3B82F6", "technology": "#7C5CFF",
}

# Navigation: (page key, label, icon).  Icons are plain BMP symbols that render
# on Windows, macOS and Linux without needing an emoji font.
NAV_ITEMS = [
    ("dashboard", "Dashboard", "▦"),
    ("news", "All News", "☰"),
    ("search", "Search News", "⌕"),
    ("categories", "Categories", "▤"),
    ("saved", "Saved Articles", "★"),
    ("sources", "News Sources", "◉"),
    ("export", "Export Data", "⇩"),
    ("analytics", "Analytics", "▥"),
    ("settings", "Settings", "⚙"),
    ("about", "About", "ⓘ"),
]

RADIUS = 16
PAD = 20


@lru_cache(maxsize=64)
def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    """Shared fonts (must be called after the Tk root exists)."""
    return ctk.CTkFont(size=size, weight=weight)


def chart_theme() -> str:
    return "dark" if ctk.get_appearance_mode() == "Dark" else "light"
