"""A small, strict, headless stand-in for ``customtkinter`` / ``tkinter``.

Purpose: let the automated tests exercise the real NewsPulse window, pages,
service layer, SQLite database and background threads on machines (CI servers,
containers) that have no display or no Tk installed.

It models only what NewsPulse uses: a widget tree, entry text, option menus,
switches, buttons with ``command`` callbacks and a deferred ``after`` queue.
It is *strict* - calling a method that real widgets do not have raises
``AttributeError`` - so typos and wiring bugs are caught instead of ignored.

What it cannot check: real layout/rendering and the exact CustomTkinter
keyword arguments.  Those need a real display (see ``test_gui_real.py``).
"""
from __future__ import annotations

import sys
import types
from typing import Any, Callable, Dict, List, Optional

STATE: Dict[str, Any] = {"confirm": True, "input_dialog": "", "appearance": "Dark"}


class _Var:
    def __init__(self, master=None, value=0, **_kw) -> None:
        self._v = value

    def get(self):
        return self._v

    def set(self, value) -> None:
        self._v = value


class Widget:
    """Base for every fake widget; keeps the parent/child tree and the config dict."""

    def __init__(self, master=None, *_args, **kw) -> None:
        self.master = master if isinstance(master, Widget) else None
        self._children: List["Widget"] = []
        self._cfg: Dict[str, Any] = dict(kw)
        self._destroyed = False
        self._bindings: Dict[str, List[Callable]] = {}
        self._manager: Optional[str] = None
        if self.master is not None:
            self.master._children.append(self)

    # ------------------------------------------------------------ config --
    def configure(self, **kw) -> None:
        self._cfg.update(kw)

    config = configure

    def cget(self, key):
        return self._cfg.get(key)

    # --------------------------------------------------------- geometry ---
    def pack(self, **_kw) -> None:
        self._manager = "pack"

    def grid(self, **_kw) -> None:
        self._manager = "grid"

    def place(self, **_kw) -> None:
        self._manager = "place"

    def pack_forget(self) -> None:
        self._manager = None

    grid_forget = grid_remove = place_forget = pack_forget

    def grid_columnconfigure(self, *_a, **_k) -> None: ...
    def grid_rowconfigure(self, *_a, **_k) -> None: ...
    def pack_propagate(self, *_a, **_k) -> None: ...
    def grid_propagate(self, *_a, **_k) -> None: ...
    def lift(self, *_a) -> None: ...
    def tkraise(self, *_a) -> None: ...
    def focus(self) -> None: ...
    def update_idletasks(self) -> None: ...
    def winfo_pointerxy(self): return (0, 0)
    def winfo_containing(self, _x, _y): return None
    def clipboard_clear(self) -> None: STATE["clipboard"] = ""

    def clipboard_append(self, text) -> None:
        STATE["clipboard"] = STATE.get("clipboard", "") + text

    def yview_moveto(self, _fraction) -> None: ...

    # ------------------------------------------------------------- tree ---
    def winfo_children(self) -> List["Widget"]:
        return list(self._children)

    def winfo_exists(self) -> int:
        return 0 if self._destroyed else 1

    def winfo_ismapped(self) -> bool:
        return self._manager is not None and not self._destroyed

    def destroy(self) -> None:
        for child in list(self._children):
            child.destroy()
        self._destroyed = True
        if self.master is not None and self in self.master._children:
            self.master._children.remove(self)

    def walk(self):
        """Depth-first iteration over this widget and all descendants (test helper)."""
        yield self
        for child in list(self._children):
            yield from child.walk()

    # ------------------------------------------------------------ events --
    def bind(self, sequence, func, add=None) -> None:
        self._bindings.setdefault(sequence, []).append(func)

    def _root(self) -> "Widget":
        node = self
        while node.master is not None:
            node = node.master
        return node

    def after(self, _ms, func=None, *args):
        root = self._root()
        job = (len(root._after_jobs), func, args)
        root._after_jobs.append(job)
        return job[0]

    def after_cancel(self, job_id) -> None:
        root = self._root()
        root._after_jobs = [j for j in root._after_jobs if j[0] != job_id]

    _after_jobs: list = []


# -------------------------------------------------------------- windows ----
class CTk(Widget):
    def __init__(self, *args, **kw) -> None:
        super().__init__(None, **kw)
        self._after_jobs = []

    def title(self, *_a): ...
    def geometry(self, *_a): ...
    def minsize(self, *_a): ...
    def iconphoto(self, *_a): ...
    def protocol(self, *_a): ...
    def mainloop(self): ...

    def pump(self) -> None:
        """Run every callback scheduled with ``after`` (they may schedule more)."""
        jobs, self._after_jobs = self._after_jobs, []
        for _id, func, args in jobs:
            if func is not None:
                func(*args)


class CTkToplevel(Widget):
    def title(self, *_a): ...
    def geometry(self, *_a): ...
    def minsize(self, *_a): ...
    def transient(self, *_a): ...


