"""Reusable, consistently-styled widgets."""
from __future__ import annotations

from tkinter import messagebox
from typing import Callable, Optional, Sequence

import customtkinter as ctk

from ui import theme
from ui.graphics import gradient_image
from ui.theme import font


# ------------------------------------------------------------- graphics ----
class GradientBar(ctk.CTkFrame):
    """A thin purple->blue accent strip (clipped, so it fits any width)."""

    def __init__(self, master, height: int = 5, **kw) -> None:
        super().__init__(master, height=height, fg_color=theme.PURPLE, corner_radius=0, **kw)
        self.pack_propagate(False)
        img = gradient_image(2600, height)
        self._image = ctk.CTkImage(light_image=img, dark_image=img, size=(2600, height))
        label = ctk.CTkLabel(self, text="", image=self._image, height=height)
        label.place(x=0, y=0)


# ---------------------------------------------------------------- buttons --
def primary_button(master, text: str, command: Optional[Callable] = None, width: int = 0, **kw) -> ctk.CTkButton:
    return ctk.CTkButton(master, text=text, command=command, width=width or 100, height=36,
                         corner_radius=10, fg_color=theme.PURPLE, hover_color=theme.PURPLE_HOVER,
                         text_color="white", font=font(13, "bold"), **kw)


def secondary_button(master, text: str, command: Optional[Callable] = None, width: int = 0, **kw) -> ctk.CTkButton:
    return ctk.CTkButton(master, text=text, command=command, width=width or 100, height=36,
                         corner_radius=10, fg_color=theme.HOVER, hover_color=theme.ACTIVE_NAV,
                         text_color=theme.TEXT, border_width=1, border_color=theme.BORDER,
                         font=font(13), **kw)


def danger_button(master, text: str, command: Optional[Callable] = None, width: int = 0, **kw) -> ctk.CTkButton:
    return ctk.CTkButton(master, text=text, command=command, width=width or 100, height=36,
                         corner_radius=10, fg_color=theme.DANGER, hover_color=theme.DANGER_HOVER,
                         text_color="white", font=font(13, "bold"), **kw)


def small_button(master, text: str, command: Optional[Callable] = None, width: int = 0, **kw) -> ctk.CTkButton:
    return ctk.CTkButton(master, text=text, command=command, width=width or 70, height=28,
                         corner_radius=8, fg_color=theme.HOVER, hover_color=theme.ACTIVE_NAV,
                         text_color=theme.TEXT, font=font(12), **kw)


def chip(master, text: str, command: Optional[Callable] = None, selected: bool = False, **kw) -> ctk.CTkButton:
    return ctk.CTkButton(master, text=text, command=command, height=30, corner_radius=15,
                         fg_color=theme.PURPLE if selected else theme.HOVER,
                         hover_color=theme.PURPLE_HOVER if selected else theme.ACTIVE_NAV,
                         text_color="white" if selected else theme.TEXT, font=font(12), **kw)


# ------------------------------------------------------------ form inputs --
def entry(master, placeholder: str = "", width: int = 160, show: str = "") -> ctk.CTkEntry:
    return ctk.CTkEntry(master, placeholder_text=placeholder, width=width, height=36, corner_radius=10,
                        fg_color=theme.INPUT_BG, border_color=theme.BORDER, text_color=theme.TEXT,
                        show=show, font=font(13))


def option_menu(master, values: Sequence[str], command: Optional[Callable] = None, width: int = 150,
                initial: Optional[str] = None) -> ctk.CTkOptionMenu:
    menu = ctk.CTkOptionMenu(master, values=list(values), command=command, width=width, height=36,
                             corner_radius=10, fg_color=theme.INPUT_BG, button_color=theme.PURPLE,
                             button_hover_color=theme.PURPLE_HOVER, text_color=theme.TEXT,
                             dropdown_fg_color=theme.CARD, dropdown_text_color=theme.TEXT,
                             dropdown_hover_color=theme.HOVER, font=font(13), dropdown_font=font(13))
    if initial is not None:
        menu.set(initial)
    return menu


