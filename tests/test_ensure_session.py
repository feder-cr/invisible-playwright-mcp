"""A start that fails must not take the rest of the conversation with it.

This is the defect that made the server unusable in practice: `_ensure_session`
assigned the module global BEFORE awaiting `start()`, so a start that raised
left a half-built object behind. Every later call then found a non-None
`_session`, skipped the start, and died on `'NoneType' object has no attribute
...` - an error that names nothing and, on a stdio server, ends the session.

Both tests below fail against that version, which is the only reason to trust
them.
"""
import pytest


class _SessionThatFailsOnce:
    """Raises on the first start and succeeds on the second.

    A stale INVISIBLE_SEAL_FILE and a proxy that is down both look like this
    from here: the object constructs fine and the failure happens in `start()`.
    """

    instances: list = []

    def __init__(self):
        self._browser = None
        self._context = None
        self.started = False
        _SessionThatFailsOnce.instances.append(self)

    async def start(self):
        if len(_SessionThatFailsOnce.instances) == 1:
            raise RuntimeError("engine/seal mismatch - refusing to launch")
        self.started = True
        self._browser = object()

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_a_failed_start_is_not_kept_and_the_next_call_retries(monkeypatch):
    from invisible_playwright_mcp import server

    _SessionThatFailsOnce.instances = []
    server._session = None
    monkeypatch.setattr(server, "StealthSession", _SessionThatFailsOnce)

    with pytest.raises(RuntimeError, match="refusing to launch"):
        await server._ensure_session()

    # The half-built object must not have been kept. Before the fix this was
    # the failed instance, and every later call returned it.
    assert server._session is None

    session = await server._ensure_session()
    assert session.started is True
    assert server._session is session
    assert len(_SessionThatFailsOnce.instances) == 2

    server._session = None


class _AlreadyPoisoned:
    """What a server that has been running since before the fix looks like."""

    def __init__(self):
        self._browser = None
        self._context = None

    async def start(self):
        raise AssertionError("the poisoned object must not be started again")

    async def close(self):
        pass


class _ConnectedBrowser:
    """`_ensure_session` asks a live browser whether it is still connected, so
    a stand-in without that method is indistinguishable from a dead one."""

    def is_connected(self):
        return True


class _Healthy:
    def __init__(self):
        self._browser = _ConnectedBrowser()
        self._context = object()
        self.started = False

    async def start(self):
        self.started = True

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_a_session_with_no_browser_is_replaced_rather_than_returned(monkeypatch):
    """The process that HAS the defect is the one you notice it in.

    A fix that only prevents the state does nothing for a server already in it,
    and there a later release never arrives - the operator has to restart, which
    is the thing they could not work out how to do from the error message.
    """
    from invisible_playwright_mcp import server

    server._session = _AlreadyPoisoned()
    monkeypatch.setattr(server, "StealthSession", _Healthy)

    session = await server._ensure_session()
    assert isinstance(session, _Healthy)
    assert session.started is True
    assert server._session is session

    server._session = None


@pytest.mark.asyncio
async def test_a_healthy_session_is_reused_and_not_restarted(monkeypatch):
    """The half that must NOT fire. A guard that rebuilds every time would open
    a second browser per call and lose the cookies of the first."""
    from invisible_playwright_mcp import server

    live = _Healthy()
    server._session = live

    def _explode():
        raise AssertionError("a healthy session must be reused, not rebuilt")

    monkeypatch.setattr(server, "StealthSession", _explode)

    assert await server._ensure_session() is live
    assert live.started is False

    server._session = None
