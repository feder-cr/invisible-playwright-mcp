"""The engine download, started when the process starts rather than when the
first tool call needs a page.

A client that runs a stdio server starts it when the session opens, or at the
latest right before its first request, so the time between the start of this
process and the first page is free. On an ordinary line the quarter-gigabyte
engine has landed before anyone has finished typing. Until 0.13.0 that download
ran INSIDE the first tool call, which is the one moment a model and a person are
both waiting, and on clients with a short tool timeout it failed with an error
that named the timeout and never the download.

This is not a second downloader. It calls the same `ensure_binary` the launch
path calls, and the registry waits for it before starting a browser, so the
launch finds the engine on disk and does nothing. The wait is not optional: two
callers of `ensure_binary` in ONE process extract into the same
`.tmp-<tag>-<pid>` directory, and the second removes the first's work. Across
processes the core already handles that race; inside a process the only second
caller is this thread, so this thread is what the launch waits for.
"""
from __future__ import annotations

import asyncio
import sys
import threading
from typing import Callable, Optional


class Abandoned(BaseException):
    """Stops the download from inside its own progress callback.

    A BaseException on purpose. `ensure_binary` swallows any Exception its
    progress callback raises, which is right for a progress bar that fails to
    draw and wrong for a thread that has to stop at process exit. This is the
    contract KeyboardInterrupt uses, and it is what a person pressing Ctrl-C in
    a terminal would send the same download.
    """


class EnginePrefetch:
    """One background download per process, awaited by whoever launches."""

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        #: The exception a failed download ended with, for diagnostics. The
        #: launch path does not read it: it calls `ensure_binary` itself and
        #: gets the live answer, which may differ by then (the network came
        #: back, or did not).
        self.error: Optional[BaseException] = None
        self.landed = False

    def start(self, fetch: Callable[..., object]) -> bool:
        """Run `fetch(progress=...)` on a daemon thread. Once per process: a
        second call does nothing and returns False."""
        if self._thread is not None:
            return False

        def run() -> None:
            try:
                fetch(progress=self._progress)
                self.landed = True
            except Abandoned:
                pass
            except Exception as exc:
                self.error = exc
                print("[invisible-playwright-mcp] engine prefetch failed: %s; "
                      "the first page will fetch it instead" % exc, file=sys.stderr)

        thread = threading.Thread(target=run, name="engine-prefetch", daemon=True)
        self._thread = thread
        thread.start()
        return True

    def _progress(self, done: int, total: int) -> None:
        if self._stop.is_set():
            raise Abandoned()

    @property
    def in_flight(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    async def wait(self) -> None:
        """Return once the download has ended, one way or the other, without
        holding the event loop while it does."""
        thread = self._thread
        if thread is None or not thread.is_alive():
            return
        await asyncio.to_thread(thread.join)

    def abandon(self, timeout: float = 3.0) -> None:
        """Stop a download in flight. For process exit.

        Daemon threads are killed at interpreter teardown without running any
        cleanup, and a download killed that way leaves its half-written archive
        behind. Asking it to stop first lets `ensure_binary` unwind through its
        own `with` blocks and remove them. The join is bounded: a socket that
        has gone quiet answers only at its read timeout, and exit must not wait
        for that.
        """
        thread = self._thread
        if thread is None or not thread.is_alive():
            return
        self._stop.set()
        thread.join(timeout)
