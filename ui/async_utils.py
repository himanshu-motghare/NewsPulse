"""Run slow work (network, big queries) off the Tk thread, safely.

Tkinter is not thread-safe, so worker threads never touch widgets.  They push
their result onto a queue and the Tk main loop picks it up with ``after()``.
"""
from __future__ import annotations

import queue
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from logger import get_logger

log = get_logger("ui.tasks")


class TaskRunner:
    def __init__(self, root: Any, workers: int = 6, interval_ms: int = 60) -> None:
        self._root = root
        self._queue: "queue.Queue" = queue.Queue()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="newspulse")
        self._interval = interval_ms
        self._closed = False
        self._root.after(self._interval, self._poll)

    def run(self, work: Callable[[], Any], on_success: Optional[Callable[[Any], None]] = None,
            on_error: Optional[Callable[[Exception], None]] = None, owner: Any = None) -> None:
        """Run ``work()`` in a thread; call a callback on the Tk thread afterwards.

        If ``owner`` (a widget) has been destroyed by then, the callback is skipped.
        """
        def job() -> None:
            try:
                self._queue.put((on_success, work(), None, owner))
            except Exception as exc:  # noqa: BLE001 - reported to the UI, never swallowed
                log.exception("Background task failed")
                self._queue.put((None, None, (on_error, exc), owner))

        if not self._closed:
            self._pool.submit(job)

    def _poll(self) -> None:
        try:
            while True:
                on_success, result, error, owner = self._queue.get_nowait()
                if owner is not None:
                    try:
                        if not owner.winfo_exists():
                            continue
                    except Exception:  # noqa: BLE001
                        continue
                try:
                    if error is not None:
                        on_error, exc = error
                        if on_error:
                            on_error(exc)
                    elif on_success:
                        on_success(result)
                except Exception:  # noqa: BLE001
                    log.exception("UI callback failed")
        except queue.Empty:
            pass
        if not self._closed:
            self._root.after(self._interval, self._poll)

    def shutdown(self) -> None:
        self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)