def segmented(master, values: Sequence[str], command: Optional[Callable] = None) -> ctk.CTkSegmentedButton:
    return ctk.CTkSegmentedButton(master, values=list(values), command=command, height=34,
                                  selected_color=theme.PURPLE, selected_hover_color=theme.PURPLE_HOVER,
                                  unselected_color=theme.INPUT_BG, unselected_hover_color=theme.HOVER,
                                  fg_color=theme.INPUT_BG, text_color=theme.TEXT, font=font(13))


def switch(master, text: str, command: Optional[Callable] = None) -> ctk.CTkSwitch:
    return ctk.CTkSwitch(master, text=text, command=command, progress_color=theme.PURPLE,
                         button_color="white", button_hover_color="#E5E7EB", font=font(13),
                         text_color=theme.TEXT)


def checkbox(master, text: str, variable=None, command: Optional[Callable] = None) -> ctk.CTkCheckBox:
    return ctk.CTkCheckBox(master, text=text, variable=variable, command=command, fg_color=theme.PURPLE,
                           hover_color=theme.PURPLE_HOVER, border_color=theme.BORDER,
                           text_color=theme.TEXT, font=font(13))


def confirm(title: str, message: str) -> bool:
    return bool(messagebox.askyesno(title, message, icon="warning"))


# ---------------------------------------------------------------- layout ---
class Card(ctk.CTkFrame):
    def __init__(self, master, **kw) -> None:
        kw.setdefault("fg_color", theme.CARD)
        kw.setdefault("corner_radius", theme.RADIUS)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", theme.BORDER)
        super().__init__(master, **kw)


def card_title(master, text: str, subtitle: str = "") -> ctk.CTkFrame:
    box = ctk.CTkFrame(master, fg_color="transparent")
    ctk.CTkLabel(box, text=text, font=font(16, "bold"), text_color=theme.TEXT, anchor="w").pack(anchor="w")
    if subtitle:
        ctk.CTkLabel(box, text=subtitle, font=font(12), text_color=theme.MUTED, anchor="w",
                     justify="left", wraplength=640).pack(anchor="w")
    return box


class StatCard(Card):
    """Headline number with an accent icon."""

    def __init__(self, master, icon: str, label: str, accent: str = theme.PURPLE) -> None:
        super().__init__(master)
        self.grid_columnconfigure(1, weight=1)
        badge = ctk.CTkFrame(self, width=48, height=48, corner_radius=14, fg_color=accent)
        badge.grid(row=0, column=0, rowspan=2, padx=(18, 12), pady=18)
        badge.grid_propagate(False)
        ctk.CTkLabel(badge, text=icon, font=font(20, "bold"), text_color="white").place(relx=0.5, rely=0.5, anchor="center")
        self.value = ctk.CTkLabel(self, text="–", font=font(28, "bold"), text_color=theme.TEXT, anchor="w")
        self.value.grid(row=0, column=1, sticky="sw", padx=(0, 16), pady=(16, 0))
        ctk.CTkLabel(self, text=label, font=font(12), text_color=theme.MUTED, anchor="w").grid(
            row=1, column=1, sticky="nw", padx=(0, 16), pady=(0, 16))

    def set_value(self, value) -> None:
        self.value.configure(text=f"{value:,}" if isinstance(value, int) else str(value))


class EmptyState(ctk.CTkFrame):
    """Friendly placeholder shown when there is nothing to display."""

    def __init__(self, master, icon: str, title: str, message: str,
                 action_text: str = "", action: Optional[Callable] = None) -> None:
        super().__init__(master, fg_color="transparent")
        ctk.CTkLabel(self, text=icon, font=font(44), text_color=theme.PURPLE).pack(pady=(36, 6))
        ctk.CTkLabel(self, text=title, font=font(18, "bold"), text_color=theme.TEXT).pack()
        ctk.CTkLabel(self, text=message, font=font(13), text_color=theme.MUTED, wraplength=460,
                     justify="center").pack(pady=(6, 14))
        if action_text and action:
            primary_button(self, action_text, action).pack()


