"""MCP server exposing browser_* tools over stealth sessions.

Tool names mirror the Microsoft Playwright MCP so prompts stay portable.
Config comes from STEALTHFOX_* env vars; a session starts lazily on first use.

Every tool here is a wrapper. The operations live in `actions.py` and the
sessions live in `registry.py`, so every client drives the browser through
exactly the same code rather than through a second implementation that would
drift from this one.

Transport is stdio by default, which is what existing clients expect. Set
STEALTHFOX_MCP_TRANSPORT=http to serve over streamable HTTP instead, which is
what lets more than one client attach to the same live browser.

THERE IS NO INTERFACE HERE, and that is the point rather than an omission. This
package served a two-pane page and a live view until 0.9.0, reaching the browser
through `registry` because it was in the same process. Both moved to `aihawk`,
which now reaches the browser over MCP like anybody else. What that buys is not
tidiness: it means no client has a privileged path, so the tools below are
provably sufficient for the flagship interface, because the flagship interface
is a client of them. A page kept inside the server is a page whose needs quietly
become the server's requirements.
"""
from __future__ import annotations

import asyncio
import atexit
import os
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP, Image

from . import actions
from .registry import DEFAULT_SESSION_ID, SessionRegistry

# Kept for callers that imported it from here. The implementation moved.
_json_capped = actions.json_capped

registry = SessionRegistry()


@asynccontextmanager
async def _lifespan(_server):
    """Deliberately does not touch the sessions.

    FastMCP runs this per MCP session, which is per CLIENT, not once per
    process. Measured: with a client attached the machine had 7 firefox
    processes, and one second after that client disconnected it had 1 again.
    Closing here would therefore kill the browser every time somebody detached,
    which is the exact behaviour the registry exists to remove.

    Cleanup is registered at process exit instead, below. On stdio the two
    moments coincide, so nothing changes for existing clients.
    """
    yield {}


def _close_sessions_at_exit() -> None:
    """Best effort shutdown of every browser when the process itself ends.

    A browser left behind is not a small leak here: Firefox launches a whole
    tree of processes, and an orphaned one goes on holding its profile
    directory and its port.
    """
    try:
        asyncio.run(registry.close_all())
    except Exception:
        pass


atexit.register(_close_sessions_at_exit)


mcp = FastMCP("stealth", lifespan=_lifespan)


async def _ensure_session(session_id: str = DEFAULT_SESSION_ID):
    return await registry.ensure(session_id)


async def _retrying(fn, *args, **kwargs):
    """Run an action, and on failure rebuild the session once and retry.

    A browser that died between two calls is the ordinary case here, not an
    exotic one: the object is still intact, so the failure surfaces inside the
    action rather than when the session was handed out.
    """
    session = await registry.ensure()
    try:
        return await fn(session, *args, **kwargs)
    except Exception:
        await registry.drop()
        session = await registry.ensure()
        return await fn(session, *args, **kwargs)


# --- pages -----------------------------------------------------------------

@mcp.tool()
async def session_new_page() -> str:
    """Open a new tab and make it the active one. Returns its page id.

    Tabs persist across calls and across clients, so this is how you keep one
    page while working on another rather than navigating back and forth."""
    return await _retrying(actions.new_page)


@mcp.tool()
async def session_list_pages() -> str:
    """Every open tab: id, title, url, and which one is active.

    Use it before session_select_page: the id alone does not tell you which tab
    you are switching to."""
    return await actions.list_pages(await registry.ensure())


@mcp.tool()
async def session_select_page(page_id: str) -> str:
    """Switch the active tab. Every other browser_* tool acts on it.

    Take the id from session_list_pages or from session_new_page."""
    return actions.select_page(await registry.ensure(), page_id)


@mcp.tool()
async def session_close_page(page_id: str = "") -> str:
    """Close a tab, or the active one when page_id is left out."""
    return await actions.close_page(await registry.ensure(), page_id)


# --- reading ---------------------------------------------------------------

@mcp.tool()
async def browser_navigate(url: str, wait_until: str = "domcontentloaded") -> str:
    """Go to a url in the active tab, opening one if none exists.

    wait_until is "domcontentloaded" by default, which returns as soon as the
    markup is parsed. Use "load" when the page needs its images and stylesheets,
    or "networkidle" for a single-page app that fetches its content after
    load."""
    return await _retrying(actions.navigate, url, wait_until=wait_until)


@mcp.tool()
async def browser_read_text(selector: str = "body", max_chars: int = 6000) -> str:
    """The visible text of an element, with the markup gone.

    The cheapest way to read a page. Narrow the selector when you know where the
    answer is; use browser_read_html instead when the structure matters, or
    browser_snapshot when you need something to click."""
    return await actions.read_text(await registry.ensure(), selector, max_chars)


