"""NewsPulse entry point.

    python main.py                 -> launch the desktop GUI
    python main.py --fetch ...     -> command-line mode (see --help)
"""
from __future__ import annotations

import sys
from typing import List, Optional


def launch_gui() -> int:
    try:
        from ui.app import run_gui
    except ImportError as exc:
        print("The graphical interface needs 'customtkinter' and Tk.\n"
              f"  ({exc})\n"
              "Install the dependencies with:  pip install -r requirements.txt\n"
              "The command-line interface works without them: python main.py --help",
              file=sys.stderr)
        return 1
    return run_gui()


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or "--gui" in argv:
        return launch_gui()
    import cli
    return cli.run(argv)


if __name__ == "__main__":
    sys.exit(main())
