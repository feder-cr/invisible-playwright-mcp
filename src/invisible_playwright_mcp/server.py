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
    """One session per server, kept only while it is actually usable.

    Two failures are handled here, and they are different:

    * A session whose browser has DIED under it. The object is intact, so
      nothing raises until a tool touches the page, and then it raises
      somewhere unhelpful. Checked up front instead.
    * A start that FAILED. This used to assign the global before awaiting
      `start()`, so a start that raised left a half-built object behind, and
      every later call found a non-None `_session`, skipped the start, and died
      on `'NoneType' object has no attribute ...` - an error that names nothing
      and, on a stdio server, ends the whole conversation. The two ways to hit
      it are ordinary: a stale INVISIBLE_SEAL_FILE, and a proxy that is down
      when the first tool runs. Both take ten seconds to fix if the message
      says what happened.

    So: an unusable session is dropped before use, and a session is stored only
    once it has actually started.
    """
    global _session
    if _session is not None:
        try:
            if _session._browser is not None and not _session._browser.is_connected():
                await _session.close()
                _session = None
            elif _session._context is None:
                _session = None
        except Exception:
            _session = None

    if _session is None:
        session = StealthSession()
        await session.start()
        _session = session
    return _session


@mcp.tool()
async def session_new_page() -> str:
    s = await _ensure_session()
    try:
        return await s.new_page()
    except Exception:
        global _session
        _session = None
        s = await _ensure_session()
        return await s.new_page()


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
    global _session
    try:
        s = await _ensure_session()
        if not s.list_pages():
            await s.new_page()
        await s.page().goto(url, wait_until=wait_until, timeout=45_000)
    except Exception:
        _session = None
        s = await _ensure_session()
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
    """Title, url, and the interactive elements that are actually visible.

    Not the accessibility tree, and the reason is measured rather than
    aesthetic: on a real sign-up page a single country `<select>` contributes
    about two hundred `<option>` nodes, which fill the character cap before the
    form the caller was looking for appears at all. Filtering to elements a
    caller can act on - and to `offsetParent !== null`, so hidden ones do not
    count - keeps the answer about the page rather than about its longest
    dropdown.
    """
    s = await _ensure_session()
    dom_summary = await s.page().evaluate("""() => {
        const inputs = Array.from(document.querySelectorAll('input, button, select, textarea, a')).map(el => ({
            tag: el.tagName.toLowerCase(),
            type: el.type || undefined,
            name: el.name || undefined,
            id: el.id || undefined,
            placeholder: el.placeholder || undefined,
            text: (el.innerText || el.value || '').trim().slice(0, 50),
            visible: el.offsetParent !== null
        })).filter(x => x.visible);
        return { title: document.title, url: location.href, interactive_elements: inputs };
    }""")
    return _json_capped(dom_summary, limit=max_chars)


@mcp.tool()
async def browser_click(selector: str) -> str:
    s = await _ensure_session()
    await s.page().click(selector, timeout=15_000)
    return f"clicked {selector}"


@mcp.tool()
async def browser_click_at(x: float, y: float, hold_seconds: float = 0.0) -> Image:
    """Click (or press-and-hold) a raw viewport coordinate instead of a
    selector - for targets a selector can't reliably reach: a slider track,
    a canvas-drawn captcha, or a precise point inside a wider element. Moves
    the pointer there first (no teleport), then down, then - if hold_seconds
    is 0 - immediately up (a plain click); otherwise waits hold_seconds
    before releasing (a press-and-hold, e.g. PerimeterX's 'press & hold').
    Returns a screenshot taken right after release, so the result of the
    click is visible without a second round-trip."""
    page = (await _ensure_session()).page()
    await page.mouse.move(x, y, steps=12)
    await page.mouse.down()
    if hold_seconds > 0:
        await page.wait_for_timeout(int(hold_seconds * 1000))
    await page.mouse.up()
    # give a post-click transition (checkmark, redirect, reflow) a moment to
    # start before the screenshot, so it reflects the outcome, not the click
    await page.wait_for_timeout(400)
    png = await page.screenshot()
    return Image(data=png, format="png")


@mcp.tool()
async def browser_type(selector: str, text: str) -> str:
    s = await _ensure_session()
    await s.page().fill(selector, text, timeout=15_000)
    return f"typed into {selector}"


@mcp.tool()
async def browser_press_key(key: str) -> str:
    s = await _ensure_session()
    await s.page().keyboard.press(key)
    return f"pressed {key}"


@mcp.tool()
async def browser_evaluate(expression: str) -> str:
    s = await _ensure_session()
    result = await s.page().evaluate(expression)
    return _json_capped(result)


@mcp.tool()
async def browser_take_screenshot() -> Image:
    """One screenshot of the active tab, on demand."""
    png = await (await _ensure_session()).page().screenshot()
    return Image(data=png, format="png")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
