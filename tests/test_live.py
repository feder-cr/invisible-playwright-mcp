"""The live view reports what is running. It must never cause anything to run.

Two rules, and both matter for a different reason.

It uses `registry.peek`, never `registry.ensure`. A view that started a browser
would launch one the moment anybody opened the page, including a monitoring
check or a stray tab left open overnight.

And it is not an MCP tool. A tool result goes into the caller's context, so a
view refreshing every few hundred milliseconds through `browser_take_screenshot`
would spend a model's whole context window on pictures of a page nobody asked
about.
"""
import pytest
from starlette.testclient import TestClient

from invisible_playwright_mcp import server


@pytest.fixture(autouse=True)
def _empty_registry():
    """Every test starts with no sessions.

    Without this the suite lies to itself: a test that leaves a session behind
    makes the next one find a full registry, so the factory is never called and
    an assertion about "nothing was started" passes while the defect is live.
    That happened - the mutation these tests exist to catch was caught by a
    different test, and this one stayed green.
    """
    server.registry._sessions.clear()
    yield
    server.registry._sessions.clear()


@pytest.fixture
def client():
    return TestClient(server.mcp.streamable_http_app())


def test_no_browser_means_no_content_rather_than_an_error(client):
    """Nothing is wrong when nothing is running, and the page should say so
    rather than blink an error at somebody watching."""
    assert server.registry.ids() == []
    r = client.get("/live/frame")
    assert r.status_code == 204


def test_asking_for_a_frame_does_not_start_a_browser(client):
    """The rule the whole module exists to keep."""
    started = []

    class _NeverWanted:
        def __init__(self):
            started.append(1)

        async def start(self):
            pass

    original = server.registry._factory
    server.registry._factory = _NeverWanted
    try:
        for _ in range(5):
            client.get("/live/frame")
    finally:
        server.registry._factory = original

    assert started == [], "the live view started a browser; it must only observe"


def test_the_page_is_served(client):
    r = client.get("/live")
    assert r.status_code == 200
    assert "live browser view" in r.text


def test_sessions_lists_what_is_running(client):
    r = client.get("/live/sessions")
    assert r.status_code == 200
    assert r.json() == {"sessions": []}


def test_a_session_with_no_pages_is_not_a_frame(client):
    """A session that exists but has no tab open has nothing to show, and asking
    it for a screenshot would raise rather than return a picture."""
    class _Pageless:
        _browser = None
        _context = object()

        def list_pages(self):
            return []

    server.registry._sessions["default"] = _Pageless()
    try:
        assert client.get("/live/frame").status_code == 204
    finally:
        server.registry._sessions.clear()
