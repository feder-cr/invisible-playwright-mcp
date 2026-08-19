import pytest


class _FakeClosedSession:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_lifespan_closes_session_on_exit_and_resets_global():
    from invisible_playwright_mcp import server

    fake = _FakeClosedSession()
    server._session = fake

    async with server._lifespan(server.mcp) as ctx:
        assert ctx == {}
        assert server._session is fake
        assert fake.closed is False

    assert fake.closed is True
    assert server._session is None


@pytest.mark.asyncio
async def test_lifespan_is_a_noop_when_no_session_was_ever_started():
    from invisible_playwright_mcp import server

    server._session = None

    async with server._lifespan(server.mcp):
        pass

    assert server._session is None
