"""The two-pane shell: conversation on the left, the live browser on the right.

What this is: the surface, and the wiring from a typed line to the browser. Every
action it performs goes through `actions.py`, the same module the MCP tools call,
so there is one implementation of "click" rather than two that drift.

What this is NOT, and the distinction is deliberate: there is no model in here.
The thing that decides what to do next is an interface, `Brain`, with one stub
implementation that understands a handful of literal commands. A stub that
answers `navigate https://...` is honest about being a stub. A stub dressed as an
agent would be the thing everyone demos and nobody can build on.

The event stream is server-sent events rather than a websocket: the traffic is
one-way (the server narrates, the client watches), SSE reconnects by itself, and
starlette already has the response type.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Awaitable, Callable, Dict, List

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse

from . import actions
from .registry import DEFAULT_SESSION_ID


class Brain:
    """What turns a sentence into browser actions.

    One method, on purpose: whatever fills this slot - an LLM, a script, a
    recorded trace - receives what the user said plus a way to act, and narrates
    as it goes. Nothing above it needs to know which.
    """

    async def handle(self, text: str, act, say) -> None:
        raise NotImplementedError


class LiteralBrain(Brain):
    """Understands literal commands and nothing else. Explicitly a placeholder.

    It exists so the shell can be built and tested end to end before there is a
    model behind it, and so the seam a model plugs into is exercised rather than
    imagined.
    """

    HELP = ("I am a placeholder, not a model. I understand: "
            "`go <url>`, `read [selector]`, `click <selector>`, "
            "`type <selector> <text>`, `shot`.")

    async def handle(self, text: str, act, say) -> None:
        parts = text.strip().split(None, 1)
        verb = parts[0].lower() if parts else ""
        rest = parts[1] if len(parts) > 1 else ""

        if verb in ("go", "open", "navigate") and rest:
            await say("tool", f"navigate {rest}")
            await say("result", await act(actions.navigate, rest))
        elif verb == "read":
            await say("tool", f"read_text {rest or 'body'}")
            await say("result", await act(actions.read_text, rest or "body"))
        elif verb == "click" and rest:
            await say("tool", f"click {rest}")
            await say("result", await act(actions.click, rest))
        elif verb == "type" and " " in rest:
            selector, value = rest.split(None, 1)
            await say("tool", f"type {selector}")
            await say("result", await act(actions.type_text, selector, value))
        elif verb == "shot":
            await say("tool", "screenshot")
            png = await act(actions.screenshot_png)
            await say("result", f"{len(png)} bytes; the view on the right is live anyway")
        else:
            await say("said", self.HELP)


PAGE = """<!doctype html>
<meta charset="utf-8"><title>AIHawk</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; height:100vh; display:flex; background:#101317; color:#e7eaec;
         font:14px/1.55 -apple-system,Segoe UI,sans-serif; }
  #left { width:44%; min-width:340px; display:flex; flex-direction:column;
          border-right:1px solid #2a3037; }
  #log { flex:1; overflow:auto; padding:16px; }
  .msg { margin-bottom:14px; }
  .you { color:#e7eaec; background:#1f242a; padding:8px 12px; border-radius:10px;
         display:inline-block; max-width:90%; }
  .tool { color:#a2abb3; font:12px/1.5 ui-monospace,Consolas,monospace; }
  .tool:before { content:"› "; color:#7c868e; }
  .result { color:#7c868e; white-space:pre-wrap; font:12px/1.5 ui-monospace,Consolas,monospace;
            border-left:2px solid #2a3037; padding-left:10px; margin-top:4px; }
  .said { color:#a2abb3; }
  .err { color:#e8836b; }
  form { display:flex; gap:8px; padding:12px; border-top:1px solid #2a3037; }
  input { flex:1; background:#1f242a; border:1px solid #2a3037; color:#e7eaec;
          padding:10px 12px; border-radius:8px; font:inherit; }
  button { background:#e38a5d; border:0; color:#101317; font-weight:600;
           padding:0 16px; border-radius:8px; cursor:pointer; }
  #right { flex:1; display:flex; flex-direction:column; }
  #bar { padding:8px 12px; border-bottom:1px solid #2a3037; color:#7c868e;
         font:12px ui-monospace,Consolas,monospace; }
  iframe { flex:1; border:0; background:#0b0d10; }
</style>
<div id="left">
  <div id="log"></div>
  <form id="f"><input id="i" placeholder="try: go https://example.com" autocomplete="off"><button>send</button></form>
</div>
<div id="right"><div id="bar">browser</div><iframe src="/live"></iframe></div>
<script>
const log = document.getElementById('log');
function add(kind, text) {
  const d = document.createElement('div');
  d.className = 'msg';
  const s = document.createElement('div');
  s.className = kind === 'you' ? 'you' : kind;
  s.textContent = text;
  d.appendChild(s); log.appendChild(d); log.scrollTop = log.scrollHeight;
}
const es = new EventSource('/chat/events');
es.onmessage = (e) => { const m = JSON.parse(e.data); add(m.kind, m.text); };
document.getElementById('f').onsubmit = async (e) => {
  e.preventDefault();
  const i = document.getElementById('i');
  const text = i.value.trim(); if (!text) return;
  i.value = ''; add('you', text);
  await fetch('/chat/send', {method:'POST', headers:{'Content-Type':'application/json'},
                            body: JSON.stringify({text})});
};
</script>
"""


class ChatService:
    """One conversation, its event listeners, and the session it drives."""

    def __init__(self, registry, brain: Brain | None = None,
                 session_id: str = DEFAULT_SESSION_ID) -> None:
        self._registry = registry
        self._brain = brain or LiteralBrain()
        self._session_id = session_id
        self._listeners: List[asyncio.Queue] = []
        self.history: List[Dict[str, str]] = []

    # --- events ---------------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._listeners.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._listeners:
            self._listeners.remove(q)

    async def emit(self, kind: str, text: str) -> None:
        event = {"kind": kind, "text": text}
        self.history.append(event)
        for q in list(self._listeners):
            q.put_nowait(event)

    # --- acting ---------------------------------------------------------

    async def _act(self, fn: Callable[..., Awaitable], *args, **kwargs):
        """Every action the chat takes goes through here, and through the same
        `actions` module the MCP tools use. There is no second path to the page
        by construction rather than by discipline."""
        session = await self._registry.ensure(self._session_id)
        return await fn(session, *args, **kwargs)

    async def send(self, text: str) -> None:
        try:
            await self._brain.handle(text, self._act, self.emit)
        except Exception as exc:
            await self.emit("err", f"{type(exc).__name__}: {exc}")


def install(mcp, registry, service: ChatService | None = None) -> ChatService:
    svc = service or ChatService(registry)

    @mcp.custom_route("/", methods=["GET"])
    async def _root(_request: Request) -> HTMLResponse:
        return HTMLResponse(PAGE)

    @mcp.custom_route("/chat/send", methods=["POST"])
    async def _send(request: Request) -> JSONResponse:
        body = await request.json()
        text = (body or {}).get("text", "")
        if not text:
            return JSONResponse({"error": "empty"}, status_code=400)
        # Run it detached: a navigation takes seconds and the caller should not
        # sit on an open request while the narration streams over SSE.
        asyncio.create_task(svc.send(text))
        return JSONResponse({"accepted": True})

    @mcp.custom_route("/chat/events", methods=["GET"])
    async def _events(_request: Request) -> StreamingResponse:
        q = svc.subscribe()

        async def stream() -> AsyncIterator[bytes]:
            try:
                for past in list(svc.history):
                    yield b"data: " + json.dumps(past).encode() + b"\n\n"
                while True:
                    event = await q.get()
                    yield b"data: " + json.dumps(event).encode() + b"\n\n"
            finally:
                svc.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store"})

    return svc
