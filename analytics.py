"""Analytics: pandas data preparation + Matplotlib figure builders.

The figure functions return :class:`matplotlib.figure.Figure` objects that the
GUI embeds in a Tk canvas and the CLI can save as PNG - no pyplot / global
state is used, so everything is safe to call from any thread.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Sequence, Tuple

import pandas as pd
import matplotlib.dates as mdates
from matplotlib.figure import Figure

from errors import ExportError
from utils import utc_now

PALETTE = ["#7C5CFF", "#3B82F6", "#22D3EE", "#F472B6", "#F59E0B", "#34D399",
           "#A78BFA", "#60A5FA", "#FB7185", "#94A3B8"]
THEMES: Dict[str, Dict[str, str]] = {
    "dark": {"bg": "#141C3A", "fg": "#E8ECFF", "muted": "#8B95C9", "grid": "#2A3566"},
    "light": {"bg": "#FFFFFF", "fg": "#1F2547", "muted": "#6B7280", "grid": "#E5E7EB"},
}


# ------------------------------------------------------------- frames ----
def to_frame(rows: Sequence[Tuple[str, int]], label: str) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=[label, "articles"])


def daily_frame(rows: Sequence[Tuple[str, int]], days: int = 14) -> pd.DataFrame:
    """Daily counts for the last ``days`` days, with zero-filled gaps."""
    end = pd.Timestamp(utc_now().date())
    index = pd.date_range(end=end, periods=days, freq="D")
    counts = {pd.Timestamp(d): n for d, n in rows}
    return pd.DataFrame({"day": index, "articles": [counts.get(d, 0) for d in index]})


# ------------------------------------------------------------ figures ----
def _new_figure(title: str, theme: str, figsize=(6.4, 3.8)):
    colors = THEMES.get(theme, THEMES["dark"])
    fig = Figure(figsize=figsize, dpi=100, facecolor=colors["bg"])
    ax = fig.add_subplot(111)
    ax.set_facecolor(colors["bg"])
    ax.set_title(title, color=colors["fg"], fontsize=12, fontweight="bold", loc="left", pad=12)
    ax.tick_params(colors=colors["muted"], labelsize=8)
    for spine in ax.spines.values():
        spine.set_visible(False)
    return fig, ax, colors


def _empty(fig: Figure, ax, colors) -> Figure:
    ax.set_xticks([])
    ax.set_yticks([])
    ax.text(0.5, 0.5, "No data yet\nFetch some news to see this chart", ha="center", va="center",
            color=colors["muted"], fontsize=11, transform=ax.transAxes)
    fig.tight_layout()
    return fig


def source_chart(frame: pd.DataFrame, theme: str = "dark", figsize=(6.4, 3.8)) -> Figure:
    fig, ax, c = _new_figure("Articles by source", theme, figsize)
    if frame.empty:
        return _empty(fig, ax, c)
    data = frame.sort_values("articles")
    labels = [s if len(s) <= 24 else s[:23] + "…" for s in data["source"]]
    bars = ax.barh(labels, data["articles"], color=PALETTE[0], height=0.6)
    ax.bar_label(bars, padding=4, color=c["fg"], fontsize=8)
    ax.xaxis.set_visible(False)
    ax.tick_params(axis="y", colors=c["fg"])
    fig.tight_layout()
    return fig


def category_chart(frame: pd.DataFrame, theme: str = "dark", kind: str = "donut", figsize=(6.4, 3.8)) -> Figure:
    fig, ax, c = _new_figure("Category distribution", theme, figsize)
    if frame.empty:
        return _empty(fig, ax, c)
    labels = [s.title() for s in frame["category"]]
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(frame))]
    if kind == "bar":
        bars = ax.bar(labels, frame["articles"], color=colors, width=0.6)
        ax.bar_label(bars, padding=3, color=c["fg"], fontsize=8)
        ax.yaxis.set_visible(False)
        ax.tick_params(axis="x", colors=c["fg"], rotation=25)
    else:
        wedges, _t, autotexts = ax.pie(
            frame["articles"], colors=colors, startangle=90, counterclock=False,
            autopct=lambda p: f"{p:.0f}%" if p >= 5 else "",
            wedgeprops={"width": 0.42, "edgecolor": c["bg"], "linewidth": 2},
            pctdistance=0.79, textprops={"color": "white", "fontsize": 8})
        ax.legend(wedges, [f"{l} ({n})" for l, n in zip(labels, frame["articles"])],
                  loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False,
                  labelcolor=c["fg"], fontsize=8)
        ax.set_aspect("equal")
    fig.tight_layout()
    return fig


def daily_chart(frame: pd.DataFrame, theme: str = "dark", figsize=(6.4, 3.8)) -> Figure:
    fig, ax, c = _new_figure("Articles collected per day", theme, figsize)
    if frame.empty or frame["articles"].sum() == 0:
        return _empty(fig, ax, c)
    ax.bar(frame["day"], frame["articles"], color=PALETTE[1], width=0.7, alpha=0.85)
    ax.plot(frame["day"], frame["articles"], color=PALETTE[0], marker="o", markersize=4, linewidth=2)
    ax.grid(axis="y", color=c["grid"], linewidth=0.6)
    ax.set_axisbelow(True)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    fig.autofmt_xdate(rotation=30)
    fig.tight_layout()
    return fig


def save_figure(fig: Figure, path: Path) -> Path:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=150, facecolor=fig.get_facecolor(), bbox_inches="tight")
    except OSError as exc:
        raise ExportError(f"Could not save the chart: {exc}") from exc
    return Path(path)