# -------------------------------------------------------------- widgets ----
class CTkFrame(Widget): ...


class CTkScrollableFrame(Widget):
    @property
    def _parent_canvas(self):
        return Widget(self)


class CTkLabel(Widget): ...


class CTkButton(Widget):
    def invoke(self) -> None:
        """Simulate a click (ignored while the button is disabled)."""
        if self._cfg.get("state") == "disabled":
            return
        command = self._cfg.get("command")
        if command:
            command()


class CTkEntry(Widget):
    def __init__(self, master=None, **kw) -> None:
        super().__init__(master, **kw)
        self._value = ""

    def get(self) -> str:
        return self._value

    def insert(self, index, text) -> None:
        pos = len(self._value) if index == "end" else int(index)
        self._value = self._value[:pos] + text + self._value[pos:]

    def delete(self, first, last=None) -> None:
        self._value = ""      # NewsPulse only ever clears whole entries

    def type(self, text: str) -> None:
        """Test helper: replace the entry's text as if the user typed it."""
        self._value = text


class _Choice(Widget):
    def __init__(self, master=None, **kw) -> None:
        super().__init__(master, **kw)
        values = list(kw.get("values", []))
        self._value = values[0] if values else ""

    def set(self, value) -> None:
        self._value = value

    def get(self):
        return self._value

    def choose(self, value) -> None:
        """Test helper: simulate the user picking ``value``."""
        self.set(value)
        command = self._cfg.get("command")
        if command:
            command(value)


class CTkOptionMenu(_Choice): ...
class CTkSegmentedButton(_Choice): ...


class CTkSwitch(Widget):
    def __init__(self, master=None, **kw) -> None:
        super().__init__(master, **kw)
        self._on = 0

    def select(self) -> None: self._on = 1
    def deselect(self) -> None: self._on = 0
    def get(self) -> int: return self._on

    def toggle(self) -> None:
        """Test helper: simulate a user click."""
        self._on = 0 if self._on else 1
        command = self._cfg.get("command")
        if command:
            command()


class CTkCheckBox(Widget):
    def click(self) -> None:
        var = self._cfg.get("variable")
        var.set(0 if var.get() else 1)
        command = self._cfg.get("command")
        if command:
            command()


class CTkProgressBar(Widget):
    def start(self) -> None: ...
    def stop(self) -> None: ...


class CTkImage:
    def __init__(self, light_image=None, dark_image=None, size=(0, 0)) -> None:
        self.size = size


class CTkFont:
    def __init__(self, *_a, **_k) -> None: ...


class CTkInputDialog:
    def __init__(self, *_a, **_k) -> None: ...

    def get_input(self):
        return STATE["input_dialog"]


def _build_modules() -> Dict[str, types.ModuleType]:
    ctk = types.ModuleType("customtkinter")
    for name, obj in list(globals().items()):
        if name.startswith("CTk"):
            setattr(ctk, name, obj)
    ctk.IntVar = ctk.StringVar = ctk.DoubleVar = ctk.BooleanVar = _Var
    ctk.set_appearance_mode = lambda mode: STATE.__setitem__("appearance", mode)
    ctk.get_appearance_mode = lambda: STATE["appearance"] if STATE["appearance"] != "System" else "Dark"
    ctk.set_default_color_theme = lambda *_a: None
    ctk.CTk = CTk

    messagebox = types.ModuleType("tkinter.messagebox")
    messagebox.askyesno = lambda *_a, **_k: STATE["confirm"]
    tk = types.ModuleType("tkinter")
    tk.messagebox = messagebox
    tk.TclError = type("TclError", (Exception,), {})

    canvas_mod = types.ModuleType("matplotlib.backends.backend_tkagg")

    class FigureCanvasTkAgg:
        def __init__(self, figure, master=None) -> None:
            self.figure, self._widget = figure, Widget(master)

        def get_tk_widget(self) -> Widget:
            return self._widget

        def draw(self) -> None:
            self.figure.canvas.draw() if hasattr(self.figure.canvas, "draw") else None

    canvas_mod.FigureCanvasTkAgg = FigureCanvasTkAgg
    return {"customtkinter": ctk, "tkinter": tk, "tkinter.messagebox": messagebox,
            "matplotlib.backends.backend_tkagg": canvas_mod}


_saved: Dict[str, Any] = {}
_MISSING = object()


def install() -> None:
    """Put the fake toolkit into ``sys.modules`` (and drop any cached ``ui`` imports)."""
    uninstall()
    STATE.update(confirm=True, input_dialog="", appearance="Dark", clipboard="")
    for name, module in _build_modules().items():
        _saved[name] = sys.modules.get(name, _MISSING)
        sys.modules[name] = module
    _purge_ui_modules()


def uninstall() -> None:
    for name, original in list(_saved.items()):
        if original is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original
    _saved.clear()
    _purge_ui_modules()


def _purge_ui_modules() -> None:
    for name in [m for m in sys.modules if m == "ui" or m.startswith("ui.")]:
        del sys.modules[name]
