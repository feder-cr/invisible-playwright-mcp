"""The live view: what the browser is looking at, served over plain HTTP.

Deliberately not an MCP tool. A tool result goes into the caller's context, so a
view that refreshed twice a second through `browser_take_screenshot` would spend
a model's entire context window on pictures of a page it is not being asked
about. These frames are for a human watching, and they never touch the agent.

It also never starts a browser. The view reports what is running; it does not
cause anything to run. `registry.peek` rather than `registry.ensure` is the
whole of that rule.

Juggler has no screencast, so there is no video stream to attach to: this is a
screenshot pump, and the page below asks for the next frame only once the
previous one has arrived, which keeps a slow browser from queueing requests it
will never catch up with.
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from . import actions
from .registry import DEFAULT_SESSION_ID

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>live browser</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; background:#101317; color:#e7eaec;
         font:13px/1.5 -apple-system,Segoe UI,sans-serif;
         display:flex; flex-direction:column; height:100vh; }
  header { padding:8px 12px; border-bottom:1px solid #2a3037;
           display:flex; gap:12px; align-items:center; }
  #url { color:#a2abb3; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  #state { margin-left:auto; color:#7c868e; }
  main { flex:1; display:flex; align-items:flex-start; justify-content:center;
         overflow:auto; padding:12px; }
  /* display:none qui, e chi la mostra deve scrivere 'block': assegnare la
     stringa vuota toglie lo stile inline e ricade su QUESTA regola, cioe'
     lascia l'immagine nascosta con i pixel gia' dentro. */
  img { max-width:100%; border:1px solid #2a3037; border-radius:6px; display:none; }
  #empty { color:#7c868e; margin:auto; text-align:center; }
</style>
<header><b>live</b><span id="url"></span><span id="state">connecting</span></header>
<main><img id="f" alt="live browser view"><div id="empty">no browser running</div></main>
<script>
const img = document.getElementById('f'), empty = document.getElementById('empty');
const state = document.getElementById('state'), urlEl = document.getElementById('url');
let stop = false;
async function tick() {
  if (stop) return;
  try {
    const r = await fetch('/live/frame?t=' + Date.now(), {cache: 'no-store'});
    if (r.status === 204) {
      img.style.display = 'none'; empty.style.display = ''; state.textContent = 'idle';
    } else if (r.ok) {
      const blob = await r.blob();
      const old = img.src;
      img.src = URL.createObjectURL(blob);
      if (old.startsWith('blob:')) URL.revokeObjectURL(old);
      img.style.display = 'block'; empty.style.display = 'none';
      state.textContent = 'live';
      urlEl.textContent = r.headers.get('x-page-url') || '';
    } else {
      state.textContent = 'error ' + r.status;
    }
  } catch (e) {
    state.textContent = 'offline';
  }
  // Ask for the next frame only once this one has landed: a browser slower than
  // the interval would otherwise accumulate requests it can never serve.
  setTimeout(tick, 400);
}
tick();
</script>
"""


def install(mcp, registry) -> None:
    """Attach the view to the app FastMCP already serves.

    Same process, same port, no second server and no new dependency: `mcp`
    already requires starlette and uvicorn for streamable-http.
    """

    @mcp.custom_route("/live", methods=["GET"])
    async def _page(_request: Request) -> HTMLResponse:
        return HTMLResponse(PAGE)

    @mcp.custom_route("/live/frame", methods=["GET"])
    async def _frame(request: Request) -> Response:
        session_id = request.query_params.get("session", DEFAULT_SESSION_ID)
        session = registry.peek(session_id)
        if session is None or not session.list_pages():
            # 204 rather than an error: nothing is wrong, there is simply no
            # browser to look at, and the page says so instead of blinking.
            return Response(status_code=204)
        try:
            png = await actions.screenshot_png(session)
        except Exception as exc:
            # A screenshot taken mid-navigation fails routinely. It is not worth
            # a 500, and it must not take the view down.
            return JSONResponse({"error": str(exc)[:200]}, status_code=503)
        headers = {"Cache-Control": "no-store"}
        try:
            headers["x-page-url"] = session.page().url
        except Exception:
            pass
        return Response(png, media_type="image/png", headers=headers)

    @mcp.custom_route("/live/sessions", methods=["GET"])
    async def _sessions(_request: Request) -> JSONResponse:
        return JSONResponse({"sessions": registry.ids()})