@mcp.tool()
async def browser_snapshot(max_chars: int = 0) -> str:
    """Title, url, and the interactive elements that are actually visible.

    Each element carries a `selector` when one can reach it: pass that string to
    browser_click or browser_type VERBATIM. It is built to match exactly one
    element, which the obvious selector often does not - measured across 958
    elements on real pages, 88% could be addressed but only 48% unambiguously,
    and Playwright acts on the first match, so a caller aiming at the third of
    five identical links would silently hit the first.

    Elements with no `selector` carry `at`, the centre coordinates, for
    browser_click_at.

    Not the accessibility tree: on a real sign-up page a single country
    `<select>` contributes about two hundred `<option>` nodes, which fill the
    character cap before the form the caller was looking for appears at all.
    """
    return await actions.snapshot(await registry.ensure(), max_chars)


@mcp.tool()
async def browser_read_html(mode: str = "form") -> str:
    """The page's HTML, cleaned down to what is worth reading.

    Use this when the STRUCTURE matters - a form and its labels, a table, what
    a control is wired to. `browser_snapshot` gives a flat inventory of things
    to click; this keeps the markup and the relationships inside it.

    mode="form" keeps the interactive surface and the text explaining it,
    mode="text" returns the prose alone, mode="full" keeps the structure with
    the noise and the attribute soup removed.
    """
    return await actions.read_html(await registry.ensure(), mode)


@mcp.tool()
async def browser_take_screenshot() -> Image:
    """One screenshot of the active tab, on demand."""
    png = await actions.screenshot_png(await registry.ensure())
    return Image(data=png, format="png")


# --- acting ----------------------------------------------------------------

@mcp.tool()
async def browser_click(selector: str) -> str:
    """Click the first element matching a CSS selector.

    Scrolls it into view and waits for it to be clickable. When no selector can
    describe the target, use browser_click_at with coordinates from
    browser_snapshot."""
    return await actions.click(await registry.ensure(), selector)


@mcp.tool()
async def browser_click_at(x: float, y: float, hold_seconds: float = 0.0) -> Image:
    """Click (or press-and-hold) a raw viewport coordinate instead of a
    selector - for targets a selector cannot reliably reach: a slider track, a
    canvas-drawn captcha, or a precise point inside a wider element. Moves the
    pointer there first (no teleport), then down, then up, holding first if
    hold_seconds is set. Returns a screenshot taken right after release.

    hold_seconds needs invisible-playwright 0.9.0 or newer to mean anything. In
    every earlier version the wait it is built on returned instantly, so the
    press and the release happened in the same frame and the hold never
    happened - on the one tool that exists for sliders and press-and-hold
    challenges. The floor in pyproject.toml is set accordingly.

    Coordinates are relative to the VIEWPORT, not to the page, so the ones in a
    snapshot go stale the moment anything scrolls: a click, a keypress, a lazy
    image loading in above the fold. Nothing raises when that happens - the
    click simply lands on whatever is at that spot now. Take a fresh snapshot
    after anything that could have moved the page, and prefer browser_click with
    the element's `selector` whenever it has one."""
    png = await actions.click_at(await registry.ensure(), x, y, hold_seconds)
    return Image(data=png, format="png")


@mcp.tool()
async def browser_type(selector: str, text: str) -> str:
    """Fill a field, replacing whatever it holds.

    This sets the value rather than typing key by key, so it will not fire the
    per-keystroke handlers an autocomplete needs. For those, click the field and
    use browser_press_key."""
    return await actions.type_text(await registry.ensure(), selector, text)


@mcp.tool()
async def browser_press_key(key: str) -> str:
    """Press a key on whatever has focus: "Enter", "Tab", "Escape",
    "ArrowDown", "Control+a", or a single character."""
    return await actions.press_key(await registry.ensure(), key)


@mcp.tool()
async def browser_evaluate(expression: str) -> str:
    """Run a JavaScript expression in the page and return the result as JSON.

    The escape hatch for what the other tools do not cover: reading a computed
    style, a value held in a framework's state, or the length of a list. Prefer
    a named tool when one fits, because this one can change the page."""
    return await actions.evaluate(await registry.ensure(), expression)


def main() -> None:
    transport = os.environ.get("STEALTHFOX_MCP_TRANSPORT", "stdio").strip().lower()
    if transport in ("http", "streamable-http"):
        # streamable-http ships with the `mcp` package, which already requires
        # starlette and uvicorn, so serving over HTTP costs no new dependency.
        mcp.settings.host = os.environ.get("STEALTHFOX_MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("STEALTHFOX_MCP_PORT", "8765"))
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
