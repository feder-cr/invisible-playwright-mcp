"""The engine download starts with the process, and the first browser waits
for it.

Until 0.13.0 the quarter-gigabyte engine was fetched inside the first tool
call that needed a page: the worst moment, because a model and a person are
both waiting, and on clients with a short tool timeout the call died with an
error about the timeout. The download now starts in `main()` and the registry
waits for it before starting a browser.

Every test here uses a fake fetch and a fake session. The known-bad case is
the one prefetch.py names in its docstring: a launch that does NOT wait starts
a second download of the same engine into the same directory. The first test
is that case, and it fails against a registry without the wait.
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from invisible_playwright_mcp.prefetch import EnginePrefetch
from invisible_playwright_mcp.registry import SessionRegistry


class _Session:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._browser = None
        self._context = None

    async def start(self):
        self._context = object()

    async def close(self):
        pass


def _registry():
    return SessionRegistry(factory=_Session, defaults=lambda: {})


@pytest.mark.asyncio
@pytest.mark.parametrize("launch", ["ensure", "restart"])
async def test_a_browser_starts_only_after_the_engine_has_landed(launch):
    reg = _registry()
    landed = threading.Event()
    order = []

    def fetch(progress=None):
        landed.wait(5)
        order.append("fetched")

    assert reg.prefetch_engine(fetch=fetch, env={}) is True

    task = asyncio.create_task(reg.ensure() if launch == "ensure" else reg.restart())
    await asyncio.sleep(0.3)
    assert not task.done(), (
        "the browser started while the engine was still downloading: a second "
        "ensure_binary in this process would now be racing the first")
    landed.set()
    session = await task
    order.append("started")

    assert order == ["fetched", "started"]
    assert session._context is not None


@pytest.mark.asyncio
async def test_a_failed_prefetch_leaves_the_first_call_to_fetch_for_itself():
    reg = _registry()

    def fetch(progress=None):
        raise RuntimeError("no network at startup")

    assert reg.prefetch_engine(fetch=fetch, env={}) is True
    session = await reg.ensure()

    assert session._context is not None, "one failed prefetch blocked every browser"
    assert isinstance(reg.prefetch.error, RuntimeError)
    assert reg.prefetch.landed is False


def test_the_prefetch_runs_once_per_process():
    reg = _registry()
    calls = []

    def fetch(progress=None):
        calls.append(1)

    assert reg.prefetch_engine(fetch=fetch, env={}) is True
    assert reg.prefetch_engine(fetch=fetch, env={}) is False
    reg.prefetch._thread.join(5)
    assert calls == [1]


def test_a_given_binary_is_not_downloaded_over():
    """STEALTHFOX_BINARY skips the download path everywhere else; a prefetch
    that ignored it would spend a quarter gigabyte the launch never uses."""
    reg = _registry()
    calls = []
    env = {"STEALTHFOX_BINARY": "C:/somewhere/firefox.exe"}

    assert reg.prefetch_engine(fetch=lambda progress=None: calls.append(1), env=env) is False
    assert calls == []
    assert reg.prefetch.in_flight is False


def test_abandon_stops_a_download_through_its_own_progress_callback():
    """`ensure_binary` swallows Exceptions raised by the progress callback, so
    the stop has to travel as a BaseException. The fake below does what the
    real download loop does: reports progress per chunk inside a bare
    `except Exception`, and checks for nothing else. A stop that was an
    ordinary Exception would be swallowed here and the thread would never
    end."""
    p = EnginePrefetch()
    chunks = []

    def fetch(progress=None):
        while True:
            try:
                progress(len(chunks), 100)
            except Exception:
                pass
            chunks.append(1)
            time.sleep(0.005)

    assert p.start(fetch) is True
    time.sleep(0.05)
    assert p.in_flight

    p.abandon(timeout=2.0)

    assert p.in_flight is False, "the download did not stop"
    assert p.error is None and p.landed is False


@pytest.mark.asyncio
async def test_wait_returns_at_once_when_nothing_was_started():
    await asyncio.wait_for(EnginePrefetch().wait(), timeout=1.0)


def test_main_starts_the_prefetch_before_serving(monkeypatch):
    from invisible_playwright_mcp import server

    order = []
    monkeypatch.setattr(server.registry, "prefetch_engine", lambda: order.append("prefetch"))
    monkeypatch.setattr(server.mcp, "run", lambda *a, **k: order.append("serve"))
    monkeypatch.delenv("STEALTHFOX_MCP_TRANSPORT", raising=False)

    server.main()

    assert order == ["prefetch", "serve"]


def test_process_exit_abandons_a_download_in_flight(monkeypatch):
    from invisible_playwright_mcp import server

    called = []
    monkeypatch.setattr(server.registry.prefetch, "abandon",
                        lambda *a, **k: called.append("abandon"))

    server._close_sessions_at_exit()

    assert called == ["abandon"]
