"""MCP server exposing browser_* tools over stealth sessions.

Tool names mirror the Microsoft Playwright MCP so prompts stay portable.
Config comes from STEALTHFOX_* env vars; a session starts lazily on first use.

Every tool here is a wrapper. The operations live in `actions.py` and the
sessions live in `registry.py`, so the built-in chat and any other client drive
the browser through exactly the same code rather than through a second
implementation that would drift from this one.

Transport is stdio by default, which is what existing clients expect. Set
STEALTHFOX_MCP_TRANSPORT=http to serve over streamable HTTP instead, which is
what lets more than one client attach to the same live browser.
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
    return await _retrying(actions.new_page)


@mcp.tool()
async def session_list_pages() -> str:
    return actions.list_pages(await registry.ensure())


@mcp.tool()
async def session_select_page(page_id: str) -> str:
    return actions.select_page(await registry.ensure(), page_id)


@mcp.tool()
async def session_close_page(page_id: str = "") -> str:
    return await actions.close_page(await registry.ensure(), page_id)


# --- reading ---------------------------------------------------------------

@mcp.tool()
async def browser_navigate(url: str, wait_until: str = "domcontentloaded") -> str:
    return await _retrying(actions.navigate, url, wait_until=wait_until)


@mcp.tool()
async def browser_read_text(selector: str = "body", max_chars: int = 6000) -> str:
    return await actions.read_text(await registry.ensure(), selector, max_chars)


@mcp.tool()
async def browser_snapshot(max_chars: int = 6000) -> str:
    """Title, url, and the interactive elements that are actually visible.

    Not the accessibility tree: on a real sign-up page a single country
    `<select>` contributes about two hundred `<option>` nodes, which fill the
    character cap before the form the caller was looking for appears at all.
    """
    return await actions.snapshot(await registry.ensure(), max_chars)


@mcp.tool()
async def browser_take_screenshot() -> Image:
    """One screenshot of the active tab, on demand."""
    png = await actions.screenshot_png(await registry.ensure())
    return Image(data=png, format="png")


# --- acting ----------------------------------------------------------------

@mcp.tool()
async def browser_click(selector: str) -> str:
    return await actions.click(await registry.ensure(), selector)


@mcp.tool()
async def browser_click_at(x: float, y: float, hold_seconds: float = 0.0) -> Image:
    """Click (or press-and-hold) a raw viewport coordinate instead of a
    selector - for targets a selector cannot reliably reach: a slider track, a
    canvas-drawn captcha, or a precise point inside a wider element. Moves the
    pointer there first (no teleport), then down, then up, holding first if
    hold_seconds is set. Returns a screenshot taken right after release."""
    png = await actions.click_at(await registry.ensure(), x, y, hold_seconds)
    return Image(data=png, format="png")


@mcp.tool()
async def browser_type(selector: str, text: str) -> str:
    return await actions.type_text(await registry.ensure(), selector, text)


@mcp.tool()
async def browser_press_key(key: str) -> str:
    return await actions.press_key(await registry.ensure(), key)


@mcp.tool()
async def browser_evaluate(expression: str) -> str:
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
