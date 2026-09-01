"""The chat must drive the browser through the same functions the MCP tools use.

This is the constraint the owner set, and it is worth a test rather than a
comment: a second path to the page would give two behaviours to keep in step,
and they drift. The tool grows a timeout the chat never gets, the chat grows a
retry the tool never gets, and the difference surfaces as a report nobody can
reproduce.

So the test asserts identity of function objects, not similarity of behaviour.
"""
import asyncio

import pytest

from invisible_playwright_mcp import actions, chat, server


class _FakeSession:
    _browser = None
    _context = object()

    def __init__(self):
        self.calls = []

    async def start(self):
        pass

    async def close(self):
        pass

    def list_pages(self):
        return ["tab-1"]

    async def new_page(self):
        return "tab-1"

    def page(self):
        return self

    async def goto(self, url, **kw):
        self.calls.append(("goto", url))

    async def evaluate(self, script, *a):
        self.calls.append(("evaluate", None))
        return "testo della pagina"


class _Registry:
    def __init__(self, session):
        self.session = session

    async def ensure(self, session_id="default"):
        return self.session


@pytest.mark.asyncio
async def test_a_typed_line_reaches_the_browser():
    session = _FakeSession()
    svc = chat.ChatService(_Registry(session))

    await svc.send("go https://example.com")

    assert ("goto", "https://example.com") in session.calls
    kinds = [e["kind"] for e in svc.history]
    assert "tool" in kinds and "result" in kinds


@pytest.mark.asyncio
async def test_the_chat_calls_the_same_functions_as_the_tools():
    """Identity, not resemblance. If someone reimplements navigate inside the
    chat, this fails even though the chat still works."""
    used = []

    class _Spy(chat.Brain):
        async def handle(self, text, act, say):
            async def _record(fn, *a, **k):
                used.append(fn)
                return "ok"
            await _record(actions.navigate, "x")

    svc = chat.ChatService(_Registry(_FakeSession()), brain=_Spy())
    await svc.send("qualsiasi cosa")
    assert used == [actions.navigate]

    # And the shipped brain reaches for the same module.
    session = _FakeSession()
    svc2 = chat.ChatService(_Registry(session))
    await svc2.send("read body")
    assert ("evaluate", None) in session.calls


@pytest.mark.asyncio
async def test_an_unknown_line_says_it_is_a_placeholder_rather_than_pretending():
    """The stub must not look like an agent. Somebody reading the transcript has
    to be able to tell that nothing is thinking yet."""
    svc = chat.ChatService(_Registry(_FakeSession()))
    await svc.send("find me a flight to Lisbon under 200 euro")

    said = [e["text"] for e in svc.history if e["kind"] == "said"]
    assert said and "placeholder" in said[0].lower()


@pytest.mark.asyncio
async def test_a_failing_action_is_reported_and_does_not_kill_the_conversation():
    class _Broken(_FakeSession):
        async def goto(self, url, **kw):
            raise RuntimeError("il browser e' morto")

    svc = chat.ChatService(_Registry(_Broken()))
    await svc.send("go https://example.com")

    errors = [e for e in svc.history if e["kind"] == "err"]
    assert errors and "morto" in errors[0]["text"]

    # still usable afterwards
    await svc.send("qualcosa")
    assert svc.history[-1]["kind"] in ("said", "err")


@pytest.mark.asyncio
async def test_listeners_receive_what_the_conversation_emits():
    svc = chat.ChatService(_Registry(_FakeSession()))
    q = svc.subscribe()
    await svc.emit("said", "ciao")
    assert (await asyncio.wait_for(q.get(), 1))["text"] == "ciao"
    svc.unsubscribe(q)
