"""Stdio MCP server exposing browser_* tools over ONE stealth session.

Tool names mirror the Microsoft Playwright MCP so prompts stay portable.
Config comes from STEALTHFOX_* env vars; the session starts lazily on first use.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP, Image

from .session import StealthSession


def _json_capped(obj, limit: int = 6000) -> str:
    """Serialize obj as JSON, capped at `limit` chars. Never slices an
    already-serialized string (that yields invalid JSON) - when the payload
    is too big it returns a small, always-valid envelope instead."""
    s = json.dumps(obj)
    if len(s) <= limit:
        return s
    return json.dumps({"truncated": True, "chars": len(s), "preview": s[:limit]})


_session: Optional[StealthSession] = None


@asynccontextmanager
async def _lifespan(_server):
    try:
        yield {}
    finally:
        global _session
        if _session is not None:
            await _session.close()
            _session = None


mcp = FastMCP("stealth", lifespan=_lifespan)


async def _ensure_session() -> StealthSession:
    global _session
    if _session is None:
        _session = StealthSession()
        await _session.start()
    return _session


@mcp.tool()
async def session_new_page() -> str:
    return await (await _ensure_session()).new_page()


@mcp.tool()
async def session_list_pages() -> str:
    return json.dumps((await _ensure_session()).list_pages())


@mcp.tool()
async def session_select_page(page_id: str) -> str:
    (await _ensure_session()).select_page(page_id)
    return f"active tab is {page_id}"


@mcp.tool()
async def session_close_page(page_id: str = "") -> str:
    await (await _ensure_session()).close_page(page_id or None)
    return "page closed"


@mcp.tool()
async def browser_navigate(url: str, wait_until: str = "domcontentloaded") -> str:
    s = await _ensure_session()
    if not s.list_pages():
        await s.new_page()
    await s.page().goto(url, wait_until=wait_until, timeout=45_000)
    return f"navigated to {url}"


@mcp.tool()
async def browser_read_text(selector: str = "body", max_chars: int = 6000) -> str:
    s = await _ensure_session()
    txt = await s.page().evaluate(
        "(sel) => { const el = document.querySelector(sel);"
        " return el ? el.innerText : null; }", selector,
    )
    return f"(no element matches {selector!r})" if txt is None else txt[:max_chars]


@mcp.tool()
async def browser_snapshot(max_chars: int = 6000) -> str:
    s = await _ensure_session()
    return _json_capped(await s.page().accessibility.snapshot(), limit=max_chars)


@mcp.tool()
async def browser_click(selector: str) -> str:
    await (await _ensure_session()).page().click(selector, timeout=15_000)
    return f"clicked {selector}"


@mcp.tool()
async def browser_type(selector: str, text: str) -> str:
    await (await _ensure_session()).page().fill(selector, text, timeout=15_000)
    return f"typed into {selector}"


@mcp.tool()
async def browser_press_key(key: str) -> str:
    await (await _ensure_session()).page().keyboard.press(key)
    return f"pressed {key}"


@mcp.tool()
async def browser_evaluate(expression: str) -> str:
    result = await (await _ensure_session()).page().evaluate(expression)
    return _json_capped(result)


@mcp.tool()
async def browser_wait_for(text: str = "", seconds: float = 0) -> str:
    s = await _ensure_session()
    if text:
        await s.page().get_by_text(text).first.wait_for(timeout=30_000)
        return f"saw text {text!r}"
    if seconds > 0:
        import asyncio
        await asyncio.sleep(min(seconds, 30))
        return f"waited {seconds}s"
    return "no-op"


@mcp.tool()
async def browser_take_screenshot() -> Image:
    png = await (await _ensure_session()).page().screenshot()
    return Image(data=png, format="png")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