class Spinner(ctk.CTkFrame):
    """Indeterminate progress bar with a caption."""

    def __init__(self, master, text: str = "Loading…") -> None:
        super().__init__(master, fg_color="transparent")
        self.label = ctk.CTkLabel(self, text=text, font=font(12), text_color=theme.MUTED)
        self.label.pack(side="left", padx=(0, 10))
        self.bar = ctk.CTkProgressBar(self, mode="indeterminate", width=110, height=6,
                                      progress_color=theme.PURPLE, fg_color=theme.BORDER)
        self.bar.pack(side="left")
        self._running = False

    def start(self, text: Optional[str] = None) -> None:
        if text is not None:
            self.label.configure(text=text)
        if not self._running:
            self._running = True
            self.bar.start()

    def stop(self) -> None:
        if self._running:
            self._running = False
            self.bar.stop()


class Toast(ctk.CTkFrame):
    """Transient message in the bottom-right corner of the window."""

    COLORS = {"info": theme.BLUE, "success": theme.SUCCESS, "warning": theme.WARNING, "error": theme.DANGER}

    def __init__(self, master) -> None:
        super().__init__(master, corner_radius=12, fg_color=theme.CARD, border_width=2, border_color=theme.BLUE)
        self.label = ctk.CTkLabel(self, text="", font=font(13), text_color=theme.TEXT, wraplength=420, justify="left")
        self.label.pack(padx=16, pady=12)
        self._job = None

    def show(self, message: str, kind: str = "info", ms: int = 6000) -> None:
        self.configure(border_color=self.COLORS.get(kind, theme.BLUE))
        self.label.configure(text=message)
        self.place(relx=1.0, rely=1.0, x=-24, y=-24, anchor="se")
        self.lift()
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(ms, self.hide)

    def hide(self) -> None:
        self._job = None
        self.place_forget()


class Pagination(ctk.CTkFrame):
    def __init__(self, master, on_page: Callable[[int], None]) -> None:
        super().__init__(master, fg_color="transparent")
        self._on_page = on_page
        self.page = 1
        self.pages = 1
        self.prev = small_button(self, "‹ Previous", lambda: self._go(self.page - 1), width=90)
        self.prev.pack(side="left")
        self.label = ctk.CTkLabel(self, text="", font=font(12), text_color=theme.MUTED)
        self.label.pack(side="left", padx=14)
        self.next = small_button(self, "Next ›", lambda: self._go(self.page + 1), width=90)
        self.next.pack(side="left")

    def _go(self, page: int) -> None:
        if 1 <= page <= self.pages:
            self._on_page(page)

    def update_state(self, page: int, pages: int, total: int) -> None:
        self.page, self.pages = page, pages
        self.label.configure(text=f"Page {page} of {pages}  ·  {total:,} articles")
        self.prev.configure(state="normal" if page > 1 else "disabled")
        self.next.configure(state="normal" if page < pages else "disabled")


class ChartFrame(ctk.CTkFrame):
    """Hosts a Matplotlib Figure inside Tk."""

    def __init__(self, master, height: int = 300) -> None:
        super().__init__(master, fg_color="transparent", height=height)
        self._canvas = None
        self.figure = None

    def show_figure(self, fig) -> None:
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.colors import to_hex
        self.clear()
        self.figure = fig
        self._canvas = FigureCanvasTkAgg(fig, master=self)
        widget = self._canvas.get_tk_widget()
        widget.configure(bg=to_hex(fig.get_facecolor()), highlightthickness=0)
        widget.pack(fill="both", expand=True)
        self._canvas.draw()

    def clear(self) -> None:
        if self._canvas is not None:
            self._canvas.get_tk_widget().destroy()
            self._canvas = None
        self.figure = None


def page_intro(master, subtitle: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, text=subtitle, font=font(13), text_color=theme.MUTED, anchor="w",
                        justify="left", wraplength=900)
